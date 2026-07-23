"""Manage player profiles and tournament draft participation."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from db.connection import open_sqlite_connection
from tournament.bracket_planning import ENTRY_SPLIT_BY_GROUP_SEED
from tournament.drafts import get_draft

FORMAT_GROUP_STAGE = "group_stage_double_elimination"
FORMAT_DOUBLE_ELIMINATION = "double_elimination"
VALID_START_POSITIONS = {"winners", "losers"}
connect_db = open_sqlite_connection


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
