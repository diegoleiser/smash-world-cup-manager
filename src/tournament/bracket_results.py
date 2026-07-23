"""Validate, save, and reset draft bracket results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db.connection import open_sqlite_connection
from tournament.bracket_finalization import (
    get_draft_bracket_champion,
    sync_draft_grand_final_reset,
)
from tournament.bracket_progression import propagate_draft_bracket_results

connect_db = open_sqlite_connection


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
