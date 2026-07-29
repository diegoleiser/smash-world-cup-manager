"""Bracket-start forecasts using the frozen complete-group Day posterior."""

from __future__ import annotations

import random
from dataclasses import dataclass

from monte_carlo.bracket_simulation import simulate_split_bracket
from monte_carlo.day_performance import DayPosteriorEstimate, estimate_group_day
from monte_carlo.group_simulation import SimulationPlayer
from monte_carlo.live_group import LiveGroupMatch, standing_match_dict
from monte_carlo.model import CombinedModel
from tournament.bracket_constants import (
    BRACKET_SIDE_LOSERS,
    BRACKET_SIDE_WINNERS,
)
from tournament.bracket_seeding import get_split_bracket_seed_pairs
from tournament.group_stage_standings import calculate_group_standings


@dataclass(frozen=True)
class BracketMatchForecast:
    match_code: str
    player_1_id: str
    player_2_id: str
    player_1_win_probability: float


@dataclass(frozen=True)
class BracketPlayerForecast:
    player_id: str
    display_name: str
    group_seed: int
    starts_in: str
    placement_probabilities: dict[int, float]
    grand_final_probability: float
    title_probability: float


@dataclass(frozen=True)
class BracketStartForecast:
    players: tuple[BracketPlayerForecast, ...]
    opening_matches: tuple[BracketMatchForecast, ...]
    day_posterior: DayPosteriorEstimate
    reset_probability: float
    simulation_count: int
    random_seed: int


def forecast_bracket_start(
    players: list[SimulationPlayer],
    group_matches: list[LiveGroupMatch],
    model: CombinedModel,
    n_simulations: int,
    random_seed: int,
) -> BracketStartForecast:
    """Forecast the split bracket immediately after a complete group."""

    if len(players) != 7:
        raise ValueError("Bracket-start forecast requires seven players.")
    if n_simulations < 1:
        raise ValueError("n_simulations must be positive.")
    members = [
        {
            "player_id": player.player_id,
            "player": player.display_name,
            "initial_seed": player.initial_seed,
        }
        for player in players
    ]
    standings = calculate_group_standings(
        members,
        [standing_match_dict(match) for match in group_matches],
        {player.player_id: player.initial_elo for player in players},
    )
    if not standings["complete"]:
        raise ValueError("Complete the Group Stage before forecasting bracket.")
    seeded_player_ids = [
        str(row["player_id"]) for row in standings["standings"]
    ]
    day_posterior = estimate_group_day(
        [player.player_id for player in players],
        group_matches,
        model,
    )

    opening_matches: list[BracketMatchForecast] = []
    pairs = get_split_bracket_seed_pairs(8)
    for side, prefix in (
        (BRACKET_SIDE_WINNERS, "W1M"),
        (BRACKET_SIDE_LOSERS, "L1M"),
    ):
        for match_number, (first_seed, second_seed) in enumerate(
            pairs[side],
            start=1,
        ):
            if second_seed > len(seeded_player_ids):
                continue
            first = seeded_player_ids[first_seed - 1]
            second = seeded_player_ids[second_seed - 1]
            opening_matches.append(
                BracketMatchForecast(
                    match_code=f"{prefix}{match_number}",
                    player_1_id=first,
                    player_2_id=second,
                    player_1_win_probability=model.set_probability(
                        first,
                        second,
                        best_of=3,
                        day_a=day_posterior.values[first],
                        day_b=day_posterior.values[second],
                    ),
                )
            )

    placement_counts = {
        player.player_id: {placement: 0 for placement in range(1, 8)}
        for player in players
    }
    grand_final_counts = {player.player_id: 0 for player in players}
    title_counts = {player.player_id: 0 for player in players}
    reset_count = 0
    rng = random.Random(random_seed)
    for _ in range(n_simulations):
        bracket = simulate_split_bracket(
            seeded_player_ids,
            model,
            day_posterior.values,
            rng,
        )
        if bracket.grand_final_reset_played:
            reset_count += 1
        final_match = next(
            match
            for match in reversed(bracket.sets)
            if match.match_code in {"GF", "GFR"}
        )
        grand_final_counts[final_match.player_1_id] += 1
        grand_final_counts[final_match.player_2_id] += 1
        title_counts[bracket.champion_id] += 1
        for player_id, placement in bracket.placements.items():
            placement_counts[player_id][placement] += 1

    denominator = float(n_simulations)
    player_by_id = {player.player_id: player for player in players}
    summaries = tuple(
        BracketPlayerForecast(
            player_id=player_id,
            display_name=player_by_id[player_id].display_name,
            group_seed=seed,
            starts_in=("winners" if seed <= 4 else "losers"),
            placement_probabilities={
                placement: count / denominator
                for placement, count in placement_counts[player_id].items()
            },
            grand_final_probability=(
                grand_final_counts[player_id] / denominator
            ),
            title_probability=title_counts[player_id] / denominator,
        )
        for seed, player_id in enumerate(seeded_player_ids, start=1)
    )
    return BracketStartForecast(
        players=summaries,
        opening_matches=tuple(opening_matches),
        day_posterior=day_posterior,
        reset_probability=reset_count / denominator,
        simulation_count=n_simulations,
        random_seed=random_seed,
    )
