#!/usr/bin/env python3
"""Create a synthetic archive and live tournament for local demonstrations."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from init_db import (  # noqa: E402
    DEFAULT_MIGRATIONS_DIR,
    DEFAULT_SCHEMA_PATH,
    initialize_database,
)
import tournament_manager as tournament  # noqa: E402


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "smash_wm.db"
DEFAULT_ARTIFACT_PATH = (
    PROJECT_ROOT / "data" / "model_artifacts" / "combined_v0.2"
)

PLAYERS = (
    ("atlas", "Atlas"),
    ("blaze", "Blaze"),
    ("comet", "Comet"),
    ("drift", "Drift"),
    ("echo", "Echo"),
    ("flux", "Flux"),
    ("grove", "Grove"),
    ("halo", "Halo"),
)

ARCHIVE_SEEDS = (
    ("atlas", "blaze", "comet", "drift", "echo", "flux", "grove", "halo"),
    ("blaze", "comet", "atlas", "echo", "drift", "halo", "flux", "grove"),
    ("comet", "atlas", "drift", "blaze", "flux", "echo", "grove", "halo"),
    ("atlas", "drift", "blaze", "comet", "echo", "grove", "halo", "flux"),
)


def _write_seed(seed_path: Path) -> None:
    payload = {
        "players": [
            {
                "player_id": player_id,
                "display_name": display_name,
                "core_player": True,
                "active": True,
                "aliases": [display_name],
            }
            for player_id, display_name in PLAYERS
        ],
        "tournaments": [],
    }
    seed_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _complete_ready_matches(
    db_path: Path,
    draft_id: str,
    strength_order: tuple[str, ...],
) -> None:
    strength = {
        player_id: position
        for position, player_id in enumerate(strength_order)
    }
    completed_count = 0

    while tournament.get_draft_bracket_champion(db_path, draft_id) is None:
        matches = tournament.get_draft_bracket_matches(db_path, draft_id)
        ready = [match for match in matches if match["status"] == "pending"]
        if not ready:
            raise RuntimeError("Synthetic bracket has no playable set.")

        match = ready[0]
        player_1_id = str(match["player_1_id"])
        player_2_id = str(match["player_2_id"])
        player_1_wins = strength[player_1_id] < strength[player_2_id]
        close_set = completed_count % 3 == 1
        winner_score = 3
        loser_score = 2 if close_set else 1

        tournament.update_draft_bracket_match(
            db_path,
            str(match["bracket_match_id"]),
            status="completed",
            player_1_score=(winner_score if player_1_wins else loser_score),
            player_2_score=(loser_score if player_1_wins else winner_score),
        )
        completed_count += 1


def _create_archived_tournaments(db_path: Path) -> None:
    for index, seed_order in enumerate(ARCHIVE_SEEDS, start=1):
        draft_id = tournament.create_draft(
            db_path,
            tournament_number=index,
            tournament_date=f"202{index + 1}-06-15",
            format_type=tournament.FORMAT_DOUBLE_ELIMINATION,
            bracket_entry_mode=tournament.BRACKET_START_ALL_WINNERS,
        )
        for seed, player_id in enumerate(seed_order, start=1):
            tournament.add_participant(
                db_path,
                draft_id,
                player_id,
                manual_seed=seed,
            )
        tournament.assign_manual_seeds(
            db_path,
            draft_id,
            {
                player_id: seed
                for seed, player_id in enumerate(seed_order, start=1)
            },
        )
        tournament.generate_draft_bracket(db_path, draft_id)
        _complete_ready_matches(db_path, draft_id, seed_order)
        tournament.finalize_draft_tournament(db_path, draft_id)


def _create_live_tournament(db_path: Path) -> None:
    seed_order = (
        "drift",
        "atlas",
        "comet",
        "blaze",
        "echo",
        "halo",
        "flux",
        "grove",
    )
    draft_id = tournament.create_draft(
        db_path,
        tournament_number=5,
        tournament_date="2026-09-12",
        format_type=tournament.FORMAT_DOUBLE_ELIMINATION,
        bracket_entry_mode=tournament.BRACKET_START_ALL_WINNERS,
    )
    for seed, player_id in enumerate(seed_order, start=1):
        tournament.add_participant(
            db_path,
            draft_id,
            player_id,
            manual_seed=seed,
        )
    tournament.assign_manual_seeds(
        db_path,
        draft_id,
        {
            player_id: seed
            for seed, player_id in enumerate(seed_order, start=1)
        },
    )
    tournament.generate_draft_bracket(db_path, draft_id)

    for _ in range(3):
        ready = [
            match
            for match in tournament.get_draft_bracket_matches(db_path, draft_id)
            if match["status"] == "pending"
        ]
        match = ready[0]
        tournament.update_draft_bracket_match(
            db_path,
            str(match["bracket_match_id"]),
            status="completed",
            player_1_score=3,
            player_2_score=1,
        )


def _write_demo_artifact(artifact_path: Path) -> None:
    artifact_path.mkdir(parents=True, exist_ok=True)
    metadata = {
        "artifact_schema_version": 1,
        "model_version": "synthetic-demo-v1",
        "training_cutoff": "synthetic-data-only",
        "trained_at": "2026-09-02T00:00:00Z",
        "database_fingerprint": "synthetic-demo",
        "player_count": len(PLAYERS),
        "set_count": 56,
        "score_known_set_count": 56,
    }
    config = {
        "model_version": "synthetic-demo-v1",
        "training_cutoff": "synthetic-data-only",
        "parameters": {
            "sigma_initial": 1.0,
            "sigma_skill_drift_per_180_days": 0.05,
            "sigma_h2h": 0.4,
            "sigma_clutch": 1.2,
            "sigma_day": 0.4,
            "prediction_clip_min": 0.005,
            "prediction_clip_max": 0.995,
        },
    }
    (artifact_path / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    (artifact_path / "config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )

    with (artifact_path / "dynamic_skill.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(("player_id", "player", "skill_log_odds"))
        for index, (player_id, display_name) in enumerate(PLAYERS):
            writer.writerow((player_id, display_name, round(0.7 - index * 0.2, 2)))

    with (artifact_path / "clutch_effects.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(("player_id", "clutch_log_odds"))
        for index, (player_id, _) in enumerate(PLAYERS):
            writer.writerow((player_id, round(((index % 3) - 1) * 0.08, 2)))

    (artifact_path / "h2h_effects.csv").write_text(
        "player_1_id,player_2_id,h2h_log_odds_for_player_1\n",
        encoding="utf-8",
    )


def create_demo_database(
    db_path: Path,
    artifact_path: Path,
    *,
    replace: bool = False,
) -> None:
    seed_path = db_path.with_suffix(".seed.json")
    if artifact_path.exists() and not replace:
        raise FileExistsError(
            f"Model artifact already exists: {artifact_path}\n"
            "Use --replace only for disposable demo data."
        )

    try:
        _write_seed(seed_path)
        initialize_database(
            db_path,
            DEFAULT_SCHEMA_PATH,
            seed_path,
            replace=replace,
            migrations_dir=DEFAULT_MIGRATIONS_DIR,
        )
    finally:
        seed_path.unlink(missing_ok=True)

    _create_archived_tournaments(db_path)
    _create_live_tournament(db_path)
    _write_demo_artifact(artifact_path)

    print(f"Synthetic demo database created: {db_path}")
    print(f"Synthetic demo model created: {artifact_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a synthetic Smash World Cup Manager demo."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--artifact", type=Path, default=DEFAULT_ARTIFACT_PATH
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace only deliberately disposable demo outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        create_demo_database(
            args.db.resolve(),
            args.artifact.resolve(),
            replace=args.replace,
        )
    except (FileExistsError, RuntimeError, ValueError) as error:
        raise SystemExit(f"Demo creation failed: {error}") from error


if __name__ == "__main__":
    main()
