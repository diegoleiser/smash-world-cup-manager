#!/usr/bin/env python3
"""Create and manage Smash World Championship tournament drafts."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any
import smash_statistics as stats


FORMAT_GROUP_STAGE = "group_stage_double_elimination"
FORMAT_DOUBLE_ELIMINATION = "double_elimination"

ENTRY_ALL_WINNERS = "all_winners"
ENTRY_SPLIT_BY_GROUP_SEED = "split_by_group_seed"

VALID_FORMATS = {
    FORMAT_GROUP_STAGE,
    FORMAT_DOUBLE_ELIMINATION,
}

VALID_ENTRY_MODES = {
    ENTRY_ALL_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
}

VALID_START_POSITIONS = {
    "winners",
    "losers",
}

GROUP_MATCH_PENDING = "pending"
GROUP_MATCH_COMPLETED = "completed"
GROUP_MATCH_FORFEIT = "forfeit"
GROUP_MATCH_CANCELLED = "cancelled"

VALID_GROUP_MATCH_STATUSES = {
    GROUP_MATCH_PENDING,
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
    GROUP_MATCH_CANCELLED,
}

BRACKET_START_ALL_WINNERS = "all_winners"
BRACKET_START_SPLIT = "split_by_group_seed"

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

def create_draft_bracket_matches(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """
    Create the empty bracket match structure for the draft's
    selected entry mode.
    """

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                bracket_entry_mode,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        if draft["status"] != "draft":
            raise ValueError(
                "The bracket can only be generated while "
                "the tournament is still a draft."
            )

        existing_match = connection.execute(
            """
            SELECT 1
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()

        if existing_match is not None:
            raise ValueError(
                "The bracket has already been generated."
            )

        seed_rows = connection.execute(
            """
            SELECT
                player_id,
                bracket_seed,
                starts_in
            FROM tournament_draft_bracket_seeds
            WHERE draft_id = ?
            ORDER BY bracket_seed
            """,
            (draft_id,),
        ).fetchall()

        if len(seed_rows) < 3:
            raise ValueError(
                "Create the bracket seed snapshot before "
                "generating the bracket."
            )

        participant_count = len(seed_rows)
        bracket_entry_mode = str(
            draft["bracket_entry_mode"]
        )

        match_plan = build_bracket_plan(
            participant_count,
            bracket_entry_mode,
        )

        created_matches: list[dict[str, Any]] = []

        for match in match_plan:
            bracket_match_id = (
                f"bracket_match_{uuid.uuid4().hex}"
            )

            initial_status = (
                "inactive"
                if match["match_type"]
                == "grand_final_reset"
                else "waiting"
            )

            connection.execute(
                """
                INSERT INTO tournament_draft_bracket_matches (
                    bracket_match_id,
                    draft_id,
                    match_code,
                    bracket_side,
                    round_number,
                    match_number,
                    round_label,
                    match_type,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bracket_match_id,
                    draft_id,
                    match["match_code"],
                    match["bracket_side"],
                    match["round_number"],
                    match["match_number"],
                    match["round_label"],
                    match["match_type"],
                    initial_status,
                ),
            )

            created_matches.append(
                {
                    **match,
                    "bracket_match_id": bracket_match_id,
                    "status": initial_status,
                }
            )

    return created_matches

def create_draft_bracket_routes(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """
    Create all winner and loser routes for the draft's
    selected bracket entry mode.
    """

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT bracket_entry_mode
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        seed_count_row = connection.execute(
            """
            SELECT COUNT(*) AS participant_count
            FROM tournament_draft_bracket_seeds
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        participant_count = int(
            seed_count_row["participant_count"]
        )

        if participant_count < 3:
            raise ValueError(
                "Create the bracket seed snapshot first."
            )

        match_rows = connection.execute(
            """
            SELECT
                bracket_match_id,
                match_code
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchall()

        if not match_rows:
            raise ValueError(
                "Generate the bracket matches first."
            )

        existing_route = connection.execute(
            """
            SELECT 1
            FROM tournament_draft_bracket_routes
            WHERE draft_id = ?
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()

        if existing_route is not None:
            raise ValueError(
                "Bracket routes have already been generated."
            )

        match_id_by_code = {
            str(row["match_code"]): str(
                row["bracket_match_id"]
            )
            for row in match_rows
        }

        route_plan = build_bracket_route_plan(
            participant_count,
            str(draft["bracket_entry_mode"]),
        )

        created_routes: list[dict[str, Any]] = []

        for route in route_plan:
            source_code = str(route["source_code"])
            target_code = str(route["target_code"])

            if source_code not in match_id_by_code:
                raise ValueError(
                    f"Source bracket match not found: "
                    f"{source_code}"
                )

            if target_code not in match_id_by_code:
                raise ValueError(
                    f"Target bracket match not found: "
                    f"{target_code}"
                )

            route_id = (
                f"bracket_route_{uuid.uuid4().hex}"
            )

            connection.execute(
                """
                INSERT INTO tournament_draft_bracket_routes (
                    route_id,
                    draft_id,
                    source_match_id,
                    source_outcome,
                    target_match_id,
                    target_slot
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    route_id,
                    draft_id,
                    match_id_by_code[source_code],
                    route["source_outcome"],
                    match_id_by_code[target_code],
                    route["target_slot"],
                ),
            )

            created_routes.append(
                {
                    "route_id": route_id,
                    **route,
                }
            )

    return created_routes

def seed_draft_bracket_matches(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """
    Assign the bracket seed snapshot to the initial matches.

    Supports:
    - all participants starting in Winners
    - split entry between Winners and Losers

    Initial matches become:
    - pending with two players
    - bye with one player
    - cancelled with no players
    """

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT bracket_entry_mode
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        seed_rows = connection.execute(
            """
            SELECT
                player_id,
                bracket_seed,
                starts_in
            FROM tournament_draft_bracket_seeds
            WHERE draft_id = ?
            ORDER BY bracket_seed
            """,
            (draft_id,),
        ).fetchall()

        if len(seed_rows) < 3:
            raise ValueError(
                "Create the bracket seed snapshot first."
            )

        bracket_matches_exist = connection.execute(
            """
            SELECT 1
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()

        if bracket_matches_exist is None:
            raise ValueError(
                "Generate the bracket matches before assigning seeds."
            )

        participant_count = len(seed_rows)
        bracket_size = get_bracket_size(participant_count)

        seed_to_player = {
            int(row["bracket_seed"]): str(row["player_id"])
            for row in seed_rows
        }

        bracket_entry_mode = str(
            draft["bracket_entry_mode"]
        )

        if bracket_entry_mode == ENTRY_ALL_WINNERS:
            initial_match_groups = {
                BRACKET_SIDE_WINNERS:
                    get_first_round_seed_pairs(
                        bracket_size
                    ),
            }

        elif (
            bracket_entry_mode
            == ENTRY_SPLIT_BY_GROUP_SEED
        ):
            initial_match_groups = (
                get_split_bracket_seed_pairs(
                    bracket_size
                )
            )

        else:
            raise ValueError(
                "Unsupported bracket entry mode: "
                f"{bracket_entry_mode}"
            )

        updated_matches: list[dict[str, Any]] = []

        for bracket_side, seed_pairs in (
            initial_match_groups.items()
        ):
            for match_number, (
                player_1_seed,
                player_2_seed,
            ) in enumerate(seed_pairs, start=1):
                if (
                    bracket_side
                    == BRACKET_SIDE_WINNERS
                ):
                    match_code = f"W1M{match_number}"
                else:
                    match_code = f"L1M{match_number}"

                player_1_id = seed_to_player.get(
                    player_1_seed
                )
                player_2_id = seed_to_player.get(
                    player_2_seed
                )

                if (
                    player_1_id is not None
                    and player_2_id is not None
                ):
                    status = "pending"
                    winner_id = None
                    completed_at_sql = "NULL"

                elif player_1_id is not None:
                    status = "bye"
                    winner_id = player_1_id
                    completed_at_sql = (
                        "CURRENT_TIMESTAMP"
                    )

                elif player_2_id is not None:
                    status = "bye"
                    winner_id = player_2_id
                    completed_at_sql = (
                        "CURRENT_TIMESTAMP"
                    )

                else:
                    status = "cancelled"
                    winner_id = None
                    completed_at_sql = (
                        "CURRENT_TIMESTAMP"
                    )

                cursor = connection.execute(
                    f"""
                    UPDATE tournament_draft_bracket_matches
                    SET
                        player_1_id = ?,
                        player_2_id = ?,
                        winner_id = ?,
                        player_1_score = NULL,
                        player_2_score = NULL,
                        status = ?,
                        completed_at = {completed_at_sql},
                        updated_at = CURRENT_TIMESTAMP
                    WHERE draft_id = ?
                      AND match_code = ?
                    """,
                    (
                        player_1_id,
                        player_2_id,
                        winner_id,
                        status,
                        draft_id,
                        match_code,
                    ),
                )

                if cursor.rowcount != 1:
                    raise ValueError(
                        "Initial bracket match not found: "
                        f"{match_code}"
                    )

                updated_matches.append(
                    {
                        "match_code": match_code,
                        "bracket_side": bracket_side,
                        "player_1_seed": player_1_seed,
                        "player_2_seed": player_2_seed,
                        "player_1_id": player_1_id,
                        "player_2_id": player_2_id,
                        "winner_id": winner_id,
                        "status": status,
                    }
                )

    return updated_matches

def generate_draft_bracket(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """
    Generate a complete double-elimination bracket.

    Steps:
    1. Create the final seed snapshot
    2. Create all bracket matches
    3. Create winner and loser routes
    4. Assign players to the initial matches
    5. Propagate automatic byes

    The function supports both:
    - all_winners
    - split_by_group_seed
    """

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                bracket_entry_mode,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        if str(draft["status"]) != "draft":
            raise ValueError(
                "The bracket can only be generated while "
                "the tournament is still a draft."
            )

        existing_match = connection.execute(
            """
            SELECT 1
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()

        if existing_match is not None:
            raise ValueError(
                "The bracket has already been generated."
            )

    seed_snapshot_created = False

    try:
        seed_rows = create_draft_bracket_seed_snapshot(
            db_path,
            draft_id,
        )
        seed_snapshot_created = True

        created_matches = create_draft_bracket_matches(
            db_path,
            draft_id,
        )

        created_routes = create_draft_bracket_routes(
            db_path,
            draft_id,
        )

        seeded_matches = seed_draft_bracket_matches(
            db_path,
            draft_id,
        )

        propagated_changes = (
            propagate_draft_bracket_results(
                db_path,
                draft_id,
            )
        )

    except Exception:
        # The individual helper functions use separate transactions.
        # Remove partial bracket data if a later step fails.
        with connect_db(db_path) as connection:
            connection.execute(
                """
                DELETE FROM tournament_draft_bracket_routes
                WHERE draft_id = ?
                """,
                (draft_id,),
            )

            connection.execute(
                """
                DELETE FROM tournament_draft_bracket_matches
                WHERE draft_id = ?
                """,
                (draft_id,),
            )

            if seed_snapshot_created:
                connection.execute(
                    """
                    DELETE FROM tournament_draft_bracket_seeds
                    WHERE draft_id = ?
                    """,
                    (draft_id,),
                )

                connection.execute(
                    """
                    UPDATE tournament_draft_participants
                    SET bracket_seed = NULL
                    WHERE draft_id = ?
                    """,
                    (draft_id,),
                )

        raise

    bracket_size = get_bracket_size(
        len(seed_rows)
    )

    return {
        "draft_id": draft_id,
        "participant_count": len(seed_rows),
        "bracket_size": bracket_size,
        "bracket_entry_mode": str(
            draft["bracket_entry_mode"]
        ),
        "seed_rows": seed_rows,
        "matches_created": len(created_matches),
        "routes_created": len(created_routes),
        "initial_matches_seeded": len(
            seeded_matches
        ),
        "automatic_progressions": (
            propagated_changes
        ),
    }

def reset_draft_bracket(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, int]:
    """
    Remove the generated bracket and unlock bracket generation again.

    Group-stage data and results are preserved.
    """

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        if str(draft["status"]) != "draft":
            raise ValueError(
                "The bracket can only be reset while "
                "the tournament is still a draft."
            )

        route_count = int(
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM tournament_draft_bracket_routes
                WHERE draft_id = ?
                """,
                (draft_id,),
            ).fetchone()["count"]
        )

        match_count = int(
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM tournament_draft_bracket_matches
                WHERE draft_id = ?
                """,
                (draft_id,),
            ).fetchone()["count"]
        )

        seed_count = int(
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM tournament_draft_bracket_seeds
                WHERE draft_id = ?
                """,
                (draft_id,),
            ).fetchone()["count"]
        )

        # Routes would also be removed through ON DELETE CASCADE,
        # but deleting them explicitly makes the operation clear.
        connection.execute(
            """
            DELETE FROM tournament_draft_bracket_routes
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

        connection.execute(
            """
            DELETE FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

        connection.execute(
            """
            DELETE FROM tournament_draft_bracket_seeds
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

        connection.execute(
            """
            UPDATE tournament_draft_participants
            SET bracket_seed = NULL
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

    return {
        "routes_deleted": route_count,
        "matches_deleted": match_count,
        "seeds_deleted": seed_count,
    }

def get_draft_bracket_matches(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """
    Return all bracket matches with player and winner names.
    """

    with connect_db(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                bm.bracket_match_id,
                bm.match_code,
                bm.bracket_side,
                bm.round_number,
                bm.match_number,
                bm.round_label,
                bm.match_type,

                bm.player_1_id,
                p1.display_name AS player_1_name,

                bm.player_2_id,
                p2.display_name AS player_2_name,

                bm.winner_id,
                winner.display_name AS winner_name,

                bm.player_1_score,
                bm.player_2_score,
                bm.status,

                bm.completed_at,
                bm.created_at,
                bm.updated_at

            FROM tournament_draft_bracket_matches AS bm

            LEFT JOIN players AS p1
              ON p1.player_id = bm.player_1_id

            LEFT JOIN players AS p2
              ON p2.player_id = bm.player_2_id

            LEFT JOIN players AS winner
              ON winner.player_id = bm.winner_id

            WHERE bm.draft_id = ?

            ORDER BY
                CASE bm.bracket_side
                    WHEN 'winners' THEN 1
                    WHEN 'losers' THEN 2
                    WHEN 'finals' THEN 3
                    ELSE 4
                END,
                bm.round_number,
                bm.match_number
            """,
            (draft_id,),
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]

def get_draft_bracket_routes(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """Return all winner and loser routes of a generated bracket."""

    with connect_db(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                r.route_id,
                r.source_match_id,
                source.match_code AS source_code,
                r.source_outcome,
                r.target_match_id,
                target.match_code AS target_code,
                r.target_slot
            FROM tournament_draft_bracket_routes AS r
            JOIN tournament_draft_bracket_matches AS source
              ON source.bracket_match_id = r.source_match_id
            JOIN tournament_draft_bracket_matches AS target
              ON target.bracket_match_id = r.target_match_id
            WHERE r.draft_id = ?
            ORDER BY
                CASE source.bracket_side
                    WHEN 'winners' THEN 1
                    WHEN 'losers' THEN 2
                    WHEN 'finals' THEN 3
                    ELSE 4
                END,
                source.round_number,
                source.match_number,
                r.source_outcome
            """,
            (draft_id,),
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]

def get_draft_bracket_state(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """
    Return a compact summary of the generated bracket.
    """

    matches = get_draft_bracket_matches(
        db_path,
        draft_id,
    )

    routes = get_draft_bracket_routes(
        db_path,
        draft_id,
    )

    champion_id = get_draft_bracket_champion(
        db_path,
        draft_id,
    )

    champion_name: str | None = None

    if champion_id is not None:
        with connect_db(db_path) as connection:
            champion = connection.execute(
                """
                SELECT display_name
                FROM players
                WHERE player_id = ?
                """,
                (champion_id,),
            ).fetchone()

        if champion is not None:
            champion_name = str(
                champion["display_name"]
            )

    return {
        "generated": bool(matches),
        "matches": matches,
        "match_count": len(matches),
        "routes": routes,
        "route_count": len(routes),
        "pending_count": sum(
            match["status"] == "pending"
            for match in matches
        ),
        "waiting_count": sum(
            match["status"] == "waiting"
            for match in matches
        ),
        "completed_count": sum(
            match["status"]
            in {"completed", "forfeit", "bye"}
            for match in matches
        ),
        "champion_id": champion_id,
        "champion_name": champion_name,
    }

def _get_bracket_match_loser_id(
    match: sqlite3.Row | dict[str, Any],
) -> str | None:
    """Return the losing player of a decided two-player match."""

    player_1_id = match["player_1_id"]
    player_2_id = match["player_2_id"]
    winner_id = match["winner_id"]

    if (
        player_1_id is None
        or player_2_id is None
        or winner_id is None
    ):
        return None

    player_1_id = str(player_1_id)
    player_2_id = str(player_2_id)
    winner_id = str(winner_id)

    if winner_id == player_1_id:
        return player_2_id

    if winner_id == player_2_id:
        return player_1_id

    raise ValueError(
        "A bracket winner is not one of the assigned players."
    )


def get_draft_finalization_preview(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """
    Validate a completed draft and calculate its archive preview.

    This function does not modify the database.

    Placements are calculated from:
    - Champion
    - Grand Final or Grand Final Reset loser
    - Losers Final loser
    - remaining Losers Bracket elimination rounds
    """

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                draft_id,
                tournament_number,
                tournament_date,
                format_type,
                bracket_entry_mode,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        if str(draft["status"]) != "draft":
            raise ValueError(
                "Only an unfinished tournament draft can be finalized."
            )

        if not draft["tournament_date"]:
            raise ValueError(
                "Set a tournament date before finalizing the tournament."
            )

        existing_tournament = connection.execute(
            """
            SELECT tournament_id
            FROM tournaments
            WHERE tournament_number = ?
            """,
            (draft["tournament_number"],),
        ).fetchone()

        if existing_tournament is not None:
            raise ValueError(
                f"WC {int(draft['tournament_number']):02d} "
                "already exists in the archive."
            )

        participant_rows = connection.execute(
            """
            SELECT
                dp.player_id,
                p.display_name AS player,
                dp.manual_seed,
                dp.bracket_seed
            FROM tournament_draft_participants AS dp
            JOIN players AS p
              ON p.player_id = dp.player_id
            WHERE dp.draft_id = ?
            ORDER BY
                dp.bracket_seed,
                dp.manual_seed,
                p.display_name COLLATE NOCASE
            """,
            (draft_id,),
        ).fetchall()

        if len(participant_rows) < 3:
            raise ValueError(
                "At least 3 participants are required."
            )

        bracket_rows = connection.execute(
            """
            SELECT
                bracket_match_id,
                match_code,
                bracket_side,
                round_number,
                match_number,
                round_label,
                match_type,
                player_1_id,
                player_2_id,
                winner_id,
                player_1_score,
                player_2_score,
                status,
                completed_at
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            ORDER BY
                CASE bracket_side
                    WHEN 'winners' THEN 1
                    WHEN 'losers' THEN 2
                    WHEN 'finals' THEN 3
                    ELSE 4
                END,
                round_number,
                match_number
            """,
            (draft_id,),
        ).fetchall()

        if not bracket_rows:
            raise ValueError(
                "Generate and complete the bracket before finalizing."
            )

        unfinished_bracket_matches = [
            str(match["match_code"])
            for match in bracket_rows
            if str(match["status"]) in {
                "pending",
                "waiting",
            }
        ]

        if unfinished_bracket_matches:
            raise ValueError(
                "The bracket is not complete. Unfinished matches: "
                + ", ".join(unfinished_bracket_matches)
            )

        group_match_rows: list[sqlite3.Row] = []

        if str(draft["format_type"]) == FORMAT_GROUP_STAGE:
            group_match_rows = connection.execute(
                """
                SELECT
                    gm.group_match_id,
                    g.group_number,
                    g.group_name,
                    gm.round_number,
                    gm.match_number,
                    gm.player_1_id,
                    gm.player_2_id,
                    gm.winner_id,
                    gm.player_1_score,
                    gm.player_2_score,
                    gm.status,
                    gm.completed_at
                FROM tournament_draft_group_matches AS gm
                JOIN tournament_draft_groups AS g
                  ON g.group_id = gm.group_id
                WHERE g.draft_id = ?
                ORDER BY
                    g.group_number,
                    gm.round_number,
                    gm.match_number
                """,
                (draft_id,),
            ).fetchall()

            if not group_match_rows:
                raise ValueError(
                    "The group-stage matches are missing."
                )

            unfinished_group_matches = [
                (
                    f"{match['group_name']} "
                    f"Round {match['round_number']} "
                    f"Match {match['match_number']}"
                )
                for match in group_match_rows
                if str(match["status"]) == GROUP_MATCH_PENDING
            ]

            if unfinished_group_matches:
                raise ValueError(
                    "The group stage is not complete. "
                    "Unfinished matches: "
                    + ", ".join(unfinished_group_matches)
                )

        player_names = {
            str(player["player_id"]): str(player["player"])
            for player in participant_rows
        }

        match_by_code = {
            str(match["match_code"]): match
            for match in bracket_rows
        }

        grand_final = match_by_code.get("GF")
        reset_final = match_by_code.get("GFR")
        losers_final = match_by_code.get("LF")

        if (
            grand_final is None
            or reset_final is None
            or losers_final is None
        ):
            raise ValueError(
                "Grand Final, Grand Final Reset, or "
                "Losers Final is missing."
            )

        champion_id = get_draft_bracket_champion(
            db_path,
            draft_id,
        )

        if champion_id is None:
            raise ValueError(
                "The bracket does not have a confirmed champion."
            )

        placements: dict[str, int] = {
            champion_id: 1,
        }

        if str(reset_final["status"]) in {
            "completed",
            "forfeit",
        }:
            runner_up_id = _get_bracket_match_loser_id(
                reset_final
            )
        else:
            runner_up_id = _get_bracket_match_loser_id(
                grand_final
            )

        if runner_up_id is None:
            raise ValueError(
                "The runner-up could not be determined."
            )

        placements[runner_up_id] = 2

        third_place_id = _get_bracket_match_loser_id(
            losers_final
        )

        if third_place_id is None:
            raise ValueError(
                "Third place could not be determined."
            )

        placements[third_place_id] = 3

        elimination_groups: dict[int, list[str]] = {}

        for match in bracket_rows:
            if str(match["bracket_side"]) != BRACKET_SIDE_LOSERS:
                continue

            if str(match["match_code"]) == "LF":
                continue

            if str(match["status"]) not in {
                "completed",
                "forfeit",
            }:
                continue

            loser_id = _get_bracket_match_loser_id(
                match
            )

            if loser_id is None:
                continue

            if loser_id in placements:
                continue

            round_number = int(match["round_number"])

            elimination_groups.setdefault(
                round_number,
                [],
            ).append(loser_id)

        next_placement = 4

        for round_number in sorted(
            elimination_groups,
            reverse=True,
        ):
            eliminated_player_ids = list(
                dict.fromkeys(
                    elimination_groups[round_number]
                )
            )

            for player_id in eliminated_player_ids:
                placements[player_id] = next_placement

            next_placement += len(
                eliminated_player_ids
            )

        participant_ids = {
            str(player["player_id"])
            for player in participant_rows
        }

        placed_player_ids = set(placements)

        if placed_player_ids != participant_ids:
            missing_player_ids = sorted(
                participant_ids - placed_player_ids
            )

            missing_names = [
                player_names.get(player_id, player_id)
                for player_id in missing_player_ids
            ]

            raise ValueError(
                "Placements could not be calculated for: "
                + ", ".join(missing_names)
            )

        placement_rows = sorted(
            [
                {
                    "player_id": player_id,
                    "player": player_names[player_id],
                    "placement": placement,
                    "seed": next(
                        (
                            int(player["bracket_seed"])
                            for player in participant_rows
                            if (
                                str(player["player_id"])
                                == player_id
                                and player["bracket_seed"]
                                is not None
                            )
                        ),
                        None,
                    ),
                }
                for player_id, placement in placements.items()
            ],
            key=lambda row: (
                int(row["placement"]),
                str(row["player"]).casefold(),
            ),
        )

        archived_group_matches = [
            match
            for match in group_match_rows
            if str(match["status"]) in {
                GROUP_MATCH_COMPLETED,
                GROUP_MATCH_FORFEIT,
            }
        ]

        archived_bracket_matches = [
            match
            for match in bracket_rows
            if str(match["status"]) in {
                "completed",
                "forfeit",
            }
        ]

    return {
        "draft_id": draft_id,
        "tournament_number": int(
            draft["tournament_number"]
        ),
        "tournament_date": str(
            draft["tournament_date"]
        ),
        "format_type": str(
            draft["format_type"]
        ),
        "bracket_entry_mode": str(
            draft["bracket_entry_mode"]
        ),
        "participant_count": len(
            participant_rows
        ),
        "champion_id": champion_id,
        "champion_name": player_names[
            champion_id
        ],
        "placements": placement_rows,
        "group_matches_to_archive": len(
            archived_group_matches
        ),
        "bracket_matches_to_archive": len(
            archived_bracket_matches
        ),
        "matches_to_archive": (
            len(archived_group_matches)
            + len(archived_bracket_matches)
        ),
        "cancelled_group_matches_omitted": sum(
            str(match["status"])
            == GROUP_MATCH_CANCELLED
            for match in group_match_rows
        ),
        "automatic_bracket_matches_omitted": sum(
            str(match["status"]) in {
                "bye",
                "cancelled",
                "inactive",
            }
            for match in bracket_rows
        ),
        "ready": True,
    }

def finalize_draft_tournament(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """
    Archive a completed tournament draft.

    The operation writes:
    - tournament
    - tournament participants and placements
    - completed group-stage matches
    - completed bracket matches

    The draft is marked as completed only after every archive row
    has been inserted successfully.
    """

    preview = get_draft_finalization_preview(
        db_path,
        draft_id,
    )

    tournament_id = (
        f"tournament_{uuid.uuid4().hex}"
    )

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                draft_id,
                tournament_number,
                tournament_date,
                format_type,
                bracket_entry_mode,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        if str(draft["status"]) != "draft":
            raise ValueError(
                "Only an unfinished draft can be finalized."
            )

        existing_tournament = connection.execute(
            """
            SELECT tournament_id
            FROM tournaments
            WHERE tournament_number = ?
            """,
            (preview["tournament_number"],),
        ).fetchone()

        if existing_tournament is not None:
            raise ValueError(
                f"WC {preview['tournament_number']:02d} "
                "already exists in the archive."
            )

        connection.execute(
            """
            INSERT INTO tournaments (
                tournament_id,
                tournament_number,
                tournament_date,
                winner_id,
                challonge_url,
                bracket_source,
                match_data_available,
                notes
            )
            VALUES (?, ?, ?, ?, NULL, ?, 1, ?)
            """,
            (
                tournament_id,
                preview["tournament_number"],
                preview["tournament_date"],
                preview["champion_id"],
                "tournament_manager",
                (
                    "Created from Tournament Manager draft "
                    f"{draft_id}. Format: "
                    f"{preview['format_type']}; bracket entry: "
                    f"{preview['bracket_entry_mode']}."
                ),
            ),
        )

        for placement in preview["placements"]:
            connection.execute(
                """
                INSERT INTO tournament_participants (
                    tournament_id,
                    player_id,
                    placement,
                    seed
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    tournament_id,
                    placement["player_id"],
                    placement["placement"],
                    placement["seed"],
                ),
            )

        play_order = 1
        archived_group_matches = 0
        archived_bracket_matches = 0

        if (
            preview["format_type"]
            == FORMAT_GROUP_STAGE
        ):
            group_matches = connection.execute(
                """
                SELECT
                    gm.group_match_id,
                    g.group_name,
                    gm.round_number,
                    gm.match_number,
                    gm.player_1_id,
                    gm.player_2_id,
                    gm.winner_id,
                    gm.player_1_score,
                    gm.player_2_score,
                    gm.status,
                    gm.completed_at
                FROM tournament_draft_group_matches AS gm
                JOIN tournament_draft_groups AS g
                  ON g.group_id = gm.group_id
                WHERE g.draft_id = ?
                  AND gm.status IN (
                      'completed',
                      'forfeit'
                  )
                ORDER BY
                    g.group_number,
                    gm.round_number,
                    gm.match_number
                """,
                (draft_id,),
            ).fetchall()

            for match in group_matches:
                is_completed = (
                    str(match["status"])
                    == GROUP_MATCH_COMPLETED
                )

                connection.execute(
                    """
                    INSERT INTO matches (
                        match_id,
                        tournament_id,
                        stage,
                        round_label,
                        bracket_side,
                        player_1_id,
                        player_2_id,
                        winner_id,
                        player_1_score,
                        player_2_score,
                        score_known,
                        walkover,
                        source,
                        suggested_play_order,
                        completed_at
                    )
                    VALUES (
                        ?, ?, 'group_stage', ?, 'group',
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?
                    )
                    """,
                    (
                        f"match_{uuid.uuid4().hex}",
                        tournament_id,
                        (
                            f"{match['group_name']} · "
                            f"Round {match['round_number']}"
                        ),
                        match["player_1_id"],
                        match["player_2_id"],
                        match["winner_id"],
                        (
                            match["player_1_score"]
                            if is_completed
                            else None
                        ),
                        (
                            match["player_2_score"]
                            if is_completed
                            else None
                        ),
                        int(is_completed),
                        int(not is_completed),
                        "tournament_manager",
                        play_order,
                        match["completed_at"],
                    ),
                )

                play_order += 1
                archived_group_matches += 1

        bracket_matches = connection.execute(
            """
            SELECT
                bracket_match_id,
                match_code,
                bracket_side,
                round_label,
                player_1_id,
                player_2_id,
                winner_id,
                player_1_score,
                player_2_score,
                status,
                completed_at
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
              AND status IN (
                  'completed',
                  'forfeit'
              )
            ORDER BY
                CASE bracket_side
                    WHEN 'winners' THEN 1
                    WHEN 'losers' THEN 2
                    WHEN 'finals' THEN 3
                    ELSE 4
                END,
                round_number,
                match_number
            """,
            (draft_id,),
        ).fetchall()

        for match in bracket_matches:
            is_completed = (
                str(match["status"]) == "completed"
            )

            connection.execute(
                """
                INSERT INTO matches (
                    match_id,
                    tournament_id,
                    stage,
                    round_label,
                    bracket_side,
                    player_1_id,
                    player_2_id,
                    winner_id,
                    player_1_score,
                    player_2_score,
                    score_known,
                    walkover,
                    source,
                    suggested_play_order,
                    completed_at
                )
                VALUES (
                    ?, ?, 'bracket', ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?
                )
                """,
                (
                    f"match_{uuid.uuid4().hex}",
                    tournament_id,
                    (
                        f"{match['round_label']} "
                        f"({match['match_code']})"
                    ),
                    match["bracket_side"],
                    match["player_1_id"],
                    match["player_2_id"],
                    match["winner_id"],
                    (
                        match["player_1_score"]
                        if is_completed
                        else None
                    ),
                    (
                        match["player_2_score"]
                        if is_completed
                        else None
                    ),
                    int(is_completed),
                    int(not is_completed),
                    "tournament_manager",
                    play_order,
                    match["completed_at"],
                ),
            )

            play_order += 1
            archived_bracket_matches += 1

        connection.execute(
            """
            UPDATE tournament_drafts
            SET
                status = 'completed',
                updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

    return {
        "tournament_id": tournament_id,
        "tournament_number":
            preview["tournament_number"],
        "champion_id":
            preview["champion_id"],
        "champion_name":
            preview["champion_name"],
        "participant_count":
            preview["participant_count"],
        "group_matches_archived":
            archived_group_matches,
        "bracket_matches_archived":
            archived_bracket_matches,
        "matches_archived": (
            archived_group_matches
            + archived_bracket_matches
        ),
        "draft_status": "completed",
    }

def create_draft_split_bracket_matches(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """
    Creates the empty split-entry bracket match structure.

    Requires an existing bracket seed snapshot.
    Routes and automatic bye progression are added separately.
    """

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                bracket_entry_mode,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        if draft["status"] != "draft":
            raise ValueError(
                "The bracket can only be generated while "
                "the tournament is still a draft."
            )

        if (
            draft["bracket_entry_mode"]
            != ENTRY_SPLIT_BY_GROUP_SEED
        ):
            raise ValueError(
                "This function only creates split-entry brackets."
            )

        existing_match = connection.execute(
            """
            SELECT 1
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()

        if existing_match is not None:
            raise ValueError(
                "The bracket has already been generated."
            )

        seed_rows = connection.execute(
            """
            SELECT
                player_id,
                bracket_seed,
                starts_in
            FROM tournament_draft_bracket_seeds
            WHERE draft_id = ?
            ORDER BY bracket_seed
            """,
            (draft_id,),
        ).fetchall()

        if len(seed_rows) < 3:
            raise ValueError(
                "Create the bracket seed snapshot before "
                "generating the bracket."
            )

        participant_count = len(seed_rows)
        match_plan = build_split_bracket_plan(
            participant_count
        )

        created_matches: list[dict[str, Any]] = []

        for match in match_plan:
            bracket_match_id = (
                f"bracket_match_{uuid.uuid4().hex}"
            )

            initial_status = (
                "inactive"
                if match["match_type"]
                == "grand_final_reset"
                else "waiting"
            )

            connection.execute(
                """
                INSERT INTO tournament_draft_bracket_matches (
                    bracket_match_id,
                    draft_id,
                    match_code,
                    bracket_side,
                    round_number,
                    match_number,
                    round_label,
                    match_type,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bracket_match_id,
                    draft_id,
                    match["match_code"],
                    match["bracket_side"],
                    match["round_number"],
                    match["match_number"],
                    match["round_label"],
                    match["match_type"],
                    initial_status,
                ),
            )

            created_matches.append(
                {
                    **match,
                    "bracket_match_id": bracket_match_id,
                    "status": initial_status,
                }
            )

    return created_matches

def seed_draft_split_bracket_matches(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """
    Assign the bracket seed snapshot to the initial Winners
    and Losers matches.

    Matches with:
    - two players become pending
    - one player become a bye
    - no players become cancelled
    """

    with connect_db(db_path) as connection:
        seed_rows = connection.execute(
            """
            SELECT
                player_id,
                bracket_seed,
                starts_in
            FROM tournament_draft_bracket_seeds
            WHERE draft_id = ?
            ORDER BY bracket_seed
            """,
            (draft_id,),
        ).fetchall()

        if len(seed_rows) < 3:
            raise ValueError(
                "Create the bracket seed snapshot first."
            )

        bracket_matches_exist = connection.execute(
            """
            SELECT 1
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()

        if bracket_matches_exist is None:
            raise ValueError(
                "Generate the bracket matches before assigning seeds."
            )

        participant_count = len(seed_rows)
        bracket_size = get_bracket_size(participant_count)

        seed_to_player = {
            int(row["bracket_seed"]): str(row["player_id"])
            for row in seed_rows
        }

        seed_pairs = get_split_bracket_seed_pairs(
            bracket_size
        )

        updated_matches: list[dict[str, Any]] = []

        for bracket_side, pairs in seed_pairs.items():
            for match_number, (
                player_1_seed,
                player_2_seed,
            ) in enumerate(pairs, start=1):
                match_code = (
                    f"W1M{match_number}"
                    if bracket_side == BRACKET_SIDE_WINNERS
                    else f"L1M{match_number}"
                )

                player_1_id = seed_to_player.get(
                    player_1_seed
                )
                player_2_id = seed_to_player.get(
                    player_2_seed
                )

                if (
                    player_1_id is not None
                    and player_2_id is not None
                ):
                    status = "pending"
                    winner_id = None
                    completed_at_sql = "NULL"

                elif player_1_id is not None:
                    status = "bye"
                    winner_id = player_1_id
                    completed_at_sql = "CURRENT_TIMESTAMP"

                elif player_2_id is not None:
                    status = "bye"
                    winner_id = player_2_id
                    completed_at_sql = "CURRENT_TIMESTAMP"

                else:
                    status = "cancelled"
                    winner_id = None
                    completed_at_sql = "CURRENT_TIMESTAMP"

                cursor = connection.execute(
                    f"""
                    UPDATE tournament_draft_bracket_matches
                    SET
                        player_1_id = ?,
                        player_2_id = ?,
                        winner_id = ?,
                        player_1_score = NULL,
                        player_2_score = NULL,
                        status = ?,
                        completed_at = {completed_at_sql},
                        updated_at = CURRENT_TIMESTAMP
                    WHERE draft_id = ?
                      AND match_code = ?
                    """,
                    (
                        player_1_id,
                        player_2_id,
                        winner_id,
                        status,
                        draft_id,
                        match_code,
                    ),
                )

                if cursor.rowcount != 1:
                    raise ValueError(
                        f"Bracket match not found: {match_code}"
                    )

                updated_matches.append(
                    {
                        "match_code": match_code,
                        "player_1_seed": player_1_seed,
                        "player_2_seed": player_2_seed,
                        "player_1_id": player_1_id,
                        "player_2_id": player_2_id,
                        "winner_id": winner_id,
                        "status": status,
                    }
                )

    return updated_matches

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

def create_draft_split_bracket_routes(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """
    Creates winner and loser routes for a split-entry bracket.

    The Grand Final Reset is handled separately because it is only
    activated when the Losers Bracket finalist wins the Grand Final.
    """

    with connect_db(db_path) as connection:
        seed_count_row = connection.execute(
            """
            SELECT COUNT(*) AS participant_count
            FROM tournament_draft_bracket_seeds
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        participant_count = int(
            seed_count_row["participant_count"]
        )

        if participant_count < 3:
            raise ValueError(
                "Create the bracket seed snapshot first."
            )

        match_rows = connection.execute(
            """
            SELECT
                bracket_match_id,
                match_code
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchall()

        if not match_rows:
            raise ValueError(
                "Generate the bracket matches first."
            )

        match_id_by_code = {
            str(row["match_code"]): str(
                row["bracket_match_id"]
            )
            for row in match_rows
        }

        existing_route = connection.execute(
            """
            SELECT 1
            FROM tournament_draft_bracket_routes
            WHERE draft_id = ?
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()

        if existing_route is not None:
            raise ValueError(
                "Bracket routes have already been generated."
            )

        bracket_size = get_bracket_size(participant_count)
        winners_size = bracket_size // 2
        winners_round_count = (
            winners_size.bit_length() - 1
        )

        route_specs: list[
            tuple[str, str, str, int]
        ] = []

        def add_route(
            source_code: str,
            source_outcome: str,
            target_code: str,
            target_slot: int,
        ) -> None:
            if source_code not in match_id_by_code:
                raise ValueError(
                    f"Source bracket match not found: "
                    f"{source_code}"
                )

            if target_code not in match_id_by_code:
                raise ValueError(
                    f"Target bracket match not found: "
                    f"{target_code}"
                )

            route_specs.append(
                (
                    source_code,
                    source_outcome,
                    target_code,
                    target_slot,
                )
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
                source_code = (
                    f"W{round_number}M{match_number}"
                )

                next_match_number = (
                    match_number + 1
                ) // 2

                target_code = (
                    "WF"
                    if next_round_number
                    == winners_round_count
                    else (
                        f"W{next_round_number}"
                        f"M{next_match_number}"
                    )
                )

                target_slot = (
                    1
                    if match_number % 2 == 1
                    else 2
                )

                add_route(
                    source_code,
                    "winner",
                    target_code,
                    target_slot,
                )

        # Initial Losers winners and Winners Round 1 losers
        # meet in Losers Round 2.
        initial_losers_matches = winners_size // 2

        for match_number in range(
            1,
            initial_losers_matches + 1,
        ):
            add_route(
                f"L1M{match_number}",
                "winner",
                f"L2M{match_number}",
                2,
            )

            reversed_winners_match = (
                initial_losers_matches
                + 1
                - match_number
            )

            add_route(
                f"W1M{reversed_winners_match}",
                "loser",
                f"L2M{match_number}",
                1,
            )

        # Remaining Losers rounds.
        losers_round_number = 2
        matches_in_entry_round = (
            initial_losers_matches
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

            # Winners of each entry round meet each other.
            for match_number in range(
                1,
                matches_in_entry_round + 1,
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
                    (
                        f"L{losers_round_number}"
                        f"M{match_number}"
                    ),
                    "winner",
                    (
                        f"L{consolidation_round}"
                        f"M{target_match_number}"
                    ),
                    target_slot,
                )

            matches_in_entry_round = (
                consolidation_match_count
            )
            losers_round_number += 2

            next_winners_round = (
                winners_round_number + 1
            )

            if (
                next_winners_round
                < winners_round_count
            ):
                # Winners of the consolidation round meet
                # losers from the next Winners round.
                for match_number in range(
                    1,
                    matches_in_entry_round + 1,
                ):
                    entry_round = (
                        losers_round_number
                    )

                    add_route(
                        (
                            f"L{losers_round_number - 1}"
                            f"M{match_number}"
                        ),
                        "winner",
                        (
                            f"L{entry_round}"
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
                            f"L{entry_round}"
                            f"M{match_number}"
                        ),
                        1,
                    )

        # Last normal Losers match advances to Losers Final.
        last_losers_round = (
            2 * winners_round_count - 1
        )

        add_route(
            f"L{last_losers_round}M1",
            "winner",
            "LF",
            1,
        )

        # Winners Final loser drops into Losers Final.
        add_route(
            "WF",
            "loser",
            "LF",
            2,
        )

        # Finalists advance to Grand Final.
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

        created_routes: list[dict[str, Any]] = []

        for (
            source_code,
            source_outcome,
            target_code,
            target_slot,
        ) in route_specs:
            route_id = (
                f"bracket_route_{uuid.uuid4().hex}"
            )

            connection.execute(
                """
                INSERT INTO tournament_draft_bracket_routes (
                    route_id,
                    draft_id,
                    source_match_id,
                    source_outcome,
                    target_match_id,
                    target_slot
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    route_id,
                    draft_id,
                    match_id_by_code[source_code],
                    source_outcome,
                    match_id_by_code[target_code],
                    target_slot,
                ),
            )

            created_routes.append(
                {
                    "route_id": route_id,
                    "source_code": source_code,
                    "source_outcome": source_outcome,
                    "target_code": target_code,
                    "target_slot": target_slot,
                }
            )

    return created_routes

def propagate_draft_bracket_results(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """
    Propagate all decided bracket matches through their routes.

    The function is idempotent: it can safely be called again after
    every saved result.

    Once all incoming routes of a target match are resolved:
    - two players -> pending
    - one player  -> bye
    - no players  -> cancelled

    Grand Final Reset is handled separately.
    """

    terminal_statuses = {
        "completed",
        "forfeit",
        "bye",
        "cancelled",
    }

    changes: list[dict[str, Any]] = []

    with connect_db(db_path) as connection:
        while True:
            iteration_changed = False

            routes = connection.execute(
                """
                SELECT
                    r.source_outcome,
                    r.target_slot,

                    source.bracket_match_id
                        AS source_match_id,
                    source.match_code
                        AS source_code,
                    source.player_1_id
                        AS source_player_1_id,
                    source.player_2_id
                        AS source_player_2_id,
                    source.winner_id
                        AS source_winner_id,
                    source.status
                        AS source_status,

                    target.bracket_match_id
                        AS target_match_id,
                    target.match_code
                        AS target_code,
                    target.player_1_id
                        AS target_player_1_id,
                    target.player_2_id
                        AS target_player_2_id,
                    target.status
                        AS target_status,
                    target.match_type
                        AS target_match_type
                FROM tournament_draft_bracket_routes AS r
                JOIN tournament_draft_bracket_matches AS source
                  ON source.bracket_match_id = r.source_match_id
                JOIN tournament_draft_bracket_matches AS target
                  ON target.bracket_match_id = r.target_match_id
                WHERE r.draft_id = ?
                ORDER BY
                    target.round_number,
                    target.match_number,
                    r.target_slot
                """,
                (draft_id,),
            ).fetchall()

            for route in routes:
                source_status = str(route["source_status"])

                if source_status not in terminal_statuses:
                    continue

                routed_player_id: str | None = None

                if route["source_outcome"] == "winner":
                    if route["source_winner_id"] is not None:
                        routed_player_id = str(
                            route["source_winner_id"]
                        )

                else:
                    player_1_id = route["source_player_1_id"]
                    player_2_id = route["source_player_2_id"]
                    winner_id = route["source_winner_id"]

                    if (
                        player_1_id is not None
                        and player_2_id is not None
                        and winner_id is not None
                    ):
                        routed_player_id = str(
                            player_2_id
                            if winner_id == player_1_id
                            else player_1_id
                        )

                target_slot_column = (
                    "player_1_id"
                    if int(route["target_slot"]) == 1
                    else "player_2_id"
                )

                current_target_player = (
                    route["target_player_1_id"]
                    if int(route["target_slot"]) == 1
                    else route["target_player_2_id"]
                )

                if (
                    current_target_player is not None
                    and routed_player_id is not None
                    and str(current_target_player)
                    != routed_player_id
                ):
                    raise ValueError(
                        "Bracket route conflict: "
                        f"{route['target_code']} slot "
                        f"{route['target_slot']} already contains "
                        f"a different player."
                    )

                if (
                    current_target_player is None
                    and routed_player_id is not None
                ):
                    connection.execute(
                        f"""
                        UPDATE tournament_draft_bracket_matches
                        SET
                            {target_slot_column} = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE bracket_match_id = ?
                        """,
                        (
                            routed_player_id,
                            route["target_match_id"],
                        ),
                    )

                    changes.append(
                        {
                            "source_code": str(
                                route["source_code"]
                            ),
                            "source_outcome": str(
                                route["source_outcome"]
                            ),
                            "target_code": str(
                                route["target_code"]
                            ),
                            "target_slot": int(
                                route["target_slot"]
                            ),
                            "player_id": routed_player_id,
                        }
                    )

                    iteration_changed = True

            target_matches = connection.execute(
                """
                SELECT DISTINCT
                    target.bracket_match_id,
                    target.match_code,
                    target.match_type,
                    target.player_1_id,
                    target.player_2_id,
                    target.winner_id,
                    target.status
                FROM tournament_draft_bracket_routes AS r
                JOIN tournament_draft_bracket_matches AS target
                  ON target.bracket_match_id = r.target_match_id
                WHERE r.draft_id = ?
                """,
                (draft_id,),
            ).fetchall()

            for target in target_matches:
                if (
                    target["match_type"]
                    == "grand_final_reset"
                ):
                    continue

                current_target_status = str(
                    target["status"]
                )

                if current_target_status in terminal_statuses:
                    continue

                incoming_sources = connection.execute(
                    """
                    SELECT source.status
                    FROM tournament_draft_bracket_routes AS r
                    JOIN tournament_draft_bracket_matches AS source
                      ON source.bracket_match_id =
                         r.source_match_id
                    WHERE r.target_match_id = ?
                    """,
                    (target["bracket_match_id"],),
                ).fetchall()

                all_sources_resolved = (
                    bool(incoming_sources)
                    and all(
                        str(source["status"])
                        in terminal_statuses
                        for source in incoming_sources
                    )
                )

                if not all_sources_resolved:
                    continue

                player_1_id = target["player_1_id"]
                player_2_id = target["player_2_id"]

                if (
                    player_1_id is not None
                    and player_2_id is not None
                ):
                    new_status = "pending"
                    winner_id = None
                    completed_at_sql = "NULL"

                elif player_1_id is not None:
                    new_status = "bye"
                    winner_id = player_1_id
                    completed_at_sql = "CURRENT_TIMESTAMP"

                elif player_2_id is not None:
                    new_status = "bye"
                    winner_id = player_2_id
                    completed_at_sql = "CURRENT_TIMESTAMP"

                else:
                    new_status = "cancelled"
                    winner_id = None
                    completed_at_sql = "CURRENT_TIMESTAMP"

                if (
                    str(target["status"]) != new_status
                    or target["winner_id"] != winner_id
                ):
                    connection.execute(
                        f"""
                        UPDATE tournament_draft_bracket_matches
                        SET
                            winner_id = ?,
                            status = ?,
                            completed_at = {completed_at_sql},
                            updated_at = CURRENT_TIMESTAMP
                        WHERE bracket_match_id = ?
                        """,
                        (
                            winner_id,
                            new_status,
                            target["bracket_match_id"],
                        ),
                    )

                    iteration_changed = True

            if not iteration_changed:
                break

    return changes

def sync_draft_grand_final_reset(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """
    Synchronise the Grand Final Reset.

    - Winners-side player wins GF:
      GFR remains inactive and the tournament has a champion.
    - Losers-side player wins GF:
      GFR is activated with the same two players.
    """

    with connect_db(db_path) as connection:
        grand_final = connection.execute(
            """
            SELECT
                player_1_id,
                player_2_id,
                winner_id,
                status
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
              AND match_code = 'GF'
            """,
            (draft_id,),
        ).fetchone()

        reset_final = connection.execute(
            """
            SELECT
                bracket_match_id,
                player_1_id,
                player_2_id,
                winner_id,
                status
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            AND match_code = 'GFR'
            """,
            (draft_id,),
        ).fetchone()

        if grand_final is None or reset_final is None:
            raise ValueError(
                "Grand Final or Grand Final Reset is missing."
            )
        
        reset_status = str(reset_final["status"])

        if (
            reset_status in {"completed", "forfeit"}
            and reset_final["winner_id"] is not None
        ):
            return {
                "reset_required": True,
                "champion_id": str(reset_final["winner_id"]),
                "reset_status": reset_status,
            }

        gf_status = str(grand_final["status"])

        if gf_status not in {
            "completed",
            "forfeit",
        }:
            connection.execute(
                """
                UPDATE tournament_draft_bracket_matches
                SET
                    player_1_id = NULL,
                    player_2_id = NULL,
                    winner_id = NULL,
                    player_1_score = NULL,
                    player_2_score = NULL,
                    status = 'inactive',
                    completed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE bracket_match_id = ?
                """,
                (reset_final["bracket_match_id"],),
            )

            return {
                "reset_required": False,
                "champion_id": None,
                "reset_status": "inactive",
            }

        winners_side_player = grand_final["player_1_id"]
        losers_side_player = grand_final["player_2_id"]
        grand_final_winner = grand_final["winner_id"]

        if (
            winners_side_player is None
            or losers_side_player is None
            or grand_final_winner is None
        ):
            raise ValueError(
                "The Grand Final result is incomplete."
            )

        if grand_final_winner == winners_side_player:
            connection.execute(
                """
                UPDATE tournament_draft_bracket_matches
                SET
                    player_1_id = NULL,
                    player_2_id = NULL,
                    winner_id = NULL,
                    player_1_score = NULL,
                    player_2_score = NULL,
                    status = 'inactive',
                    completed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE bracket_match_id = ?
                """,
                (reset_final["bracket_match_id"],),
            )

            return {
                "reset_required": False,
                "champion_id": str(winners_side_player),
                "reset_status": "inactive",
            }

        if grand_final_winner != losers_side_player:
            raise ValueError(
                "The Grand Final winner is not one of its players."
            )

        connection.execute(
            """
            UPDATE tournament_draft_bracket_matches
            SET
                player_1_id = ?,
                player_2_id = ?,
                winner_id = NULL,
                player_1_score = NULL,
                player_2_score = NULL,
                status = 'pending',
                completed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE bracket_match_id = ?
            """,
            (
                winners_side_player,
                losers_side_player,
                reset_final["bracket_match_id"],
            ),
        )

        return {
            "reset_required": True,
            "champion_id": None,
            "reset_status": "pending",
        }
    
def get_draft_bracket_champion(
    db_path: str | Path,
    draft_id: str,
) -> str | None:
    """
    Return the champion once the bracket is fully decided.
    """

    with connect_db(db_path) as connection:
        reset_final = connection.execute(
            """
            SELECT
                winner_id,
                status
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
              AND match_code = 'GFR'
            """,
            (draft_id,),
        ).fetchone()

        if (
            reset_final is not None
            and str(reset_final["status"])
            in {"completed", "forfeit"}
            and reset_final["winner_id"] is not None
        ):
            return str(reset_final["winner_id"])

        grand_final = connection.execute(
            """
            SELECT
                player_1_id,
                winner_id,
                status
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
              AND match_code = 'GF'
            """,
            (draft_id,),
        ).fetchone()

        if (
            grand_final is not None
            and str(grand_final["status"])
            in {"completed", "forfeit"}
            and grand_final["winner_id"]
            == grand_final["player_1_id"]
        ):
            return str(grand_final["winner_id"])

    return None

def reset_draft_bracket_match_result(
    db_path: str | Path,
    bracket_match_id: str,
) -> dict[str, Any]:
    """
    Reset one bracket result and all matches that depend on it.

    The selected match keeps its assigned players and becomes pending.
    Downstream matches are cleared and then rebuilt from all remaining
    decided upstream results.

    Automatic bye matches cannot be reset manually.
    """

    with connect_db(db_path) as connection:
        source_match = connection.execute(
            """
            SELECT
                bracket_match_id,
                draft_id,
                match_code,
                match_type,
                player_1_id,
                player_2_id,
                status
            FROM tournament_draft_bracket_matches
            WHERE bracket_match_id = ?
            """,
            (bracket_match_id,),
        ).fetchone()

        if source_match is None:
            raise ValueError(
                f"Bracket match not found: {bracket_match_id}"
            )

        source_status = str(source_match["status"])

        if source_status == "bye":
            raise ValueError(
                "Automatic bye matches cannot be reset manually."
            )

        if source_status not in {
            "completed",
            "forfeit",
            "cancelled",
        }:
            raise ValueError(
                "Only decided or cancelled matches can be reset."
            )

        if (
            source_match["player_1_id"] is None
            or source_match["player_2_id"] is None
        ):
            raise ValueError(
                "The selected match does not have two assigned players."
            )

        draft_id = str(source_match["draft_id"])

        route_rows = connection.execute(
            """
            SELECT
                source_match_id,
                target_match_id
            FROM tournament_draft_bracket_routes
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchall()

        targets_by_source: dict[str, list[str]] = {}

        for route in route_rows:
            source_id = str(route["source_match_id"])
            target_id = str(route["target_match_id"])

            targets_by_source.setdefault(
                source_id,
                [],
            ).append(target_id)

        downstream_match_ids: set[str] = set()
        queue = list(
            targets_by_source.get(
                bracket_match_id,
                [],
            )
        )

        while queue:
            current_match_id = queue.pop(0)

            if current_match_id in downstream_match_ids:
                continue

            downstream_match_ids.add(current_match_id)

            queue.extend(
                targets_by_source.get(
                    current_match_id,
                    [],
                )
            )

        downstream_rows = []

        if downstream_match_ids:
            placeholders = ", ".join(
                "?"
                for _ in downstream_match_ids
            )

            downstream_rows = connection.execute(
                f"""
                SELECT
                    bracket_match_id,
                    match_code,
                    match_type
                FROM tournament_draft_bracket_matches
                WHERE bracket_match_id IN ({placeholders})
                """,
                tuple(downstream_match_ids),
            ).fetchall()

        downstream_codes = {
            str(row["match_code"])
            for row in downstream_rows
        }

        # GFR has no normal route from GF, so add it explicitly whenever
        # the Grand Final itself is reset or becomes downstream.
        if (
            str(source_match["match_code"]) == "GF"
            or "GF" in downstream_codes
        ):
            reset_final = connection.execute(
                """
                SELECT bracket_match_id
                FROM tournament_draft_bracket_matches
                WHERE draft_id = ?
                  AND match_code = 'GFR'
                """,
                (draft_id,),
            ).fetchone()

            if reset_final is not None:
                downstream_match_ids.add(
                    str(reset_final["bracket_match_id"])
                )

        # Clear every dependent match completely. Remaining valid players
        # will be restored by propagate_draft_bracket_results().
        for downstream_match_id in downstream_match_ids:
            downstream_match = connection.execute(
                """
                SELECT match_type
                FROM tournament_draft_bracket_matches
                WHERE bracket_match_id = ?
                """,
                (downstream_match_id,),
            ).fetchone()

            if downstream_match is None:
                continue

            new_status = (
                "inactive"
                if str(downstream_match["match_type"])
                == "grand_final_reset"
                else "waiting"
            )

            connection.execute(
                """
                UPDATE tournament_draft_bracket_matches
                SET
                    player_1_id = NULL,
                    player_2_id = NULL,
                    winner_id = NULL,
                    player_1_score = NULL,
                    player_2_score = NULL,
                    status = ?,
                    completed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE bracket_match_id = ?
                """,
                (
                    new_status,
                    downstream_match_id,
                ),
            )

        # Keep the selected match's players, but remove its result.
        connection.execute(
            """
            UPDATE tournament_draft_bracket_matches
            SET
                winner_id = NULL,
                player_1_score = NULL,
                player_2_score = NULL,
                status = 'pending',
                completed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE bracket_match_id = ?
            """,
            (bracket_match_id,),
        )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

    propagated_changes = propagate_draft_bracket_results(
        db_path,
        draft_id,
    )

    grand_final_state = sync_draft_grand_final_reset(
        db_path,
        draft_id,
    )

    return {
        "draft_id": draft_id,
        "bracket_match_id": bracket_match_id,
        "match_code": str(source_match["match_code"]),
        "matches_cleared": len(downstream_match_ids),
        "propagated_changes": propagated_changes,
        "grand_final_state": grand_final_state,
    }

def update_draft_bracket_match(
    db_path: str | Path,
    bracket_match_id: str,
    *,
    status: str,
    player_1_score: int | None = None,
    player_2_score: int | None = None,
    winner_id: str | None = None,
) -> dict[str, Any]:
    """
    Save a bracket result and propagate the winner and loser.

    Supported result statuses:
    - completed
    - forfeit
    - pending
    - cancelled
    """

    valid_statuses = {
        "pending",
        "completed",
        "forfeit",
        "cancelled",
    }

    if status not in valid_statuses:
        raise ValueError(
            f"Unsupported bracket match status: {status}"
        )

    with connect_db(db_path) as connection:
        match = connection.execute(
            """
            SELECT
                draft_id,
                match_code,
                match_type,
                player_1_id,
                player_2_id,
                status
            FROM tournament_draft_bracket_matches
            WHERE bracket_match_id = ?
            """,
            (bracket_match_id,),
        ).fetchone()

        if match is None:
            raise ValueError(
                f"Bracket match not found: {bracket_match_id}"
            )

        draft_id = str(match["draft_id"])
        player_1_id = match["player_1_id"]
        player_2_id = match["player_2_id"]

        if status in {"completed", "forfeit"}:
            if player_1_id is None or player_2_id is None:
                raise ValueError(
                    "Both players must be assigned before "
                    "the match can be decided."
                )

        if status == "completed":
            if (
                player_1_score is None
                or player_2_score is None
            ):
                raise ValueError(
                    "Both scores are required."
                )

            player_1_score = int(player_1_score)
            player_2_score = int(player_2_score)

            if player_1_score < 0 or player_2_score < 0:
                raise ValueError(
                    "Scores cannot be negative."
                )

            if player_1_score == player_2_score:
                raise ValueError(
                    "Bracket matches cannot end in a draw."
                )

            calculated_winner_id = (
                str(player_1_id)
                if player_1_score > player_2_score
                else str(player_2_id)
            )

            if (
                winner_id is not None
                and winner_id != calculated_winner_id
            ):
                raise ValueError(
                    "The selected winner does not match the score."
                )

            winner_id = calculated_winner_id
            completed_at_sql = "CURRENT_TIMESTAMP"

        elif status == "forfeit":
            if winner_id not in {
                str(player_1_id),
                str(player_2_id),
            }:
                raise ValueError(
                    "Select one of the assigned players as winner."
                )

            player_1_score = None
            player_2_score = None
            completed_at_sql = "CURRENT_TIMESTAMP"

        elif status == "cancelled":
            winner_id = None
            player_1_score = None
            player_2_score = None
            completed_at_sql = "CURRENT_TIMESTAMP"

        else:
            winner_id = None
            player_1_score = None
            player_2_score = None
            completed_at_sql = "NULL"

        connection.execute(
            f"""
            UPDATE tournament_draft_bracket_matches
            SET
                winner_id = ?,
                player_1_score = ?,
                player_2_score = ?,
                status = ?,
                completed_at = {completed_at_sql},
                updated_at = CURRENT_TIMESTAMP
            WHERE bracket_match_id = ?
            """,
            (
                winner_id,
                player_1_score,
                player_2_score,
                status,
                bracket_match_id,
            ),
        )

    propagated_changes = propagate_draft_bracket_results(
        db_path,
        draft_id,
    )

    grand_final_state = sync_draft_grand_final_reset(
        db_path,
        draft_id,
    )

    champion_id = get_draft_bracket_champion(
        db_path,
        draft_id,
    )

    return {
        "draft_id": draft_id,
        "bracket_match_id": bracket_match_id,
        "match_code": str(match["match_code"]),
        "status": status,
        "winner_id": winner_id,
        "player_1_score": player_1_score,
        "player_2_score": player_2_score,
        "propagated_changes": propagated_changes,
        "grand_final_state": grand_final_state,
        "champion_id": champion_id,
    }

def connect_db(db_path: str | Path) -> sqlite3.Connection:
    """Opens the SQLite database with foreign keys enabled."""

    path = Path(db_path)

    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection

def _draft_has_group_matches(
    connection: sqlite3.Connection,
    draft_id: str,
) -> bool:
    """Returns whether group matches exist for a tournament draft."""

    row = connection.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM tournament_draft_group_matches AS gm
            JOIN tournament_draft_groups AS g
              ON g.group_id = gm.group_id
            WHERE g.draft_id = ?
        )
        """,
        (draft_id,),
    ).fetchone()

    return bool(row[0])

def validate_draft_configuration(
    format_type: str,
    bracket_entry_mode: str,
) -> None:
    """Validates the tournament format and bracket-entry combination."""

    if format_type not in VALID_FORMATS:
        raise ValueError(
            f"Unsupported tournament format: {format_type}"
        )

    if bracket_entry_mode not in VALID_ENTRY_MODES:
        raise ValueError(
            f"Unsupported bracket entry mode: {bracket_entry_mode}"
        )

    if (
        format_type == FORMAT_DOUBLE_ELIMINATION
        and bracket_entry_mode != ENTRY_ALL_WINNERS
    ):
        raise ValueError(
            "Double-elimination-only tournaments must start "
            "all players in the Winners Bracket."
        )


def create_draft(
    db_path: str | Path,
    tournament_number: int,
    tournament_date: str | None,
    format_type: str,
    bracket_entry_mode: str = ENTRY_ALL_WINNERS,
) -> str:
    """Creates a new tournament draft and returns its ID."""

    if tournament_number <= 0:
        raise ValueError("Tournament number must be greater than zero.")

    validate_draft_configuration(
        format_type,
        bracket_entry_mode,
    )

    draft_id = f"draft_{uuid.uuid4().hex}"

    with connect_db(db_path) as connection:
        existing_archive = connection.execute(
            """
            SELECT tournament_id
            FROM tournaments
            WHERE tournament_number = ?
            """,
            (tournament_number,),
        ).fetchone()

        if existing_archive is not None:
            raise ValueError(
                f"WM {tournament_number:02d} already exists "
                f"in the tournament archive."
            )

        existing_draft = connection.execute(
            """
            SELECT draft_id
            FROM tournament_drafts
            WHERE tournament_number = ?
            """,
            (tournament_number,),
        ).fetchone()

        if existing_draft is not None:
            raise ValueError(
                f"A draft for WM {tournament_number:02d} "
                f"already exists."
            )

        connection.execute(
            """
            INSERT INTO tournament_drafts (
                draft_id,
                tournament_number,
                tournament_date,
                format_type,
                bracket_entry_mode,
                status
            )
            VALUES (?, ?, ?, ?, ?, 'draft')
            """,
            (
                draft_id,
                tournament_number,
                tournament_date,
                format_type,
                bracket_entry_mode,
            ),
        )

    return draft_id

def update_draft_date(
    db_path: str | Path,
    draft_id: str,
    tournament_date: str | None,
) -> None:
    """Update the tournament date of an unfinished draft."""

    cleaned_date = (
        tournament_date.strip()
        if tournament_date is not None
        and tournament_date.strip()
        else None
    )

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                draft_id,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        if str(draft["status"]) != "draft":
            raise ValueError(
                "The tournament date can only be changed "
                "while the tournament is still a draft."
            )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET
                tournament_date = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (
                cleaned_date,
                draft_id,
            ),
        )

def list_drafts(
    db_path: str | Path,
    *,
    include_cancelled: bool = False,
) -> list[dict[str, Any]]:
    """Returns tournament drafts ordered by tournament number."""

    query = """
        SELECT
            d.draft_id,
            d.tournament_number,
            d.tournament_date,
            d.format_type,
            d.bracket_entry_mode,
            d.status,
            d.created_at,
            d.updated_at,
            COUNT(dp.player_id) AS participant_count
        FROM tournament_drafts AS d
        LEFT JOIN tournament_draft_participants AS dp
          ON dp.draft_id = d.draft_id
    """

    parameters: tuple[Any, ...] = ()

    if not include_cancelled:
        query += " WHERE d.status != ?"
        parameters = ("cancelled",)

    query += """
        GROUP BY
            d.draft_id,
            d.tournament_number,
            d.tournament_date,
            d.format_type,
            d.bracket_entry_mode,
            d.status,
            d.created_at,
            d.updated_at
        ORDER BY d.tournament_number DESC
    """

    with connect_db(db_path) as connection:
        rows = connection.execute(
            query,
            parameters,
        ).fetchall()

    return [dict(row) for row in rows]


def get_draft(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """Returns one draft together with its participants."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                draft_id,
                tournament_number,
                tournament_date,
                format_type,
                bracket_entry_mode,
                status,
                created_at,
                updated_at
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        participants = connection.execute(
            """
            SELECT
                dp.player_id,
                p.display_name AS player,
                dp.manual_seed,
                dp.group_seed,
                dp.bracket_seed,
                dp.starts_in
            FROM tournament_draft_participants AS dp
            JOIN players AS p
              ON p.player_id = dp.player_id
            WHERE dp.draft_id = ?
            ORDER BY
                CASE
                    WHEN dp.bracket_seed IS NULL THEN 1
                    ELSE 0
                END,
                dp.bracket_seed,
                CASE
                    WHEN dp.manual_seed IS NULL THEN 1
                    ELSE 0
                END,
                dp.manual_seed,
                p.display_name COLLATE NOCASE
            """,
            (draft_id,),
        ).fetchall()

    return {
        **dict(draft),
        "participants": [dict(row) for row in participants],
    }

def create_player(
    db_path: str | Path,
    display_name: str,
    *,
    active: bool = True,
    core_player: bool = False,
    notes: str | None = None,
) -> str:
    """Creates a new player profile and returns the player ID."""

    cleaned_name = display_name.strip()

    if not cleaned_name:
        raise ValueError("Player name must not be empty.")

    player_id = f"player_{uuid.uuid4().hex}"

    with connect_db(db_path) as connection:
        existing_player = connection.execute(
            """
            SELECT player_id
            FROM players
            WHERE display_name = ? COLLATE NOCASE
            """,
            (cleaned_name,),
        ).fetchone()

        if existing_player is not None:
            raise ValueError(
                f"A player named {cleaned_name} already exists."
            )

        try:
            connection.execute(
                """
                INSERT INTO players (
                    player_id,
                    display_name,
                    core_player,
                    active,
                    notes
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    player_id,
                    cleaned_name,
                    int(core_player),
                    int(active),
                    notes.strip() if notes and notes.strip() else None,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "The player profile could not be created."
            ) from exc

    return player_id

def create_player_and_add_to_draft(
    db_path: str | Path,
    draft_id: str,
    display_name: str,
    *,
    active: bool = True,
    core_player: bool = False,
    notes: str | None = None,
) -> str:
    """Creates a player profile and immediately adds it to a draft."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["status"] != "draft":
            raise ValueError(
                "New players can only be added while the tournament "
                "is still a draft."
            )

    player_id = create_player(
        db_path,
        display_name,
        active=active,
        core_player=core_player,
        notes=notes,
    )

    try:
        draft = get_draft(db_path, draft_id)

        if draft["format_type"] == FORMAT_DOUBLE_ELIMINATION:
            next_seed = len(draft["participants"]) + 1
            manual_seed = next_seed
            bracket_seed = next_seed
        else:
            manual_seed = None
            bracket_seed = None

        add_participant(
            db_path,
            draft_id,
            player_id,
            manual_seed=manual_seed,
            group_seed=None,
            bracket_seed=bracket_seed,
            starts_in="winners",
        )
    except Exception:
        # Avoid leaving behind an unused player profile if adding fails.
        with connect_db(db_path) as connection:
            connection.execute(
                """
                DELETE FROM players
                WHERE player_id = ?
                """,
                (player_id,),
            )
        raise

    return player_id

def add_participant(
    db_path: str | Path,
    draft_id: str,
    player_id: str,
    *,
    manual_seed: int | None = None,
    group_seed: int | None = None,
    bracket_seed: int | None = None,
    starts_in: str = "winners",
) -> None:
    """Adds one player to a tournament draft."""

    if starts_in not in VALID_START_POSITIONS:
        raise ValueError(
            f"Unsupported bracket start position: {starts_in}"
        )

    for label, seed in (
        ("manual seed", manual_seed),
        ("group seed", group_seed),
        ("bracket seed", bracket_seed),
    ):
        if seed is not None and seed <= 0:
            raise ValueError(f"{label.title()} must be greater than zero.")

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                bracket_entry_mode,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["status"] not in {"draft", "group_stage", "bracket_ready"}:
            raise ValueError(
                "Participants cannot be changed after "
                "the tournament has started."
            )
        
        if (
            draft["format_type"] == FORMAT_GROUP_STAGE
            and _draft_has_group_matches(connection, draft_id)
        ):
            raise ValueError(
                "Participants cannot be added after the group matches "
                "have been generated. Reset the group matches first."
            )

        player = connection.execute(
            """
            SELECT player_id
            FROM players
            WHERE player_id = ?
            """,
            (player_id,),
        ).fetchone()

        if player is None:
            raise ValueError(f"Player not found: {player_id}")

        if (
            starts_in == "losers"
            and draft["format_type"] != FORMAT_GROUP_STAGE
        ):
            raise ValueError(
                "Players may only start in the Losers Bracket "
                "after a group stage."
            )

        if (
            starts_in == "losers"
            and draft["bracket_entry_mode"]
            != ENTRY_SPLIT_BY_GROUP_SEED
        ):
            raise ValueError(
                "This draft is configured for all players "
                "to start in the Winners Bracket."
            )

        try:
            connection.execute(
                """
                INSERT INTO tournament_draft_participants (
                    draft_id,
                    player_id,
                    manual_seed,
                    group_seed,
                    bracket_seed,
                    starts_in
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    player_id,
                    manual_seed,
                    group_seed,
                    bracket_seed,
                    starts_in,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "The player is already in the draft, "
                "or one of the assigned seeds is already used."
            ) from exc

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )


def update_participant(
    db_path: str | Path,
    draft_id: str,
    player_id: str,
    *,
    manual_seed: int | None,
    group_seed: int | None,
    bracket_seed: int | None,
    starts_in: str,
) -> None:
    """Updates seed and starting-position data for one participant."""

    if starts_in not in VALID_START_POSITIONS:
        raise ValueError(
            f"Unsupported bracket start position: {starts_in}"
        )

    for label, seed in (
        ("manual seed", manual_seed),
        ("group seed", group_seed),
        ("bracket seed", bracket_seed),
    ):
        if seed is not None and seed <= 0:
            raise ValueError(f"{label.title()} must be greater than zero.")

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                bracket_entry_mode,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["status"] not in {"draft", "group_stage", "bracket_ready"}:
            raise ValueError(
                "Participants cannot be changed after "
                "the tournament has started."
            )
        
        if (
            draft["format_type"] == FORMAT_GROUP_STAGE
            and _draft_has_group_matches(connection, draft_id)
        ):
            raise ValueError(
                "Participant settings cannot be changed after the group "
                "matches have been generated. Reset the group matches first."
            )

        if (
            starts_in == "losers"
            and (
                draft["format_type"] != FORMAT_GROUP_STAGE
                or draft["bracket_entry_mode"]
                != ENTRY_SPLIT_BY_GROUP_SEED
            )
        ):
            raise ValueError(
                "Losers Bracket entry is not allowed "
                "for this tournament configuration."
            )

        try:
            cursor = connection.execute(
                """
                UPDATE tournament_draft_participants
                SET
                    manual_seed = ?,
                    group_seed = ?,
                    bracket_seed = ?,
                    starts_in = ?
                WHERE draft_id = ?
                  AND player_id = ?
                """,
                (
                    manual_seed,
                    group_seed,
                    bracket_seed,
                    starts_in,
                    draft_id,
                    player_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "One of the assigned seeds is already used."
            ) from exc

        if cursor.rowcount == 0:
            raise ValueError(
                "The player is not part of this tournament draft."
            )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

def assign_manual_seeds(
    db_path: str | Path,
    draft_id: str,
    seed_by_player_id: dict[str, int],
) -> None:
    """Assigns a complete manual seeding to a draft."""

    if not seed_by_player_id:
        raise ValueError("At least one participant is required.")

    assigned_seeds = list(seed_by_player_id.values())
    participant_count = len(seed_by_player_id)

    if any(seed <= 0 for seed in assigned_seeds):
        raise ValueError("Seeds must be greater than zero.")

    expected_seeds = set(range(1, participant_count + 1))

    if set(assigned_seeds) != expected_seeds:
        raise ValueError(
            f"Seeds must contain every number from 1 to "
            f"{participant_count} exactly once."
        )

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["format_type"] != FORMAT_DOUBLE_ELIMINATION:
            raise ValueError(
                "Manual seeding is currently only available for "
                "double-elimination-only tournaments."
            )

        if draft["status"] != "draft":
            raise ValueError(
                "Seeds can only be changed while the tournament "
                "is still a draft."
            )

        participant_rows = connection.execute(
            """
            SELECT player_id
            FROM tournament_draft_participants
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchall()

        participant_ids = {
            str(row["player_id"])
            for row in participant_rows
        }

        supplied_ids = {
            str(player_id)
            for player_id in seed_by_player_id
        }

        if supplied_ids != participant_ids:
            raise ValueError(
                "A seed must be assigned to every participant."
            )

        # Clear existing seeds first so that players can swap seeds
        # without temporarily violating the unique constraints.
        connection.execute(
            """
            UPDATE tournament_draft_participants
            SET
                manual_seed = NULL,
                bracket_seed = NULL
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

        for player_id, seed in seed_by_player_id.items():
            connection.execute(
                """
                UPDATE tournament_draft_participants
                SET
                    manual_seed = ?,
                    bracket_seed = ?,
                    starts_in = 'winners'
                WHERE draft_id = ?
                  AND player_id = ?
                """,
                (
                    seed,
                    seed,
                    draft_id,
                    player_id,
                ),
            )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

def get_automatic_seed_order(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """Returns the suggested draft seeding based on activity and Elo."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                draft_id,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["status"] != "draft":
            raise ValueError(
                "Automatic seeding is only available while "
                "the tournament is still a draft."
            )

        participant_rows = connection.execute(
            """
            SELECT
                dp.player_id,
                dp.manual_seed AS current_seed,
                p.display_name,
                p.active,
                COUNT(DISTINCT tp.tournament_id) AS appearances
            FROM tournament_draft_participants AS dp
            JOIN players AS p
              ON p.player_id = dp.player_id
            LEFT JOIN tournament_participants AS tp
              ON tp.player_id = p.player_id
            WHERE dp.draft_id = ?
            GROUP BY
                dp.player_id,
                dp.manual_seed,
                p.display_name,
                p.active
            """,
            (draft_id,),
        ).fetchall()

    if not participant_rows:
        raise ValueError(
            "At least one participant is required before generating seeds."
        )

    ranking = stats.get_elo_ranking(
        db_path,
        active_only=False,
    )

    ranking_by_player_id = {
        str(entry["player_id"]): entry
        for entry in ranking
    }

    seed_candidates: list[dict[str, Any]] = []

    for row in participant_rows:
        player_id = str(row["player_id"])
        ranking_entry = ranking_by_player_id.get(player_id)

        appearances = int(row["appearances"] or 0)
        is_active = bool(row["active"])

        if appearances == 0:
            category = "new"
            category_priority = 2
        elif is_active:
            category = "active"
            category_priority = 0
        else:
            category = "inactive"
            category_priority = 1

        current_elo = (
            float(ranking_entry["elo"])
            if ranking_entry is not None
            and ranking_entry.get("elo") is not None
            else 1000.0
        )

        rated_matches = (
            int(ranking_entry["rated_matches"])
            if ranking_entry is not None
            else 0
        )

        current_seed = (
            int(row["current_seed"])
            if row["current_seed"] is not None
            else 999999
        )

        seed_candidates.append(
            {
                "player_id": player_id,
                "player": str(row["display_name"]),
                "category": category,
                "category_priority": category_priority,
                "elo": current_elo,
                "rated_matches": rated_matches,
                "current_seed": current_seed,
            }
        )

    seed_candidates.sort(
        key=lambda player: (
            player["category_priority"],
            -player["elo"],
            -player["rated_matches"],
            player["current_seed"],
            player["player"].casefold(),
        )
    )

    return [
        {
            **player,
            "suggested_seed": index,
        }
        for index, player in enumerate(
            seed_candidates,
            start=1,
        )
    ]

def apply_automatic_seeding(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """Generates and saves the suggested draft seeding."""

    suggested_order = get_automatic_seed_order(
        db_path,
        draft_id,
    )

    ordered_player_ids = [
        str(player["player_id"])
        for player in suggested_order
    ]

    save_participant_order(
        db_path,
        draft_id,
        ordered_player_ids,
    )

    return suggested_order

def save_participant_order(
    db_path: str | Path,
    draft_id: str,
    ordered_player_ids: list[str],
) -> None:
    """Saves participant order as consecutive manual and bracket seeds."""

    if not ordered_player_ids:
        raise ValueError("At least one participant is required.")

    if len(ordered_player_ids) != len(set(ordered_player_ids)):
        raise ValueError("Each participant may only appear once.")

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["status"] != "draft":
            raise ValueError(
                "Participant order can only be changed while "
                "the tournament is still a draft."
            )
        
        if (
            draft["format_type"] == FORMAT_GROUP_STAGE
            and _draft_has_group_matches(connection, draft_id)
        ):
            raise ValueError(
                "Participant order cannot be changed after the group "
                "matches have been generated. Reset the group matches first."
            )

        participant_rows = connection.execute(
            """
            SELECT player_id
            FROM tournament_draft_participants
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchall()

        stored_player_ids = {
            str(row["player_id"])
            for row in participant_rows
        }

        supplied_player_ids = {
            str(player_id)
            for player_id in ordered_player_ids
        }

        if supplied_player_ids != stored_player_ids:
            raise ValueError(
                "The order must contain every participant exactly once."
            )

        # Clear seeds first to avoid temporary UNIQUE conflicts.
        connection.execute(
            """
            UPDATE tournament_draft_participants
            SET
                manual_seed = NULL,
                bracket_seed = NULL
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

        for seed, player_id in enumerate(
            ordered_player_ids,
            start=1,
        ):
            bracket_seed = (
                seed
                if draft["format_type"] == FORMAT_DOUBLE_ELIMINATION
                else None
            )

            connection.execute(
                """
                UPDATE tournament_draft_participants
                SET
                    manual_seed = ?,
                    bracket_seed = ?,
                    starts_in = 'winners'
                WHERE draft_id = ?
                AND player_id = ?
                """,
                (
                    seed,
                    bracket_seed,
                    draft_id,
                    player_id,
                ),
            )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

def get_draft_groups(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """Returns all groups and assigned players for a tournament draft."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT draft_id
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        group_rows = connection.execute(
            """
            SELECT
                group_id,
                group_number,
                group_name
            FROM tournament_draft_groups
            WHERE draft_id = ?
            ORDER BY group_number
            """,
            (draft_id,),
        ).fetchall()

        groups: list[dict[str, Any]] = []

        for group_row in group_rows:
            member_rows = connection.execute(
                """
                SELECT
                    gm.player_id,
                    p.display_name AS player,
                    dp.manual_seed,
                    gm.group_position
                FROM tournament_draft_group_members AS gm
                JOIN players AS p
                  ON p.player_id = gm.player_id
                JOIN tournament_draft_participants AS dp
                  ON dp.player_id = gm.player_id
                 AND dp.draft_id = ?
                WHERE gm.group_id = ?
                ORDER BY
                    CASE
                        WHEN gm.group_position IS NULL THEN 1
                        ELSE 0
                    END,
                    gm.group_position,
                    dp.manual_seed,
                    p.display_name COLLATE NOCASE
                """,
                (
                    draft_id,
                    group_row["group_id"],
                ),
            ).fetchall()

            groups.append(
                {
                    **dict(group_row),
                    "members": [
                        dict(member)
                        for member in member_rows
                    ],
                }
            )

    return groups

def reset_draft_groups(
    db_path: str | Path,
    draft_id: str,
) -> None:
    """Deletes all group assignments and groups for a draft."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["format_type"] != FORMAT_GROUP_STAGE:
            raise ValueError(
                "Groups are only available for group-stage tournaments."
            )

        if draft["status"] != "draft":
            raise ValueError(
                "Groups can only be reset while the tournament "
                "is still a draft."
            )
        
        if _draft_has_group_matches(connection, draft_id):
            raise ValueError(
                "Groups cannot be reset after the group matches "
                "have been generated. Reset the group matches first."
            )

        connection.execute(
            """
            DELETE FROM tournament_draft_groups
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

def create_draft_groups(
    db_path: str | Path,
    draft_id: str,
    group_count: int,
) -> list[dict[str, Any]]:
    """Creates groups and assigns participants using snake seeding."""

    if group_count <= 0:
        raise ValueError("At least one group is required.")

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["format_type"] != FORMAT_GROUP_STAGE:
            raise ValueError(
                "Groups are only available for group-stage tournaments."
            )

        if draft["status"] != "draft":
            raise ValueError(
                "Groups can only be created while the tournament "
                "is still a draft."
            )
        
        if _draft_has_group_matches(connection, draft_id):
            raise ValueError(
                "Groups cannot be recreated after the group matches "
                "have been generated. Reset the group matches first."
            )

        participants = connection.execute(
            """
            SELECT
                player_id,
                manual_seed
            FROM tournament_draft_participants
            WHERE draft_id = ?
            ORDER BY
                CASE
                    WHEN manual_seed IS NULL THEN 1
                    ELSE 0
                END,
                manual_seed,
                player_id
            """,
            (draft_id,),
        ).fetchall()

        participant_count = len(participants)

        if participant_count < 2:
            raise ValueError(
                "At least two participants are required "
                "for a group stage."
            )

        if participant_count < group_count * 2:
            raise ValueError(
                "Each group must contain at least two participants."
            )

        seeds = [
            int(participant["manual_seed"])
            for participant in participants
            if participant["manual_seed"] is not None
        ]

        expected_seeds = list(range(1, participant_count + 1))

        if sorted(seeds) != expected_seeds:
            raise ValueError(
                "Generate and save a complete initial seeding "
                "before creating groups."
            )

        # Recreating groups replaces the previous group setup.
        connection.execute(
            """
            DELETE FROM tournament_draft_groups
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

        created_groups: list[dict[str, Any]] = []

        for group_index in range(group_count):
            group_number = group_index + 1
            group_name = (
                "Group A"
                if group_count == 1
                else f"Group {chr(65 + group_index)}"
            )
            group_id = f"group_{uuid.uuid4().hex}"

            connection.execute(
                """
                INSERT INTO tournament_draft_groups (
                    group_id,
                    draft_id,
                    group_number,
                    group_name
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    group_id,
                    draft_id,
                    group_number,
                    group_name,
                ),
            )

            created_groups.append(
                {
                    "group_id": group_id,
                    "group_number": group_number,
                    "group_name": group_name,
                }
            )

        group_member_counts = [0] * group_count

        for participant_index, participant in enumerate(participants):
            row_number = participant_index // group_count
            position_in_row = participant_index % group_count

            if row_number % 2 == 0:
                group_index = position_in_row
            else:
                group_index = group_count - 1 - position_in_row

            group = created_groups[group_index]
            group_member_counts[group_index] += 1

            connection.execute(
                """
                INSERT INTO tournament_draft_group_members (
                    group_id,
                    player_id,
                    group_position
                )
                VALUES (?, ?, ?)
                """,
                (
                    group["group_id"],
                    participant["player_id"],
                    group_member_counts[group_index],
                ),
            )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

    return get_draft_groups(
        db_path,
        draft_id,
    )

def move_draft_group_member(
    db_path: str | Path,
    draft_id: str,
    player_id: str,
    target_group_id: str,
) -> list[dict[str, Any]]:
    """Moves one participant to another group and resequences positions."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["format_type"] != FORMAT_GROUP_STAGE:
            raise ValueError(
                "Group assignments are only available for "
                "group-stage tournaments."
            )

        if draft["status"] != "draft":
            raise ValueError(
                "Group assignments can only be changed while "
                "the tournament is still a draft."
            )

        if _draft_has_group_matches(connection, draft_id):
            raise ValueError(
                "Group assignments cannot be changed after "
                "the group matches have been generated. "
                "Reset the group matches first."
            )

        target_group = connection.execute(
            """
            SELECT
                group_id,
                draft_id
            FROM tournament_draft_groups
            WHERE group_id = ?
            """,
            (target_group_id,),
        ).fetchone()

        if target_group is None:
            raise ValueError(
                f"Target group not found: {target_group_id}"
            )

        if str(target_group["draft_id"]) != draft_id:
            raise ValueError(
                "The target group belongs to another tournament draft."
            )

        current_membership = connection.execute(
            """
            SELECT
                gm.group_id,
                gm.group_position
            FROM tournament_draft_group_members AS gm
            JOIN tournament_draft_groups AS g
              ON g.group_id = gm.group_id
            WHERE g.draft_id = ?
              AND gm.player_id = ?
            """,
            (
                draft_id,
                player_id,
            ),
        ).fetchone()

        if current_membership is None:
            raise ValueError(
                "The player is not assigned to a group in this draft."
            )

        source_group_id = str(current_membership["group_id"])

        if source_group_id == target_group_id:
            raise ValueError(
                "The player is already assigned to the selected group."
            )

        source_member_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM tournament_draft_group_members
                WHERE group_id = ?
                """,
                (source_group_id,),
            ).fetchone()[0]
        )

        if source_member_count <= 2:
            raise ValueError(
                "The player cannot be moved because every group "
                "must contain at least two players."
            )

        target_position = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM tournament_draft_group_members
                WHERE group_id = ?
                """,
                (target_group_id,),
            ).fetchone()[0]
        ) + 1

        connection.execute(
            """
            DELETE FROM tournament_draft_group_members
            WHERE group_id = ?
              AND player_id = ?
            """,
            (
                source_group_id,
                player_id,
            ),
        )

        connection.execute(
            """
            INSERT INTO tournament_draft_group_members (
                group_id,
                player_id,
                group_position
            )
            VALUES (?, ?, ?)
            """,
            (
                target_group_id,
                player_id,
                target_position,
            ),
        )

        source_members = connection.execute(
            """
            SELECT player_id
            FROM tournament_draft_group_members
            WHERE group_id = ?
            ORDER BY
                CASE
                    WHEN group_position IS NULL THEN 1
                    ELSE 0
                END,
                group_position,
                player_id
            """,
            (source_group_id,),
        ).fetchall()

        for position, member in enumerate(
            source_members,
            start=1,
        ):
            connection.execute(
                """
                UPDATE tournament_draft_group_members
                SET group_position = ?
                WHERE group_id = ?
                  AND player_id = ?
                """,
                (
                    position,
                    source_group_id,
                    member["player_id"],
                ),
            )

        target_members = connection.execute(
            """
            SELECT player_id
            FROM tournament_draft_group_members
            WHERE group_id = ?
            ORDER BY
                CASE
                    WHEN group_position IS NULL THEN 1
                    ELSE 0
                END,
                group_position,
                player_id
            """,
            (target_group_id,),
        ).fetchall()

        for position, member in enumerate(
            target_members,
            start=1,
        ):
            connection.execute(
                """
                UPDATE tournament_draft_group_members
                SET group_position = ?
                WHERE group_id = ?
                  AND player_id = ?
                """,
                (
                    position,
                    target_group_id,
                    member["player_id"],
                ),
            )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

    return get_draft_groups(
        db_path,
        draft_id,
    )

def generate_round_robin_pairings(
    player_ids: list[str],
) -> list[list[tuple[str, str]]]:
    """Generates round-robin pairings using the circle method."""

    if len(player_ids) < 2:
        raise ValueError(
            "At least two players are required for round-robin matches."
        )

    if len(player_ids) != len(set(player_ids)):
        raise ValueError("Each player may only appear once.")

    rotation: list[str | None] = list(player_ids)

    if len(rotation) % 2 == 1:
        rotation.append(None)

    player_count = len(rotation)
    round_count = player_count - 1
    matches_per_round = player_count // 2

    rounds: list[list[tuple[str, str]]] = []

    for round_index in range(round_count):
        round_pairings: list[tuple[str, str]] = []

        for pairing_index in range(matches_per_round):
            player_1 = rotation[pairing_index]
            player_2 = rotation[player_count - 1 - pairing_index]

            # None represents the bye in an odd-sized group.
            if player_1 is None or player_2 is None:
                continue

            # Alternate the displayed order slightly between rounds.
            if round_index % 2 == 1:
                player_1, player_2 = player_2, player_1

            round_pairings.append(
                (
                    str(player_1),
                    str(player_2),
                )
            )

        rounds.append(round_pairings)

        rotation = [
            rotation[0],
            rotation[-1],
            *rotation[1:-1],
        ]

    return rounds

def get_draft_group_matches(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """Returns all group-stage matches for a tournament draft."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT draft_id
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        rows = connection.execute(
            """
            SELECT
                gm.group_match_id,
                gm.group_id,
                g.group_number,
                g.group_name,
                gm.round_number,
                gm.match_number,
                gm.player_1_id,
                p1.display_name AS player_1,
                gm.player_2_id,
                p2.display_name AS player_2,
                gm.winner_id,
                winner.display_name AS winner,
                gm.player_1_score,
                gm.player_2_score,
                gm.status,
                gm.completed_at,
                gm.created_at,
                gm.updated_at
            FROM tournament_draft_group_matches AS gm
            JOIN tournament_draft_groups AS g
              ON g.group_id = gm.group_id
            JOIN players AS p1
              ON p1.player_id = gm.player_1_id
            JOIN players AS p2
              ON p2.player_id = gm.player_2_id
            LEFT JOIN players AS winner
              ON winner.player_id = gm.winner_id
            WHERE g.draft_id = ?
            ORDER BY
                g.group_number,
                gm.round_number,
                gm.match_number
            """,
            (draft_id,),
        ).fetchall()

    return [dict(row) for row in rows]

def create_draft_group_matches(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """Creates round-robin matches for every group in a draft."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["format_type"] != FORMAT_GROUP_STAGE:
            raise ValueError(
                "Group matches are only available for "
                "group-stage tournaments."
            )

        if draft["status"] != "draft":
            raise ValueError(
                "Group matches can only be generated while "
                "the tournament is still a draft."
            )

        group_rows = connection.execute(
            """
            SELECT
                group_id,
                group_number,
                group_name
            FROM tournament_draft_groups
            WHERE draft_id = ?
            ORDER BY group_number
            """,
            (draft_id,),
        ).fetchall()

        if not group_rows:
            raise ValueError(
                "Create the tournament groups before generating matches."
            )

        group_members: dict[str, list[str]] = {}

        for group in group_rows:
            members = connection.execute(
                """
                SELECT gm.player_id
                FROM tournament_draft_group_members AS gm
                JOIN tournament_draft_participants AS dp
                  ON dp.player_id = gm.player_id
                 AND dp.draft_id = ?
                WHERE gm.group_id = ?
                ORDER BY
                    CASE
                        WHEN gm.group_position IS NULL THEN 1
                        ELSE 0
                    END,
                    gm.group_position,
                    CASE
                        WHEN dp.manual_seed IS NULL THEN 1
                        ELSE 0
                    END,
                    dp.manual_seed,
                    gm.player_id
                """,
                (
                    draft_id,
                    group["group_id"],
                ),
            ).fetchall()

            player_ids = [
                str(member["player_id"])
                for member in members
            ]

            if len(player_ids) < 2:
                raise ValueError(
                    f"{group['group_name']} must contain "
                    "at least two players."
                )

            group_members[str(group["group_id"])] = player_ids

        # Recreating matches discards all existing group-match results.
        connection.execute(
            """
            DELETE FROM tournament_draft_group_matches
            WHERE group_id IN (
                SELECT group_id
                FROM tournament_draft_groups
                WHERE draft_id = ?
            )
            """,
            (draft_id,),
        )

        for group in group_rows:
            group_id = str(group["group_id"])

            rounds = generate_round_robin_pairings(
                group_members[group_id]
            )

            for round_number, pairings in enumerate(
                rounds,
                start=1,
            ):
                for match_number, (
                    player_1_id,
                    player_2_id,
                ) in enumerate(
                    pairings,
                    start=1,
                ):
                    group_match_id = (
                        f"group_match_{uuid.uuid4().hex}"
                    )

                    connection.execute(
                        """
                        INSERT INTO tournament_draft_group_matches (
                            group_match_id,
                            group_id,
                            round_number,
                            match_number,
                            player_1_id,
                            player_2_id,
                            status
                        )
                        VALUES (?, ?, ?, ?, ?, ?, 'pending')
                        """,
                        (
                            group_match_id,
                            group_id,
                            round_number,
                            match_number,
                            player_1_id,
                            player_2_id,
                        ),
                    )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

    return get_draft_group_matches(
        db_path,
        draft_id,
    )

def reset_draft_group_matches(
    db_path: str | Path,
    draft_id: str,
) -> None:
    """Deletes all group-stage matches for a tournament draft."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["format_type"] != FORMAT_GROUP_STAGE:
            raise ValueError(
                "Group matches are only available for "
                "group-stage tournaments."
            )

        if draft["status"] != "draft":
            raise ValueError(
                "Group matches can only be reset while "
                "the tournament is still a draft."
            )

        connection.execute(
            """
            DELETE FROM tournament_draft_group_matches
            WHERE group_id IN (
                SELECT group_id
                FROM tournament_draft_groups
                WHERE draft_id = ?
            )
            """,
            (draft_id,),
        )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

def update_draft_group_match(
    db_path: str | Path,
    group_match_id: str,
    *,
    status: str,
    winner_id: str | None = None,
    player_1_score: int | None = None,
    player_2_score: int | None = None,
) -> dict[str, Any]:
    """Updates the result and status of one group-stage match."""

    if status not in VALID_GROUP_MATCH_STATUSES:
        raise ValueError(
            f"Unsupported group-match status: {status}"
        )

    if player_1_score is not None and player_1_score < 0:
        raise ValueError("Player 1 score cannot be negative.")

    if player_2_score is not None and player_2_score < 0:
        raise ValueError("Player 2 score cannot be negative.")

    with connect_db(db_path) as connection:
        match = connection.execute(
            """
            SELECT
                gm.group_match_id,
                gm.player_1_id,
                gm.player_2_id,
                g.draft_id,
                d.format_type,
                d.status AS draft_status
            FROM tournament_draft_group_matches AS gm
            JOIN tournament_draft_groups AS g
              ON g.group_id = gm.group_id
            JOIN tournament_drafts AS d
              ON d.draft_id = g.draft_id
            WHERE gm.group_match_id = ?
            """,
            (group_match_id,),
        ).fetchone()

        if match is None:
            raise ValueError(
                f"Group match not found: {group_match_id}"
            )

        if match["format_type"] != FORMAT_GROUP_STAGE:
            raise ValueError(
                "Group-match results are only available for "
                "group-stage tournaments."
            )

        if match["draft_status"] != "draft":
            raise ValueError(
                "Group-match results can only be changed while "
                "the tournament is still a draft."
            )

        player_1_id = str(match["player_1_id"])
        player_2_id = str(match["player_2_id"])

        if status == GROUP_MATCH_COMPLETED:
            if player_1_score is None or player_2_score is None:
                raise ValueError(
                    "A played match requires both scores."
                )

            if player_1_score == player_2_score:
                raise ValueError(
                    "A played match cannot end in a draw."
                )

            calculated_winner_id = (
                player_1_id
                if player_1_score > player_2_score
                else player_2_id
            )

            if (
                winner_id is not None
                and winner_id != calculated_winner_id
            ):
                raise ValueError(
                    "The selected winner does not match the score."
                )

            winner_id = calculated_winner_id

        elif status == GROUP_MATCH_FORFEIT:
            if winner_id not in {player_1_id, player_2_id}:
                raise ValueError(
                    "Select the winner of the W–L match."
                )

            player_1_score = None
            player_2_score = None

        elif status in {
            GROUP_MATCH_PENDING,
            GROUP_MATCH_CANCELLED,
        }:
            winner_id = None
            player_1_score = None
            player_2_score = None

        try:
            connection.execute(
                """
                UPDATE tournament_draft_group_matches
                SET
                    status = ?,
                    winner_id = ?,
                    player_1_score = ?,
                    player_2_score = ?,
                    completed_at = CASE
                        WHEN ? IN ('completed', 'forfeit')
                        THEN CURRENT_TIMESTAMP
                        ELSE NULL
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE group_match_id = ?
                """,
                (
                    status,
                    winner_id,
                    player_1_score,
                    player_2_score,
                    status,
                    group_match_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "The group-match result could not be saved."
            ) from exc

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (match["draft_id"],),
        )

        updated_match = connection.execute(
            """
            SELECT
                gm.group_match_id,
                gm.group_id,
                g.group_number,
                g.group_name,
                gm.round_number,
                gm.match_number,
                gm.player_1_id,
                p1.display_name AS player_1,
                gm.player_2_id,
                p2.display_name AS player_2,
                gm.winner_id,
                winner.display_name AS winner,
                gm.player_1_score,
                gm.player_2_score,
                gm.status,
                gm.completed_at,
                gm.created_at,
                gm.updated_at
            FROM tournament_draft_group_matches AS gm
            JOIN tournament_draft_groups AS g
              ON g.group_id = gm.group_id
            JOIN players AS p1
              ON p1.player_id = gm.player_1_id
            JOIN players AS p2
              ON p2.player_id = gm.player_2_id
            LEFT JOIN players AS winner
              ON winner.player_id = gm.winner_id
            WHERE gm.group_match_id = ?
            """,
            (group_match_id,),
        ).fetchone()

    if updated_match is None:
        raise ValueError(
            "The updated group match could not be loaded."
        )

    return dict(updated_match)

def _percentage(
    numerator: int,
    denominator: int,
) -> float | None:
    """Returns a percentage or None when no attempts exist."""

    if denominator <= 0:
        return None

    return numerator / denominator * 100.0

def _mini_table_wins(
    player_ids: set[str],
    matches: list[dict[str, Any]],
) -> dict[str, int]:
    """Counts set wins only in matches between tied players."""

    wins = {
        player_id: 0
        for player_id in player_ids
    }

    for match in matches:
        if match["status"] not in {
            GROUP_MATCH_COMPLETED,
            GROUP_MATCH_FORFEIT,
        }:
            continue

        player_1_id = str(match["player_1_id"])
        player_2_id = str(match["player_2_id"])

        if (
            player_1_id not in player_ids
            or player_2_id not in player_ids
        ):
            continue

        winner_id = match["winner_id"]

        if winner_id is not None:
            wins[str(winner_id)] += 1

    return wins

def _resolve_group_tie(
    tied_players: list[dict[str, Any]],
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolves tied players using mini-tables and fallback criteria."""

    if len(tied_players) <= 1:
        return tied_players

    tied_player_ids = {
        str(player["player_id"])
        for player in tied_players
    }

    mini_wins = _mini_table_wins(
        tied_player_ids,
        matches,
    )

    mini_win_values = {
        mini_wins[str(player["player_id"])]
        for player in tied_players
    }

    # A useful mini-table must split the tied group into
    # at least two different win totals.
    if len(mini_win_values) > 1:
        groups_by_mini_wins: dict[
            int,
            list[dict[str, Any]],
        ] = {}

        for player in tied_players:
            player_id = str(player["player_id"])
            mini_win_count = mini_wins[player_id]

            player_with_tiebreak = {
                **player,
                "mini_table_wins": mini_win_count,
            }

            groups_by_mini_wins.setdefault(
                mini_win_count,
                [],
            ).append(player_with_tiebreak)

        resolved: list[dict[str, Any]] = []

        for mini_win_count in sorted(
            groups_by_mini_wins,
            reverse=True,
        ):
            subgroup = groups_by_mini_wins[
                mini_win_count
            ]

            if len(subgroup) > 1:
                subgroup = _resolve_group_tie(
                    subgroup,
                    matches,
                )

            resolved.extend(subgroup)

        return resolved

    # The mini-table could not split the players.
    # Continue with the remaining tournament rules.
    return sorted(
        tied_players,
        key=lambda player: (
            -(
                float(player["game_win_percentage"])
                if player["game_win_percentage"] is not None
                else -1.0
            ),
            -int(player["games_won"]),
            -float(player["initial_elo"]),
            int(player["initial_seed"]),
            str(player["player"]).casefold(),
        ),
    )

def get_draft_group_standings(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """Calculates the current standings for every draft group."""

    elo_ranking = stats.get_elo_ranking(
        db_path,
        active_only=False,
    )

    elo_by_player_id = {
        str(entry["player_id"]): float(entry["elo"])
        for entry in elo_ranking
    }

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        if draft["format_type"] != FORMAT_GROUP_STAGE:
            raise ValueError(
                "Group standings are only available for "
                "group-stage tournaments."
            )

        group_rows = connection.execute(
            """
            SELECT
                group_id,
                group_number,
                group_name
            FROM tournament_draft_groups
            WHERE draft_id = ?
            ORDER BY group_number
            """,
            (draft_id,),
        ).fetchall()

        standings_by_group: list[dict[str, Any]] = []

        for group in group_rows:
            group_id = str(group["group_id"])

            member_rows = connection.execute(
                """
                SELECT
                    gm.player_id,
                    p.display_name AS player,
                    dp.manual_seed AS initial_seed
                FROM tournament_draft_group_members AS gm
                JOIN players AS p
                  ON p.player_id = gm.player_id
                JOIN tournament_draft_participants AS dp
                  ON dp.draft_id = ?
                 AND dp.player_id = gm.player_id
                WHERE gm.group_id = ?
                ORDER BY
                    dp.manual_seed,
                    p.display_name COLLATE NOCASE
                """,
                (
                    draft_id,
                    group_id,
                ),
            ).fetchall()

            match_rows = connection.execute(
                """
                SELECT
                    group_match_id,
                    player_1_id,
                    player_2_id,
                    winner_id,
                    player_1_score,
                    player_2_score,
                    status
                FROM tournament_draft_group_matches
                WHERE group_id = ?
                ORDER BY
                    round_number,
                    match_number
                """,
                (group_id,),
            ).fetchall()

            matches = [
                dict(match)
                for match in match_rows
            ]

            standings: dict[
                str,
                dict[str, Any],
            ] = {}

            for member in member_rows:
                player_id = str(member["player_id"])

                standings[player_id] = {
                    "player_id": player_id,
                    "player": str(member["player"]),
                    "initial_seed": int(
                        member["initial_seed"]
                    ),
                    "initial_elo": elo_by_player_id.get(
                        player_id,
                        1000.0,
                    ),
                    "sets_played": 0,
                    "sets_won": 0,
                    "sets_lost": 0,
                    "games_won": 0,
                    "games_lost": 0,
                    "mini_table_wins": None,
                }

            for match in matches:
                status = str(match["status"])

                if status not in {
                    GROUP_MATCH_COMPLETED,
                    GROUP_MATCH_FORFEIT,
                }:
                    continue

                player_1_id = str(
                    match["player_1_id"]
                )
                player_2_id = str(
                    match["player_2_id"]
                )
                winner_id = str(match["winner_id"])

                player_1 = standings[player_1_id]
                player_2 = standings[player_2_id]

                player_1["sets_played"] += 1
                player_2["sets_played"] += 1

                if winner_id == player_1_id:
                    player_1["sets_won"] += 1
                    player_2["sets_lost"] += 1
                else:
                    player_2["sets_won"] += 1
                    player_1["sets_lost"] += 1

                # W–L matches count as sets but do not add games.
                if status == GROUP_MATCH_COMPLETED:
                    player_1_score = int(
                        match["player_1_score"]
                    )
                    player_2_score = int(
                        match["player_2_score"]
                    )

                    player_1["games_won"] += (
                        player_1_score
                    )
                    player_1["games_lost"] += (
                        player_2_score
                    )

                    player_2["games_won"] += (
                        player_2_score
                    )
                    player_2["games_lost"] += (
                        player_1_score
                    )

            standing_rows = list(
                standings.values()
            )

            for player in standing_rows:
                player["set_win_percentage"] = (
                    _percentage(
                        int(player["sets_won"]),
                        int(player["sets_played"]),
                    )
                )

                total_games = (
                    int(player["games_won"])
                    + int(player["games_lost"])
                )

                player["game_win_percentage"] = (
                    _percentage(
                        int(player["games_won"]),
                        total_games,
                    )
                )

            # First criterion: total set wins.
            players_by_set_wins: dict[
                int,
                list[dict[str, Any]],
            ] = {}

            for player in standing_rows:
                players_by_set_wins.setdefault(
                    int(player["sets_won"]),
                    [],
                ).append(player)

            ordered_players: list[
                dict[str, Any]
            ] = []

            for set_win_count in sorted(
                players_by_set_wins,
                reverse=True,
            ):
                tied_players = players_by_set_wins[
                    set_win_count
                ]

                if len(tied_players) > 1:
                    tied_players = _resolve_group_tie(
                        tied_players,
                        matches,
                    )

                ordered_players.extend(
                    tied_players
                )

            for placement, player in enumerate(
                ordered_players,
                start=1,
            ):
                player["placement"] = placement

            total_matches = len(matches)
            decided_matches = sum(
                str(match["status"])
                in {
                    GROUP_MATCH_COMPLETED,
                    GROUP_MATCH_FORFEIT,
                }
                for match in matches
            )
            cancelled_matches = sum(
                str(match["status"])
                == GROUP_MATCH_CANCELLED
                for match in matches
            )
            pending_matches = sum(
                str(match["status"])
                == GROUP_MATCH_PENDING
                for match in matches
            )

            standings_by_group.append(
                {
                    "group_id": group_id,
                    "group_number": int(
                        group["group_number"]
                    ),
                    "group_name": str(
                        group["group_name"]
                    ),
                    "standings": ordered_players,
                    "total_matches": total_matches,
                    "decided_matches": decided_matches,
                    "cancelled_matches":
                        cancelled_matches,
                    "pending_matches": pending_matches,
                    "complete": (
                        pending_matches == 0
                    ),
                }
            )

    return standings_by_group

def _next_power_of_two(value: int) -> int:
    """Returns the smallest power of two greater than or equal to value."""

    if value <= 0:
        raise ValueError("The value must be greater than zero.")

    power = 1

    while power < value:
        power *= 2

    return power

def get_draft_global_group_ranking(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """Builds the global ranking after the tournament group stage."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                bracket_entry_mode
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        if draft["format_type"] != FORMAT_GROUP_STAGE:
            raise ValueError(
                "A global group ranking is only available for "
                "group-stage tournaments."
            )

    group_standings = get_draft_group_standings(
        db_path,
        draft_id,
    )

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
    bracket_size = _next_power_of_two(
        participant_count
    )

    bracket_entry_mode = str(
        draft["bracket_entry_mode"]
    )

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

def create_draft_bracket_seed_snapshot(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """
    Saves the final bracket seeding as an immutable snapshot.

    For group-stage tournaments, the global group ranking is used.
    For bracket-only tournaments, the current participant order is used.
    """

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                format_type,
                bracket_entry_mode,
                status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(
                f"Tournament draft not found: {draft_id}"
            )

        existing_matches = connection.execute(
            """
            SELECT 1
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()

        if existing_matches is not None:
            raise ValueError(
                "The bracket seed snapshot cannot be changed after "
                "the bracket has been generated."
            )

        if draft["format_type"] == FORMAT_GROUP_STAGE:
            ranking_result = get_draft_global_group_ranking(
                db_path,
                draft_id,
            )

            if not ranking_result["complete"]:
                raise ValueError(
                    "All group matches must be decided before "
                    "the bracket seeding can be created."
                )

            seed_rows = [
                {
                    "player_id": str(player["player_id"]),
                    "bracket_seed": int(
                        player["global_seed"]
                    ),
                    "starts_in": str(player["starts_in"]),
                }
                for player in ranking_result["ranking"]
            ]

        else:
            participants = connection.execute(
                """
                SELECT
                    dp.player_id,
                    dp.manual_seed,
                    p.display_name
                FROM tournament_draft_participants AS dp
                JOIN players AS p
                  ON p.player_id = dp.player_id
                WHERE dp.draft_id = ?
                ORDER BY
                    CASE
                        WHEN dp.manual_seed IS NULL THEN 1
                        ELSE 0
                    END,
                    dp.manual_seed,
                    p.display_name COLLATE NOCASE
                """,
                (draft_id,),
            ).fetchall()

            seed_rows = [
                {
                    "player_id": str(player["player_id"]),
                    "bracket_seed": seed,
                    "starts_in": BRACKET_SIDE_WINNERS,
                }
                for seed, player in enumerate(
                    participants,
                    start=1,
                )
            ]

        if len(seed_rows) < 3:
            raise ValueError(
                "A double-elimination bracket requires at least "
                "3 participants."
            )

        get_bracket_size(len(seed_rows))

        connection.execute(
            """
            DELETE FROM tournament_draft_bracket_seeds
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

        connection.executemany(
            """
            INSERT INTO tournament_draft_bracket_seeds (
                draft_id,
                player_id,
                bracket_seed,
                starts_in
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    draft_id,
                    row["player_id"],
                    row["bracket_seed"],
                    row["starts_in"],
                )
                for row in seed_rows
            ],
        )

        connection.executemany(
            """
            UPDATE tournament_draft_participants
            SET
                bracket_seed = ?,
                starts_in = ?
            WHERE draft_id = ?
              AND player_id = ?
            """,
            [
                (
                    row["bracket_seed"],
                    row["starts_in"],
                    draft_id,
                    row["player_id"],
                )
                for row in seed_rows
            ],
        )

    return seed_rows

def remove_participant(
    db_path: str | Path,
    draft_id: str,
    player_id: str,
) -> None:
    """Removes one player from a tournament draft."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                status,
                format_type
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["status"] not in {"draft", "group_stage", "bracket_ready"}:
            raise ValueError(
                "Participants cannot be changed after the group matches "
                "have been generated. Reset the group matches first."
            )
        
        if (
            draft["format_type"] == FORMAT_GROUP_STAGE
            and _draft_has_group_matches(connection, draft_id)
        ):
            raise ValueError(
                "Participants cannot be changed after the group matches "
                "have been generated. Reset the group matches first."
            )

        cursor = connection.execute(
            """
            DELETE FROM tournament_draft_participants
            WHERE draft_id = ?
              AND player_id = ?
            """,
            (draft_id, player_id),
        )

        if cursor.rowcount == 0:
            raise ValueError(
                "The player is not part of this tournament draft."
            )

        if draft["format_type"] == FORMAT_DOUBLE_ELIMINATION:
            remaining_participants = connection.execute(
                """
                SELECT player_id
                FROM tournament_draft_participants
                WHERE draft_id = ?
                ORDER BY
                    CASE
                        WHEN manual_seed IS NULL THEN 1
                        ELSE 0
                    END,
                    manual_seed,
                    player_id
                """,
                (draft_id,),
            ).fetchall()

            connection.execute(
                """
                UPDATE tournament_draft_participants
                SET
                    manual_seed = NULL,
                    bracket_seed = NULL
                WHERE draft_id = ?
                """,
                (draft_id,),
            )

            for seed, participant in enumerate(
                remaining_participants,
                start=1,
            ):
                connection.execute(
                    """
                    UPDATE tournament_draft_participants
                    SET
                        manual_seed = ?,
                        bracket_seed = ?
                    WHERE draft_id = ?
                      AND player_id = ?
                    """,
                    (
                        seed,
                        seed,
                        draft_id,
                        participant["player_id"],
                    ),
                )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )


def delete_draft(
    db_path: str | Path,
    draft_id: str,
) -> None:
    """Permanently deletes a tournament draft and its participants."""

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT status
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()

        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")

        if draft["status"] in {"in_progress", "completed"}:
            raise ValueError(
                "An active or completed tournament cannot "
                "be deleted as a draft."
            )

        connection.execute(
            """
            DELETE FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        )