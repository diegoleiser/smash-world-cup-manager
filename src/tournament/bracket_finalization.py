"""Resolve Grand Final Reset state and the bracket champion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db.connection import open_sqlite_connection

connect_db = open_sqlite_connection


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
