#!/usr/bin/env python3
"""Rule-based narrative generation for Smash World Championship statistics."""

from __future__ import annotations

from typing import Any


def _decided_history(h2h: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns head-to-head matches with a recognized winner."""

    player_names = {
        str(h2h["player_a"]["player"]),
        str(h2h["player_b"]["player"]),
    }

    return [
        match
        for match in h2h.get("history", [])
        if match.get("winner") in player_names
    ]


def _current_streak(
    history: list[dict[str, Any]],
) -> tuple[str | None, int]:
    """Returns the winner and length of the current head-to-head streak."""

    if not history:
        return None, 0

    streak_winner = history[-1].get("winner")
    if not streak_winner:
        return None, 0

    streak_length = 0
    for match in reversed(history):
        if match.get("winner") != streak_winner:
            break
        streak_length += 1

    return str(streak_winner), streak_length


def _overall_summary(
    player_a: str,
    player_b: str,
    wins_a: int,
    wins_b: int,
) -> str:
    """Builds the all-time head-to-head sentence."""

    if wins_a == wins_b:
        return (
            f"The all-time series between {player_a} and {player_b} "
            f"is tied at {wins_a}–{wins_b}."
        )

    if wins_a > wins_b:
        leader = player_a
        trailer = player_b
        leader_wins = wins_a
        trailer_wins = wins_b
    else:
        leader = player_b
        trailer = player_a
        leader_wins = wins_b
        trailer_wins = wins_a

    margin = leader_wins - trailer_wins

    if margin == 1:
        return (
            f"{leader} narrowly leads the all-time series against {trailer} "
            f"{leader_wins}–{trailer_wins}."
        )

    return (
        f"{leader} leads the all-time series against {trailer} "
        f"{leader_wins}–{trailer_wins}."
    )


def generate_rivalry_summary(h2h: dict[str, Any]) -> str:
    """
    Generates a short rule-based rivalry summary.

    The input is expected to match the dictionary returned by
    ``smash_statistics.get_head_to_head()``.
    """

    player_a = str(h2h["player_a"]["player"])
    player_b = str(h2h["player_b"]["player"])
    wins_a = int(h2h["player_a"].get("wins", 0))
    wins_b = int(h2h["player_b"].get("wins", 0))

    history = _decided_history(h2h)

    if not history:
        return f"{player_a} and {player_b} have not faced each other yet."

    if len(history) == 1:
        winner = str(history[0]["winner"])
        return (
            f"{player_a} and {player_b} have faced each other only once, "
            f"with {winner} taking the win."
        )

    overall = _overall_summary(
        player_a,
        player_b,
        wins_a,
        wins_b,
    )

    streak_winner, streak_length = _current_streak(history)
    if streak_winner is not None and streak_length >= 3:
        return (
            f"{overall} {streak_winner} has won the last "
            f"{streak_length} sets."
        )

    recent_matches = history[-5:]
    if len(recent_matches) == 5:
        recent_wins_a = sum(
            match["winner"] == player_a
            for match in recent_matches
        )
        recent_wins_b = sum(
            match["winner"] == player_b
            for match in recent_matches
        )

        if recent_wins_a >= 4:
            recent_leader = player_a
            recent_wins = recent_wins_a
        elif recent_wins_b >= 4:
            recent_leader = player_b
            recent_wins = recent_wins_b
        else:
            recent_leader = None
            recent_wins = 0

        if recent_leader is not None:
            all_time_leader = None
            if wins_a > wins_b:
                all_time_leader = player_a
            elif wins_b > wins_a:
                all_time_leader = player_b

            connector = (
                "However, "
                if all_time_leader is not None
                and recent_leader != all_time_leader
                else ""
            )
            return (
                f"{overall} {connector}{recent_leader} has won "
                f"{recent_wins} of the last five sets."
            )

    return overall
