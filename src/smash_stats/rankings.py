"""General player rankings and terminal presentation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from smash_stats.common import _format_number, _format_percent
from smash_stats.database import DEFAULT_DB_PATH
from smash_stats.player_stats import get_all_player_stats


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

    print(f"\nSmash WC Ranking ({sort_by})")
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
