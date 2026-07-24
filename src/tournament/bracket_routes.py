"""Winner and loser routes for supported double-elimination brackets.

Route order, target slots, and reversed Winners-to-Losers assignments encode
project-specific tournament behavior. Grand Final Reset activation remains a
runtime concern and therefore has no normal incoming route here."""

from __future__ import annotations

from typing import Any

from tournament.bracket_constants import (
    ENTRY_ALL_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
)
from tournament.bracket_seeding import get_bracket_size


def build_all_winners_route_plan(
    participant_count: int,
) -> list[dict[str, Any]]:
    """
    Build winner and loser routes for a standard double-elimination
    bracket in which everyone starts in Winners.

    The Grand Final Reset has no normal incoming route. It is activated
    separately when the Losers-side finalist wins the Grand Final.
    """

    bracket_size = get_bracket_size(participant_count)
    winners_round_count = bracket_size.bit_length() - 1

    routes: list[dict[str, Any]] = []

    def add_route(
        source_code: str,
        source_outcome: str,
        target_code: str,
        target_slot: int,
    ) -> None:
        routes.append(
            {
                "source_code": source_code,
                "source_outcome": source_outcome,
                "target_code": target_code,
                "target_slot": target_slot,
            }
        )

    # Winners advance through the Winners Bracket.
    for round_number in range(
        1,
        winners_round_count,
    ):
        matches_in_round = (
            bracket_size // (2 ** round_number)
        )
        next_round_number = round_number + 1

        for match_number in range(
            1,
            matches_in_round + 1,
        ):
            target_match_number = (
                match_number + 1
            ) // 2

            target_code = (
                "WF"
                if next_round_number
                == winners_round_count
                else (
                    f"W{next_round_number}"
                    f"M{target_match_number}"
                )
            )

            target_slot = (
                1
                if match_number % 2 == 1
                else 2
            )

            add_route(
                f"W{round_number}M{match_number}",
                "winner",
                target_code,
                target_slot,
            )

    # Winners Round 1 losers enter Losers Round 1.
    initial_losers_match_count = bracket_size // 4

    for losers_match_number in range(
        1,
        initial_losers_match_count + 1,
    ):
        first_winners_match = (
            2 * losers_match_number - 1
        )
        second_winners_match = (
            2 * losers_match_number
        )

        add_route(
            f"W1M{first_winners_match}",
            "loser",
            f"L1M{losers_match_number}",
            1,
        )

        add_route(
            f"W1M{second_winners_match}",
            "loser",
            f"L1M{losers_match_number}",
            2,
        )

    # Remaining Winners losers enter alternating Losers rounds.
    #
    # Example for an 8-player bracket:
    # L1 winners + W2 losers -> L2
    # L2 winners             -> L3
    #
    # Example for a 16-player bracket:
    # L1 winners + W2 losers -> L2
    # L2 winners             -> L3
    # L3 winners + W3 losers -> L4
    # L4 winners             -> L5
    previous_losers_round = 1
    previous_match_count = initial_losers_match_count

    for winners_round_number in range(
        2,
        winners_round_count,
    ):
        entry_round = previous_losers_round + 1
        entry_match_count = previous_match_count

        # The Winners loser is reversed across this Losers round.
        # This reduces immediate rematches.
        for match_number in range(
            1,
            entry_match_count + 1,
        ):
            reversed_winners_match = (
                entry_match_count
                + 1
                - match_number
            )

            add_route(
                (
                    f"W{winners_round_number}"
                    f"M{reversed_winners_match}"
                ),
                "loser",
                f"L{entry_round}M{match_number}",
                1,
            )

            add_route(
                (
                    f"L{previous_losers_round}"
                    f"M{match_number}"
                ),
                "winner",
                f"L{entry_round}M{match_number}",
                2,
            )

        consolidation_round = entry_round + 1
        consolidation_match_count = (
            entry_match_count // 2
        )

        for match_number in range(
            1,
            entry_match_count + 1,
        ):
            target_match_number = (
                match_number + 1
            ) // 2

            target_slot = (
                1
                if match_number % 2 == 1
                else 2
            )

            add_route(
                f"L{entry_round}M{match_number}",
                "winner",
                (
                    f"L{consolidation_round}"
                    f"M{target_match_number}"
                ),
                target_slot,
            )

        previous_losers_round = consolidation_round
        previous_match_count = consolidation_match_count

    # Last normal Losers match advances to Losers Final.
    add_route(
        f"L{previous_losers_round}M1",
        "winner",
        "LF",
        1,
    )

    # Winners Final loser enters Losers Final.
    add_route(
        "WF",
        "loser",
        "LF",
        2,
    )

    # Both finalists advance to the Grand Final.
    add_route(
        "WF",
        "winner",
        "GF",
        1,
    )

    add_route(
        "LF",
        "winner",
        "GF",
        2,
    )

    return routes


def build_split_bracket_route_plan(
    participant_count: int,
) -> list[dict[str, Any]]:
    """
    Build winner and loser routes for a split-entry bracket.

    The upper half starts in Winners.
    The lower half starts in Losers.
    """

    bracket_size = get_bracket_size(participant_count)
    winners_size = bracket_size // 2
    winners_round_count = (
        winners_size.bit_length() - 1
    )

    routes: list[dict[str, Any]] = []

    def add_route(
        source_code: str,
        source_outcome: str,
        target_code: str,
        target_slot: int,
    ) -> None:
        routes.append(
            {
                "source_code": source_code,
                "source_outcome": source_outcome,
                "target_code": target_code,
                "target_slot": target_slot,
            }
        )

    if winners_round_count == 1:
        add_route(
            "L1M1",
            "winner",
            "LF",
            1,
        )
        add_route(
            "WF",
            "loser",
            "LF",
            2,
        )
        add_route(
            "WF",
            "winner",
            "GF",
            1,
        )
        add_route(
            "LF",
            "winner",
            "GF",
            2,
        )
        return routes

    # Winners advance through the Winners Bracket.
    for round_number in range(
        1,
        winners_round_count,
    ):
        matches_in_round = (
            winners_size // (2 ** round_number)
        )
        next_round_number = round_number + 1

        for match_number in range(
            1,
            matches_in_round + 1,
        ):
            target_match_number = (
                match_number + 1
            ) // 2

            target_code = (
                "WF"
                if next_round_number
                == winners_round_count
                else (
                    f"W{next_round_number}"
                    f"M{target_match_number}"
                )
            )

            add_route(
                f"W{round_number}M{match_number}",
                "winner",
                target_code,
                (
                    1
                    if match_number % 2 == 1
                    else 2
                ),
            )

    initial_losers_match_count = winners_size // 2

    # Initial Losers winners and Winners Round 1 losers
    # meet in Losers Round 2.
    for match_number in range(
        1,
        initial_losers_match_count + 1,
    ):
        add_route(
            f"L1M{match_number}",
            "winner",
            f"L2M{match_number}",
            2,
        )

        reversed_winners_match = (
            initial_losers_match_count
            + 1
            - match_number
        )

        add_route(
            f"W1M{reversed_winners_match}",
            "loser",
            f"L2M{match_number}",
            1,
        )

    losers_round_number = 2
    matches_in_entry_round = (
        initial_losers_match_count
    )

    for winners_round_number in range(
        1,
        winners_round_count,
    ):
        consolidation_round = (
            losers_round_number + 1
        )
        consolidation_match_count = (
            matches_in_entry_round // 2
        )

        for match_number in range(
            1,
            matches_in_entry_round + 1,
        ):
            add_route(
                (
                    f"L{losers_round_number}"
                    f"M{match_number}"
                ),
                "winner",
                (
                    f"L{consolidation_round}"
                    f"M{(match_number + 1) // 2}"
                ),
                (
                    1
                    if match_number % 2 == 1
                    else 2
                ),
            )

        matches_in_entry_round = (
            consolidation_match_count
        )
        losers_round_number += 2

        next_winners_round = (
            winners_round_number + 1
        )

        if next_winners_round < winners_round_count:
            for match_number in range(
                1,
                matches_in_entry_round + 1,
            ):
                add_route(
                    (
                        f"L{losers_round_number - 1}"
                        f"M{match_number}"
                    ),
                    "winner",
                    (
                        f"L{losers_round_number}"
                        f"M{match_number}"
                    ),
                    2,
                )

                reversed_winners_match = (
                    matches_in_entry_round
                    + 1
                    - match_number
                )

                add_route(
                    (
                        f"W{next_winners_round}"
                        f"M{reversed_winners_match}"
                    ),
                    "loser",
                    (
                        f"L{losers_round_number}"
                        f"M{match_number}"
                    ),
                    1,
                )

    last_losers_round = (
        2 * winners_round_count - 1
    )

    add_route(
        f"L{last_losers_round}M1",
        "winner",
        "LF",
        1,
    )

    add_route(
        "WF",
        "loser",
        "LF",
        2,
    )

    add_route(
        "WF",
        "winner",
        "GF",
        1,
    )

    add_route(
        "LF",
        "winner",
        "GF",
        2,
    )

    return routes


def build_bracket_route_plan(
    participant_count: int,
    bracket_entry_mode: str,
) -> list[dict[str, Any]]:
    """
    Build the route plan for the selected bracket entry mode.
    """

    if bracket_entry_mode == ENTRY_ALL_WINNERS:
        return build_all_winners_route_plan(
            participant_count
        )

    if bracket_entry_mode == ENTRY_SPLIT_BY_GROUP_SEED:
        return build_split_bracket_route_plan(
            participant_count
        )

    raise ValueError(
        f"Unsupported bracket entry mode: "
        f"{bracket_entry_mode}"
    )
