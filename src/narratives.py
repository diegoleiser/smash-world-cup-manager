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


def generate_player_summary(
    profile: dict[str, Any],
    insights: dict[str, Any],
    current_rank: int | None,
) -> str:
    """Generates a varied rule-based career summary for a player."""

    player = str(profile["player"])
    titles = int(profile.get("titles", 0))
    appearances = int(profile.get("appearances", 0))
    current_elo = float(profile.get("current_elo") or 1000.0)
    peak_elo = float(profile.get("peak_elo") or 1000.0)
    decided_matches = int(profile.get("decided_matches", 0))
    winrate = profile.get("winrate")
    best_result = profile.get("best_result")

    nemesis = insights.get("nemesis")
    longest_win_streak = int(
        insights.get("longest_win_streak", 0)
    )
    best_elo_event = insights.get("best_elo_event")

    appearance_word = (
        "appearance"
        if appearances == 1
        else "appearances"
    )

    # Career introduction
    if appearances <= 1 and titles == 0:
        opening = (
            f"{player} has made {appearances} recorded tournament "
            f"{appearance_word} so far."
        )
    elif titles == 0:
        opening = (
            f"{player} has appeared in {appearances} tournaments "
            f"and is still chasing a first championship."
        )
    elif titles == 1:
        opening = (
            f"{player} has one World Championship title across "
            f"{appearances} tournament {appearance_word}."
        )
    elif titles == 2:
        opening = (
            f"{player} is a two-time World Champion with "
            f"{appearances} tournament appearances."
        )
    else:
        opening = (
            f"{player} is one of the archive's most successful players, "
            f"with {titles} World Championship titles across "
            f"{appearances} appearances."
        )

    if decided_matches == 0:
        return (
            f"{opening} No completed set data is available "
            f"for this player yet."
        )

    # Current performance
    if current_rank == 1:
        performance = (
            f"They currently lead the Elo ranking with a rating "
            f"of {current_elo:.1f}"
        )
    elif current_rank is not None:
        performance = (
            f"They currently rank #{current_rank} with an Elo rating "
            f"of {current_elo:.1f}"
        )
    else:
        performance = (
            f"Their current Elo rating stands at {current_elo:.1f}"
        )

    if winrate is not None:
        performance += (
            f" and have won {float(winrate):.1f}% of recorded sets."
        )
    else:
        performance += "."

    # Select one personal storyline.
    storyline: str | None = None

    if longest_win_streak >= 4:
        storyline = (
            f"Their longest winning streak stands at "
            f"{longest_win_streak} sets."
        )

    elif (
        nemesis
        and int(nemesis.get("matches", 0)) >= 3
        and float(nemesis.get("winrate", 100.0)) < 50.0
    ):
        storyline = (
            f"Their toughest recorded opponent has been "
            f"{nemesis['opponent']}, against whom they hold a "
            f"{nemesis['wins']}–{nemesis['losses']} record."
        )

    elif best_elo_event:
        tournament = best_elo_event.get("tournament")
        change = float(best_elo_event.get("elo_change", 0.0))

        if tournament and change > 0:
            storyline = (
                f"Their biggest Elo gain came at {tournament}, "
                f"with an increase of {change:.1f} points."
            )

    if storyline is None and peak_elo > current_elo:
        storyline = (
            f"Their career-high Elo rating is {peak_elo:.1f}."
        )

    if storyline is None and best_result is not None:
        placement = int(best_result)
        storyline = (
            f"Their best tournament finish is "
            f"{_ordinal(placement)} place."
        )

    sentences = [opening, performance]

    if storyline:
        sentences.append(storyline)

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

def _select_milestone(
    milestones: list[str] | None,
) -> str | None:
    """Selects the most important milestone for a tournament recap."""

    if not milestones:
        return None

    priority_rules = [
        ("first World Championship title", 100),
        ("50 recorded set wins", 90),
        ("25 recorded set wins", 80),
        ("new career-best placement", 70),
        ("new career-high Elo", 60),
        ("tenth tournament appearance", 50),
        ("10 World Championship titles", 45),
        ("5 World Championship titles", 40),
        ("10 recorded set wins", 30),
        ("fifth tournament appearance", 20),
    ]

    def priority(text: str) -> int:
        for phrase, score in priority_rules:
            if phrase in text:
                return score
        return 0

    return max(
        milestones,
        key=priority,
        default=None,
    )

def _ordinal(number: int) -> str:
    """Formats an integer as an English ordinal number."""

    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {
            1: "st",
            2: "nd",
            3: "rd",
        }.get(number % 10, "th")

    return f"{number}{suffix}"

def generate_tournament_summary(
    tournament: dict[str, Any],
    participants: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    elo_changes: list[dict[str, Any]],
    *,
    winner_title_number: int | None = None,
    defending_champion: str | None = None,
    milestones: list[str] | None = None,
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
            f"{_ordinal(winner_title_number)} World Championship title."
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

    selected_milestone = _select_milestone(milestones)

    selected_sentences = sentences[:3]

    if selected_milestone:
        # Avoid repeating the title milestone when the recap already contains
        # a dedicated title sentence.
        title_already_mentioned = (
            "World Championship title" in selected_milestone
            and any(
                "World Championship title" in sentence
                for sentence in selected_sentences
            )
        )

        if not title_already_mentioned:
            selected_sentences.append(selected_milestone)

    if len(selected_sentences) < 4:
        for sentence in sentences[3:]:
            if sentence not in selected_sentences:
                selected_sentences.append(sentence)

            if len(selected_sentences) == 4:
                break

    return " ".join(selected_sentences)

def generate_tournament_preview(
    preview_data: dict[str, Any],
) -> str:
    """Generates an extended preview for the next tournament."""

    ranking = preview_data.get("ranking", [])
    titles = preview_data.get("titles", [])
    recent_form = preview_data.get("recent_form", [])
    defending_champion = preview_data.get("defending_champion")
    latest_tournament = preview_data.get("latest_tournament")
    featured_rivalry = preview_data.get("featured_rivalry")

    if not ranking:
        return "Not enough ranking data is available for a tournament preview."

    sentences: list[str] = []

    leader = ranking[0]
    leader_name = str(leader["player"])
    leader_elo = float(leader["elo"])

    if len(ranking) >= 2:
        second = ranking[1]
        second_name = str(second["player"])
        elo_gap = leader_elo - float(second["elo"])

        if elo_gap <= 15:
            sentences.append(
                f"{leader_name} enters the next World Championship as the "
                f"current Elo leader, but {second_name} trails by only "
                f"{elo_gap:.1f} points."
            )
        elif elo_gap <= 35:
            sentences.append(
                f"{leader_name} leads the current Elo ranking, with "
                f"{second_name} remaining within striking distance at "
                f"{elo_gap:.1f} points behind."
            )
        else:
            sentences.append(
                f"{leader_name} enters as the leading contender with an Elo "
                f"rating of {leader_elo:.1f}, holding a {elo_gap:.1f}-point "
                f"advantage over {second_name}."
            )
    else:
        sentences.append(
            f"{leader_name} enters as the current Elo leader with a rating "
            f"of {leader_elo:.1f}."
        )

    if defending_champion:
        if defending_champion == leader_name:
            sentences.append(
                f"The Elo leader is also the defending champion after "
                f"winning {latest_tournament or 'the previous tournament'}."
            )
        else:
            sentences.append(
                f"{defending_champion} returns as the defending champion "
                f"after winning {latest_tournament or 'the previous tournament'}."
            )

    title_contenders = [
        row
        for row in titles
        if int(row.get("titles", 0)) > 0
    ]

    if title_contenders:
        title_contenders.sort(
            key=lambda row: (
                -int(row["titles"]),
                str(row["player"]).casefold(),
            )
        )

        title_leader = title_contenders[0]
        top_titles = int(title_leader["titles"])

        tied_leaders = [
            row
            for row in title_contenders
            if int(row["titles"]) == top_titles
        ]

        if len(tied_leaders) >= 2:
            names = " and ".join(
                str(row["player"])
                for row in tied_leaders[:2]
            )
            sentences.append(
                f"The all-time title race is tied, with {names} holding "
                f"{top_titles} championships each."
            )
        elif len(title_contenders) >= 2:
            challenger = title_contenders[1]
            challenger_titles = int(challenger["titles"])

            if top_titles - challenger_titles == 1:
                sentences.append(
                    f"{title_leader['player']} leads the all-time title race "
                    f"with {top_titles} championships, but "
                    f"{challenger['player']} is only one title behind."
                )
            else:
                sentences.append(
                    f"{title_leader['player']} remains the most decorated "
                    f"player in the active field with {top_titles} titles."
                )
        else:
            sentences.append(
                f"{title_leader['player']} is the only active player with "
                f"a World Championship title."
            )

    eligible_form = [
        row
        for row in recent_form
        if int(row.get("matches", 0)) >= 5
        and row.get("winrate") is not None
    ]

    if eligible_form:
        best_form = max(
            eligible_form,
            key=lambda row: (
                float(row["winrate"]),
                int(row["wins"]),
            ),
        )

        best_form_name = str(best_form["player"])
        best_form_wins = int(best_form["wins"])
        best_form_matches = int(best_form["matches"])

        if best_form_name == leader_name:
            sentences.append(
                f"The favourite also carries the strongest recent set record, "
                f"winning {best_form_wins} of the last "
                f"{best_form_matches} matches."
            )
        else:
            sentences.append(
                f"{best_form_name} arrives in the strongest recent form, "
                f"having won {best_form_wins} of the last "
                f"{best_form_matches} recorded sets."
            )

    positive_trends = [
        row
        for row in recent_form
        if float(row.get("elo_change_last_three", 0.0)) > 0
    ]

    if positive_trends:
        strongest_trend = max(
            positive_trends,
            key=lambda row: float(row["elo_change_last_three"]),
        )

        trend_name = str(strongest_trend["player"])
        trend_gain = float(strongest_trend["elo_change_last_three"])

        already_featured = (
            eligible_form
            and trend_name == str(best_form["player"])
        )

        if not already_featured and trend_gain >= 15:
            rank_lookup = {
                str(row["player"]): int(row["rank"])
                for row in ranking
            }
            trend_rank = rank_lookup.get(trend_name)

            if trend_rank is not None and trend_rank > 3:
                sentences.append(
                    f"{trend_name} could be the main dark horse after gaining "
                    f"{trend_gain:.1f} Elo points across the last three "
                    f"tournaments."
                )
            else:
                sentences.append(
                    f"{trend_name} has also been trending upward, gaining "
                    f"{trend_gain:.1f} Elo points across the last three "
                    f"tournaments."
                )

    form_by_player = {
        str(row["player"]): row
        for row in eligible_form
    }

    for contender in ranking[:3]:
        contender_name = str(contender["player"])
        form = form_by_player.get(contender_name)

        if not form:
            continue

        winrate = float(form["winrate"])
        losses = int(form["losses"])
        matches = int(form["matches"])
        elo_change = float(form.get("elo_change_last_three", 0.0))

        if winrate < 50.0 and (
            losses >= 6
            or elo_change <= -20.0
        ):
            sentences.append(
                f"{contender_name} remains a major contender but enters in "
                f"poor form, having lost {losses} of the last "
                f"{matches} recorded sets."
            )
            break

    if featured_rivalry:
        player_a = str(featured_rivalry["player_a"])
        player_b = str(featured_rivalry["player_b"])
        wins_a = int(featured_rivalry["wins_a"])
        wins_b = int(featured_rivalry["wins_b"])

        if wins_a == wins_b:
            sentences.append(
                f"One rivalry to watch is {player_a} against {player_b}, "
                f"with their all-time series tied at {wins_a}–{wins_b}."
            )
        elif wins_a > wins_b:
            sentences.append(
                f"One rivalry to watch is {player_a} against {player_b}, "
                f"with {player_a} leading the all-time series "
                f"{wins_a}–{wins_b}."
            )
        else:
            sentences.append(
                f"One rivalry to watch is {player_a} against {player_b}, "
                f"with {player_b} leading the all-time series "
                f"{wins_b}–{wins_a}."
            )

    if len(ranking) >= 3:
        top_three_gap = (
            float(ranking[0]["elo"])
            - float(ranking[2]["elo"])
        )

        if top_three_gap <= 40:
            sentences.append(
                "With the leading contenders still closely grouped in Elo, "
                "the next championship appears wide open."
            )
        else:
            sentences.append(
                "The chasing field will need a strong performance to close "
                "the gap to the current frontrunners."
            )

    return " ".join(sentences)