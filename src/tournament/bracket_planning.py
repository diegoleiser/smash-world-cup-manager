"""Pure planning rules for World Championship double-elimination brackets.

This module builds deterministic match and route metadata only. It has no
database or Streamlit dependencies. The route ordering and reversed seed
assignments are project rules and must remain covered by characterization
tests when changed.
"""

from __future__ import annotations

from typing import Any


ENTRY_ALL_WINNERS = "all_winners"
ENTRY_SPLIT_BY_GROUP_SEED = "split_by_group_seed"

BRACKET_SIDE_WINNERS = "winners"
BRACKET_SIDE_LOSERS = "losers"
BRACKET_SIDE_FINALS = "finals"

MIN_BRACKET_SIZE = 4
MAX_BRACKET_SIZE = 32


def get_bracket_size(participant_count: int) -> int:
    """
    Return the smallest supported power-of-two bracket size.

    Examples:
        3-4 players   -> 4
        5-8 players   -> 8
        9-16 players  -> 16
        17-32 players -> 32
    """
    if participant_count < 3:
        raise ValueError(
            "A double-elimination bracket requires at least 3 participants."
        )

    bracket_size = 1 << (participant_count - 1).bit_length()

    if bracket_size < MIN_BRACKET_SIZE:
        bracket_size = MIN_BRACKET_SIZE

    if bracket_size > MAX_BRACKET_SIZE:
        raise ValueError(
            f"Brackets larger than {MAX_BRACKET_SIZE} are not supported."
        )

    return bracket_size


def get_standard_seed_order(bracket_size: int) -> list[int]:
    """
    Return standard seeded bracket positions.

    The returned list is read in pairs.

    Example for an 8-player bracket:
        [1, 8, 4, 5, 2, 7, 3, 6]

    This creates:
        1 vs 8
        4 vs 5
        2 vs 7
        3 vs 6
    """
    if bracket_size < 2 or bracket_size & (bracket_size - 1):
        raise ValueError(
            "Bracket size must be a power of two."
        )

    seed_order = [1, 2]
    current_size = 2

    while current_size < bracket_size:
        next_size = current_size * 2
        seed_order = [
            seed
            for existing_seed in seed_order
            for seed in (
                existing_seed,
                next_size + 1 - existing_seed,
            )
        ]
        current_size = next_size

    return seed_order


def get_first_round_seed_pairs(
    bracket_size: int,
) -> list[tuple[int, int]]:
    """Pair adjacent positions from the standard seed ordering."""
    seed_order = get_standard_seed_order(bracket_size)

    return [
        (
            seed_order[index],
            seed_order[index + 1],
        )
        for index in range(0, len(seed_order), 2)
    ]


def get_split_bracket_seed_pairs(
    bracket_size: int,
) -> dict[str, list[tuple[int, int]]]:
    """
    Split a bracket so that the upper half starts in Winners
    and the lower half starts in Losers.

    Example for size 8:
        Winners: 1 vs 4, 2 vs 3
        Losers:  5 vs 8, 6 vs 7
    """
    if bracket_size < MIN_BRACKET_SIZE:
        raise ValueError(
            f"Bracket size must be at least {MIN_BRACKET_SIZE}."
        )

    if bracket_size & (bracket_size - 1):
        raise ValueError(
            "Bracket size must be a power of two."
        )

    half_size = bracket_size // 2
    half_seed_order = get_standard_seed_order(half_size)

    winners_pairs = [
        (
            half_seed_order[index],
            half_seed_order[index + 1],
        )
        for index in range(0, len(half_seed_order), 2)
    ]

    losers_seed_order = [
        seed + half_size
        for seed in half_seed_order
    ]

    losers_pairs = [
        (
            losers_seed_order[index],
            losers_seed_order[index + 1],
        )
        for index in range(0, len(losers_seed_order), 2)
    ]

    return {
        BRACKET_SIDE_WINNERS: winners_pairs,
        BRACKET_SIDE_LOSERS: losers_pairs,
    }


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
