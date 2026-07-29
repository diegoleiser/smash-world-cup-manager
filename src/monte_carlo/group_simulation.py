"""Single-group Round Robin simulation using canonical project tiebreaks."""

from __future__ import annotations

import random
from dataclasses import dataclass

from monte_carlo.day_performance import sample_day_values
from monte_carlo.model import CombinedModel
from monte_carlo.scorelines import simulate_scoreline
from tournament.group_stage_pairings import generate_round_robin_pairings
from tournament.group_stage_standings import (
    GROUP_MATCH_COMPLETED,
    calculate_group_standings,
)


@dataclass(frozen=True)
class SimulationPlayer:
    player_id: str
    display_name: str
    initial_seed: int
    initial_elo: float


@dataclass(frozen=True)
class SimulatedGroupSet:
    player_1_id: str
    player_2_id: str
    winner_id: str
    player_1_score: int
    player_2_score: int


@dataclass(frozen=True)
class GroupSimulationResult:
    standings: tuple[dict[str, object], ...]
    sets: tuple[SimulatedGroupSet, ...]
    day_values: dict[str, float]


def simulate_group(
    players: list[SimulationPlayer],
    model: CombinedModel,
    rng: random.Random,
) -> GroupSimulationResult:
    """Simulate one complete Bo3 Round Robin group."""

    if len(players) < 2:
        raise ValueError("A simulated group requires at least two players.")
    player_ids = [player.player_id for player in players]
    if len(set(player_ids)) != len(player_ids):
        raise ValueError("A player cannot appear twice in one group.")
    missing_players = [
        player_id for player_id in player_ids if player_id not in model.players
    ]
    if missing_players:
        raise KeyError(
            "Players missing from model artifact: "
            + ", ".join(sorted(missing_players))
        )

    day_values = sample_day_values(
        player_ids,
        model.config.sigma_day,
        rng,
    )
    rounds = generate_round_robin_pairings(player_ids)
    simulated_sets: list[SimulatedGroupSet] = []
    standing_matches: list[dict[str, object]] = []

    for round_pairings in rounds:
        for player_1_id, player_2_id in round_pairings:
            normal, decider = model.game_probabilities(
                player_1_id,
                player_2_id,
                day_a=day_values[player_1_id],
                day_b=day_values[player_2_id],
            )
            set_probability = model.set_probability(
                player_1_id,
                player_2_id,
                best_of=3,
                day_a=day_values[player_1_id],
                day_b=day_values[player_2_id],
            )
            player_1_won = rng.random() < set_probability
            score = simulate_scoreline(
                player_a_won=player_1_won,
                normal_game_probability=normal,
                decider_game_probability=decider,
                best_of=3,
                rng=rng,
            )
            winner_id = player_1_id if player_1_won else player_2_id
            simulated_set = SimulatedGroupSet(
                player_1_id=player_1_id,
                player_2_id=player_2_id,
                winner_id=winner_id,
                player_1_score=score.player_a_score,
                player_2_score=score.player_b_score,
            )
            simulated_sets.append(simulated_set)
            standing_matches.append(
                {
                    "player_1_id": player_1_id,
                    "player_2_id": player_2_id,
                    "winner_id": winner_id,
                    "player_1_score": score.player_a_score,
                    "player_2_score": score.player_b_score,
                    "status": GROUP_MATCH_COMPLETED,
                }
            )

    members = [
        {
            "player_id": player.player_id,
            "player": player.display_name,
            "initial_seed": player.initial_seed,
        }
        for player in players
    ]
    standings_result = calculate_group_standings(
        members,
        standing_matches,
        {
            player.player_id: player.initial_elo
            for player in players
        },
    )
    return GroupSimulationResult(
        standings=tuple(standings_result["standings"]),
        sets=tuple(simulated_sets),
        day_values=day_values,
    )
