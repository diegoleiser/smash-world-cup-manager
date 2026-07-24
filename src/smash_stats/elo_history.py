"""Database-backed Elo history and ranking calculations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from smash_stats.database import (
    DEFAULT_DB_PATH,
    connect_db,
    resolve_player,
)
from smash_stats.elo_rules import (
    ELO_K_FACTOR,
    ELO_START_RATING,
    calculate_elo_change,
    calculate_margin_multiplier,
)


def calculate_elo_history(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    start_rating: float = ELO_START_RATING,
    k_factor: float = ELO_K_FACTOR,
) -> list[dict[str, Any]]:
    """
    Calculates the complete Elo history chronologically from all matches.

    Only decided matches without walkovers are included.
    Players receive their starting Elo immediately before their first rated match.
    """

    if k_factor <= 0:
        raise ValueError("The K factor must be greater than zero.")

    with connect_db(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                m.match_id,
                m.tournament_id,
                t.tournament_number,
                t.tournament_date,
                m.round_label,
                m.stage,
                m.player_1_id,
                p1.display_name AS player_1_name,
                m.player_2_id,
                p2.display_name AS player_2_name,
                m.winner_id,
                m.player_1_score,
                m.player_2_score,
                m.score_known,
                m.completed_at,
                m.suggested_play_order
            FROM matches AS m
            JOIN tournaments AS t
              ON t.tournament_id = m.tournament_id
            JOIN players AS p1
              ON p1.player_id = m.player_1_id
            JOIN players AS p2
              ON p2.player_id = m.player_2_id
            WHERE m.winner_id IS NOT NULL
              AND COALESCE(m.walkover, 0) = 0
              AND m.player_1_id IS NOT NULL
              AND m.player_2_id IS NOT NULL
              AND m.player_1_id != m.player_2_id
            ORDER BY
                t.tournament_number,
                CASE WHEN m.completed_at IS NULL THEN 1 ELSE 0 END,
                m.completed_at,
                CASE WHEN m.suggested_play_order IS NULL THEN 1 ELSE 0 END,
                m.suggested_play_order,
                m.match_id
            """
        ).fetchall()

    ratings: dict[str, float] = {}
    history: list[dict[str, Any]] = []

    for sequence_number, row in enumerate(rows, start=1):
        player_1_id = str(row["player_1_id"])
        player_2_id = str(row["player_2_id"])
        winner_id = str(row["winner_id"])

        if winner_id not in {player_1_id, player_2_id}:
            continue

        loser_id = (
            player_2_id
            if winner_id == player_1_id
            else player_1_id
        )

        winner_name = (
            row["player_1_name"]
            if winner_id == player_1_id
            else row["player_2_name"]
        )
        loser_name = (
            row["player_2_name"]
            if winner_id == player_1_id
            else row["player_1_name"]
        )

        winner_rating_before = ratings.get(
            winner_id,
            start_rating,
        )
        loser_rating_before = ratings.get(
            loser_id,
            start_rating,
        )

        player_1_score_raw = row["player_1_score"]
        player_2_score_raw = row["player_2_score"]

        player_1_score = (
            int(player_1_score_raw)
            if player_1_score_raw is not None
            else None
        )
        player_2_score = (
            int(player_2_score_raw)
            if player_2_score_raw is not None
            else None
        )

        score_is_usable = (
            bool(row["score_known"])
            and player_1_score is not None
            and player_2_score is not None
        )

        winner_score: int | None = None
        loser_score: int | None = None

        if score_is_usable:
            if winner_id == player_1_id:
                winner_score = player_1_score
                loser_score = player_2_score
            else:
                winner_score = player_2_score
                loser_score = player_1_score

        margin_multiplier = calculate_margin_multiplier(
            winner_score,
            loser_score,
        )
        rating_change = calculate_elo_change(
            winner_rating_before,
            loser_rating_before,
            winner_score=winner_score,
            loser_score=loser_score,
            k_factor=k_factor,
        )

        winner_rating_after = winner_rating_before + rating_change
        loser_rating_after = loser_rating_before - rating_change

        ratings[winner_id] = winner_rating_after
        ratings[loser_id] = loser_rating_after

        history.append(
            {
                "sequence": sequence_number,
                "match_id": row["match_id"],
                "tournament_id": row["tournament_id"],
                "tournament_number": row["tournament_number"],
                "tournament_date": row["tournament_date"],
                "round_label": row["round_label"],
                "stage": row["stage"],
                "winner_id": winner_id,
                "winner": winner_name,
                "loser_id": loser_id,
                "loser": loser_name,
                "winner_score": winner_score,
                "loser_score": loser_score,
                "score_known": score_is_usable,
                "margin_multiplier": round(margin_multiplier, 2),
                "rating_change": round(rating_change, 4),
                "winner_rating_before": round(
                    winner_rating_before,
                    4,
                ),
                "winner_rating_after": round(
                    winner_rating_after,
                    4,
                ),
                "loser_rating_before": round(
                    loser_rating_before,
                    4,
                ),
                "loser_rating_after": round(
                    loser_rating_after,
                    4,
                ),
            }
        )

    return history


def get_elo_ranking(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    active_only: bool = True,
    start_rating: float = ELO_START_RATING,
    k_factor: float = ELO_K_FACTOR,
) -> list[dict[str, Any]]:
    """Returns the current Elo ranking for all players with rated matches."""

    history = calculate_elo_history(
        db_path,
        start_rating=start_rating,
        k_factor=k_factor,
    )

    ratings: dict[str, float] = {}
    match_counts: dict[str, int] = {}

    for event in history:
        winner_id = event["winner_id"]
        loser_id = event["loser_id"]

        ratings[winner_id] = event["winner_rating_after"]
        ratings[loser_id] = event["loser_rating_after"]

        match_counts[winner_id] = match_counts.get(winner_id, 0) + 1
        match_counts[loser_id] = match_counts.get(loser_id, 0) + 1

    if not ratings:
        return []

    placeholders = ", ".join("?" for _ in ratings)

    with connect_db(db_path) as connection:
        player_rows = connection.execute(
            f"""
            SELECT
                player_id,
                display_name,
                core_player,
                active
            FROM players
            WHERE player_id IN ({placeholders})
            """,
            tuple(ratings),
        ).fetchall()

    players_by_id = {
        str(row["player_id"]): row
        for row in player_rows
    }

    ranking_entries: list[dict[str, Any]] = []

    for player_id, rating in ratings.items():
        player = players_by_id[player_id]

        if active_only and not bool(player["active"]):
            continue

        ranking_entries.append(
            {
                "player_id": player_id,
                "player": player["display_name"],
                "active": bool(player["active"]),
                "core_player": bool(player["core_player"]),
                "elo": round(float(rating), 1),
                "elo_exact": round(float(rating), 4),
                "rated_matches": match_counts[player_id],
            }
        )

    ranking_entries.sort(
        key=lambda entry: (
            -entry["elo_exact"],
            -entry["rated_matches"],
            entry["player"].casefold(),
        )
    )

    return [
        {
            "rank": rank,
            **entry,
        }
        for rank, entry in enumerate(ranking_entries, start=1)
    ]


def get_player_elo_history(
    player_reference: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    start_rating: float = ELO_START_RATING,
    k_factor: float = ELO_K_FACTOR,
) -> list[dict[str, Any]]:
    """Returns every Elo change for a specific player."""

    with connect_db(db_path) as connection:
        player = resolve_player(connection, player_reference)
        player_id = str(player["player_id"])

    full_history = calculate_elo_history(
        db_path,
        start_rating=start_rating,
        k_factor=k_factor,
    )

    player_history: list[dict[str, Any]] = []

    for event in full_history:
        if event["winner_id"] == player_id:
            player_history.append(
                {
                    **event,
                    "result": "win",
                    "opponent_id": event["loser_id"],
                    "opponent": event["loser"],
                    "elo_before": event["winner_rating_before"],
                    "elo_after": event["winner_rating_after"],
                    "elo_change": event["rating_change"],
                }
            )
        elif event["loser_id"] == player_id:
            player_history.append(
                {
                    **event,
                    "result": "loss",
                    "opponent_id": event["winner_id"],
                    "opponent": event["winner"],
                    "elo_before": event["loser_rating_before"],
                    "elo_after": event["loser_rating_after"],
                    "elo_change": -event["rating_change"],
                }
            )

    return player_history
def get_player_elo_summary(
    player_reference: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    start_rating: float = ELO_START_RATING,
    k_factor: float = ELO_K_FACTOR,
) -> dict[str, Any]:
    """Returns a player’s current Elo and all-time peak Elo."""

    history = get_player_elo_history(
        player_reference,
        db_path,
        start_rating=start_rating,
        k_factor=k_factor,
    )

    if not history:
        return {
            "current_elo": None,
            "peak_elo": None,
            "peak_elo_tournament": None,
            "peak_elo_match_id": None,
            "rated_matches": 0,
        }

    peak_event = max(
        history,
        key=lambda event: float(event["elo_after"]),
    )

    return {
        "current_elo": round(float(history[-1]["elo_after"]), 1),
        "peak_elo": round(float(peak_event["elo_after"]), 1),
        "peak_elo_tournament": peak_event["tournament_number"],
        "peak_elo_match_id": peak_event["match_id"],
        "rated_matches": len(history),
    }
def get_elo_ranking_timeline(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    active_only: bool = True,
    start_rating: float = ELO_START_RATING,
    k_factor: float = ELO_K_FACTOR,
) -> list[dict[str, Any]]:
    """
    Returns a complete Elo snapshot after each tournament.

    Ranks are calculated among the players visible in the selected view. With `active_only=True`, inactive players are removed first and the remaining ranks are reassigned consecutively from 1.
    """

    history = calculate_elo_history(
        db_path,
        start_rating=start_rating,
        k_factor=k_factor,
    )

    if not history:
        return []

    with connect_db(db_path) as connection:
        player_rows = connection.execute(
            """
            SELECT
                player_id,
                display_name,
                core_player,
                active
            FROM players
            """
        ).fetchall()

    players_by_id = {
        str(row["player_id"]): row
        for row in player_rows
    }

    events_by_tournament: dict[int, list[dict[str, Any]]] = {}
    tournament_dates: dict[int, Any] = {}

    for event in history:
        tournament_number = int(event["tournament_number"])
        events_by_tournament.setdefault(tournament_number, []).append(event)
        tournament_dates[tournament_number] = event["tournament_date"]

    ratings: dict[str, float] = {}
    rated_matches: dict[str, int] = {}
    timeline: list[dict[str, Any]] = []

    for tournament_number in sorted(events_by_tournament):
        for event in events_by_tournament[tournament_number]:
            winner_id = str(event["winner_id"])
            loser_id = str(event["loser_id"])

            ratings[winner_id] = float(event["winner_rating_after"])
            ratings[loser_id] = float(event["loser_rating_after"])

            rated_matches[winner_id] = rated_matches.get(winner_id, 0) + 1
            rated_matches[loser_id] = rated_matches.get(loser_id, 0) + 1

        ranked_player_ids = sorted(
            ratings,
            key=lambda player_id: (
                -ratings[player_id],
                -rated_matches[player_id],
                str(players_by_id[player_id]["display_name"]).casefold(),
            ),
        )

        visible_player_ids = [
            player_id
            for player_id in ranked_player_ids
            if not active_only or bool(players_by_id[player_id]["active"])
        ]

        ranks = {
            player_id: rank
            for rank, player_id in enumerate(visible_player_ids, start=1)
        }

        for player_id in visible_player_ids:
            player = players_by_id[player_id]

            timeline.append(
                {
                    "tournament_number": tournament_number,
                    "tournament": f"WM {tournament_number:02d}",
                    "tournament_date": tournament_dates[tournament_number],
                    "player_id": player_id,
                    "player": player["display_name"],
                    "active": bool(player["active"]),
                    "core_player": bool(player["core_player"]),
                    "elo": round(ratings[player_id], 1),
                    "elo_exact": round(ratings[player_id], 4),
                    "rank": ranks[player_id],
                    "rated_matches": rated_matches[player_id],
                    "played_in_tournament": any(
                        player_id in {
                            str(event["winner_id"]),
                            str(event["loser_id"]),
                        }
                        for event in events_by_tournament[tournament_number]
                    ),
                }
            )

    return timeline


def get_player_elo_timeline(
    player_reference: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    active_only: bool = False,
    start_rating: float = ELO_START_RATING,
    k_factor: float = ELO_K_FACTOR,
) -> list[dict[str, Any]]:
    """
    Returns a player’s Elo and rank after every tournament since their debut.

    Tournaments without participation are also included: Elo remains unchanged, while rank may change due to other players’ results.
    """

    with connect_db(db_path) as connection:
        player = resolve_player(connection, player_reference)
        player_id = str(player["player_id"])

    timeline = get_elo_ranking_timeline(
        db_path,
        active_only=active_only,
        start_rating=start_rating,
        k_factor=k_factor,
    )

    return [
        entry
        for entry in timeline
        if entry["player_id"] == player_id
    ]

