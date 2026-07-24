"""Persist and evaluate Group Stage structures for tournament drafts."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

import smash_statistics as stats
from db.connection import open_sqlite_connection
from tournament.group_stage_pairings import generate_round_robin_pairings
from tournament.group_stage_ranking import build_global_group_ranking
from tournament.group_stage_standings import (
    GROUP_MATCH_CANCELLED,
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
    GROUP_MATCH_PENDING,
    VALID_GROUP_MATCH_STATUSES,
    calculate_group_standings,
)
from tournament.participants import _draft_has_group_matches

FORMAT_GROUP_STAGE = "group_stage_double_elimination"
connect_db = open_sqlite_connection


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

        bracket_exists = connection.execute(
            """
            SELECT 1
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()

        if bracket_exists is not None:
            raise ValueError(
                "Reset the bracket before resetting the group matches."
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

        bracket_exists = connection.execute(
            """
            SELECT 1
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            LIMIT 1
            """,
            (match["draft_id"],),
        ).fetchone()

        if bracket_exists is not None:
            raise ValueError(
                "Reset the bracket before changing group-match results."
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
