#!/usr/bin/env python3
"""Milestone detection for Smash World Championship tournaments."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


APPEARANCE_MILESTONES = {5, 10}
WIN_MILESTONES = {10, 25, 50}


def _get_tournament(
    connection: sqlite3.Connection,
    tournament_number: int,
) -> sqlite3.Row:
    """Loads one tournament or raises a clear error."""

    tournament = connection.execute(
        """
        SELECT
            tournament_id,
            tournament_number,
            tournament_date,
            winner_id
        FROM tournaments
        WHERE tournament_number = ?
        """,
        (tournament_number,),
    ).fetchone()

    if tournament is None:
        raise ValueError(f"WM {tournament_number:02d} was not found.")

    return tournament


def _detect_title_milestone(
    connection: sqlite3.Connection,
    tournament: sqlite3.Row,
) -> str | None:
    """Returns the winner's title milestone."""

    winner = connection.execute(
        """
        SELECT display_name
        FROM players
        WHERE player_id = ?
        """,
        (tournament["winner_id"],),
    ).fetchone()

    if winner is None:
        return None

    title_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM tournaments
            WHERE winner_id = ?
              AND tournament_number <= ?
            """,
            (
                tournament["winner_id"],
                tournament["tournament_number"],
            ),
        ).fetchone()[0]
    )

    player = str(winner["display_name"])

    if title_count == 1:
        return f"{player} won a first World Championship title."

    return (
        f"{player} reached {title_count} World Championship titles."
    )


def _detect_appearance_milestones(
    connection: sqlite3.Connection,
    tournament: sqlite3.Row,
) -> list[str]:
    """Detects fifth and tenth tournament appearances."""

    rows = connection.execute(
        """
        SELECT
            p.display_name AS player,
            COUNT(previous_tp.tournament_id) AS appearances
        FROM tournament_participants AS current_tp
        JOIN players AS p
          ON p.player_id = current_tp.player_id
        JOIN tournaments AS current_tournament
          ON current_tournament.tournament_id = current_tp.tournament_id
        JOIN tournament_participants AS previous_tp
          ON previous_tp.player_id = current_tp.player_id
        JOIN tournaments AS previous_tournament
          ON previous_tournament.tournament_id = previous_tp.tournament_id
        WHERE current_tp.tournament_id = ?
          AND previous_tournament.tournament_number
              <= current_tournament.tournament_number
        GROUP BY
            current_tp.player_id,
            p.display_name
        ORDER BY p.display_name COLLATE NOCASE
        """,
        (tournament["tournament_id"],),
    ).fetchall()

    milestones: list[str] = []

    for row in rows:
        appearances = int(row["appearances"])

        if appearances not in APPEARANCE_MILESTONES:
            continue

        ordinal = "fifth" if appearances == 5 else "tenth"

        milestones.append(
            f"{row['player']} made a {ordinal} tournament appearance."
        )

    return milestones


def _detect_win_milestones(
    connection: sqlite3.Connection,
    tournament: sqlite3.Row,
) -> list[str]:
    """Detects cumulative set-win milestones reached at this tournament."""

    rows = connection.execute(
        """
        SELECT
            p.player_id,
            p.display_name AS player,

            SUM(
                CASE
                    WHEN t.tournament_number <= ?
                     AND m.winner_id = p.player_id
                    THEN 1
                    ELSE 0
                END
            ) AS wins_after,

            SUM(
                CASE
                    WHEN t.tournament_number < ?
                     AND m.winner_id = p.player_id
                    THEN 1
                    ELSE 0
                END
            ) AS wins_before

        FROM tournament_participants AS tp
        JOIN players AS p
          ON p.player_id = tp.player_id
        LEFT JOIN matches AS m
          ON (
                m.player_1_id = p.player_id
                OR m.player_2_id = p.player_id
             )
        LEFT JOIN tournaments AS t
          ON t.tournament_id = m.tournament_id
        WHERE tp.tournament_id = ?
        GROUP BY
            p.player_id,
            p.display_name
        ORDER BY p.display_name COLLATE NOCASE
        """,
        (
            tournament["tournament_number"],
            tournament["tournament_number"],
            tournament["tournament_id"],
        ),
    ).fetchall()

    milestones: list[str] = []

    for row in rows:
        wins_before = int(row["wins_before"] or 0)
        wins_after = int(row["wins_after"] or 0)

        for threshold in sorted(WIN_MILESTONES):
            if wins_before < threshold <= wins_after:
                milestones.append(
                    f"{row['player']} reached {threshold} recorded set wins."
                )

    return milestones


def _detect_placement_milestones(
    connection: sqlite3.Connection,
    tournament: sqlite3.Row,
) -> list[str]:
    """Detects new personal best tournament placements."""

    rows = connection.execute(
        """
        SELECT
            p.display_name AS player,
            current_tp.placement AS current_placement,
            MIN(previous_tp.placement) AS previous_best
        FROM tournament_participants AS current_tp
        JOIN players AS p
          ON p.player_id = current_tp.player_id
        LEFT JOIN tournament_participants AS previous_tp
          ON previous_tp.player_id = current_tp.player_id
        LEFT JOIN tournaments AS previous_tournament
          ON previous_tournament.tournament_id
             = previous_tp.tournament_id
         AND previous_tournament.tournament_number < ?
        WHERE current_tp.tournament_id = ?
        GROUP BY
            current_tp.player_id,
            p.display_name,
            current_tp.placement
        ORDER BY p.display_name COLLATE NOCASE
        """,
        (
            tournament["tournament_number"],
            tournament["tournament_id"],
        ),
    ).fetchall()

    milestones: list[str] = []

    for row in rows:
        current_placement = row["current_placement"]
        previous_best = row["previous_best"]

        if current_placement is None:
            continue

        current_placement = int(current_placement)

        # A debut placement is not treated as a new personal record.
        if previous_best is None:
            continue

        if current_placement < int(previous_best):
            milestones.append(
                f"{row['player']} achieved a new career-best placement "
                f"of {current_placement}."
            )

    return milestones


def _detect_elo_milestones(
    connection: sqlite3.Connection,
    tournament: sqlite3.Row,
) -> list[str]:
    """Detects new personal peak Elo ratings reached at the tournament."""

    rows = connection.execute(
        """
        SELECT
            p.display_name AS player,
            MAX(
                CASE
                    WHEN current_tournament.tournament_number = ?
                    THEN rh.rating_after
                END
            ) AS tournament_peak,
            MAX(
                CASE
                    WHEN current_tournament.tournament_number < ?
                    THEN rh.rating_after
                END
            ) AS previous_peak
        FROM tournament_participants AS tp
        JOIN players AS p
          ON p.player_id = tp.player_id
        LEFT JOIN rating_history AS rh
          ON rh.player_id = tp.player_id
        LEFT JOIN tournaments AS current_tournament
          ON current_tournament.tournament_id = rh.tournament_id
        WHERE tp.tournament_id = ?
        GROUP BY
            tp.player_id,
            p.display_name
        ORDER BY p.display_name COLLATE NOCASE
        """,
        (
            tournament["tournament_number"],
            tournament["tournament_number"],
            tournament["tournament_id"],
        ),
    ).fetchall()

    milestones: list[str] = []

    for row in rows:
        tournament_peak = row["tournament_peak"]
        previous_peak = row["previous_peak"]

        if tournament_peak is None:
            continue

        tournament_peak = float(tournament_peak)

        # The player's first rating is not described as a new career high.
        if previous_peak is None:
            continue

        if tournament_peak > float(previous_peak):
            milestones.append(
                f"{row['player']} reached a new career-high Elo "
                f"of {tournament_peak:.1f}."
            )

    return milestones


def detect_tournament_milestones(
    db_path: str | Path,
    tournament_number: int,
) -> list[str]:
    """Returns notable milestones reached at one tournament."""

    path = Path(db_path)

    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row

    try:
        tournament = _get_tournament(
            connection,
            tournament_number,
        )

        milestones: list[str] = []

        title_milestone = _detect_title_milestone(
            connection,
            tournament,
        )
        if title_milestone:
            milestones.append(title_milestone)

        milestones.extend(
            _detect_appearance_milestones(
                connection,
                tournament,
            )
        )
        milestones.extend(
            _detect_win_milestones(
                connection,
                tournament,
            )
        )
        milestones.extend(
            _detect_placement_milestones(
                connection,
                tournament,
            )
        )
        milestones.extend(
            _detect_elo_milestones(
                connection,
                tournament,
            )
        )

        return milestones

    finally:
        connection.close()