"""Deterministic match metadata for supported double-elimination brackets.

This module describes which matches exist. It intentionally does not assign
players, persist records, or advance results."""

from __future__ import annotations

from typing import Any

from tournament.bracket_constants import (
    BRACKET_SIDE_FINALS,
    BRACKET_SIDE_LOSERS,
    BRACKET_SIDE_WINNERS,
    ENTRY_ALL_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
)
from tournament.bracket_seeding import get_bracket_size


def build_split_bracket_plan(
    participant_count: int,
) -> list[dict[str, Any]]:
    """
    Builds the match structure for a split-entry double-elimination
    bracket.

    The upper half starts in Winners.
    The lower half starts in Losers.

    This function only creates match metadata. It does not write
    anything to the database yet.
    """

    bracket_size = get_bracket_size(participant_count)
    winners_size = bracket_size // 2

    winners_round_count = winners_size.bit_length() - 1
    matches: list[dict[str, Any]] = []

    # Winners Bracket
    matches_in_round = winners_size // 2

    for round_number in range(1, winners_round_count + 1):
        for match_number in range(1, matches_in_round + 1):
            is_final = (
                round_number == winners_round_count
                and match_number == 1
            )

            matches.append(
                {
                    "match_code": (
                        "WF"
                        if is_final
                        else f"W{round_number}M{match_number}"
                    ),
                    "bracket_side": BRACKET_SIDE_WINNERS,
                    "round_number": round_number,
                    "match_number": match_number,
                    "round_label": (
                        "Winners Final"
                        if is_final
                        else f"Winners Round {round_number}"
                    ),
                    "match_type": (
                        "winners_final"
                        if is_final
                        else "standard"
                    ),
                }
            )

        matches_in_round //= 2

    # Initial Losers round containing the lower bracket seeds.
    initial_losers_matches = winners_size // 2

    for match_number in range(1, initial_losers_matches + 1):
        matches.append(
            {
                "match_code": f"L1M{match_number}",
                "bracket_side": BRACKET_SIDE_LOSERS,
                "round_number": 1,
                "match_number": match_number,
                "round_label": "Losers Round 1",
                "match_type": "standard",
            }
        )

    # Each non-final Winners round creates:
    # 1. a Losers round receiving Winners losers
    # 2. a consolidation Losers round
    losers_round_number = 2
    matches_in_entry_round = initial_losers_matches

    for winners_round in range(1, winners_round_count):
        # Winners losers enter here.
        for match_number in range(
            1,
            matches_in_entry_round + 1,
        ):
            matches.append(
                {
                    "match_code": (
                        f"L{losers_round_number}"
                        f"M{match_number}"
                    ),
                    "bracket_side": BRACKET_SIDE_LOSERS,
                    "round_number": losers_round_number,
                    "match_number": match_number,
                    "round_label": (
                        f"Losers Round {losers_round_number}"
                    ),
                    "match_type": "standard",
                }
            )

        losers_round_number += 1
        matches_in_entry_round //= 2

        # Winners of the previous Losers round eliminate each other.
        for match_number in range(
            1,
            matches_in_entry_round + 1,
        ):
            matches.append(
                {
                    "match_code": (
                        f"L{losers_round_number}"
                        f"M{match_number}"
                    ),
                    "bracket_side": BRACKET_SIDE_LOSERS,
                    "round_number": losers_round_number,
                    "match_number": match_number,
                    "round_label": (
                        f"Losers Round {losers_round_number}"
                    ),
                    "match_type": "standard",
                }
            )

        losers_round_number += 1

    # The Winners Final loser enters the Losers Final.
    matches.append(
        {
            "match_code": "LF",
            "bracket_side": BRACKET_SIDE_LOSERS,
            "round_number": losers_round_number,
            "match_number": 1,
            "round_label": "Losers Final",
            "match_type": "losers_final",
        }
    )

    # Grand Final
    matches.append(
        {
            "match_code": "GF",
            "bracket_side": BRACKET_SIDE_FINALS,
            "round_number": 1,
            "match_number": 1,
            "round_label": "Grand Final",
            "match_type": "grand_final",
        }
    )

    # Grand Final Reset
    matches.append(
        {
            "match_code": "GFR",
            "bracket_side": BRACKET_SIDE_FINALS,
            "round_number": 2,
            "match_number": 1,
            "round_label": "Grand Final Reset",
            "match_type": "grand_final_reset",
        }
    )

    return matches


def build_all_winners_bracket_plan(
    participant_count: int,
) -> list[dict[str, Any]]:
    """
    Build a standard double-elimination bracket in which every
    participant starts in the Winners Bracket.

    The plan includes:
    - Winners Bracket
    - Losers Bracket
    - Losers Final
    - Grand Final
    - Grand Final Reset
    """

    bracket_size = get_bracket_size(participant_count)
    winners_round_count = bracket_size.bit_length() - 1

    matches: list[dict[str, Any]] = []

    # Winners Bracket
    matches_in_round = bracket_size // 2

    for round_number in range(
        1,
        winners_round_count + 1,
    ):
        for match_number in range(
            1,
            matches_in_round + 1,
        ):
            is_final = (
                round_number == winners_round_count
                and match_number == 1
            )

            matches.append(
                {
                    "match_code": (
                        "WF"
                        if is_final
                        else f"W{round_number}M{match_number}"
                    ),
                    "bracket_side": BRACKET_SIDE_WINNERS,
                    "round_number": round_number,
                    "match_number": match_number,
                    "round_label": (
                        "Winners Final"
                        if is_final
                        else f"Winners Round {round_number}"
                    ),
                    "match_type": (
                        "winners_final"
                        if is_final
                        else "standard"
                    ),
                }
            )

        matches_in_round //= 2

    # Losers Bracket
    #
    # 8-player example:
    # L1: 2 matches
    # L2: 2 matches
    # L3: 1 match
    # LF: 1 match
    #
    # 16-player example:
    # L1: 4 matches
    # L2: 4 matches
    # L3: 2 matches
    # L4: 2 matches
    # L5: 1 match
    # LF: 1 match

    losers_round_number = 1
    losers_match_count = bracket_size // 4

    while losers_match_count >= 1:
        # First round at this size.
        for match_number in range(
            1,
            losers_match_count + 1,
        ):
            matches.append(
                {
                    "match_code": (
                        f"L{losers_round_number}"
                        f"M{match_number}"
                    ),
                    "bracket_side": BRACKET_SIDE_LOSERS,
                    "round_number": losers_round_number,
                    "match_number": match_number,
                    "round_label": (
                        f"Losers Round {losers_round_number}"
                    ),
                    "match_type": "standard",
                }
            )

        losers_round_number += 1

        # At every size except the final size, there is another
        # Losers round with the same number of matches.
        if losers_match_count > 1:
            for match_number in range(
                1,
                losers_match_count + 1,
            ):
                matches.append(
                    {
                        "match_code": (
                            f"L{losers_round_number}"
                            f"M{match_number}"
                        ),
                        "bracket_side": BRACKET_SIDE_LOSERS,
                        "round_number": losers_round_number,
                        "match_number": match_number,
                        "round_label": (
                            f"Losers Round "
                            f"{losers_round_number}"
                        ),
                        "match_type": "standard",
                    }
                )

            losers_round_number += 1

        losers_match_count //= 2

    matches.append(
        {
            "match_code": "LF",
            "bracket_side": BRACKET_SIDE_LOSERS,
            "round_number": losers_round_number,
            "match_number": 1,
            "round_label": "Losers Final",
            "match_type": "losers_final",
        }
    )

    matches.append(
        {
            "match_code": "GF",
            "bracket_side": BRACKET_SIDE_FINALS,
            "round_number": 1,
            "match_number": 1,
            "round_label": "Grand Final",
            "match_type": "grand_final",
        }
    )

    matches.append(
        {
            "match_code": "GFR",
            "bracket_side": BRACKET_SIDE_FINALS,
            "round_number": 2,
            "match_number": 1,
            "round_label": "Grand Final Reset",
            "match_type": "grand_final_reset",
        }
    )

    return matches


def build_bracket_plan(
    participant_count: int,
    bracket_entry_mode: str,
) -> list[dict[str, Any]]:
    """
    Build the match plan for the selected bracket entry mode.
    """

    if bracket_entry_mode == ENTRY_SPLIT_BY_GROUP_SEED:
        return build_split_bracket_plan(
            participant_count
        )

    if bracket_entry_mode == ENTRY_ALL_WINNERS:
        return build_all_winners_bracket_plan(
            participant_count
        )

    raise ValueError(
        f"Unsupported bracket entry mode: "
        f"{bracket_entry_mode}"
    )
