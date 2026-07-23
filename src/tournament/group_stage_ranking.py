"""Pure cross-group ranking and bracket-entry assignment."""

from __future__ import annotations

from typing import Any

from tournament.bracket_constants import (
    ENTRY_SPLIT_BY_GROUP_SEED,
)


def _next_power_of_two(value: int) -> int:
    """Return the smallest power of two greater than or equal to ``value``."""

    if value <= 0:
        raise ValueError("The value must be greater than zero.")

    power = 1

    while power < value:
        power *= 2

    return power


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
