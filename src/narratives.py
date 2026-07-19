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


def _title_phrase(titles: int) -> str:
    """Returns a natural-language championship phrase."""

    if titles <= 0:
        return "is still searching for a first championship"
    if titles == 1:
        return "is a World Championship winner"
    if titles == 2:
        return "is a two-time World Champion"

    return f"is a {titles}-time World Champion"


def generate_player_summary(
    profile: dict[str, Any],
    insights: dict[str, Any],
    current_rank: int | None,
) -> str:
    """
    Generates a short rule-based career summary for a player.

    The input is expected to match the data returned by
    ``smash_statistics.get_player_stats()`` and the dashboard's
    ``load_player_insights()`` helper.
    """

    player = str(profile["player"])
    titles = int(profile.get("titles", 0))
    appearances = int(profile.get("appearances", 0))
    current_elo = float(profile.get("current_elo", 1000.0))
    decided_matches = int(profile.get("decided_matches", 0))
    winrate = profile.get("winrate")
    best_elo_event = insights.get("best_elo_event")

    appearance_word = "appearance" if appearances == 1 else "appearances"

    opening = (
        f"{player} {_title_phrase(titles)} with "
        f"{appearances} tournament {appearance_word}."
    )

    if decided_matches == 0:
        return (
            f"{opening} No completed match data is available "
            f"for this player yet."
        )

    if current_rank is not None:
        ranking_sentence = (
            f"{player} currently ranks #{current_rank} with an Elo rating "
            f"of {current_elo:.1f}"
        )
    else:
        ranking_sentence = (
            f"{player} currently has an Elo rating of {current_elo:.1f}"
        )

    if winrate is not None:
        ranking_sentence += (
            f" and has won {float(winrate):.1f}% of recorded sets."
        )
    else:
        ranking_sentence += "."

    sentences = [opening, ranking_sentence]

    if best_elo_event:
        tournament = best_elo_event.get("tournament")
        change = float(best_elo_event.get("elo_change", 0.0))

        if tournament and change > 0:
            sentences.append(
                f"The biggest Elo gain came at {tournament}, "
                f"with an increase of {change:.1f} points."
            )

    return " ".join(sentences)

def _find_final_match(
    matches: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Returns the last completed knockout match."""

    knockout_matches = [
        match
        for match in matches
        if match.get("stage") == "knockout"
        and match.get("winner")
    ]

    if not knockout_matches:
        return None

    return knockout_matches[-1]


def _format_match_score(match: dict[str, Any]) -> str | None:
    """Formats a match score from the winner's perspective."""

    if not match.get("score_known"):
        return None

    score_1 = match.get("player_1_score")
    score_2 = match.get("player_2_score")

    if score_1 is None or score_2 is None:
        return None

    if match.get("winner") == match.get("player_1"):
        return f"{score_1}–{score_2}"

    if match.get("winner") == match.get("player_2"):
        return f"{score_2}–{score_1}"

    return f"{score_1}–{score_2}"


def _most_match_wins(
    matches: list[dict[str, Any]],
) -> tuple[str | None, int]:
    """Returns the player with the most completed match wins."""

    wins: dict[str, int] = {}

    for match in matches:
        winner = match.get("winner")
        if not winner:
            continue

        winner = str(winner)
        wins[winner] = wins.get(winner, 0) + 1

    if not wins:
        return None, 0

    player, total = max(
        wins.items(),
        key=lambda item: (item[1], item[0]),
    )

    return player, total


def _count_close_sets(
    matches: list[dict[str, Any]],
) -> int:
    """Counts sets decided by a single game."""

    close_sets = 0

    for match in matches:
        if not match.get("score_known"):
            continue

        score_1 = match.get("player_1_score")
        score_2 = match.get("player_2_score")

        if score_1 is None or score_2 is None:
            continue

        if abs(int(score_1) - int(score_2)) == 1:
            close_sets += 1

    return close_sets


def _largest_elo_upset(
    matches: list[dict[str, Any]],
    elo_changes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Finds the largest win by a player with a lower pre-tournament Elo.

    Elo ratings from before the tournament are used, rather than ratings
    recalculated after every individual set.
    """

    elo_before = {
        str(row["Players"]): float(row["Elo Before"])
        for row in elo_changes
    }

    biggest_upset: dict[str, Any] | None = None

    for match in matches:
        winner = match.get("winner")
        player_1 = match.get("player_1")
        player_2 = match.get("player_2")

        if not winner or not player_1 or not player_2:
            continue

        loser = player_2 if winner == player_1 else player_1

        winner_elo = elo_before.get(str(winner))
        loser_elo = elo_before.get(str(loser))

        if winner_elo is None or loser_elo is None:
            continue

        elo_gap = loser_elo - winner_elo

        if elo_gap <= 0:
            continue

        if biggest_upset is None or elo_gap > biggest_upset["elo_gap"]:
            biggest_upset = {
                "winner": str(winner),
                "loser": str(loser),
                "elo_gap": elo_gap,
                "tournament": match.get("tournament"),
            }

    return biggest_upset


def generate_tournament_summary(
    tournament: dict[str, Any],
    participants: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    elo_changes: list[dict[str, Any]],
    *,
    winner_title_number: int | None = None,
    defending_champion: str | None = None,
) -> str:
    """Generates a rule-based recap for one tournament."""

    tournament_number = int(tournament["tournament_number"])
    tournament_name = f"WM {tournament_number:02d}"
    winner = str(tournament.get("winner") or "An unknown player")

    podium = {
        int(row["placement"]): str(row["player"])
        for row in participants
        if row.get("placement") in (1, 2, 3)
    }

    runner_up = podium.get(2)
    third_place = podium.get(3)

    final_match = _find_final_match(matches)
    final_score = (
        _format_match_score(final_match)
        if final_match is not None
        else None
    )

    # Opening sentence
    if runner_up and final_score:
        opening = (
            f"{winner} won {tournament_name} by defeating "
            f"{runner_up} {final_score} in the final."
        )
    elif runner_up:
        opening = (
            f"{winner} won {tournament_name}, with {runner_up} "
            f"finishing as runner-up."
        )
    else:
        opening = f"{winner} won {tournament_name}."

    sentences = [opening]

    # Title context
    if defending_champion == winner:
        sentences.append(f"{winner} successfully defended the title.")
    elif winner_title_number == 1:
        sentences.append(
            f"It was the first World Championship title of "
            f"{winner}'s career."
        )
    elif winner_title_number and winner_title_number > 1:
        sentences.append(
            f"The victory marked {winner}'s "
            f"{winner_title_number}th World Championship title."
        )

    # Main tournament performance
    wins_leader, wins_total = _most_match_wins(matches)

    if wins_leader and wins_total:
        if wins_leader == winner:
            sentences.append(
                f"The champion also recorded the most match wins "
                f"with {wins_total}."
            )
        else:
            sentences.append(
                f"{wins_leader} recorded the most match wins "
                f"with {wins_total}."
            )

    # Elo and upset storylines
    if elo_changes:
        biggest_gain = max(
            elo_changes,
            key=lambda row: float(row["Elo Change"]),
        )
        biggest_loss = min(
            elo_changes,
            key=lambda row: float(row["Elo Change"]),
        )

        gain = float(biggest_gain["Elo Change"])
        loss = float(biggest_loss["Elo Change"])

        if gain > 0:
            elo_sentence = (
                f"{biggest_gain['Players']} made the biggest Elo gain "
                f"at {gain:+.1f}"
            )

            if loss < 0:
                elo_sentence += (
                    f", while {biggest_loss['Players']} had the largest "
                    f"drop at {loss:+.1f}."
                )
            else:
                elo_sentence += "."

            sentences.append(elo_sentence)

    biggest_upset = _largest_elo_upset(matches, elo_changes)

    if biggest_upset:
        sentences.append(
            f"The biggest Elo upset came when "
            f"{biggest_upset['winner']} defeated "
            f"{biggest_upset['loser']} despite a "
            f"{biggest_upset['elo_gap']:.1f}-point rating gap."
        )

    # General tournament context
    close_sets = _count_close_sets(matches)
    participant_count = len(participants)
    match_count = len(matches)

    context_parts = [
        f"{participant_count} players competed across "
        f"{match_count} recorded matches"
    ]

    if close_sets:
        set_word = "set" if close_sets == 1 else "sets"
        context_parts.append(
            f"{close_sets} {set_word} decided by a single game"
        )

    if third_place:
        context_parts.append(f"{third_place} finishing third")

    context_sentence = ", with ".join(context_parts) + "."
    sentences.append(context_sentence)

    # Keep the recap readable rather than listing every statistic.
    return " ".join(sentences[:4])