"""Create, seed, inspect, and reset generated draft brackets."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from db.connection import open_sqlite_connection
from tournament.bracket_finalization import get_draft_bracket_champion
from tournament.bracket_planning import (
    BRACKET_SIDE_WINNERS,
    ENTRY_ALL_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
    build_bracket_plan,
    build_bracket_route_plan,
    get_bracket_size,
    get_first_round_seed_pairs,
    get_split_bracket_seed_pairs,
)
from tournament.bracket_progression import propagate_draft_bracket_results


connect_db = open_sqlite_connection


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
                    if (
                        bracket_entry_mode
                        == ENTRY_SPLIT_BY_GROUP_SEED
                        and bracket_size == 4
                    ):
                        match_code = "WF"
                    else:
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
    *,
    create_seed_snapshot: Callable[
        [str | Path, str],
        list[dict[str, Any]],
    ],
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
        seed_rows = create_seed_snapshot(
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

    playable_sets = [
        match
        for match in matches
        if match["status"]
        not in {
            "inactive",
            "bye",
            "cancelled",
        }
    ]

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
        "playable_set_count": len(playable_sets),
        "ready_set_count": sum(
            match["status"] == "pending"
            for match in playable_sets
        ),
        "waiting_set_count": sum(
            match["status"] == "waiting"
            for match in playable_sets
        ),
        "played_set_count": sum(
            match["status"] in {"completed", "forfeit"}
            for match in playable_sets
        ),
        "champion_id": champion_id,
        "champion_name": champion_name,
    }
