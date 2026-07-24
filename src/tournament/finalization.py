"""Validate completed drafts and archive them as tournaments.

This module owns the final boundary between editable Tournament Manager drafts
and the permanent tournament, participant, and match archive.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from db.connection import open_sqlite_connection
from tournament.bracket_constants import BRACKET_SIDE_LOSERS
from tournament.bracket_finalization import get_draft_bracket_champion
from tournament.group_stage_standings import (
    GROUP_MATCH_CANCELLED,
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
    GROUP_MATCH_PENDING,
)


FORMAT_GROUP_STAGE = "group_stage_double_elimination"
connect_db = open_sqlite_connection


def _get_bracket_match_loser_id(
    match: sqlite3.Row | dict[str, Any],
) -> str | None:
    """Return the losing player of a decided two-player match."""

    player_1_id = match["player_1_id"]
    player_2_id = match["player_2_id"]
    winner_id = match["winner_id"]

    if (
        player_1_id is None
        or player_2_id is None
        or winner_id is None
    ):
        return None

    player_1_id = str(player_1_id)
    player_2_id = str(player_2_id)
    winner_id = str(winner_id)

    if winner_id == player_1_id:
        return player_2_id

    if winner_id == player_2_id:
        return player_1_id

    raise ValueError(
        "A bracket winner is not one of the assigned players."
    )


def get_draft_finalization_preview(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """
    Validate a completed draft and calculate its archive preview.

    This function does not modify the database.

    Placements are calculated from:
    - Champion
    - Grand Final or Grand Final Reset loser
    - Losers Final loser
    - remaining Losers Bracket elimination rounds
    """

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                draft_id,
                tournament_number,
                tournament_date,
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
                "Only an unfinished tournament draft can be finalized."
            )

        if not draft["tournament_date"]:
            raise ValueError(
                "Set a tournament date before finalizing the tournament."
            )

        existing_tournament = connection.execute(
            """
            SELECT tournament_id
            FROM tournaments
            WHERE tournament_number = ?
            """,
            (draft["tournament_number"],),
        ).fetchone()

        if existing_tournament is not None:
            raise ValueError(
                f"WC {int(draft['tournament_number']):02d} "
                "already exists in the archive."
            )

        participant_rows = connection.execute(
            """
            SELECT
                dp.player_id,
                p.display_name AS player,
                dp.manual_seed,
                dp.bracket_seed
            FROM tournament_draft_participants AS dp
            JOIN players AS p
              ON p.player_id = dp.player_id
            WHERE dp.draft_id = ?
            ORDER BY
                dp.bracket_seed,
                dp.manual_seed,
                p.display_name COLLATE NOCASE
            """,
            (draft_id,),
        ).fetchall()

        if len(participant_rows) < 3:
            raise ValueError(
                "At least 3 participants are required."
            )

        bracket_rows = connection.execute(
            """
            SELECT
                bracket_match_id,
                match_code,
                bracket_side,
                round_number,
                match_number,
                round_label,
                match_type,
                player_1_id,
                player_2_id,
                winner_id,
                player_1_score,
                player_2_score,
                status,
                completed_at
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
            ORDER BY
                CASE bracket_side
                    WHEN 'winners' THEN 1
                    WHEN 'losers' THEN 2
                    WHEN 'finals' THEN 3
                    ELSE 4
                END,
                round_number,
                match_number
            """,
            (draft_id,),
        ).fetchall()

        if not bracket_rows:
            raise ValueError(
                "Generate and complete the bracket before finalizing."
            )

        unfinished_bracket_matches = [
            str(match["match_code"])
            for match in bracket_rows
            if str(match["status"]) in {
                "pending",
                "waiting",
            }
        ]

        if unfinished_bracket_matches:
            raise ValueError(
                "The bracket is not complete. Unfinished matches: "
                + ", ".join(unfinished_bracket_matches)
            )

        group_match_rows: list[sqlite3.Row] = []

        if str(draft["format_type"]) == FORMAT_GROUP_STAGE:
            group_match_rows = connection.execute(
                """
                SELECT
                    gm.group_match_id,
                    g.group_number,
                    g.group_name,
                    gm.round_number,
                    gm.match_number,
                    gm.player_1_id,
                    gm.player_2_id,
                    gm.winner_id,
                    gm.player_1_score,
                    gm.player_2_score,
                    gm.status,
                    gm.completed_at
                FROM tournament_draft_group_matches AS gm
                JOIN tournament_draft_groups AS g
                  ON g.group_id = gm.group_id
                WHERE g.draft_id = ?
                ORDER BY
                    g.group_number,
                    gm.round_number,
                    gm.match_number
                """,
                (draft_id,),
            ).fetchall()

            if not group_match_rows:
                raise ValueError(
                    "The group-stage matches are missing."
                )

            unfinished_group_matches = [
                (
                    f"{match['group_name']} "
                    f"Round {match['round_number']} "
                    f"Match {match['match_number']}"
                )
                for match in group_match_rows
                if str(match["status"]) == GROUP_MATCH_PENDING
            ]

            if unfinished_group_matches:
                raise ValueError(
                    "The group stage is not complete. "
                    "Unfinished matches: "
                    + ", ".join(unfinished_group_matches)
                )

        player_names = {
            str(player["player_id"]): str(player["player"])
            for player in participant_rows
        }
        bracket_seeds = {
            str(player["player_id"]): int(player["bracket_seed"])
            for player in participant_rows
            if player["bracket_seed"] is not None
        }

        match_by_code = {
            str(match["match_code"]): match
            for match in bracket_rows
        }

        grand_final = match_by_code.get("GF")
        reset_final = match_by_code.get("GFR")
        losers_final = match_by_code.get("LF")

        if (
            grand_final is None
            or reset_final is None
            or losers_final is None
        ):
            raise ValueError(
                "Grand Final, Grand Final Reset, or "
                "Losers Final is missing."
            )

        champion_id = get_draft_bracket_champion(
            db_path,
            draft_id,
        )

        if champion_id is None:
            raise ValueError(
                "The bracket does not have a confirmed champion."
            )

        placements: dict[str, int] = {
            champion_id: 1,
        }

        if str(reset_final["status"]) in {
            "completed",
            "forfeit",
        }:
            runner_up_id = _get_bracket_match_loser_id(
                reset_final
            )
        else:
            runner_up_id = _get_bracket_match_loser_id(
                grand_final
            )

        if runner_up_id is None:
            raise ValueError(
                "The runner-up could not be determined."
            )

        placements[runner_up_id] = 2

        third_place_id = _get_bracket_match_loser_id(
            losers_final
        )

        if third_place_id is None:
            raise ValueError(
                "Third place could not be determined."
            )

        placements[third_place_id] = 3

        elimination_groups: dict[int, list[str]] = {}

        for match in bracket_rows:
            if str(match["bracket_side"]) != BRACKET_SIDE_LOSERS:
                continue

            if str(match["match_code"]) == "LF":
                continue

            match_status = str(match["status"])

            if match_status not in {
                "completed",
                "forfeit",
                "cancelled",
            }:
                continue

            if match_status == "cancelled":
                player_1_id = match["player_1_id"]
                player_2_id = match["player_2_id"]

                if (
                    player_1_id is None
                    or player_2_id is None
                    or str(player_1_id) not in bracket_seeds
                    or str(player_2_id) not in bracket_seeds
                ):
                    continue

                # Both players leave the tournament. The worse-seeded
                # player belongs to this round; the better-seeded player
                # is represented by the automatic forfeit in the next one.
                loser_id = max(
                    (str(player_1_id), str(player_2_id)),
                    key=bracket_seeds.__getitem__,
                )
            else:
                loser_id = _get_bracket_match_loser_id(
                    match
                )

            if loser_id is None:
                continue

            if loser_id in placements:
                continue

            round_number = int(match["round_number"])

            elimination_groups.setdefault(
                round_number,
                [],
            ).append(loser_id)

        next_placement = 4

        for round_number in sorted(
            elimination_groups,
            reverse=True,
        ):
            eliminated_player_ids = list(
                dict.fromkeys(
                    elimination_groups[round_number]
                )
            )

            for player_id in eliminated_player_ids:
                placements[player_id] = next_placement

            next_placement += len(
                eliminated_player_ids
            )

        participant_ids = {
            str(player["player_id"])
            for player in participant_rows
        }

        placed_player_ids = set(placements)

        if placed_player_ids != participant_ids:
            missing_player_ids = sorted(
                participant_ids - placed_player_ids
            )

            missing_names = [
                player_names.get(player_id, player_id)
                for player_id in missing_player_ids
            ]

            raise ValueError(
                "Placements could not be calculated for: "
                + ", ".join(missing_names)
            )

        placement_rows = sorted(
            [
                {
                    "player_id": player_id,
                    "player": player_names[player_id],
                    "placement": placement,
                    "seed": next(
                        (
                            int(player["bracket_seed"])
                            for player in participant_rows
                            if (
                                str(player["player_id"])
                                == player_id
                                and player["bracket_seed"]
                                is not None
                            )
                        ),
                        None,
                    ),
                }
                for player_id, placement in placements.items()
            ],
            key=lambda row: (
                int(row["placement"]),
                str(row["player"]).casefold(),
            ),
        )

        archived_group_matches = [
            match
            for match in group_match_rows
            if str(match["status"]) in {
                GROUP_MATCH_COMPLETED,
                GROUP_MATCH_FORFEIT,
            }
        ]

        archived_bracket_matches = [
            match
            for match in bracket_rows
            if str(match["status"]) in {
                "completed",
                "forfeit",
            }
        ]

    return {
        "draft_id": draft_id,
        "tournament_number": int(
            draft["tournament_number"]
        ),
        "tournament_date": str(
            draft["tournament_date"]
        ),
        "format_type": str(
            draft["format_type"]
        ),
        "bracket_entry_mode": str(
            draft["bracket_entry_mode"]
        ),
        "participant_count": len(
            participant_rows
        ),
        "champion_id": champion_id,
        "champion_name": player_names[
            champion_id
        ],
        "placements": placement_rows,
        "group_matches_to_archive": len(
            archived_group_matches
        ),
        "bracket_matches_to_archive": len(
            archived_bracket_matches
        ),
        "matches_to_archive": (
            len(archived_group_matches)
            + len(archived_bracket_matches)
        ),
        "cancelled_group_matches_omitted": sum(
            str(match["status"])
            == GROUP_MATCH_CANCELLED
            for match in group_match_rows
        ),
        "automatic_bracket_matches_omitted": sum(
            str(match["status"]) in {
                "bye",
                "cancelled",
                "inactive",
            }
            for match in bracket_rows
        ),
        "ready": True,
    }

def finalize_draft_tournament(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """
    Archive a completed tournament draft.

    The operation writes:
    - tournament
    - tournament participants and placements
    - completed group-stage matches
    - completed bracket matches

    The draft is marked as completed only after every archive row
    has been inserted successfully.
    """

    preview = get_draft_finalization_preview(
        db_path,
        draft_id,
    )

    tournament_id = (
        f"tournament_{uuid.uuid4().hex}"
    )

    with connect_db(db_path) as connection:
        draft = connection.execute(
            """
            SELECT
                draft_id,
                tournament_number,
                tournament_date,
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
                "Only an unfinished draft can be finalized."
            )

        existing_tournament = connection.execute(
            """
            SELECT tournament_id
            FROM tournaments
            WHERE tournament_number = ?
            """,
            (preview["tournament_number"],),
        ).fetchone()

        if existing_tournament is not None:
            raise ValueError(
                f"WC {preview['tournament_number']:02d} "
                "already exists in the archive."
            )

        connection.execute(
            """
            INSERT INTO tournaments (
                tournament_id,
                tournament_number,
                tournament_date,
                winner_id,
                challonge_url,
                bracket_source,
                match_data_available,
                notes
            )
            VALUES (?, ?, ?, ?, NULL, ?, 1, ?)
            """,
            (
                tournament_id,
                preview["tournament_number"],
                preview["tournament_date"],
                preview["champion_id"],
                "tournament_manager",
                (
                    "Created from Tournament Manager draft "
                    f"{draft_id}. Format: "
                    f"{preview['format_type']}; bracket entry: "
                    f"{preview['bracket_entry_mode']}."
                ),
            ),
        )

        for placement in preview["placements"]:
            connection.execute(
                """
                INSERT INTO tournament_participants (
                    tournament_id,
                    player_id,
                    placement,
                    seed
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    tournament_id,
                    placement["player_id"],
                    placement["placement"],
                    placement["seed"],
                ),
            )

        play_order = 1
        archived_group_matches = 0
        archived_bracket_matches = 0

        if (
            preview["format_type"]
            == FORMAT_GROUP_STAGE
        ):
            group_matches = connection.execute(
                """
                SELECT
                    gm.group_match_id,
                    g.group_name,
                    gm.round_number,
                    gm.match_number,
                    gm.player_1_id,
                    gm.player_2_id,
                    gm.winner_id,
                    gm.player_1_score,
                    gm.player_2_score,
                    gm.status,
                    gm.completed_at
                FROM tournament_draft_group_matches AS gm
                JOIN tournament_draft_groups AS g
                  ON g.group_id = gm.group_id
                WHERE g.draft_id = ?
                  AND gm.status IN (
                      'completed',
                      'forfeit'
                  )
                ORDER BY
                    g.group_number,
                    gm.round_number,
                    gm.match_number
                """,
                (draft_id,),
            ).fetchall()

            for match in group_matches:
                is_completed = (
                    str(match["status"])
                    == GROUP_MATCH_COMPLETED
                )

                connection.execute(
                    """
                    INSERT INTO matches (
                        match_id,
                        tournament_id,
                        stage,
                        round_label,
                        bracket_side,
                        player_1_id,
                        player_2_id,
                        winner_id,
                        player_1_score,
                        player_2_score,
                        score_known,
                        walkover,
                        source,
                        suggested_play_order,
                        completed_at
                    )
                    VALUES (
                        ?, ?, 'group_stage', ?, 'group',
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?
                    )
                    """,
                    (
                        f"match_{uuid.uuid4().hex}",
                        tournament_id,
                        (
                            f"{match['group_name']} · "
                            f"Round {match['round_number']}"
                        ),
                        match["player_1_id"],
                        match["player_2_id"],
                        match["winner_id"],
                        (
                            match["player_1_score"]
                            if is_completed
                            else None
                        ),
                        (
                            match["player_2_score"]
                            if is_completed
                            else None
                        ),
                        int(is_completed),
                        int(not is_completed),
                        "tournament_manager",
                        play_order,
                        match["completed_at"],
                    ),
                )

                play_order += 1
                archived_group_matches += 1

        bracket_matches = connection.execute(
            """
            SELECT
                bracket_match_id,
                match_code,
                bracket_side,
                round_label,
                player_1_id,
                player_2_id,
                winner_id,
                player_1_score,
                player_2_score,
                status,
                completed_at
            FROM tournament_draft_bracket_matches
            WHERE draft_id = ?
              AND status IN (
                  'completed',
                  'forfeit'
              )
            ORDER BY
                CASE bracket_side
                    WHEN 'winners' THEN 1
                    WHEN 'losers' THEN 2
                    WHEN 'finals' THEN 3
                    ELSE 4
                END,
                round_number,
                match_number
            """,
            (draft_id,),
        ).fetchall()

        for match in bracket_matches:
            is_completed = (
                str(match["status"]) == "completed"
            )

            connection.execute(
                """
                INSERT INTO matches (
                    match_id,
                    tournament_id,
                    stage,
                    round_label,
                    bracket_side,
                    player_1_id,
                    player_2_id,
                    winner_id,
                    player_1_score,
                    player_2_score,
                    score_known,
                    walkover,
                    source,
                    suggested_play_order,
                    completed_at
                )
                VALUES (
                    ?, ?, 'bracket', ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?
                )
                """,
                (
                    f"match_{uuid.uuid4().hex}",
                    tournament_id,
                    (
                        f"{match['round_label']} "
                        f"({match['match_code']})"
                    ),
                    match["bracket_side"],
                    match["player_1_id"],
                    match["player_2_id"],
                    match["winner_id"],
                    (
                        match["player_1_score"]
                        if is_completed
                        else None
                    ),
                    (
                        match["player_2_score"]
                        if is_completed
                        else None
                    ),
                    int(is_completed),
                    int(not is_completed),
                    "tournament_manager",
                    play_order,
                    match["completed_at"],
                ),
            )

            play_order += 1
            archived_bracket_matches += 1

        # A successfully archived appearance makes every participant active
        # again. Keeping this update inside the archive transaction ensures
        # that a failed finalization cannot change player activity by itself.
        connection.execute(
            """
            UPDATE players
            SET active = 1
            WHERE player_id IN (
                SELECT player_id
                FROM tournament_draft_participants
                WHERE draft_id = ?
            )
            """,
            (draft_id,),
        )

        connection.execute(
            """
            UPDATE tournament_drafts
            SET
                status = 'completed',
                updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (draft_id,),
        )

    return {
        "tournament_id": tournament_id,
        "tournament_number":
            preview["tournament_number"],
        "champion_id":
            preview["champion_id"],
        "champion_name":
            preview["champion_name"],
        "participant_count":
            preview["participant_count"],
        "group_matches_archived":
            archived_group_matches,
        "bracket_matches_archived":
            archived_bracket_matches,
        "matches_archived": (
            archived_group_matches
            + archived_bracket_matches
        ),
        "draft_status": "completed",
    }
