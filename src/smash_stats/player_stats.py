"""Player summary statistics and tournament history."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from smash_stats.common import _percentage
from smash_stats.database import DEFAULT_DB_PATH, connect_db, resolve_player
from smash_stats.elo_history import get_player_elo_summary


def get_player_stats(
    player_reference: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    include_elo: bool = False,
    elo_k_factor: float = 32.0,
) -> dict[str, Any]:
    """
    Calculates a player’s overall statistics.

    `player_reference` may be either the internal player_id or the display name.
    """

    with connect_db(db_path) as connection:
        player = resolve_player(connection, player_reference)
        player_id = player["player_id"]

        participation = connection.execute(
            """
            SELECT
                COUNT(*) AS appearances,
                MIN(tp.placement) AS best_result,
                AVG(tp.placement) AS average_result,
                SUM(CASE WHEN tp.placement IS NOT NULL THEN 1 ELSE 0 END)
                    AS known_placements
            FROM tournament_participants AS tp
            WHERE tp.player_id = ?
            """,
            (player_id,),
        ).fetchone()

        title_stats = connection.execute(
            """
            SELECT COUNT(*) AS titles
            FROM tournaments
            WHERE winner_id = ?
            """
            ,
            (player_id,),
        ).fetchone()

        match_stats = connection.execute(
            """
            SELECT
                COUNT(*) AS matches,
                SUM(CASE WHEN winner_id = ? THEN 1 ELSE 0 END) AS wins,
                SUM(
                    CASE
                        WHEN winner_id IS NOT NULL
                         AND winner_id != ?
                        THEN 1
                        ELSE 0
                    END
                ) AS losses,
                SUM(CASE WHEN winner_id IS NULL THEN 1 ELSE 0 END)
                    AS undecided_matches,

                SUM(CASE WHEN stage = 'group' THEN 1 ELSE 0 END)
                    AS group_matches,
                SUM(
                    CASE
                        WHEN stage = 'group'
                         AND winner_id = ?
                        THEN 1
                        ELSE 0
                    END
                ) AS group_wins,
                SUM(
                    CASE
                        WHEN stage = 'group'
                         AND winner_id IS NOT NULL
                         AND winner_id != ?
                        THEN 1
                        ELSE 0
                    END
                ) AS group_losses,

                SUM(CASE WHEN stage = 'knockout' THEN 1 ELSE 0 END)
                    AS knockout_matches,
                SUM(
                    CASE
                        WHEN stage = 'knockout'
                         AND winner_id = ?
                        THEN 1
                        ELSE 0
                    END
                ) AS knockout_wins,
                SUM(
                    CASE
                        WHEN stage = 'knockout'
                         AND winner_id IS NOT NULL
                         AND winner_id != ?
                        THEN 1
                        ELSE 0
                    END
                ) AS knockout_losses
            FROM matches
            WHERE player_1_id = ?
               OR player_2_id = ?
            """,
            (
                player_id,
                player_id,
                player_id,
                player_id,
                player_id,
                player_id,
                player_id,
                player_id,
            ),
        ).fetchone()

        game_stats = connection.execute(
            """
            SELECT
                SUM(
                    CASE
                        WHEN player_1_id = ? THEN player_1_score
                        ELSE player_2_score
                    END
                ) AS games_won,
                SUM(
                    CASE
                        WHEN player_1_id = ? THEN player_2_score
                        ELSE player_1_score
                    END
                ) AS games_lost,
                COUNT(*) AS matches_with_known_score
            FROM matches
            WHERE (player_1_id = ? OR player_2_id = ?)
              AND score_known = 1
              AND player_1_score IS NOT NULL
              AND player_2_score IS NOT NULL
              AND walkover = 0
            """,
            (
                player_id,
                player_id,
                player_id,
                player_id,
            ),
        ).fetchone()

    appearances = participation["appearances"] or 0
    titles = title_stats["titles"] or 0
    matches = match_stats["matches"] or 0
    wins = match_stats["wins"] or 0
    losses = match_stats["losses"] or 0
    decided_matches = wins + losses

    group_matches = match_stats["group_matches"] or 0
    group_wins = match_stats["group_wins"] or 0
    group_losses = match_stats["group_losses"] or 0
    group_decided = group_wins + group_losses

    knockout_matches = match_stats["knockout_matches"] or 0
    knockout_wins = match_stats["knockout_wins"] or 0
    knockout_losses = match_stats["knockout_losses"] or 0
    knockout_decided = knockout_wins + knockout_losses

    average_result = participation["average_result"]

    stats = {
        "player_id": player_id,
        "player": player["display_name"],
        "core_player": bool(player["core_player"]),
        "active": bool(player["active"]),

        "appearances": appearances,
        "titles": titles,

        "known_placements": participation["known_placements"] or 0,
        "best_result": participation["best_result"],
        "average_result": (
            round(float(average_result), 2)
            if average_result is not None
            else None
        ),

        "matches": matches,
        "decided_matches": decided_matches,
        "wins": wins,
        "losses": losses,
        "undecided_matches": match_stats["undecided_matches"] or 0,
        "winrate": _percentage(wins, decided_matches),

        "games_won": game_stats["games_won"] or 0,
        "games_lost": game_stats["games_lost"] or 0,
        "matches_with_known_score": (
            game_stats["matches_with_known_score"] or 0
        ),
        "game_winrate": _percentage(
            game_stats["games_won"] or 0,
            (game_stats["games_won"] or 0)
            + (game_stats["games_lost"] or 0),
        ),

        "group_matches": group_matches,
        "group_wins": group_wins,
        "group_losses": group_losses,
        "group_winrate": _percentage(group_wins, group_decided),

        "knockout_matches": knockout_matches,
        "knockout_wins": knockout_wins,
        "knockout_losses": knockout_losses,
        "knockout_winrate": _percentage(
            knockout_wins,
            knockout_decided,
        ),
    }

    if include_elo:
        stats.update(
            get_player_elo_summary(
                player_id,
                db_path,
                k_factor=elo_k_factor,
            )
        )

    return stats


def get_all_player_stats(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """Calculates statistics for all players."""

    with connect_db(db_path) as connection:
        query = """
            SELECT player_id
            FROM players
        """

        if active_only:
            query += " WHERE active = 1"

        query += " ORDER BY display_name COLLATE NOCASE"

        player_ids = [
            row["player_id"]
            for row in connection.execute(query).fetchall()
        ]

    return [
        get_player_stats(player_id, db_path)
        for player_id in player_ids
    ]


def get_player_history(
    player_reference: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """
    Returns a player’s tournament history in chronological order.

    Titles are determined through tournaments.winner_id. Placements come from tournament_participants and may be None for incomplete historical tournaments.
    """

    with connect_db(db_path) as connection:
        player = resolve_player(connection, player_reference)
        player_id = player["player_id"]

        rows = connection.execute(
            """
            SELECT
                t.tournament_id,
                t.tournament_number,
                t.tournament_date,
                t.winner_id,
                winner.display_name AS winner_name,
                t.match_data_available,
                tp.placement,
                tp.seed,
                COUNT(m.match_id) AS matches,
                SUM(CASE WHEN m.winner_id = ? THEN 1 ELSE 0 END) AS wins,
                SUM(
                    CASE
                        WHEN m.winner_id IS NOT NULL
                         AND m.winner_id != ?
                        THEN 1
                        ELSE 0
                    END
                ) AS losses
            FROM tournament_participants AS tp
            JOIN tournaments AS t
              ON t.tournament_id = tp.tournament_id
            JOIN players AS winner
              ON winner.player_id = t.winner_id
            LEFT JOIN matches AS m
              ON m.tournament_id = t.tournament_id
             AND (m.player_1_id = ? OR m.player_2_id = ?)
            WHERE tp.player_id = ?
            GROUP BY
                t.tournament_id,
                t.tournament_number,
                t.tournament_date,
                t.winner_id,
                winner.display_name,
                t.match_data_available,
                tp.placement,
                tp.seed
            ORDER BY
                t.tournament_date,
                t.tournament_number
            """,
            (
                player_id,
                player_id,
                player_id,
                player_id,
                player_id,
            ),
        ).fetchall()

    return [
        {
            "tournament_id": row["tournament_id"],
            "tournament": f"WC {row['tournament_number']:02d}",
            "tournament_number": row["tournament_number"],
            "date": row["tournament_date"],
            "placement": row["placement"],
            "seed": row["seed"],
            "winner_id": row["winner_id"],
            "winner": row["winner_name"],
            "won_tournament": row["winner_id"] == player_id,
            "match_data_available": bool(row["match_data_available"]),
            "matches": row["matches"] or 0,
            "wins": row["wins"] or 0,
            "losses": row["losses"] or 0,
        }
        for row in rows
    ]
