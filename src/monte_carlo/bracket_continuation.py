"""Simulate only the unresolved remainder of a persisted draft bracket."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from monte_carlo.bracket_simulation import (
    BracketSimulationResult,
    SimulatedBracketSet,
)
from monte_carlo.model import CombinedModel
from monte_carlo.scorelines import simulate_scoreline
from tournament.bracket_constants import BRACKET_SIDE_LOSERS


TERMINAL_STATUSES = {"completed", "forfeit", "bye", "cancelled"}


@dataclass(frozen=True)
class BracketContinuationInput:
    matches: tuple[dict[str, Any], ...]
    routes: tuple[dict[str, Any], ...]
    seeded_player_ids: tuple[str, ...]


@dataclass(frozen=True)
class ContinuationMatchForecast:
    match_code: str
    player_1_id: str
    player_2_id: str
    player_1_win_probability: float


@dataclass(frozen=True)
class ContinuationPlayerForecast:
    player_id: str
    placement_probabilities: dict[int, float]
    grand_final_probability: float
    title_probability: float


@dataclass(frozen=True)
class BracketContinuationForecast:
    players: tuple[ContinuationPlayerForecast, ...]
    ready_matches: tuple[ContinuationMatchForecast, ...]
    reset_probability: float
    simulation_count: int
    random_seed: int


def _resolved_outcome(
    match: dict[str, Any],
) -> tuple[str | None, str | None]:
    status = str(match["status"])
    first = (
        str(match["player_1_id"])
        if match.get("player_1_id") is not None
        else None
    )
    second = (
        str(match["player_2_id"])
        if match.get("player_2_id") is not None
        else None
    )
    winner = (
        str(match["winner_id"])
        if match.get("winner_id") is not None
        else None
    )
    if status == "cancelled" and first is not None and second is not None:
        raise ValueError(
            "Live forecasting of a real two-player cancelled Bracket Set "
            "is not supported yet."
        )
    if winner is None:
        return None, None
    loser = (
        second
        if winner == first and second is not None
        else first if winner == second and first is not None else None
    )
    return winner, loser


def simulate_bracket_continuation(
    state: BracketContinuationInput,
    model: CombinedModel,
    day_values: dict[str, float],
    rng: random.Random,
) -> BracketSimulationResult:
    """Keep persisted outcomes fixed and simulate all unresolved Sets."""

    matches = {
        str(match["match_code"]): dict(match) for match in state.matches
    }
    if not {"GF", "GFR", "LF"} <= set(matches):
        raise ValueError("Persisted bracket is missing required Finals.")
    slots = {
        code: [
            (
                str(match["player_1_id"])
                if match.get("player_1_id") is not None
                else None
            ),
            (
                str(match["player_2_id"])
                if match.get("player_2_id") is not None
                else None
            ),
        ]
        for code, match in matches.items()
    }
    resolved = {
        code: _resolved_outcome(match)
        for code, match in matches.items()
        if str(match["status"]) in TERMINAL_STATUSES
    }
    if (
        "GF" in resolved
        and str(matches["GFR"]["status"]) == "inactive"
        and resolved["GF"][0] == slots["GF"][0]
    ):
        resolved["GFR"] = (resolved["GF"][0], None)
    incoming: dict[tuple[str, int], list[str]] = {}
    for route in state.routes:
        incoming.setdefault(
            (str(route["target_code"]), int(route["target_slot"]) - 1),
            [],
        ).append(str(route["source_code"]))
    played_sets: list[SimulatedBracketSet] = []
    elimination_groups: dict[int, list[str]] = {}
    for code, (_, loser) in resolved.items():
        match = matches[code]
        if (
            loser is not None
            and str(match["bracket_side"]) == BRACKET_SIDE_LOSERS
        ):
            elimination_groups.setdefault(
                int(match["round_number"]),
                [],
            ).append(loser)

    def inputs_closed(code: str) -> bool:
        return all(
            slots[code][slot] is not None
            or (
                incoming.get((code, slot), [])
                and all(
                    source in resolved
                    for source in incoming[(code, slot)]
                )
            )
            or not incoming.get((code, slot), [])
            for slot in (0, 1)
        )

    def propagate(code: str, winner: str | None, loser: str | None) -> None:
        for route in state.routes:
            if str(route["source_code"]) != code:
                continue
            player_id = (
                winner
                if str(route["source_outcome"]) == "winner"
                else loser
            )
            if player_id is not None:
                slots[str(route["target_code"])][
                    int(route["target_slot"]) - 1
                ] = player_id

    while True:
        progress = False
        for code, match in matches.items():
            if code in resolved:
                continue
            if code == "GFR" and str(match["status"]) == "inactive":
                continue
            if not inputs_closed(code):
                continue
            first, second = slots[code]
            if first is None and second is None:
                resolved[code] = (None, None)
                progress = True
                continue
            if first is None or second is None:
                winner = first or second
                resolved[code] = (winner, None)
                propagate(code, winner, None)
                progress = True
                continue
            best_of = 5 if code in {"GF", "GFR"} else 3
            normal, decider = model.game_probabilities(
                first,
                second,
                day_a=day_values[first],
                day_b=day_values[second],
            )
            probability = model.set_probability(
                first,
                second,
                best_of=best_of,
                day_a=day_values[first],
                day_b=day_values[second],
            )
            first_won = rng.random() < probability
            winner = first if first_won else second
            loser = second if first_won else first
            score = simulate_scoreline(
                player_a_won=first_won,
                normal_game_probability=normal,
                decider_game_probability=decider,
                best_of=best_of,
                rng=rng,
            )
            played_sets.append(
                SimulatedBracketSet(
                    match_code=code,
                    player_1_id=first,
                    player_2_id=second,
                    winner_id=winner,
                    player_1_score=score.player_a_score,
                    player_2_score=score.player_b_score,
                    best_of=best_of,
                )
            )
            resolved[code] = (winner, loser)
            if str(match["bracket_side"]) == BRACKET_SIDE_LOSERS:
                elimination_groups.setdefault(
                    int(match["round_number"]),
                    [],
                ).append(loser)
            propagate(code, winner, loser)
            if code == "GF":
                if winner == first:
                    resolved["GFR"] = (winner, None)
                else:
                    slots["GFR"] = [first, second]
                    matches["GFR"]["status"] = "pending"
            progress = True

        if "GF" in resolved and "GFR" in resolved:
            break
        if not progress:
            raise RuntimeError("Persisted bracket continuation stalled.")

    reset_played = any(match.match_code == "GFR" for match in played_sets) or (
        str(matches["GFR"]["status"]) in {"completed", "forfeit"}
    )
    final_code = "GFR" if reset_played else "GF"
    champion, runner_up = resolved[final_code]
    if champion is None or runner_up is None:
        # A non-played GFR records the GF winner but no loser.
        champion, runner_up = resolved["GF"]
    if champion is None or runner_up is None:
        raise RuntimeError("Bracket continuation could not determine finalists.")
    third = resolved["LF"][1]
    if third is None:
        raise RuntimeError("Bracket continuation could not determine third place.")
    placements = {champion: 1, runner_up: 2, third: 3}
    next_placement = 4
    losers_final_round = int(matches["LF"]["round_number"])
    for round_number in sorted(elimination_groups, reverse=True):
        if round_number == losers_final_round:
            continue
        eliminated = [
            player_id
            for player_id in dict.fromkeys(elimination_groups[round_number])
            if player_id not in placements
        ]
        for player_id in eliminated:
            placements[player_id] = next_placement
        next_placement += len(eliminated)
    if set(placements) != set(state.seeded_player_ids):
        raise RuntimeError("Bracket continuation did not place every player.")
    return BracketSimulationResult(
        champion_id=champion,
        placements=placements,
        sets=tuple(played_sets),
        grand_final_reset_played=reset_played,
    )


def forecast_bracket_continuation(
    state: BracketContinuationInput,
    model: CombinedModel,
    day_values: dict[str, float],
    n_simulations: int,
    random_seed: int,
) -> BracketContinuationForecast:
    """Aggregate the unresolved persisted bracket over many simulations."""

    if n_simulations < 1:
        raise ValueError("n_simulations must be positive.")
    ready_matches = tuple(
        ContinuationMatchForecast(
            match_code=str(match["match_code"]),
            player_1_id=str(match["player_1_id"]),
            player_2_id=str(match["player_2_id"]),
            player_1_win_probability=model.set_probability(
                str(match["player_1_id"]),
                str(match["player_2_id"]),
                best_of=(
                    5
                    if str(match["match_code"]) in {"GF", "GFR"}
                    else 3
                ),
                day_a=day_values[str(match["player_1_id"])],
                day_b=day_values[str(match["player_2_id"])],
            ),
        )
        for match in state.matches
        if (
            str(match["status"]) == "pending"
            and match.get("player_1_id") is not None
            and match.get("player_2_id") is not None
        )
    )
    placement_counts = {
        player_id: {placement: 0 for placement in range(1, 8)}
        for player_id in state.seeded_player_ids
    }
    grand_final_counts = {
        player_id: 0 for player_id in state.seeded_player_ids
    }
    title_counts = {player_id: 0 for player_id in state.seeded_player_ids}
    reset_count = 0
    rng = random.Random(random_seed)
    for _ in range(n_simulations):
        result = simulate_bracket_continuation(
            state,
            model,
            day_values,
            rng,
        )
        if result.grand_final_reset_played:
            reset_count += 1
        title_counts[result.champion_id] += 1
        for player_id, placement in result.placements.items():
            placement_counts[player_id][placement] += 1
        finalists = [
            player_id
            for player_id, placement in result.placements.items()
            if placement in {1, 2}
        ]
        for player_id in finalists:
            grand_final_counts[player_id] += 1
    denominator = float(n_simulations)
    return BracketContinuationForecast(
        players=tuple(
            ContinuationPlayerForecast(
                player_id=player_id,
                placement_probabilities={
                    placement: count / denominator
                    for placement, count in placement_counts[player_id].items()
                },
                grand_final_probability=(
                    grand_final_counts[player_id] / denominator
                ),
                title_probability=title_counts[player_id] / denominator,
            )
            for player_id in state.seeded_player_ids
        ),
        ready_matches=ready_matches,
        reset_probability=reset_count / denominator,
        simulation_count=n_simulations,
        random_seed=random_seed,
    )
