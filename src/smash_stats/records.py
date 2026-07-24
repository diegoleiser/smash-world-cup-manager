"""All-time Smash World Championship records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from smash_stats.database import DEFAULT_DB_PATH, connect_db
from smash_stats.elo_history import (
    calculate_elo_history,
    get_elo_ranking_timeline,
)
from smash_stats.elo_rules import ELO_K_FACTOR, ELO_START_RATING


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

