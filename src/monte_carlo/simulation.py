"""Pre-tournament Monte Carlo orchestration and aggregation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone

from monte_carlo.bracket_simulation import simulate_split_bracket
from monte_carlo.group_simulation import SimulationPlayer, simulate_group
from monte_carlo.model import CombinedModel


TIEBREAK_VERSION = "group-tiebreak-v2"
FORMAT_VERSION = "seven-player-split-de-v1"


@dataclass(frozen=True)
class PlayerSimulationSummary:
    player_id: str
    display_name: str
    expected_group_wins: float
    group_seed_probabilities: dict[int, float]
    winners_probability: float
    placement_probabilities: dict[int, float]
    grand_final_probability: float
    title_probability: float


@dataclass(frozen=True)
class SimulationMetadata:
    model_version: str
    training_cutoff: str
    simulation_count: int
    random_seed: int
    generated_at: str
    sigma_day: float
    tiebreak_version: str
    format_version: str


@dataclass(frozen=True)
class SimulationResult:
    players: tuple[PlayerSimulationSummary, ...]
    metadata: SimulationMetadata
    reset_probability: float


def simulate_pre_tournament(
    players: list[SimulationPlayer],
    model: CombinedModel,
    n_simulations: int,
    random_seed: int,
) -> SimulationResult:
    """Simulate the current seven-player group plus split DE format."""

    if len(players) != 7:
        raise ValueError(
            "The current production simulator requires exactly seven players."
        )
    if n_simulations < 1:
        raise ValueError("n_simulations must be positive.")
    ordered_players = sorted(players, key=lambda player: player.initial_seed)
    if [player.initial_seed for player in ordered_players] != list(
        range(1, 8)
    ):
        raise ValueError("Initial seeds must be exactly 1 through 7.")

    rng = random.Random(random_seed)
    player_by_id = {
        player.player_id: player for player in ordered_players
    }
    group_win_totals = {player_id: 0 for player_id in player_by_id}
    group_seed_counts = {
        player_id: {seed: 0 for seed in range(1, 8)}
        for player_id in player_by_id
    }
    winners_counts = {player_id: 0 for player_id in player_by_id}
    placement_counts = {
        player_id: {placement: 0 for placement in range(1, 8)}
        for player_id in player_by_id
    }
    grand_final_counts = {player_id: 0 for player_id in player_by_id}
    title_counts = {player_id: 0 for player_id in player_by_id}
    reset_count = 0

    for _ in range(n_simulations):
        group = simulate_group(ordered_players, model, rng)
        seeded_player_ids = [
            str(row["player_id"]) for row in group.standings
        ]
        for row in group.standings:
            player_id = str(row["player_id"])
            group_win_totals[player_id] += int(row["sets_won"])
            group_seed = int(row["placement"])
            group_seed_counts[player_id][group_seed] += 1
            if group_seed <= 4:
                winners_counts[player_id] += 1

        bracket = simulate_split_bracket(
            seeded_player_ids,
            model,
            group.day_values,
            rng,
        )
        if bracket.grand_final_reset_played:
            reset_count += 1
        final_match = next(
            match
            for match in reversed(bracket.sets)
            if match.match_code in {"GF", "GFR"}
        )
        for finalist in (final_match.player_1_id, final_match.player_2_id):
            grand_final_counts[finalist] += 1
        title_counts[bracket.champion_id] += 1
        for player_id, placement in bracket.placements.items():
            placement_counts[player_id][placement] += 1

    denominator = float(n_simulations)
    summaries = tuple(
        PlayerSimulationSummary(
            player_id=player.player_id,
            display_name=player.display_name,
            expected_group_wins=(
                group_win_totals[player.player_id] / denominator
            ),
            group_seed_probabilities={
                seed: count / denominator
                for seed, count in group_seed_counts[player.player_id].items()
            },
            winners_probability=(
                winners_counts[player.player_id] / denominator
            ),
            placement_probabilities={
                placement: count / denominator
                for placement, count in placement_counts[
                    player.player_id
                ].items()
            },
            grand_final_probability=(
                grand_final_counts[player.player_id] / denominator
            ),
            title_probability=(
                title_counts[player.player_id] / denominator
            ),
        )
        for player in ordered_players
    )
    return SimulationResult(
        players=summaries,
        metadata=SimulationMetadata(
            model_version=model.config.model_version,
            training_cutoff=model.config.training_cutoff,
            simulation_count=n_simulations,
            random_seed=random_seed,
            generated_at=datetime.now(timezone.utc).isoformat(),
            sigma_day=model.config.sigma_day,
            tiebreak_version=TIEBREAK_VERSION,
            format_version=FORMAT_VERSION,
        ),
        reset_probability=reset_count / denominator,
    )
