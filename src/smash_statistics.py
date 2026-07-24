#!/usr/bin/env python3
"""Dynamically calculated statistics for the Smash World Championship archive."""

from __future__ import annotations

import argparse
import json
import sqlite3
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
    get_elo_ranking_timeline,
    get_player_elo_history,
    get_player_elo_summary,
    get_player_elo_timeline,
)
from smash_stats.common import (
    _format_number,
    _format_percent,
    _percentage,
)
from smash_stats.rankings import get_ranking, print_ranking
from smash_stats.records import get_smash_records, print_smash_records
from smash_stats.head_to_head import (
    get_all_head_to_heads,
    get_head_to_head,
    print_all_head_to_heads,
    print_head_to_head,
)
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

    for tournament_number in grouped:
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

    for tournament_number in grouped:
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
