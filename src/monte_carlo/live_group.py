"""Live Group Stage forecasts with completed results fixed."""

from __future__ import annotations

import random
from dataclasses import dataclass

from monte_carlo.group_simulation import SimulationPlayer
from monte_carlo.model import CombinedModel
from monte_carlo.scorelines import simulate_scoreline
from tournament.group_stage_standings import (
    GROUP_MATCH_CANCELLED,
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
    GROUP_MATCH_PENDING,
    VALID_GROUP_MATCH_STATUSES,
    calculate_group_standings,
)


@dataclass(frozen=True)
class LiveGroupMatch:
    player_1_id: str
    player_2_id: str
    status: str
    winner_id: str | None = None
    player_1_score: int | None = None
    player_2_score: int | None = None


@dataclass(frozen=True)
class LiveGroupPlayerForecast:
    player_id: str
    display_name: str
    current_sets_won: int
    current_sets_lost: int
    expected_final_sets_won: float
    group_seed_probabilities: dict[int, float]
    winners_probability: float


@dataclass(frozen=True)
class LiveGroupForecast:
    players: tuple[LiveGroupPlayerForecast, ...]
    current_standings: tuple[dict[str, object], ...]
    completed_sets: int
    pending_sets: int
    simulation_count: int
    random_seed: int
    model_version: str
    training_cutoff: str
    probability_policy: str


def _validate_live_group(
    players: list[SimulationPlayer],
    matches: list[LiveGroupMatch],
    model: CombinedModel,
) -> None:
    if len(players) < 2:
        raise ValueError("A live group requires at least two players.")
    player_ids = [player.player_id for player in players]
    player_id_set = set(player_ids)
    if len(player_id_set) != len(player_ids):
        raise ValueError("Live group players must be unique.")
    missing_from_model = player_id_set - set(model.players)
    if missing_from_model:
        raise KeyError(
            "Players missing from model artifact: "
            + ", ".join(sorted(missing_from_model))
        )
    seen_pairs: set[frozenset[str]] = set()
    for match in matches:
        if match.status not in VALID_GROUP_MATCH_STATUSES:
            raise ValueError(f"Unsupported live group status: {match.status}")
        if (
            match.player_1_id not in player_id_set
            or match.player_2_id not in player_id_set
        ):
            raise ValueError("Live group Set references a non-member.")
        pair = frozenset((match.player_1_id, match.player_2_id))
        if len(pair) != 2 or pair in seen_pairs:
            raise ValueError("Every live group pairing must be unique.")
        seen_pairs.add(pair)
        if match.status in {GROUP_MATCH_COMPLETED, GROUP_MATCH_FORFEIT}:
            if match.winner_id not in pair:
                raise ValueError("A decided Set requires a valid winner.")
        elif match.winner_id is not None:
            raise ValueError("Pending or cancelled Sets cannot have a winner.")
        if match.status == GROUP_MATCH_COMPLETED:
            scores = (match.player_1_score, match.player_2_score)
            if (scores[0] is None) != (scores[1] is None):
                raise ValueError("A completed Set must have both scores or none.")
        elif (
            match.player_1_score is not None
            or match.player_2_score is not None
        ):
            raise ValueError("Only completed Sets may contain scores.")


def _standing_match(match: LiveGroupMatch) -> dict[str, object]:
    return {
        "player_1_id": match.player_1_id,
        "player_2_id": match.player_2_id,
        "status": match.status,
        "winner_id": match.winner_id,
        "player_1_score": match.player_1_score,
        "player_2_score": match.player_2_score,
    }


def forecast_live_group(
    players: list[SimulationPlayer],
    matches: list[LiveGroupMatch],
    model: CombinedModel,
    n_simulations: int,
    random_seed: int,
    *,
    winners_count: int = 4,
) -> LiveGroupForecast:
    """Forecast a live group while freezing all already resolved Sets."""

    _validate_live_group(players, matches, model)
    if n_simulations < 1:
        raise ValueError("n_simulations must be positive.")
    if not 1 <= winners_count < len(players):
        raise ValueError("winners_count must split the group.")

    members = [
        {
            "player_id": player.player_id,
            "player": player.display_name,
            "initial_seed": player.initial_seed,
        }
        for player in players
    ]
    elo_by_player_id = {
        player.player_id: player.initial_elo for player in players
    }
    current = calculate_group_standings(
        members,
        [_standing_match(match) for match in matches],
        elo_by_player_id,
    )
    current_by_player_id = {
        str(row["player_id"]): row for row in current["standings"]
    }
    pending_matches = [
        match for match in matches if match.status == GROUP_MATCH_PENDING
    ]
    fixed_matches = [
        _standing_match(match)
        for match in matches
        if match.status != GROUP_MATCH_PENDING
    ]

    rng = random.Random(random_seed)
    final_win_totals = {player.player_id: 0 for player in players}
    seed_counts = {
        player.player_id: {
            seed: 0 for seed in range(1, len(players) + 1)
        }
        for player in players
    }
    winners_counts = {player.player_id: 0 for player in players}

    for _ in range(n_simulations):
        simulated_matches = list(fixed_matches)
        for match in pending_matches:
            normal, decider = model.game_probabilities(
                match.player_1_id,
                match.player_2_id,
            )
            probability = model.set_probability(
                match.player_1_id,
                match.player_2_id,
                best_of=3,
            )
            player_1_won = rng.random() < probability
            score = simulate_scoreline(
                player_a_won=player_1_won,
                normal_game_probability=normal,
                decider_game_probability=decider,
                best_of=3,
                rng=rng,
            )
            simulated_matches.append(
                {
                    "player_1_id": match.player_1_id,
                    "player_2_id": match.player_2_id,
                    "status": GROUP_MATCH_COMPLETED,
                    "winner_id": (
                        match.player_1_id
                        if player_1_won
                        else match.player_2_id
                    ),
                    "player_1_score": score.player_a_score,
                    "player_2_score": score.player_b_score,
                }
            )
        final_standings = calculate_group_standings(
            members,
            simulated_matches,
            elo_by_player_id,
        )["standings"]
        for row in final_standings:
            player_id = str(row["player_id"])
            placement = int(row["placement"])
            final_win_totals[player_id] += int(row["sets_won"])
            seed_counts[player_id][placement] += 1
            if placement <= winners_count:
                winners_counts[player_id] += 1

    denominator = float(n_simulations)
    forecasts = tuple(
        LiveGroupPlayerForecast(
            player_id=player.player_id,
            display_name=player.display_name,
            current_sets_won=int(
                current_by_player_id[player.player_id]["sets_won"]
            ),
            current_sets_lost=int(
                current_by_player_id[player.player_id]["sets_lost"]
            ),
            expected_final_sets_won=(
                final_win_totals[player.player_id] / denominator
            ),
            group_seed_probabilities={
                seed: count / denominator
                for seed, count in seed_counts[player.player_id].items()
            },
            winners_probability=(
                winners_counts[player.player_id] / denominator
            ),
        )
        for player in sorted(players, key=lambda item: item.initial_seed)
    )
    return LiveGroupForecast(
        players=forecasts,
        current_standings=tuple(current["standings"]),
        completed_sets=sum(
            match.status in {GROUP_MATCH_COMPLETED, GROUP_MATCH_FORFEIT}
            for match in matches
        ),
        pending_sets=len(pending_matches),
        simulation_count=n_simulations,
        random_seed=random_seed,
        model_version=model.config.model_version,
        training_cutoff=model.config.training_cutoff,
        probability_policy=(
            "Completed results fixed; remaining Sets use frozen "
            "pre-tournament strengths with Day Performance disabled."
        ),
    )
