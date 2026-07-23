#!/usr/bin/env python3
"""Create and manage Smash World Championship tournament drafts."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any
import smash_statistics as stats
from db.connection import open_sqlite_connection
from tournament.bracket_planning import (
    BRACKET_SIDE_FINALS,
    BRACKET_SIDE_LOSERS,
    BRACKET_SIDE_WINNERS,
    ENTRY_ALL_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
    MAX_BRACKET_SIZE,
    MIN_BRACKET_SIZE,
    build_all_winners_bracket_plan,
    build_all_winners_route_plan,
    build_bracket_plan,
    build_bracket_route_plan,
    build_split_bracket_plan,
    build_split_bracket_route_plan,
    get_bracket_size,
    get_first_round_seed_pairs,
    get_split_bracket_seed_pairs,
    get_standard_seed_order,
)
from tournament.group_stage_pairings import (
    generate_round_robin_pairings,
)
from tournament.group_stage_ranking import (
    build_global_group_ranking,
)
from tournament.group_stage_standings import (
    GROUP_MATCH_CANCELLED,
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
    GROUP_MATCH_PENDING,
    VALID_GROUP_MATCH_STATUSES,
    calculate_group_standings,
)


FORMAT_GROUP_STAGE = "group_stage_double_elimination"
FORMAT_DOUBLE_ELIMINATION = "double_elimination"

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

BRACKET_START_ALL_WINNERS = "all_winners"
BRACKET_START_SPLIT = "split_by_group_seed"


from tournament.bracket_generation import (
    create_draft_bracket_matches,
    create_draft_bracket_routes,
    generate_draft_bracket as _generate_draft_bracket,
    get_draft_bracket_matches,
    get_draft_bracket_routes,
    get_draft_bracket_state,
    reset_draft_bracket,
    seed_draft_bracket_matches,
)


def generate_draft_bracket(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """Generate a bracket using the current draft seed snapshot rules."""

    return _generate_draft_bracket(
        db_path,
        draft_id,
        create_seed_snapshot=create_draft_bracket_seed_snapshot,
    )


from tournament.finalization import (
    finalize_draft_tournament,
    get_draft_finalization_preview,
)


from tournament.legacy_split_bracket import (
    create_draft_split_bracket_matches,
    create_draft_split_bracket_routes,
    seed_draft_split_bracket_matches,
)

from tournament.bracket_finalization import (
    get_draft_bracket_champion,
    sync_draft_grand_final_reset,
)
from tournament.bracket_progression import (
    propagate_draft_bracket_results,
)
from tournament.bracket_results import (
    reset_draft_bracket_match_result,
    update_draft_bracket_match,
)


def connect_db(db_path: str | Path) -> sqlite3.Connection:
    """Opens the SQLite database with foreign keys enabled."""

    return open_sqlite_connection(db_path)

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




def get_draft_group_standings(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """Load each group and calculate its current ordered standings."""

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
            SELECT format_type
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

            calculation = calculate_group_standings(
                [dict(member) for member in member_rows],
                [dict(match) for match in match_rows],
                elo_by_player_id,
            )

            standings_by_group.append(
                {
                    "group_id": group_id,
                    "group_number": int(group["group_number"]),
                    "group_name": str(group["group_name"]),
                    **calculation,
                }
            )

    return standings_by_group


def get_draft_global_group_ranking(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """Load Group standings and build the global Bracket seed order."""

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

        bracket_entry_mode = str(
            draft["bracket_entry_mode"]
        )

    group_standings = get_draft_group_standings(
        db_path,
        draft_id,
    )

    return build_global_group_ranking(
        group_standings,
        bracket_entry_mode,
    )

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
