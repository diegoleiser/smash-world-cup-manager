"""Pure cross-group ranking and bracket-entry assignment."""

from __future__ import annotations

from typing import Any

from tournament.bracket_constants import (
    BRACKET_SIDE_LOSERS,
    BRACKET_SIDE_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
)
from tournament.bracket_seeding import (
    get_first_round_seed_pairs,
    get_split_bracket_seed_pairs,
)


def _next_power_of_two(value: int) -> int:
    """Return the smallest power of two greater than or equal to ``value``."""

    if value <= 0:
        raise ValueError("The value must be greater than zero.")

    power = 1

    while power < value:
        power *= 2

    return power


def _first_round_seed_pairs(
    bracket_size: int,
    bracket_entry_mode: str,
) -> list[tuple[int, int]]:
    """Return every first-round pairing used by the selected entry mode."""

    if bracket_entry_mode == ENTRY_SPLIT_BY_GROUP_SEED:
        split_pairs = get_split_bracket_seed_pairs(bracket_size)
        return [
            *split_pairs[BRACKET_SIDE_WINNERS],
            *split_pairs[BRACKET_SIDE_LOSERS],
        ]

    return get_first_round_seed_pairs(bracket_size)


def _avoid_first_round_group_rematches(
    ranking_candidates: list[dict[str, Any]],
    bracket_size: int,
    bracket_entry_mode: str,
    winners_count: int,
) -> None:
    """
    Reduce same-group first-round matches without changing placement tiers.

    Players may only exchange seeds when they finished at the same group
    placement and start on the same bracket side. Statistical ranking remains
    the tie-breaker whenever a swap does not strictly reduce rematches.
    """

    if len(
        {
            str(player["group_id"])
            for player in ranking_candidates
        }
    ) <= 1:
        return

    participant_count = len(ranking_candidates)
    active_pairs = [
        (seed_1, seed_2)
        for seed_1, seed_2 in _first_round_seed_pairs(
            bracket_size,
            bracket_entry_mode,
        )
        if seed_1 <= participant_count and seed_2 <= participant_count
    ]

    def conflict_count() -> int:
        return sum(
            ranking_candidates[seed_1 - 1]["group_id"]
            == ranking_candidates[seed_2 - 1]["group_id"]
            for seed_1, seed_2 in active_pairs
        )

    while True:
        current_conflicts = conflict_count()
        best_swap: tuple[int, int] | None = None
        best_conflicts = current_conflicts

        for first_index in range(participant_count):
            first_player = ranking_candidates[first_index]

            for second_index in range(
                first_index + 1,
                participant_count,
            ):
                second_player = ranking_candidates[second_index]

                if (
                    first_player["group_placement"]
                    != second_player["group_placement"]
                ):
                    continue

                if (
                    bracket_entry_mode
                    == ENTRY_SPLIT_BY_GROUP_SEED
                    and (first_index < winners_count)
                    != (second_index < winners_count)
                ):
                    continue

                ranking_candidates[first_index], ranking_candidates[
                    second_index
                ] = (
                    second_player,
                    first_player,
                )
                swapped_conflicts = conflict_count()
                ranking_candidates[first_index], ranking_candidates[
                    second_index
                ] = (
                    first_player,
                    second_player,
                )

                if (
                    swapped_conflicts < best_conflicts
                    or (
                        swapped_conflicts == best_conflicts
                        and swapped_conflicts < current_conflicts
                        and (
                            best_swap is None
                            or first_index > best_swap[0]
                        )
                    )
                ):
                    best_conflicts = swapped_conflicts
                    best_swap = (first_index, second_index)

        if best_swap is None:
            return

        first_index, second_index = best_swap
        ranking_candidates[first_index], ranking_candidates[second_index] = (
            ranking_candidates[second_index],
            ranking_candidates[first_index],
        )


def build_global_group_ranking(
    group_standings: list[dict[str, Any]],
    bracket_entry_mode: str,
) -> dict[str, Any]:
    """
    Combine group tables into the global Bracket seed order.

    Group placement is compared before cross-group percentages. This ensures
    that every group winner is seeded ahead of every runner-up, regardless of
    score margins in groups with different results.
    """

    if not group_standings:
        raise ValueError(
            "Create the tournament groups before calculating "
            "the global ranking."
        )

    ranking_candidates: list[dict[str, Any]] = []

    for group in group_standings:
        for player in group["standings"]:
            ranking_candidates.append(
                {
                    **player,
                    "group_id": str(group["group_id"]),
                    "group_name": str(group["group_name"]),
                    "group_placement": int(
                        player["placement"]
                    ),
                }
            )

    ranking_candidates.sort(
        key=lambda player: (
            int(player["group_placement"]),
            -(
                float(player["set_win_percentage"])
                if player["set_win_percentage"] is not None
                else -1.0
            ),
            -(
                float(player["game_win_percentage"])
                if player["game_win_percentage"] is not None
                else -1.0
            ),
            -int(player["games_won"]),
            -float(player["initial_elo"]),
            int(player["initial_seed"]),
            str(player["player"]).casefold(),
        )
    )

    participant_count = len(ranking_candidates)
    bracket_size = _next_power_of_two(participant_count)

    if bracket_entry_mode == ENTRY_SPLIT_BY_GROUP_SEED:
        winners_count = bracket_size // 2
        losers_count = (
            participant_count - winners_count
        )
    else:
        winners_count = participant_count
        losers_count = 0

    _avoid_first_round_group_rematches(
        ranking_candidates,
        bracket_size,
        bracket_entry_mode,
        winners_count,
    )

    ranked_players: list[dict[str, Any]] = []

    for global_seed, player in enumerate(
        ranking_candidates,
        start=1,
    ):
        starts_in = (
            "losers"
            if (
                bracket_entry_mode
                == ENTRY_SPLIT_BY_GROUP_SEED
                and global_seed > winners_count
            )
            else "winners"
        )

        ranked_players.append(
            {
                **player,
                "global_seed": global_seed,
                "starts_in": starts_in,
            }
        )

    pending_matches = sum(
        int(group["pending_matches"])
        for group in group_standings
    )
    cancelled_matches = sum(
        int(group["cancelled_matches"])
        for group in group_standings
    )
    total_matches = sum(
        int(group["total_matches"])
        for group in group_standings
    )
    decided_matches = sum(
        int(group["decided_matches"])
        for group in group_standings
    )

    return {
        "ranking": ranked_players,
        "participant_count": participant_count,
        "bracket_size": bracket_size,
        "winners_count": winners_count,
        "losers_count": losers_count,
        "bracket_entry_mode": bracket_entry_mode,
        "total_matches": total_matches,
        "decided_matches": decided_matches,
        "pending_matches": pending_matches,
        "cancelled_matches": cancelled_matches,
        "complete": pending_matches == 0,
    }
