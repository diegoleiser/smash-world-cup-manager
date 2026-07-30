"""In-memory simulation using the Tournament Manager's bracket plans."""

from __future__ import annotations

import random
from dataclasses import dataclass

from monte_carlo.model import CombinedModel
from monte_carlo.scorelines import simulate_scoreline
from tournament.bracket_constants import (
    BRACKET_SIDE_LOSERS,
    BRACKET_SIDE_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
)
from tournament.bracket_matches import build_bracket_plan
from tournament.bracket_routes import build_bracket_route_plan
from tournament.bracket_seeding import (
    get_bracket_size,
    get_split_bracket_seed_pairs,
)


@dataclass(frozen=True)
class SimulatedBracketSet:
    match_code: str
    player_1_id: str
    player_2_id: str
    winner_id: str
    player_1_score: int
    player_2_score: int
    best_of: int


@dataclass(frozen=True)
class BracketSimulationResult:
    champion_id: str
    placements: dict[str, int]
    sets: tuple[SimulatedBracketSet, ...]
    grand_final_reset_played: bool


def simulate_split_bracket(
    seeded_player_ids: list[str],
    model: CombinedModel,
    day_values: dict[str, float],
    rng: random.Random,
) -> BracketSimulationResult:
    """Simulate the project split-entry Double Elimination bracket."""

    participant_count = len(seeded_player_ids)
    if participant_count < 3:
        raise ValueError("A bracket requires at least three players.")
    if len(set(seeded_player_ids)) != participant_count:
        raise ValueError("Bracket seeds must contain unique players.")
    for player_id in seeded_player_ids:
        if player_id not in model.players:
            raise KeyError(f"Unknown model player: {player_id}")
        if player_id not in day_values:
            raise KeyError(f"Missing Day value for player: {player_id}")

    plan = build_bracket_plan(
        participant_count,
        ENTRY_SPLIT_BY_GROUP_SEED,
    )
    routes = build_bracket_route_plan(
        participant_count,
        ENTRY_SPLIT_BY_GROUP_SEED,
    )
    match_metadata = {
        str(match["match_code"]): match for match in plan
    }
    slots: dict[str, list[str | None]] = {
        code: [None, None] for code in match_metadata
    }
    resolved: dict[str, tuple[str | None, str | None]] = {}
    incoming: dict[tuple[str, int], list[str]] = {}
    for route in routes:
        incoming.setdefault(
            (str(route["target_code"]), int(route["target_slot"]) - 1),
            [],
        ).append(str(route["source_code"]))

    bracket_size = get_bracket_size(participant_count)
    pairs = get_split_bracket_seed_pairs(bracket_size)
    seeded = {
        seed: (
            seeded_player_ids[seed - 1]
            if seed <= participant_count
            else None
        )
        for seed in range(1, bracket_size + 1)
    }
    for side in (BRACKET_SIDE_WINNERS, BRACKET_SIDE_LOSERS):
        first_round_codes = [
            str(match["match_code"])
            for match in plan
            if (
                str(match["bracket_side"]) == side
                and int(match["round_number"]) == 1
            )
        ]
        for match_number, (first_seed, second_seed) in enumerate(
            pairs[side],
        ):
            slots[first_round_codes[match_number]] = [
                seeded[first_seed],
                seeded[second_seed],
            ]

    played_sets: list[SimulatedBracketSet] = []
    elimination_groups: dict[int, list[str]] = {}
    reset_active = False

    def inputs_closed(code: str) -> bool:
        for slot_index in (0, 1):
            if slots[code][slot_index] is not None:
                continue
            sources = incoming.get((code, slot_index), [])
            if sources and not all(source in resolved for source in sources):
                return False
        return True

    def propagate(code: str, winner: str, loser: str | None) -> None:
        for route in routes:
            if str(route["source_code"]) != code:
                continue
            player_id = (
                winner
                if str(route["source_outcome"]) == "winner"
                else loser
            )
            if player_id is None:
                continue
            target = str(route["target_code"])
            target_slot = int(route["target_slot"]) - 1
            slots[target][target_slot] = player_id

    while True:
        progress = False
        for match in plan:
            code = str(match["match_code"])
            if code in resolved:
                continue
            if code == "GFR" and not reset_active:
                continue
            if not inputs_closed(code):
                continue
            player_1_id, player_2_id = slots[code]
            if player_1_id is None and player_2_id is None:
                resolved[code] = (None, None)
                progress = True
                continue
            if player_1_id is None or player_2_id is None:
                winner_id = player_1_id or player_2_id
                assert winner_id is not None
                resolved[code] = (winner_id, None)
                propagate(code, winner_id, None)
                progress = True
                continue

            best_of = 5 if code in {"GF", "GFR"} else 3
            normal, decider = model.game_probabilities(
                player_1_id,
                player_2_id,
                day_a=day_values[player_1_id],
                day_b=day_values[player_2_id],
            )
            probability = model.set_probability(
                player_1_id,
                player_2_id,
                best_of=best_of,
                day_a=day_values[player_1_id],
                day_b=day_values[player_2_id],
            )
            player_1_won = rng.random() < probability
            winner_id = player_1_id if player_1_won else player_2_id
            loser_id = player_2_id if player_1_won else player_1_id
            score = simulate_scoreline(
                player_a_won=player_1_won,
                normal_game_probability=normal,
                decider_game_probability=decider,
                best_of=best_of,
                rng=rng,
            )
            played_sets.append(
                SimulatedBracketSet(
                    match_code=code,
                    player_1_id=player_1_id,
                    player_2_id=player_2_id,
                    winner_id=winner_id,
                    player_1_score=score.player_a_score,
                    player_2_score=score.player_b_score,
                    best_of=best_of,
                )
            )
            resolved[code] = (winner_id, loser_id)
            if str(match["bracket_side"]) == BRACKET_SIDE_LOSERS:
                elimination_groups.setdefault(
                    int(match["round_number"]),
                    [],
                ).append(loser_id)
            propagate(code, winner_id, loser_id)
            if code == "GF":
                winners_side_finalist = player_1_id
                if winner_id == winners_side_finalist:
                    resolved["GFR"] = (winner_id, None)
                else:
                    reset_active = True
                    slots["GFR"] = [player_1_id, player_2_id]
            progress = True

        if "GF" in resolved and "GFR" in resolved:
            break
        if not progress:
            unresolved = [
                code for code in match_metadata if code not in resolved
            ]
            raise RuntimeError(
                "Bracket simulation stalled: " + ", ".join(unresolved)
            )

    final_code = "GFR" if reset_active else "GF"
    champion_id, runner_up_id = resolved[final_code]
    assert runner_up_id is not None
    losers_final_loser = resolved["LF"][1]
    assert losers_final_loser is not None
    placements = {
        champion_id: 1,
        runner_up_id: 2,
        losers_final_loser: 3,
    }
    next_placement = 4
    losers_final_round = int(match_metadata["LF"]["round_number"])
    for round_number in sorted(elimination_groups, reverse=True):
        if round_number == losers_final_round:
            continue
        players = list(dict.fromkeys(elimination_groups[round_number]))
        players = [player for player in players if player not in placements]
        for player_id in players:
            placements[player_id] = next_placement
        next_placement += len(players)
    if set(placements) != set(seeded_player_ids):
        raise RuntimeError("Bracket simulation did not place every player.")
    return BracketSimulationResult(
        champion_id=champion_id,
        placements=placements,
        sets=tuple(played_sets),
        grand_final_reset_played=reset_active,
    )
