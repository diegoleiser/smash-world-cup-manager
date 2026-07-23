"""Legacy split-bracket database helpers kept for API compatibility.

The active generator uses the shared bracket plans in bracket_generation.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from db.connection import open_sqlite_connection
from tournament.bracket_planning import (
    BRACKET_SIDE_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
    build_split_bracket_plan,
    get_bracket_size,
    get_split_bracket_seed_pairs,
)


connect_db = open_sqlite_connection


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
