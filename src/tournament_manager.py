#!/usr/bin/env python3
"""Create and manage Smash World Championship tournament drafts."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any


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


def connect_db(db_path: str | Path) -> sqlite3.Connection:
    """Opens the SQLite database with foreign keys enabled."""

    path = Path(db_path)

    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


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

        if draft["format_type"] != FORMAT_DOUBLE_ELIMINATION:
            raise ValueError(
                "Manual participant order is currently only available "
                "for double-elimination-only tournaments."
            )

        if draft["status"] != "draft":
            raise ValueError(
                "Participant order can only be changed while "
                "the tournament is still a draft."
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
                "Participants cannot be removed after "
                "the tournament has started."
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