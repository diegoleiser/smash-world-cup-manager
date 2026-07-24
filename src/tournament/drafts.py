"""Create, load, update, and delete tournament drafts."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from db.connection import open_sqlite_connection
from tournament.bracket_planning import ENTRY_ALL_WINNERS

FORMAT_GROUP_STAGE = "group_stage_double_elimination"
FORMAT_DOUBLE_ELIMINATION = "double_elimination"
VALID_FORMATS = {FORMAT_GROUP_STAGE, FORMAT_DOUBLE_ELIMINATION}
VALID_ENTRY_MODES = {ENTRY_ALL_WINNERS, "split_by_group_seed"}
connect_db = open_sqlite_connection


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
                f"WC {tournament_number:02d} already exists "
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
                f"A draft for WC {tournament_number:02d} "
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
