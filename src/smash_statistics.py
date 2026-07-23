#!/usr/bin/env python3
"""Dynamically calculated statistics for the Smash World Championship archive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from smash_stats.database import (
    DEFAULT_DB_PATH,
    PlayerNotFoundError,
    connect_db,
    resolve_player,
)
from smash_stats.elo_rules import (
    ELO_K_FACTOR,
    ELO_MAX_MARGIN_MULTIPLIER,
    ELO_START_RATING,
    calculate_elo_change,
    calculate_expected_score,
    calculate_margin_multiplier,
)
from smash_stats.elo_history import (
    calculate_elo_history,
    get_elo_ranking,
    get_player_elo_history,
    get_player_elo_summary,
)
from smash_stats.common import _percentage
from smash_stats.player_stats import (
    get_all_player_stats,
    get_player_history,
    get_player_stats,
)



def print_player_history(
    player_reference: str,
    history: list[dict[str, Any]],
) -> None:
    """Gibt die Tournament History eines Playerss als Tabelle aus."""

    print(f"\nTournament History for {player_reference}")
    print("=" * 82)

    if not history:
        print("No tournament appearances found.")
        return

    header = (
        f"{'Tournament':<9} {'Date':<12} {'Placement':<7} {'Seed':<6} "
        f"{'Record':<9} {'Winner':<12} {'Titles':<5}"
    )
    print(header)
    print("-" * len(header))

    for entry in history:
        placement = (
            str(entry["placement"])
            if entry["placement"] is not None
            else "–"
        )
        seed = str(entry["seed"]) if entry["seed"] is not None else "–"
        record = f"{entry['wins']}-{entry['losses']}"

        print(
            f"{entry['tournament']:<9} "
            f"{entry['date']:<12} "
            f"{placement:<7} "
            f"{seed:<6} "
            f"{record:<9} "
            f"{entry['winner']:<12} "
            f"{_yes_no(entry['won_tournament']):<5}"
        )



def get_head_to_head(
    player_a_reference: str,
    player_b_reference: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """
    Calculates the head-to-head record between two players.

    Unknown scores count toward the match record when a winner is known, but not toward the game record.
    """

    with connect_db(db_path) as connection:
        player_a = resolve_player(connection, player_a_reference)
        player_b = resolve_player(connection, player_b_reference)

        player_a_id = player_a["player_id"]
        player_b_id = player_b["player_id"]

        if player_a_id == player_b_id:
            raise ValueError("A head-to-head comparison requires two different players.")

        matches = connection.execute(
            """
            SELECT
                m.match_id,
                m.tournament_id,
                t.tournament_number,
                t.tournament_date,
                m.stage,
                m.bracket_side,
                m.round_label,
                m.player_1_id,
                m.player_2_id,
                m.winner_id,
                m.player_1_score,
                m.player_2_score,
                m.score_known,
                m.walkover,
                m.completed_at,
                m.suggested_play_order
            FROM matches AS m
            JOIN tournaments AS t
              ON t.tournament_id = m.tournament_id
            WHERE
                (m.player_1_id = ? AND m.player_2_id = ?)
                OR
                (m.player_1_id = ? AND m.player_2_id = ?)
            ORDER BY
                t.tournament_date,
                t.tournament_number,
                CASE WHEN m.completed_at IS NULL THEN 1 ELSE 0 END,
                m.completed_at,
                CASE WHEN m.suggested_play_order IS NULL THEN 1 ELSE 0 END,
                m.suggested_play_order,
                m.match_id
            """,
            (
                player_a_id,
                player_b_id,
                player_b_id,
                player_a_id,
            ),
        ).fetchall()

    player_a_wins = 0
    player_b_wins = 0
    undecided_matches = 0
    player_a_games = 0
    player_b_games = 0
    matches_with_known_score = 0
    match_history: list[dict[str, Any]] = []

    for row in matches:
        if row["winner_id"] == player_a_id:
            player_a_wins += 1
        elif row["winner_id"] == player_b_id:
            player_b_wins += 1
        else:
            undecided_matches += 1

        score_known = bool(row["score_known"])
        score_a: int | None = None
        score_b: int | None = None

        player_1_score = row["player_1_score"]
        player_2_score = row["player_2_score"]

        if (
            score_known
            and player_1_score is not None
            and player_2_score is not None
            and not row["walkover"]
        ):
            if row["player_1_id"] == player_a_id:
                score_a = int(player_1_score)
                score_b = int(player_2_score)
            else:
                score_a = int(player_2_score)
                score_b = int(player_1_score)

            player_a_games += score_a
            player_b_games += score_b
            matches_with_known_score += 1

        winner_name = None
        if row["winner_id"] == player_a_id:
            winner_name = player_a["display_name"]
        elif row["winner_id"] == player_b_id:
            winner_name = player_b["display_name"]

        score_text = (
            f"{score_a}-{score_b}"
            if score_a is not None and score_b is not None
            else None
        )

        match_history.append(
            {
                "match_id": row["match_id"],
                "tournament_id": row["tournament_id"],
                "tournament": f"WM {row['tournament_number']:02d}",
                "tournament_number": row["tournament_number"],
                "date": row["tournament_date"],
                "stage": row["stage"],
                "bracket_side": row["bracket_side"],
                "round_label": row["round_label"],
                "winner": winner_name,
                "winner_id": row["winner_id"],
                "score": score_text,
                "score_known": score_text is not None,
                "walkover": bool(row["walkover"]),
            }
        )

    decided_matches = player_a_wins + player_b_wins
    games_total = player_a_games + player_b_games
    last_match = match_history[-1] if match_history else None

    return {
        "player_a": {
            "player_id": player_a_id,
            "player": player_a["display_name"],
            "wins": player_a_wins,
            "winrate": _percentage(player_a_wins, decided_matches),
            "games_won": player_a_games,
            "game_winrate": _percentage(player_a_games, games_total),
        },
        "player_b": {
            "player_id": player_b_id,
            "player": player_b["display_name"],
            "wins": player_b_wins,
            "winrate": _percentage(player_b_wins, decided_matches),
            "games_won": player_b_games,
            "game_winrate": _percentage(player_b_games, games_total),
        },
        "matches": len(matches),
        "decided_matches": decided_matches,
        "undecided_matches": undecided_matches,
        "matches_with_known_score": matches_with_known_score,
        "last_match": last_match,
        "history": match_history,
    }



def get_all_head_to_heads(
    player_reference: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """
    Calculates a player’s head-to-head record against all previous opponents.

    Only opponents with at least one match in the database are included.
    """

    with connect_db(db_path) as connection:
        player = resolve_player(connection, player_reference)
        player_id = player["player_id"]

        opponent_rows = connection.execute(
            """
            SELECT DISTINCT
                CASE
                    WHEN player_1_id = ? THEN player_2_id
                    ELSE player_1_id
                END AS opponent_id
            FROM matches
            WHERE player_1_id = ?
               OR player_2_id = ?
            """,
            (
                player_id,
                player_id,
                player_id,
            ),
        ).fetchall()

    head_to_heads: list[dict[str, Any]] = []

    for row in opponent_rows:
        opponent_id = row["opponent_id"]
        head_to_head = get_head_to_head(
            player_id,
            opponent_id,
            db_path,
        )

        player_a = head_to_head["player_a"]
        player_b = head_to_head["player_b"]

        head_to_heads.append(
            {
                "opponent_id": player_b["player_id"],
                "opponent": player_b["player"],
                "matches": head_to_head["matches"],
                "wins": player_a["wins"],
                "losses": player_b["wins"],
                "undecided_matches": head_to_head["undecided_matches"],
                "winrate": player_a["winrate"],
                "games_won": player_a["games_won"],
                "games_lost": player_b["games_won"],
                "game_winrate": player_a["game_winrate"],
                "matches_with_known_score": (
                    head_to_head["matches_with_known_score"]
                ),
                "last_match": head_to_head["last_match"],
            }
        )

    return sorted(
        head_to_heads,
        key=lambda entry: (
            -entry["matches"],
            -entry["wins"],
            entry["opponent"].casefold(),
        ),
    )


def print_all_head_to_heads(
    player_reference: str,
    head_to_heads: list[dict[str, Any]],
) -> None:
    """Gibt alle direkten Recorden eines Playerss als Tabelle aus."""

    print(f"\nHead-to-Heads for {player_reference}")
    print("=" * 92)

    if not head_to_heads:
        print("No head-to-head matches found.")
        return

    header = (
        f"{'Opponent':<15} {'Matches':>7} {'Record':>9} "
        f"{'Win Rate':>10} {'Games':>10} {'Game-WR':>10}"
    )
    print(header)
    print("-" * len(header))

    for entry in head_to_heads:
        match_record = f"{entry['wins']}-{entry['losses']}"
        game_record = f"{entry['games_won']}-{entry['games_lost']}"

        print(
            f"{entry['opponent']:<15} "
            f"{entry['matches']:>7} "
            f"{match_record:>9} "
            f"{_format_percent(entry['winrate']):>10} "
            f"{game_record:>10} "
            f"{_format_percent(entry['game_winrate']):>10}"
        )


def print_head_to_head(stats: dict[str, Any]) -> None:
    """Gibt eine direkte Playersbilanz im Terminal aus."""

    player_a = stats["player_a"]
    player_b = stats["player_b"]

    print(f"\nHead-to-Head: {player_a['player']} vs. {player_b['player']}")
    print("=" * 64)

    print("\nMatchbilanz")
    print("-" * 64)
    print(
        f"{player_a['player']}: {player_a['wins']} Wins "
        f"({_format_percent(player_a['winrate'])})"
    )
    print(
        f"{player_b['player']}: {player_b['wins']} Wins "
        f"({_format_percent(player_b['winrate'])})"
    )
    print(f"Matches insgesamt:        {stats['matches']}")
    print(f"Unentschieden/unknown:  {stats['undecided_matches']}")

    print("\nGamebilanz")
    print("-" * 64)
    print(
        f"{player_a['player']}: {player_a['games_won']} Games "
        f"({_format_percent(player_a['game_winrate'])})"
    )
    print(
        f"{player_b['player']}: {player_b['games_won']} Games "
        f"({_format_percent(player_b['game_winrate'])})"
    )
    print(f"Matches with scores:        {stats['matches_with_known_score']}")

    print("\nLetzte Begegnung")
    print("-" * 64)

    last_match = stats["last_match"]

    if last_match is None:
        print("No head-to-head matches found.")
        return

    score = last_match["score"] or "Unknown score"
    winner = last_match["winner"] or "Unknown winner"
    phase = last_match["stage"] or "Unknown stage"

    print(
        f"{last_match['tournament']} am {last_match['date']}: "
        f"{winner} gewann ({score}, {phase})"
    )



def get_ranking(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    sort_by: str = "overall",
    active_only: bool = True,
    minimum_matches: int = 0,
) -> list[dict[str, Any]]:
    """
    Erstellt ein Playersranking aus den dynamisch berechneten Statistiken.

    Supported sorting modes:
    - overall: Titles, durchschnittliche Placementierung, Win Rate, Wins
    - titles: Titles, durchschnittliche Placementierung, Wins
    - wins: Wins, Win Rate, Titles
    - winrate: Win Rate, Wins, Titles
    - games: gewonnene Games, Game-Win Rate, Wins
    - appearances: Appearances, Titles, Wins
    """

    valid_sort_modes = {
        "overall",
        "titles",
        "wins",
        "winrate",
        "games",
        "appearances",
    }

    if sort_by not in valid_sort_modes:
        valid = ", ".join(sorted(valid_sort_modes))
        raise ValueError(
            f"Unknowne Ranking-Sortierung: {sort_by}. "
            f"Allowed values: {valid}"
        )

    if minimum_matches < 0:
        raise ValueError("minimum_matches darf nicht negativ sein.")

    stats = get_all_player_stats(
        db_path,
        active_only=active_only,
    )

    filtered_stats = [
        entry
        for entry in stats
        if entry["matches"] >= minimum_matches
    ]

    def placement_sort_value(entry: dict[str, Any]) -> float:
        average_result = entry["average_result"]
        return (
            float(average_result)
            if average_result is not None
            else float("inf")
        )

    def percent_sort_value(value: float | None) -> float:
        return value if value is not None else -1.0

    def overall_key(entry: dict[str, Any]) -> tuple[Any, ...]:
        return (
            -entry["titles"],
            placement_sort_value(entry),
            -percent_sort_value(entry["winrate"]),
            -entry["wins"],
            entry["player"].casefold(),
        )

    def titles_key(entry: dict[str, Any]) -> tuple[Any, ...]:
        return (
            -entry["titles"],
            placement_sort_value(entry),
            -entry["wins"],
            -percent_sort_value(entry["winrate"]),
            entry["player"].casefold(),
        )

    def wins_key(entry: dict[str, Any]) -> tuple[Any, ...]:
        return (
            -entry["wins"],
            -percent_sort_value(entry["winrate"]),
            -entry["titles"],
            placement_sort_value(entry),
            entry["player"].casefold(),
        )

    def winrate_key(entry: dict[str, Any]) -> tuple[Any, ...]:
        return (
            -percent_sort_value(entry["winrate"]),
            -entry["wins"],
            -entry["titles"],
            placement_sort_value(entry),
            entry["player"].casefold(),
        )

    def games_key(entry: dict[str, Any]) -> tuple[Any, ...]:
        return (
            -entry["games_won"],
            -percent_sort_value(entry["game_winrate"]),
            -entry["wins"],
            entry["player"].casefold(),
        )

    def appearances_key(entry: dict[str, Any]) -> tuple[Any, ...]:
        return (
            -entry["appearances"],
            -entry["titles"],
            -entry["wins"],
            entry["player"].casefold(),
        )

    sort_functions = {
        "overall": overall_key,
        "titles": titles_key,
        "wins": wins_key,
        "winrate": winrate_key,
        "games": games_key,
        "appearances": appearances_key,
    }

    ranked_stats = sorted(
        filtered_stats,
        key=sort_functions[sort_by],
    )

    return [
        {
            "rank": index,
            "player_id": entry["player_id"],
            "player": entry["player"],
            "active": entry["active"],
            "core_player": entry["core_player"],
            "titles": entry["titles"],
            "appearances": entry["appearances"],
            "best_result": entry["best_result"],
            "average_result": entry["average_result"],
            "matches": entry["matches"],
            "wins": entry["wins"],
            "losses": entry["losses"],
            "winrate": entry["winrate"],
            "games_won": entry["games_won"],
            "games_lost": entry["games_lost"],
            "game_winrate": entry["game_winrate"],
        }
        for index, entry in enumerate(ranked_stats, start=1)
    ]


def print_ranking(
    ranking: list[dict[str, Any]],
    *,
    sort_by: str,
) -> None:
    """Gibt ein Playersranking als Tabelle im Terminal aus."""

    print(f"\nSmash-WM-Ranking ({sort_by})")
    print("=" * 102)

    if not ranking:
        print("No players meet the selected criteria.")
        return

    header = (
        f"{'Rank':>4}  {'Players':<14} {'Titles':>6} {'TN':>4} "
        f"{'Ø Placement':>8} {'Record':>10} {'Win Rate':>9} "
        f"{'Games':>11} {'Game-WR':>9}"
    )
    print(header)
    print("-" * len(header))

    for entry in ranking:
        placement = _format_number(entry["average_result"])
        match_record = f"{entry['wins']}-{entry['losses']}"
        game_record = f"{entry['games_won']}-{entry['games_lost']}"

        print(
            f"{entry['rank']:>4}  "
            f"{entry['player']:<14} "
            f"{entry['titles']:>6} "
            f"{entry['appearances']:>4} "
            f"{placement:>8} "
            f"{match_record:>10} "
            f"{_format_percent(entry['winrate']):>9} "
            f"{game_record:>11} "
            f"{_format_percent(entry['game_winrate']):>9}"
        )








def get_smash_records(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    active_only: bool = False,
    start_rating: float = ELO_START_RATING,
    k_factor: float = ELO_K_FACTOR,
) -> dict[str, Any]:
    """
    Calculates key all-time records for the Smash World Championship.

    By default, historical records include inactive players. With `active_only=True`, only currently active players are included.
    """

    with connect_db(db_path) as connection:
        player_rows = connection.execute(
            """
            SELECT
                player_id,
                display_name,
                active,
                core_player
            FROM players
            """
        ).fetchall()

        tournament_rows = connection.execute(
            """
            SELECT
                tournament_id,
                tournament_number,
                tournament_date,
                winner_id
            FROM tournaments
            ORDER BY tournament_number
            """
        ).fetchall()

        match_rows = connection.execute(
            """
            SELECT
                m.match_id,
                m.tournament_id,
                m.player_1_id,
                m.player_2_id,
                m.winner_id,
                m.player_1_score,
                m.player_2_score,
                m.score_known,
                m.walkover,
                m.completed_at,
                m.suggested_play_order,
                t.tournament_number,
                t.tournament_date
            FROM matches AS m
            JOIN tournaments AS t
              ON t.tournament_id = m.tournament_id
            WHERE
                m.winner_id IS NOT NULL
                AND COALESCE(m.walkover, 0) = 0
            ORDER BY
                t.tournament_number,
                COALESCE(m.completed_at, ''),
                COALESCE(m.suggested_play_order, 0),
                m.match_id
            """
        ).fetchall()

    players = {
        str(row["player_id"]): {
            "player_id": str(row["player_id"]),
            "player": row["display_name"],
            "active": bool(row["active"]),
            "core_player": bool(row["core_player"]),
        }
        for row in player_rows
    }

    eligible_ids = {
        player_id
        for player_id, player in players.items()
        if not active_only or player["active"]
    }

    stats: dict[str, dict[str, Any]] = {
        player_id: {
            **players[player_id],
            "matches": 0,
            "wins": 0,
            "losses": 0,
            "titles": 0,
            "tournament_participations": set(),
            "longest_win_streak": 0,
            "longest_loss_streak": 0,
            "current_win_streak": 0,
            "current_loss_streak": 0,
        }
        for player_id in eligible_ids
    }

    for tournament in tournament_rows:
        winner_id = tournament["winner_id"]
        if winner_id is not None and str(winner_id) in stats:
            stats[str(winner_id)]["titles"] += 1

    ordered_matches = []
    for row in match_rows:
        player_1_id = str(row["player_1_id"]) if row["player_1_id"] is not None else None
        player_2_id = str(row["player_2_id"]) if row["player_2_id"] is not None else None
        winner_id = str(row["winner_id"])

        if player_1_id is None or player_2_id is None:
            continue

        loser_id = player_2_id if winner_id == player_1_id else player_1_id

        ordered_matches.append(
            {
                "match_id": row["match_id"],
                "tournament_number": row["tournament_number"],
                "tournament_date": row["tournament_date"],
                "winner_id": winner_id,
                "loser_id": loser_id,
            }
        )

        if winner_id in stats:
            entry = stats[winner_id]
            entry["matches"] += 1
            entry["wins"] += 1
            entry["tournament_participations"].add(row["tournament_number"])
            entry["current_win_streak"] += 1
            entry["current_loss_streak"] = 0
            entry["longest_win_streak"] = max(
                entry["longest_win_streak"],
                entry["current_win_streak"],
            )

        if loser_id in stats:
            entry = stats[loser_id]
            entry["matches"] += 1
            entry["losses"] += 1
            entry["tournament_participations"].add(row["tournament_number"])
            entry["current_loss_streak"] += 1
            entry["current_win_streak"] = 0
            entry["longest_loss_streak"] = max(
                entry["longest_loss_streak"],
                entry["current_loss_streak"],
            )

    for entry in stats.values():
        entry["participations"] = len(entry["tournament_participations"])
        del entry["tournament_participations"]
        entry["win_rate"] = (
            round(entry["wins"] / entry["matches"] * 100, 1)
            if entry["matches"]
            else 0.0
        )

    elo_history = calculate_elo_history(
        db_path,
        start_rating=start_rating,
        k_factor=k_factor,
    )

    peak_elo_record = None
    biggest_match_gain = None

    for event in elo_history:
        for player_id_key, player_key, before_key, after_key in (
            (
                str(event["winner_id"]),
                "winner",
                "winner_rating_before",
                "winner_rating_after",
            ),
            (
                str(event["loser_id"]),
                "loser",
                "loser_rating_before",
                "loser_rating_after",
            ),
        ):
            if player_id_key not in eligible_ids:
                continue

            after = float(event[after_key])
            before = float(event[before_key])
            change = after - before

            peak_candidate = {
                "player_id": player_id_key,
                "player": event[player_key],
                "elo": round(after, 1),
                "tournament_number": int(event["tournament_number"]),
                "tournament": f"WM {int(event['tournament_number']):02d}",
                "tournament_date": event["tournament_date"],
                "match_id": event["match_id"],
            }

            if (
                peak_elo_record is None
                or peak_candidate["elo"] > peak_elo_record["elo"]
            ):
                peak_elo_record = peak_candidate

            gain_candidate = {
                "player_id": player_id_key,
                "player": event[player_key],
                "change": round(change, 1),
                "before": round(before, 1),
                "after": round(after, 1),
                "tournament_number": int(event["tournament_number"]),
                "tournament": f"WM {int(event['tournament_number']):02d}",
                "tournament_date": event["tournament_date"],
                "match_id": event["match_id"],
                "opponent": (
                    event["loser"]
                    if player_key == "winner"
                    else event["winner"]
                ),
            }

            if (
                biggest_match_gain is None
                or gain_candidate["change"] > biggest_match_gain["change"]
            ):
                biggest_match_gain = gain_candidate

    timeline = get_elo_ranking_timeline(
        db_path,
        active_only=active_only,
        start_rating=start_rating,
        k_factor=k_factor,
    )

    rank_one_counts: dict[str, int] = {}
    top_three_counts: dict[str, int] = {}
    biggest_lead = None

    grouped_timeline: dict[int, list[dict[str, Any]]] = {}
    for entry in timeline:
        grouped_timeline.setdefault(
            entry["tournament_number"],
            [],
        ).append(entry)

        if entry["rank"] == 1:
            rank_one_counts[entry["player_id"]] = (
                rank_one_counts.get(entry["player_id"], 0) + 1
            )

        if entry["rank"] <= 3:
            top_three_counts[entry["player_id"]] = (
                top_three_counts.get(entry["player_id"], 0) + 1
            )

    for tournament_number, entries in grouped_timeline.items():
        sorted_entries = sorted(entries, key=lambda item: item["rank"])

        if len(sorted_entries) < 2:
            continue

        leader = sorted_entries[0]
        runner_up = sorted_entries[1]
        lead = round(float(leader["elo"]) - float(runner_up["elo"]), 1)

        candidate = {
            "player_id": leader["player_id"],
            "player": leader["player"],
            "lead": lead,
            "leader_elo": leader["elo"],
            "runner_up": runner_up["player"],
            "runner_up_elo": runner_up["elo"],
            "tournament_number": tournament_number,
            "tournament": leader["tournament"],
            "tournament_date": leader["tournament_date"],
        }

        if biggest_lead is None or lead > biggest_lead["lead"]:
            biggest_lead = candidate

    def best_stat(
        key: str,
        *,
        minimum_matches: int = 0,
    ) -> dict[str, Any] | None:
        candidates = [
            entry
            for entry in stats.values()
            if entry["matches"] >= minimum_matches
        ]
        if not candidates:
            return None

        best = max(
            candidates,
            key=lambda entry: (
                entry[key],
                entry["wins"],
                -entry["losses"],
                entry["player"].casefold(),
            ),
        )
        return {
            "player_id": best["player_id"],
            "player": best["player"],
            "value": best[key],
            "matches": best["matches"],
            "wins": best["wins"],
            "losses": best["losses"],
        }

    def best_count(
        counts: dict[str, int],
    ) -> dict[str, Any] | None:
        if not counts:
            return None

        player_id, value = max(
            counts.items(),
            key=lambda item: (
                item[1],
                stats.get(item[0], {}).get("wins", 0),
                players[item[0]]["player"].casefold(),
            ),
        )
        return {
            "player_id": player_id,
            "player": players[player_id]["player"],
            "value": value,
        }

    return {
        "highest_elo": peak_elo_record,
        "most_titles": best_stat("titles"),
        "most_wins": best_stat("wins"),
        "most_matches": best_stat("matches"),
        "most_participations": best_stat("participations"),
        "highest_win_rate": best_stat("win_rate", minimum_matches=5),
        "longest_win_streak": best_stat("longest_win_streak"),
        "longest_loss_streak": best_stat("longest_loss_streak"),
        "most_rank_one_finishes": best_count(rank_one_counts),
        "most_top_three_finishes": best_count(top_three_counts),
        "biggest_elo_lead": biggest_lead,
        "biggest_single_match_elo_gain": biggest_match_gain,
        "players": sorted(
            stats.values(),
            key=lambda entry: entry["player"].casefold(),
        ),
    }


def print_smash_records(records: dict[str, Any]) -> None:
    """Gibt die Hall-of-Fame-Rekorde formatiert aus."""

    print("\nSmash World Championship – Hall of Fame")
    print("=" * 72)

    def print_simple(
        label: str,
        record: dict[str, Any] | None,
        *,
        suffix: str = "",
        decimals: int | None = None,
    ) -> None:
        if record is None:
            print(f"{label:<34} no data")
            return

        value = record["value"]
        if decimals is not None:
            value_text = f"{float(value):.{decimals}f}{suffix}"
        else:
            value_text = f"{value}{suffix}"

        print(f"{label:<34} {record['player']:<18} {value_text}")

    highest_elo = records["highest_elo"]
    if highest_elo:
        print(
            f"{'Highest Elo of all time':<34} "
            f"{highest_elo['player']:<18} "
            f"{highest_elo['elo']:.1f} "
            f"({highest_elo['tournament']})"
        )

    print_simple("Meiste Titles", records["most_titles"])
    print_simple("Meiste Match Wins", records["most_wins"])
    print_simple("Meiste Matches", records["most_matches"])
    print_simple("Meiste Appearances", records["most_participations"])
    print_simple(
        "Highest Win Rate (min. 5 matches)",
        records["highest_win_rate"],
        suffix="%",
        decimals=1,
    )
    print_simple(
        "Longest Win Streak",
        records["longest_win_streak"],
        suffix=" Wins",
    )
    print_simple(
        "Longest Losing Streak",
        records["longest_loss_streak"],
        suffix=" Niederlagen",
    )
    print_simple(
        "Meiste Tournaments auf Rank 1",
        records["most_rank_one_finishes"],
    )
    print_simple(
        "Meiste Top-3-Placements",
        records["most_top_three_finishes"],
    )

    lead = records["biggest_elo_lead"]
    if lead:
        print(
            f"{'Largest Elo Lead':<34} "
            f"{lead['player']:<18} "
            f"{lead['lead']:.1f} "
            f"ahead of {lead['runner_up']} ({lead['tournament']})"
        )

    gain = records["biggest_single_match_elo_gain"]
    if gain:
        print(
            f"{'Biggest Elo Gain in einem Match':<34} "
            f"{gain['player']:<18} "
            f"{gain['change']:+.1f} "
            f"against {gain['opponent']} ({gain['tournament']})"
        )


def get_elo_tournament_changes(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    active_only: bool = True,
    start_rating: float = ELO_START_RATING,
    k_factor: float = ELO_K_FACTOR,
) -> list[dict[str, Any]]:
    """
    Calculates the largest Elo and ranking changes per tournament.

    Each snapshot after the current tournament is compared with the snapshot after the previous tournament. Players appearing for the first time have no ranking change because no previous rank exists.
    """

    timeline = get_elo_ranking_timeline(
        db_path,
        active_only=active_only,
        start_rating=start_rating,
        k_factor=k_factor,
    )

    if not timeline:
        return []

    grouped: dict[int, list[dict[str, Any]]] = {}
    for entry in timeline:
        grouped.setdefault(entry["tournament_number"], []).append(entry)

    previous_by_player: dict[str, dict[str, Any]] = {}
    changes: list[dict[str, Any]] = []

    for tournament_number in sorted(grouped):
        entries = grouped[tournament_number]
        current_by_player = {
            str(entry["player_id"]): entry
            for entry in entries
        }

        elo_changes: list[dict[str, Any]] = []
        rank_changes: list[dict[str, Any]] = []

        for player_id, current in current_by_player.items():
            previous = previous_by_player.get(player_id)

            if previous is None:
                continue

            elo_delta = round(
                float(current["elo_exact"]) - float(previous["elo_exact"]),
                4,
            )
            rank_delta = int(previous["rank"]) - int(current["rank"])

            elo_changes.append(
                {
                    "player_id": player_id,
                    "player": current["player"],
                    "before": round(float(previous["elo_exact"]), 1),
                    "after": round(float(current["elo_exact"]), 1),
                    "change": round(elo_delta, 1),
                }
            )

            rank_changes.append(
                {
                    "player_id": player_id,
                    "player": current["player"],
                    "before": int(previous["rank"]),
                    "after": int(current["rank"]),
                    "change": rank_delta,
                }
            )

        positive_elo_changes = [
            item for item in elo_changes if item["change"] > 0
        ]
        negative_elo_changes = [
            item for item in elo_changes if item["change"] < 0
        ]
        positive_rank_changes = [
            item for item in rank_changes if item["change"] > 0
        ]
        negative_rank_changes = [
            item for item in rank_changes if item["change"] < 0
        ]

        biggest_elo_gain = (
            max(
                positive_elo_changes,
                key=lambda item: (
                    item["change"],
                    item["player"].casefold(),
                ),
            )
            if positive_elo_changes
            else None
        )

        biggest_elo_loss = (
            min(
                negative_elo_changes,
                key=lambda item: (
                    item["change"],
                    item["player"].casefold(),
                ),
            )
            if negative_elo_changes
            else None
        )

        biggest_rank_gain = (
            max(
                positive_rank_changes,
                key=lambda item: (
                    item["change"],
                    item["player"].casefold(),
                ),
            )
            if positive_rank_changes
            else None
        )

        biggest_rank_loss = (
            min(
                negative_rank_changes,
                key=lambda item: (
                    item["change"],
                    item["player"].casefold(),
                ),
            )
            if negative_rank_changes
            else None
        )

        changes.append(
            {
                "tournament_number": tournament_number,
                "tournament": entries[0]["tournament"],
                "tournament_date": entries[0]["tournament_date"],
                "biggest_elo_gain": biggest_elo_gain,
                "biggest_elo_loss": biggest_elo_loss,
                "biggest_rank_gain": biggest_rank_gain,
                "biggest_rank_loss": biggest_rank_loss,
            }
        )

        previous_by_player = current_by_player

    return changes


def print_elo_tournament_changes(
    changes: list[dict[str, Any]],
    *,
    tournament_number: int | None = None,
) -> None:
    """Prints the largest Elo and ranking changes per tournament."""

    if tournament_number is not None:
        changes = [
            entry
            for entry in changes
            if entry["tournament_number"] == tournament_number
        ]

    print("\nElo and Ranking Changes by Tournament")
    print("=" * 96)

    if not changes:
        print("No matching tournament data found.")
        return

    for entry in changes:
        print(f"\n{entry['tournament']} – {entry['tournament_date']}")
        print("-" * 96)

        gain = entry["biggest_elo_gain"]
        loss = entry["biggest_elo_loss"]
        rank_gain = entry["biggest_rank_gain"]
        rank_loss = entry["biggest_rank_loss"]

        if not any((gain, loss, rank_gain, rank_loss)):
            print("No previous comparison snapshot is available.")
            continue

        if gain is not None:
            print(
                f"Biggest Elo Gain:   {gain['player']:<18} "
                f"{gain['before']:>7.1f} → {gain['after']:>7.1f} "
                f"({gain['change']:+.1f})"
            )
        else:
            print("Biggest Elo Gain:   none")

        if loss is not None:
            print(
                f"Biggest Elo Loss:  {loss['player']:<18} "
                f"{loss['before']:>7.1f} → {loss['after']:>7.1f} "
                f"({loss['change']:+.1f})"
            )
        else:
            print("Biggest Elo Loss:  none")

        if rank_gain is not None:
            print(
                f"Biggest Rank Gain: {rank_gain['player']:<18} "
                f"{rank_gain['before']:>2} → {rank_gain['after']:<2} "
                f"({rank_gain['change']:+d})"
            )
        else:
            print("Biggest Rank Gain: none")

        if rank_loss is not None:
            print(
                f"Biggest Rank Loss:  {rank_loss['player']:<18} "
                f"{rank_loss['before']:>2} → {rank_loss['after']:<2} "
                f"({rank_loss['change']:+d})"
            )
        else:
            print("Biggest Rank Loss:  none")


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


def print_player_elo_timeline(
    player_name: str,
    timeline: list[dict[str, Any]],
) -> None:
    """Prints a player’s Elo and rank after each tournament."""

    print(f"\nElo Ranking History for {player_name}")
    print("=" * 64)

    if not timeline:
        print("No rated matches found.")
        return

    header = (
        f"{'Tournament':<9} {'Date':<12} {'Elo':>9} "
        f"{'Rank':>7} {'Played':>10}"
    )
    print(header)
    print("-" * len(header))

    for entry in timeline:
        print(
            f"{entry['tournament']:<9} "
            f"{str(entry['tournament_date']):<12} "
            f"{entry['elo']:>9.1f} "
            f"{entry['rank']:>7} "
            f"{_yes_no(entry['played_in_tournament']):>10}"
        )


def print_elo_ranking_timeline(
    timeline: list[dict[str, Any]],
) -> None:
    """Prints all historical Elo rankings grouped by tournament."""

    if not timeline:
        print("\nNo rated matches found.")
        return

    grouped: dict[int, list[dict[str, Any]]] = {}
    for entry in timeline:
        grouped.setdefault(entry["tournament_number"], []).append(entry)

    print("\nHistorische Elo-Rankings")

    for tournament_number in sorted(grouped):
        entries = sorted(grouped[tournament_number], key=lambda entry: entry["rank"])
        tournament_date = entries[0]["tournament_date"]

        print(f"\nWM {tournament_number:02d} – {tournament_date}")
        print("-" * 50)
        print(f"{'Rank':>4}  {'Players':<18} {'Elo':>9}")
        print("-" * 36)

        for entry in entries:
            print(
                f"{entry['rank']:>4}  "
                f"{entry['player']:<18} "
                f"{entry['elo']:>9.1f}"
            )



def get_biggest_upsets(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    limit: int = 10,
    k_factor: float = ELO_K_FACTOR,
) -> list[dict[str, Any]]:
    """Returns the biggest upsets by Elo gain."""

    if limit <= 0:
        raise ValueError("limit must be greater than zero.")

    history = calculate_elo_history(
        db_path,
        k_factor=k_factor,
    )

    upsets = [
        {
            "rank": 0,
            "match_id": event["match_id"],
            "tournament_number": event["tournament_number"],
            "tournament_date": event["tournament_date"],
            "stage": event["stage"],
            "round_label": event["round_label"],
            "winner": event["winner"],
            "loser": event["loser"],
            "winner_elo_before": event["winner_rating_before"],
            "loser_elo_before": event["loser_rating_before"],
            "elo_difference_before": round(
                float(event["loser_rating_before"])
                - float(event["winner_rating_before"]),
                1,
            ),
            "elo_gain": round(float(event["rating_change"]), 1),
            "winner_score": event["winner_score"],
            "loser_score": event["loser_score"],
        }
        for event in history
    ]

    upsets.sort(
        key=lambda event: (
            -event["elo_gain"],
            -event["elo_difference_before"],
            event["tournament_number"],
            event["match_id"],
        )
    )

    selected = upsets[:limit]
    for rank, event in enumerate(selected, start=1):
        event["rank"] = rank

    return selected


def print_biggest_upsets(upsets: list[dict[str, Any]]) -> None:
    """Prints the biggest Elo upsets as a table."""

    print("\nBiggest Elo Upsets")
    print("=" * 94)

    if not upsets:
        print("No rated matches found.")
        return

    header = (
        f"{'Rank':>4} {'WM':>4} {'Winner':<16} {'Loser':<16} "
        f"{'Score':>7} {'Elo Before':>20} {'Gain':>8}"
    )
    print(header)
    print("-" * len(header))

    for event in upsets:
        score = (
            f"{event['winner_score']}:{event['loser_score']}"
            if event["winner_score"] is not None
            else "–"
        )
        before = (
            f"{event['winner_elo_before']:.1f}–"
            f"{event['loser_elo_before']:.1f}"
        )
        print(
            f"{event['rank']:>4} "
            f"{event['tournament_number']:>4} "
            f"{event['winner']:<16} "
            f"{event['loser']:<16} "
            f"{score:>7} "
            f"{before:>20} "
            f"{event['elo_gain']:>+8.1f}"
        )


def print_elo_ranking(ranking: list[dict[str, Any]]) -> None:
    """Gibt das aktuelle Elo-Ranking im Terminal aus."""

    print("\nCurrent Elo Ranking")
    print("=" * 54)

    if not ranking:
        print("No rated matches found.")
        return

    header = (
        f"{'Rank':>4}  {'Players':<18} "
        f"{'Elo':>8} {'Matches':>8} {'Active':>7}"
    )
    print(header)
    print("-" * len(header))

    for entry in ranking:
        print(
            f"{entry['rank']:>4}  "
            f"{entry['player']:<18} "
            f"{entry['elo']:>8.1f} "
            f"{entry['rated_matches']:>8} "
            f"{_yes_no(entry['active']):>7}"
        )


def print_player_elo_history(
    player_name: str,
    history: list[dict[str, Any]],
) -> None:
    """Gibt den Elo History eines Playerss im Terminal aus."""

    print(f"\nElo History for {player_name}")
    print("=" * 88)

    if not history:
        print("No rated matches found.")
        return

    header = (
        f"{'WM':>4} {'Opponent':<16} {'Res.':>5} {'Score':>7} "
        f"{'Before':>9} {'Change':>10} {'After':>9}"
    )
    print(header)
    print("-" * len(header))

    for event in history:
        if event["winner_score"] is None:
            score = "–"
        elif event["result"] == "win":
            score = f"{event['winner_score']}:{event['loser_score']}"
        else:
            score = f"{event['loser_score']}:{event['winner_score']}"

        result = "S" if event["result"] == "win" else "N"

        print(
            f"{event['tournament_number']:>4} "
            f"{event['opponent']:<16} "
            f"{result:>5} "
            f"{score:>7} "
            f"{event['elo_before']:>9.1f} "
            f"{event['elo_change']:>+10.1f} "
            f"{event['elo_after']:>9.1f}"
        )



def print_player_stats(stats: dict[str, Any]) -> None:
    """Gibt eine lesbare Playersstatistik im Terminal aus."""

    print(f"\nStatistics for {stats['player']}")
    print("=" * 48)

    print(f"Players-ID:              {stats['player_id']}")
    print(f"Active:                   {_yes_no(stats['active'])}")
    print(f"Core-Players:            {_yes_no(stats['core_player'])}")

    print("\nTournaments")
    print("-" * 48)
    print(f"Appearances:               {stats['appearances']}")
    print(f"Titles:                    {stats['titles']}")
    print(f"Bestes Resultat:          {_format_placement(stats['best_result'])}")
    print(
        f"Average Placement:            "
        f"{_format_number(stats['average_result'])}"
    )
    print(f"Bekannte Placements:   {stats['known_placements']}")

    if "current_elo" in stats:
        print("\nElo")
        print("-" * 48)
        current_elo = stats["current_elo"]
        peak_elo = stats["peak_elo"]
        peak_tournament = stats["peak_elo_tournament"]
        print(
            "Current Elo:           "
            + (f"{current_elo:.1f}" if current_elo is not None else "–")
        )
        print(
            "Peak Elo:            "
            + (
                f"{peak_elo:.1f} (after WC {peak_tournament:02d})"
                if peak_elo is not None and peak_tournament is not None
                else "–"
            )
        )
        print(f"Rated Matches:        {stats['rated_matches']}")

    print("\nMatches")
    print("-" * 48)
    print(f"Matches:                  {stats['matches']}")
    print(f"Wins:                    {stats['wins']}")
    print(f"Niederlagen:              {stats['losses']}")
    print(f"Unentschieden/unknown:  {stats['undecided_matches']}")
    print(f"Win Rate:                  {_format_percent(stats['winrate'])}")

    print("\nGames")
    print("-" * 48)
    print(f"Games gewonnen:           {stats['games_won']}")
    print(f"Games verloren:           {stats['games_lost']}")
    print(f"Game-Win Rate:             {_format_percent(stats['game_winrate'])}")
    print(
        f"Matches with scores:        "
        f"{stats['matches_with_known_score']}"
    )

    print("\nStagen")
    print("-" * 48)
    print(
        f"Gruppe:                   "
        f"{stats['group_wins']}-{stats['group_losses']} "
        f"({_format_percent(stats['group_winrate'])})"
    )
    print(
        f"Knockout:                 "
        f"{stats['knockout_wins']}-{stats['knockout_losses']} "
        f"({_format_percent(stats['knockout_winrate'])})"
    )


def _format_percent(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f} %"


def _format_number(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}"


def _format_placement(value: int | None) -> str:
    return "–" if value is None else str(value)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculates player statistics for the Smash World Championship archive."
    )
    parser.add_argument(
        "player",
        nargs="?",
        help="Player ID or display name",
    )
    parser.add_argument(
        "opponent",
        nargs="?",
        help="Second player for --head-to-head",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Output statistics for all players as JSON",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive players in rankings",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output individual statistics as JSON",
    )
    parser.add_argument(
        "--ranking",
        choices=[
            "overall",
            "titles",
            "wins",
            "winrate",
            "games",
            "appearances",
        ],
        help="Output the player ranking by the selected criterion",
    )
    parser.add_argument(
        "--minimum-matches",
        type=int,
        default=0,
        help="Minimum number of matches for rankings",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Output tournament history for the specified player",
    )
    parser.add_argument(
        "--head-to-head",
        action="store_true",
        help="Output head-to-head record between player and opponent",
    )
    parser.add_argument(
        "--all-head-to-heads",
        action="store_true",
        help="Output records against all previous opponents",
    )
    parser.add_argument(
        "--elo-ranking",
        action="store_true",
        help="Output current Elo ranking",
    )
    parser.add_argument(
        "--elo-history",
        action="store_true",
        help="Output Elo history for the specified player",
    )
    parser.add_argument(
        "--elo-timeline",
        action="store_true",
        help="Output a player’s Elo and rank after each tournament",
    )
    parser.add_argument(
        "--elo-ranking-timeline",
        action="store_true",
        help="Output the full Elo ranking after each tournament",
    )
    parser.add_argument(
        "--elo-changes",
        action="store_true",
        help="Output the largest Elo and ranking changes per tournament",
    )
    parser.add_argument(
        "--records",
        action="store_true",
        help="Output all-time records and Hall of Fame",
    )
    parser.add_argument(
        "--tournament-number",
        type=int,
        help="Ausgabe auf eine bestimmte WM-Nummer begrenzen",
    )
    parser.add_argument(
        "--upsets",
        action="store_true",
        help="Output the biggest Elo upsets",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of entries for lists such as --upsets",
    )
    parser.add_argument(
        "--elo-k",
        type=float,
        default=ELO_K_FACTOR,
        help="K factor for Elo calculation",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        if args.all:
            stats = get_all_player_stats(
                args.db,
                active_only=False,
            )
            print(json.dumps(stats, ensure_ascii=False, indent=2))
            return

        if args.records:
            records = get_smash_records(
                args.db,
                active_only=not args.include_inactive,
                k_factor=args.elo_k,
            )

            if args.json:
                print(json.dumps(records, ensure_ascii=False, indent=2))
            else:
                print_smash_records(records)

            return

        if args.elo_changes:
            changes = get_elo_tournament_changes(
                args.db,
                active_only=not args.include_inactive,
                k_factor=args.elo_k,
            )

            if args.tournament_number is not None:
                changes = [
                    entry
                    for entry in changes
                    if entry["tournament_number"] == args.tournament_number
                ]

            if args.json:
                print(json.dumps(changes, ensure_ascii=False, indent=2))
            else:
                print_elo_tournament_changes(
                    changes,
                    tournament_number=args.tournament_number,
                )

            return

        if args.elo_ranking_timeline:
            timeline = get_elo_ranking_timeline(
                args.db,
                active_only=not args.include_inactive,
                k_factor=args.elo_k,
            )

            if args.json:
                print(json.dumps(timeline, ensure_ascii=False, indent=2))
            else:
                print_elo_ranking_timeline(timeline)

            return

        if args.elo_ranking:
            ranking = get_elo_ranking(
                args.db,
                active_only=not args.include_inactive,
                k_factor=args.elo_k,
            )

            if args.json:
                print(
                    json.dumps(
                        ranking,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print_elo_ranking(ranking)

            return

        if args.ranking:
            ranking = get_ranking(
                args.db,
                sort_by=args.ranking,
                active_only=not args.include_inactive,
                minimum_matches=args.minimum_matches,
            )

            if args.json:
                print(
                    json.dumps(
                        ranking,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print_ranking(
                    ranking,
                    sort_by=args.ranking,
                )

            return

        if args.upsets:
            upsets = get_biggest_upsets(
                args.db,
                limit=args.limit,
                k_factor=args.elo_k,
            )

            if args.json:
                print(json.dumps(upsets, ensure_ascii=False, indent=2))
            else:
                print_biggest_upsets(upsets)

            return

        if not args.player:
            raise ValueError(
                "Specify a player or use a ranking command."
            )

        if args.elo_timeline:
            timeline = get_player_elo_timeline(
                args.player,
                args.db,
                k_factor=args.elo_k,
            )

            if args.json:
                print(json.dumps(timeline, ensure_ascii=False, indent=2))
            else:
                with connect_db(args.db) as connection:
                    player_name = resolve_player(
                        connection,
                        args.player,
                    )["display_name"]

                print_player_elo_timeline(
                    player_name,
                    timeline,
                )

            return

        if args.elo_history:
            history = get_player_elo_history(
                args.player,
                args.db,
                k_factor=args.elo_k,
            )

            if args.json:
                print(
                    json.dumps(
                        history,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                with connect_db(args.db) as connection:
                    player_name = resolve_player(
                        connection,
                        args.player,
                    )["display_name"]

                print_player_elo_history(
                    player_name,
                    history,
                )

            return

        if args.all_head_to_heads:
            head_to_heads = get_all_head_to_heads(
                args.player,
                args.db,
            )

            if args.json:
                print(
                    json.dumps(
                        head_to_heads,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                with connect_db(args.db) as connection:
                    player_name = resolve_player(
                        connection,
                        args.player,
                    )["display_name"]

                print_all_head_to_heads(
                    player_name,
                    head_to_heads,
                )

            return

        if args.head_to_head:
            if not args.opponent:
                raise ValueError(
                    "A second player is required for --head-to-head."
                )

            head_to_head = get_head_to_head(
                args.player,
                args.opponent,
                args.db,
            )

            if args.json:
                print(
                    json.dumps(
                        head_to_head,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print_head_to_head(head_to_head)

            return

        if args.history:
            history = get_player_history(args.player, args.db)

            if args.json:
                print(json.dumps(history, ensure_ascii=False, indent=2))
            else:
                with connect_db(args.db) as connection:
                    player_name = resolve_player(
                        connection,
                        args.player,
                    )["display_name"]

                print_player_history(player_name, history)

            return

        stats = get_player_stats(
            args.player,
            args.db,
            include_elo=True,
            elo_k_factor=args.elo_k,
        )

        if args.json:
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        else:
            print_player_stats(stats)

    except (FileNotFoundError, PlayerNotFoundError, ValueError) as error:
        raise SystemExit(f"Errors: {error}") from error
    except sqlite3.Error as error:
        raise SystemExit(f"Database error: {error}") from error


if __name__ == "__main__":
    main()
