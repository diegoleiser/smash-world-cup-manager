"""Order draft participants and persist final bracket seed snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import smash_statistics as stats
from db.connection import open_sqlite_connection
from tournament.bracket_planning import BRACKET_SIDE_WINNERS, get_bracket_size
from tournament.participants import _draft_has_group_matches

FORMAT_GROUP_STAGE = "group_stage_double_elimination"
FORMAT_DOUBLE_ELIMINATION = "double_elimination"
connect_db = open_sqlite_connection


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

def create_draft_bracket_seed_snapshot(
    db_path: str | Path,
    draft_id: str,
    *,
    get_global_group_ranking: Callable[
        [str | Path, str],
        dict[str, Any],
    ],
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
            ranking_result = get_global_group_ranking(
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
