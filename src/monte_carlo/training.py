"""Reproducible MAP training for the frozen Combined model."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from monte_carlo.artifacts import ARTIFACT_SCHEMA_VERSION, load_artifact
from monte_carlo.config import ModelConfig, load_model_config
from monte_carlo.probability import sigmoid


@dataclass(frozen=True)
class TrainingResult:
    artifact_path: Path
    success: bool
    message: str
    iterations: int
    objective: float


def database_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def load_training_data(
    db_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load valid non-walkover Sets and the player registry."""

    if not db_path.is_file():
        raise FileNotFoundError(f"Training database not found: {db_path}")
    with sqlite3.connect(db_path) as connection:
        players = pd.read_sql_query(
            """
            SELECT player_id, display_name, core_player, active
            FROM players
            ORDER BY player_id
            """,
            connection,
        )
        matches = pd.read_sql_query(
            """
            SELECT
                m.match_id,
                m.player_1_id,
                m.player_2_id,
                m.winner_id,
                m.player_1_score,
                m.player_2_score,
                m.score_known,
                m.stage,
                m.round_label,
                t.tournament_number,
                t.tournament_date
            FROM matches AS m
            JOIN tournaments AS t ON t.tournament_id = m.tournament_id
            WHERE m.winner_id IS NOT NULL
              AND COALESCE(m.walkover, 0) = 0
              AND m.player_1_id IS NOT NULL
              AND m.player_2_id IS NOT NULL
              AND m.player_1_id != m.player_2_id
            ORDER BY
                t.tournament_number,
                COALESCE(m.completed_at, ''),
                COALESCE(m.suggested_play_order, 2147483647),
                m.match_id
            """,
            connection,
        )
    if matches.empty:
        raise ValueError("Training database contains no valid Sets.")
    known_players = set(players["player_id"].astype(str))
    referenced = set(matches["player_1_id"].astype(str)) | set(
        matches["player_2_id"].astype(str)
    )
    if not referenced <= known_players:
        raise ValueError("Training Sets reference unknown players.")
    maximum_knockout_round: dict[int, int] = {}
    knockout = matches[matches["stage"] == "knockout"]
    for tournament_number, tournament_matches in knockout.groupby(
        "tournament_number"
    ):
        positive_rounds: list[int] = []
        for value in tournament_matches["round_label"].dropna():
            try:
                round_number = int(str(value))
            except ValueError:
                continue
            if round_number > 0:
                positive_rounds.append(round_number)
        maximum_knockout_round[int(tournament_number)] = (
            max(positive_rounds) if positive_rounds else -1
        )

    def infer_best_of(row: pd.Series) -> int:
        if (
            int(row["score_known"] or 0) == 1
            and pd.notna(row["player_1_score"])
            and pd.notna(row["player_2_score"])
        ):
            return (
                5
                if max(
                    int(row["player_1_score"]),
                    int(row["player_2_score"]),
                )
                >= 3
                else 3
            )
        try:
            round_number = int(str(row["round_label"]))
        except ValueError:
            round_number = 0
        is_historical_final = (
            str(row["stage"]) == "knockout"
            and round_number > 0
            and round_number
            == maximum_knockout_round.get(int(row["tournament_number"]), -1)
        )
        return 5 if is_historical_final else 3

    matches["best_of"] = matches.apply(infer_best_of, axis=1)
    return players, matches


class CombinedTrainer:
    """Frozen Gaussian-random-walk skill plus H2H and Clutch MAP fit."""

    def __init__(
        self,
        players: pd.DataFrame,
        matches: pd.DataFrame,
        config: ModelConfig,
    ) -> None:
        self.players_frame = players
        self.matches = matches
        self.config = config
        self.player_ids = players["player_id"].astype(str).tolist()
        self.player_index = {
            player_id: index
            for index, player_id in enumerate(self.player_ids)
        }
        self.core_ids = sorted(
            players.loc[
                (players["core_player"] == 1) & (players["active"] == 1),
                "player_id",
            ].astype(str)
        )
        self.core_index = {
            player_id: index
            for index, player_id in enumerate(self.core_ids)
        }
        self.h2h_pairs = [
            (first, second)
            for index, first in enumerate(self.core_ids)
            for second in self.core_ids[index + 1 :]
        ]
        self.h2h_index = {
            pair: index for index, pair in enumerate(self.h2h_pairs)
        }
        self.tournaments = sorted(
            matches["tournament_number"].astype(int).unique()
        )
        self.tournament_index = {
            number: index for index, number in enumerate(self.tournaments)
        }
        dates = matches.groupby("tournament_number")[
            "tournament_date"
        ].first()
        self.tournament_dates = {
            int(number): pd.Timestamp(value)
            for number, value in dates.items()
        }

    @property
    def layout(self) -> tuple[int, int, int]:
        skill_count = len(self.tournaments) * len(self.player_ids)
        return skill_count, len(self.h2h_pairs), len(self.core_ids)

    def _pair_effect(self, first: str, second: str) -> tuple[int | None, float]:
        if first not in self.core_index or second not in self.core_index:
            return None, 0.0
        pair = (first, second) if first < second else (second, first)
        return self.h2h_index[pair], 1.0 if pair[0] == first else -1.0

    def objective(self, values: np.ndarray) -> tuple[float, np.ndarray]:
        skill_count, h2h_count, clutch_count = self.layout
        skills = values[:skill_count].reshape(
            len(self.tournaments),
            len(self.player_ids),
        )
        h2h = values[skill_count : skill_count + h2h_count]
        clutch = values[skill_count + h2h_count :]
        gradient = np.zeros_like(values)
        skill_gradient = gradient[:skill_count].reshape(skills.shape)
        h2h_gradient = gradient[
            skill_count : skill_count + h2h_count
        ]
        clutch_gradient = gradient[skill_count + h2h_count :]

        initial_variance = self.config.sigma_initial**2
        objective = 0.5 * float(np.sum(skills[0] ** 2)) / initial_variance
        skill_gradient[0] += skills[0] / initial_variance
        for index in range(1, len(self.tournaments)):
            previous = self.tournaments[index - 1]
            current = self.tournaments[index]
            elapsed_days = max(
                (self.tournament_dates[current] - self.tournament_dates[previous]).days,
                30,
            )
            variance = self.config.sigma_skill_drift_per_180_days**2 * max(
                elapsed_days / 180.0,
                0.25,
            )
            difference = skills[index] - skills[index - 1]
            objective += 0.5 * float(np.sum(difference**2)) / variance
            residual = difference / variance
            skill_gradient[index] += residual
            skill_gradient[index - 1] -= residual
        objective += 0.5 * float(np.sum(h2h**2)) / self.config.sigma_h2h**2
        h2h_gradient += h2h / self.config.sigma_h2h**2
        objective += (
            0.5 * float(np.sum(clutch**2)) / self.config.sigma_clutch**2
        )
        clutch_gradient += clutch / self.config.sigma_clutch**2

        for row in self.matches.itertuples(index=False):
            first = str(row.player_1_id)
            second = str(row.player_2_id)
            tournament = self.tournament_index[int(row.tournament_number)]
            first_index = self.player_index[first]
            second_index = self.player_index[second]
            h2h_index, h2h_sign = self._pair_effect(first, second)
            eta = skills[tournament, first_index] - skills[
                tournament, second_index
            ]
            if h2h_index is not None:
                eta += h2h_sign * h2h[h2h_index]

            def add_residual(residual: float) -> None:
                skill_gradient[tournament, first_index] += residual
                skill_gradient[tournament, second_index] -= residual
                if h2h_index is not None:
                    h2h_gradient[h2h_index] += h2h_sign * residual

            score_known = (
                int(row.score_known or 0) == 1
                and pd.notna(row.player_1_score)
                and pd.notna(row.player_2_score)
            )
            if score_known:
                first_score = int(row.player_1_score)
                second_score = int(row.player_2_score)
                wins_needed = 3 if max(first_score, second_score) >= 3 else 2
                reached_decider = (
                    first_score + second_score == 2 * wins_needed - 1
                )
                normal_wins = first_score
                normal_games = first_score + second_score
                if reached_decider:
                    normal_games -= 1
                    if first_score == wins_needed:
                        normal_wins -= 1
                if normal_games:
                    probability = sigmoid(float(eta))
                    objective += (
                        normal_games * np.logaddexp(0.0, eta)
                        - normal_wins * eta
                    )
                    add_residual(normal_games * probability - normal_wins)
                if reached_decider:
                    decider_eta = eta
                    if first in self.core_index and second in self.core_index:
                        decider_eta += (
                            clutch[self.core_index[first]]
                            - clutch[self.core_index[second]]
                        )
                    actual = 1.0 if first_score == wins_needed else 0.0
                    probability = sigmoid(float(decider_eta))
                    residual = probability - actual
                    objective += np.logaddexp(0.0, decider_eta) - actual * decider_eta
                    add_residual(residual)
                    if first in self.core_index and second in self.core_index:
                        clutch_gradient[self.core_index[first]] += residual
                        clutch_gradient[self.core_index[second]] -= residual
            else:
                actual = 1.0 if str(row.winner_id) == first else 0.0
                game_probability = sigmoid(float(eta))
                if int(row.best_of) == 5:
                    set_probability = (
                        10 * game_probability**3
                        - 15 * game_probability**4
                        + 6 * game_probability**5
                    )
                    derivative = (
                        30
                        * game_probability**3
                        * (1 - game_probability) ** 3
                    )
                else:
                    set_probability = (
                        3 * game_probability**2 - 2 * game_probability**3
                    )
                    derivative = (
                        6
                        * game_probability**2
                        * (1 - game_probability) ** 2
                    )
                set_probability = float(
                    np.clip(set_probability, 1e-9, 1 - 1e-9)
                )
                objective -= actual * np.log(set_probability) + (
                    1 - actual
                ) * np.log(1 - set_probability)
                add_residual(
                    (set_probability - actual)
                    * derivative
                    / (set_probability * (1 - set_probability))
                )
        return float(objective), gradient

    def fit(self) -> tuple[np.ndarray, dict[str, object]]:
        total = sum(self.layout)
        result = minimize(
            fun=self.objective,
            x0=np.zeros(total),
            jac=True,
            method="L-BFGS-B",
            options={
                "maxiter": 2500,
                "ftol": 1e-10,
                "gtol": 1e-6,
                "maxls": 30,
            },
        )
        return np.asarray(result.x), {
            "success": bool(result.success),
            "message": str(result.message),
            "iterations": int(result.nit),
            "objective": float(result.fun),
        }

    def parameter_rows(
        self,
        values: np.ndarray,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        skill_count, h2h_count, _ = self.layout
        skills = values[:skill_count].reshape(
            len(self.tournaments), len(self.player_ids)
        )[-1]
        h2h = values[skill_count : skill_count + h2h_count]
        clutch = values[skill_count + h2h_count :]
        names = dict(
            zip(
                self.players_frame["player_id"].astype(str),
                self.players_frame["display_name"].astype(str),
            )
        )
        return (
            [
                {
                    "player_id": player_id,
                    "player": names[player_id],
                    "skill_log_odds": float(skills[self.player_index[player_id]]),
                }
                for player_id in self.player_ids
            ],
            [
                {
                    "player_1_id": first,
                    "player_2_id": second,
                    "h2h_log_odds_for_player_1": float(h2h[index]),
                }
                for index, (first, second) in enumerate(self.h2h_pairs)
            ],
            [
                {
                    "player_id": player_id,
                    "clutch_log_odds": float(clutch[self.core_index[player_id]]),
                }
                for player_id in self.core_ids
            ],
        )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty artifact table: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def train_artifact(
    db_path: Path,
    config_path: Path,
    output_path: Path,
) -> TrainingResult:
    """Fit the frozen Combined model and write one loadable artifact."""

    if output_path.exists() and any(output_path.iterdir()):
        raise FileExistsError(
            f"Artifact output directory is not empty: {output_path}"
        )
    config = load_model_config(config_path)
    players, matches = load_training_data(db_path)
    trainer = CombinedTrainer(players, matches, config)
    values, diagnostics = trainer.fit()
    if not diagnostics["success"]:
        raise RuntimeError(f"Model fit failed: {diagnostics['message']}")
    skill_rows, h2h_rows, clutch_rows = trainer.parameter_rows(values)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "config.json").write_text(
        config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_csv(output_path / "dynamic_skill.csv", skill_rows)
    _write_csv(output_path / "h2h_effects.csv", h2h_rows)
    _write_csv(output_path / "clutch_effects.csv", clutch_rows)
    score_known = (
        (matches["score_known"] == 1)
        & matches["player_1_score"].notna()
        & matches["player_2_score"].notna()
    )
    metadata = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_version": config.model_version,
        "training_cutoff": config.training_cutoff,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "database_fingerprint": database_fingerprint(db_path),
        "player_count": len(skill_rows),
        "set_count": len(matches),
        "score_known_set_count": int(score_known.sum()),
    }
    (output_path / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_path / "fit_diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2) + "\n",
        encoding="utf-8",
    )
    load_artifact(output_path)
    return TrainingResult(
        artifact_path=output_path,
        success=True,
        message=str(diagnostics["message"]),
        iterations=int(diagnostics["iterations"]),
        objective=float(diagnostics["objective"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Combined model.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/model_freeze_candidate_v0.2.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = train_artifact(args.db, args.config, args.output)
    print(f"Artifact created: {result.artifact_path}")
    print(f"Iterations: {result.iterations}")
    print(f"Objective: {result.objective:.6f}")


if __name__ == "__main__":
    main()
