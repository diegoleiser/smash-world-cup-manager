"""Pure helpers for Tournament Control Center presentation."""

from __future__ import annotations

from typing import Any


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
