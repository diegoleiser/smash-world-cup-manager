"""Pure helpers for Tournament Control Center presentation."""

from __future__ import annotations

from typing import Any


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def finalization_standings_table_data(
    placements: list[dict[str, Any]],
) -> tuple[list[list[str]], dict[int, str]]:
    """Build the shared final standings rows for both manager views."""

    placement_counts: dict[int, int] = {}
    for placement in placements:
        placement_value = int(placement["placement"])
        placement_counts[placement_value] = (
            placement_counts.get(placement_value, 0) + 1
        )

    medal_by_placement = {1: "🥇", 2: "🥈", 3: "🥉"}
    rows = []
    for placement in placements:
        placement_value = int(placement["placement"])
        initial_seed = int(placement["initial_seed"])
        elo_after = float(placement["elo_after"])
        elo_change = float(placement["elo_change"])
        rows.append([
            (
                f"{medal_by_placement.get(placement_value, '')} "
                f"{'T-' if placement_counts[placement_value] > 1 else ''}"
                f"{_ordinal(placement_value)}"
            ).strip(),
            str(placement["player"]),
            f"Seed #{initial_seed}",
            (
                f"▲ {initial_seed - placement_value}"
                if initial_seed > placement_value
                else (
                    f"▼ {placement_value - initial_seed}"
                    if initial_seed < placement_value
                    else "= Seed"
                )
            ),
            f"{elo_after:.1f} ({elo_change:+.1f})",
        ])

    return rows, ({0: "winners"} if rows else {})


def group_ready_matches(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prioritize open sets while spreading play across participants."""

    played_counts: dict[str, int] = {}
    for match in matches:
        if str(match["status"]) not in {"completed", "forfeit"}:
            continue
        for key in ("player_1_id", "player_2_id"):
            player_id = str(match[key])
            played_counts[player_id] = played_counts.get(player_id, 0) + 1

    return sorted(
        (
            match
            for match in matches
            if str(match["status"]) == "pending"
        ),
        key=lambda match: (
            max(
                played_counts.get(str(match["player_1_id"]), 0),
                played_counts.get(str(match["player_2_id"]), 0),
            ),
            int(match["round_number"]),
            int(match["match_number"]),
        ),
    )
