#!/usr/bin/env python3
"""Implementations for rule-based Smash World Championship narratives."""

from __future__ import annotations

from typing import Any

from narrative_common import (
    _select_preview_sentences,
    _select_tournament_sentences,
    _sentence_count,
    _stable_variant,
)


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


def _rivalry_trajectory_sentence(
    history: list[dict[str, Any]],
    player_a: str,
    player_b: str,
) -> str | None:
    """Describe a comeback or repeated changes of control in the series."""

    wins = {player_a: 0, player_b: 0}
    largest_deficit = {player_a: 0, player_b: 0}
    previous_leader: str | None = None
    lead_changes = 0

    for meeting in history:
        winner = str(meeting["winner"])
        wins[winner] += 1
        largest_deficit[player_a] = max(
            largest_deficit[player_a],
            wins[player_b] - wins[player_a],
        )
        largest_deficit[player_b] = max(
            largest_deficit[player_b],
            wins[player_a] - wins[player_b],
        )
        leader = (
            player_a
            if wins[player_a] > wins[player_b]
            else player_b
            if wins[player_b] > wins[player_a]
            else None
        )
        if (
            leader is not None
            and previous_leader is not None
            and leader != previous_leader
        ):
            lead_changes += 1
        if leader is not None:
            previous_leader = leader

    final_leader = (
        player_a
        if wins[player_a] > wins[player_b]
        else player_b
        if wins[player_b] > wins[player_a]
        else None
    )
    if final_leader and largest_deficit[final_leader] >= 2:
        return (
            f"The series has changed direction over time: {final_leader} "
            f"once trailed by {largest_deficit[final_leader]} sets before "
            f"moving in front."
        )
    if lead_changes >= 2:
        return (
            f"Control of the rivalry has changed hands {lead_changes} times, "
            f"showing how often its direction has shifted."
        )
    return None


def _rivalry_scoreline_sentence(
    history: list[dict[str, Any]],
) -> str | None:
    """Summarize whether known set scores tend to be close or decisive."""

    known_scores = []
    for meeting in history:
        score = meeting.get("score")
        if not score or "-" not in str(score) or meeting.get("walkover"):
            continue
        left, right = str(score).split("-", 1)
        try:
            known_scores.append((int(left), int(right)))
        except ValueError:
            continue

    if len(known_scores) < 4:
        return None

    full_distance = sum(
        abs(left - right) == 1 and max(left, right) in {2, 3}
        for left, right in known_scores
    )
    sweeps = sum(min(left, right) == 0 for left, right in known_scores)

    if full_distance / len(known_scores) >= 0.5:
        return (
            f"The scorelines underline that competitiveness: "
            f"{full_distance} of {len(known_scores)} recorded sets went "
            f"the full distance."
        )
    if sweeps / len(known_scores) >= 0.5:
        return (
            f"The individual meetings have often been decisive, with "
            f"{sweeps} sweeps across {len(known_scores)} known scores."
        )
    return (
        f"Across {len(known_scores)} known scores, the rivalry has mixed "
        f"close contests with more decisive results."
    )


def _rivalry_stage_sentence(
    history: list[dict[str, Any]],
    player_a: str,
    player_b: str,
) -> str | None:
    """Describe a meaningful split between Group and Bracket results."""

    group = {player_a: 0, player_b: 0}
    bracket = {player_a: 0, player_b: 0}
    for meeting in history:
        target = (
            group
            if str(meeting.get("stage") or "") in {"group", "group_stage"}
            else bracket
        )
        target[str(meeting["winner"])] += 1

    if sum(group.values()) < 2 or sum(bracket.values()) < 2:
        return None
    group_leader = max(group, key=group.get)
    bracket_leader = max(bracket, key=bracket.get)
    if group[group_leader] == group[player_b if group_leader == player_a else player_a]:
        return None
    if bracket[bracket_leader] == bracket[player_b if bracket_leader == player_a else player_a]:
        return None
    if group_leader != bracket_leader:
        return (
            f"Tournament stage has mattered: {group_leader} leads the Group "
            f"Stage meetings {group[group_leader]}–{min(group.values())}, "
            f"while {bracket_leader} leads in the Bracket "
            f"{bracket[bracket_leader]}–{min(bracket.values())}."
        )
    return None


def _rivalry_revenge_sentence(
    history: list[dict[str, Any]],
) -> str | None:
    """Find the latest same-tournament rematch won by the earlier loser."""

    by_tournament: dict[str, list[dict[str, Any]]] = {}
    for meeting in history:
        tournament = str(meeting.get("tournament") or "")
        if tournament:
            by_tournament.setdefault(tournament, []).append(meeting)

    for tournament, meetings in reversed(list(by_tournament.items())):
        if len(meetings) >= 2:
            first_winner = meetings[0].get("winner")
            last_winner = meetings[-1].get("winner")
            if first_winner and last_winner and first_winner != last_winner:
                return (
                    f"At {tournament}, {last_winner} avenged an earlier loss "
                    f"by winning the rematch later in the event."
                )
    return None


def _select_rivalry_sentences(sentences: list[str]) -> list[str]:
    """Select the strongest rivalry angles and retain narrative order."""

    if len(sentences) <= 8:
        return sentences

    priorities = {
        "Most recently": 100,
        "changed direction": 95,
        "changed hands": 90,
        "Recent momentum": 90,
        "Recent results": 90,
        "avenged an earlier loss": 85,
        "Tournament stage has mattered": 80,
        "scorelines": 75,
        "individual meetings": 75,
        "known scores": 70,
        "longest streak": 65,
        "game record": 60,
        "decided sets": 50,
    }
    ranked = sorted(
        enumerate(sentences[1:], start=1),
        key=lambda item: max(
            (
                score
                for phrase, score in priorities.items()
                if phrase in item[1]
            ),
            default=40,
        ),
        reverse=True,
    )[:7]
    selected_indexes = {0, *(index for index, _ in ranked)}
    return [
        sentence
        for index, sentence in enumerate(sentences)
        if index in selected_indexes
    ]


def _overall_summary(
    player_a: str,
    player_b: str,
    wins_a: int,
    wins_b: int,
) -> str:
    """Builds the all-time head-to-head sentence."""

    seed = f"{player_a}|{player_b}|overall"

    if wins_a == wins_b:
        return _stable_variant(
            seed,
            f"The all-time series between {player_a} and {player_b} "
            f"is tied at {wins_a}–{wins_b}.",
            f"Nothing separates {player_a} and {player_b} in the set "
            f"record, which stands at {wins_a}–{wins_b}.",
            f"After their recorded meetings, {player_a} and {player_b} "
            f"remain level at {wins_a}–{wins_b}.",
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
        return _stable_variant(
            seed,
            f"{leader} narrowly leads the all-time series against {trailer} "
            f"{leader_wins}–{trailer_wins}.",
            f"Only one set separates the two players, with {leader} ahead "
            f"of {trailer} {leader_wins}–{trailer_wins}.",
            f"The head-to-head remains finely balanced, although {leader} "
            f"holds a {leader_wins}–{trailer_wins} edge over {trailer}.",
        )

    return _stable_variant(
        seed,
        f"{leader} leads the all-time series against {trailer} "
        f"{leader_wins}–{trailer_wins}.",
        f"The historical advantage belongs to {leader}, who holds a "
        f"{leader_wins}–{trailer_wins} record against {trailer}.",
        f"Across all recorded sets, {leader} has built a "
        f"{leader_wins}–{trailer_wins} lead over {trailer}.",
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
        return _stable_variant(
            f"{player_a}|{player_b}|unplayed",
            f"{player_a} and {player_b} have not faced each other yet.",
            f"There is no recorded set between {player_a} and {player_b} yet.",
        )

    if len(history) == 1:
        winner = str(history[0]["winner"])
        return _stable_variant(
            f"{player_a}|{player_b}|single",
            f"{player_a} and {player_b} have faced each other only once, "
            f"with {winner} winning the set.",
            f"The rivalry currently consists of a single set, won by "
            f"{winner}.",
        )

    sentences = [
        _overall_summary(
            player_a,
            player_b,
            wins_a,
            wins_b,
        )
    ]

    decided_sets = wins_a + wins_b
    set_margin = abs(wins_a - wins_b)
    set_leader = None
    if wins_a > wins_b:
        set_leader = player_a
    elif wins_b > wins_a:
        set_leader = player_b

    if decided_sets >= 6:
        if set_margin <= 2:
            sentences.append(
                _stable_variant(
                    f"{player_a}|{player_b}|balanced",
                    f"Even after {decided_sets} decided sets, neither player "
                    f"has been able to create lasting separation.",
                    f"The rivalry has stayed competitive across "
                    f"{decided_sets} decided sets, with every advantage "
                    f"remaining vulnerable.",
                    f"Over {decided_sets} decided sets, the matchup has "
                    f"consistently resisted a clear long-term favourite.",
                )
            )
        elif set_leader is not None and max(wins_a, wins_b) / decided_sets >= 0.7:
            sentences.append(
                f"Across {decided_sets} decided sets, {set_leader} has "
                f"established clear control of the matchup."
            )
        else:
            sentences.append(
                f"The {decided_sets} recorded meetings have produced a "
                f"competitive rivalry despite the current gap."
            )

    for storyline in (
        _rivalry_trajectory_sentence(history, player_a, player_b),
        _rivalry_stage_sentence(history, player_a, player_b),
        _rivalry_scoreline_sentence(history),
    ):
        if storyline:
            sentences.append(storyline)

    games_a = int(h2h["player_a"].get("games_won", 0))
    games_b = int(h2h["player_b"].get("games_won", 0))
    known_scores = int(h2h.get("matches_with_known_score", 0))
    if known_scores >= 3 and games_a + games_b > 0:
        game_margin = abs(games_a - games_b)
        game_leader = None
        if games_a > games_b:
            game_leader = player_a
        elif games_b > games_a:
            game_leader = player_b

        if game_margin <= max(2, round((games_a + games_b) * 0.1)):
            sentences.append(
                f"That balance is reflected in a game record of "
                f"{games_a}–{games_b} from {player_a}'s perspective."
            )
        else:
            leader_games = max(games_a, games_b)
            trailer_games = min(games_a, games_b)
            if game_leader == set_leader:
                sentences.append(
                    f"The game record reinforces that advantage, with "
                    f"{game_leader} ahead {leader_games}–{trailer_games}."
                )
            else:
                sentences.append(
                    f"The game record tells a different story: "
                    f"{game_leader} leads {leader_games}–{trailer_games} "
                    f"despite trailing in sets."
                )

    streak_winner, streak_length = _current_streak(history)
    longest_streaks = {player_a: 0, player_b: 0}
    running_winner: str | None = None
    running_length = 0
    for meeting in history:
        winner = str(meeting["winner"])
        if winner == running_winner:
            running_length += 1
        else:
            running_winner = winner
            running_length = 1
        longest_streaks[winner] = max(
            longest_streaks[winner],
            running_length,
        )
    historical_streak_leader = max(
        longest_streaks,
        key=longest_streaks.get,
    )
    historical_streak = longest_streaks[historical_streak_leader]
    if historical_streak >= 3 and historical_streak > streak_length:
        sentences.append(
            f"The longest streak in the rivalry belongs to "
            f"{historical_streak_leader}, who once won "
            f"{historical_streak} consecutive sets."
        )

    recent_leader = None
    if streak_winner is not None and streak_length >= 2:
        recent_leader = streak_winner
        sentences.append(
            _stable_variant(
                f"{player_a}|{player_b}|momentum",
                f"Recent momentum belongs to {streak_winner}, who has won "
                f"the last {streak_length} sets.",
                f"Recent momentum has moved toward {streak_winner} after "
                f"{streak_length} consecutive set wins.",
                f"Recent momentum now favours {streak_winner}, currently "
                f"on a {streak_length}-set run in this matchup.",
            )
        )
    else:
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
                recent_wins = 0

            if recent_leader is not None:
                transition = (
                    "Recent results have shifted the picture, with"
                    if set_leader is not None and recent_leader != set_leader
                    else "Recent form also favours"
                )
                sentences.append(
                    f"{transition} {recent_leader} winning "
                    f"{recent_wins} of the last five sets."
                )

    revenge_storyline = _rivalry_revenge_sentence(history)
    if revenge_storyline:
        sentences.append(revenge_storyline)

    last_match = h2h.get("last_match")
    if last_match and last_match.get("winner"):
        last_winner = str(last_match["winner"])
        last_score = last_match.get("score")
        if last_score and "-" in str(last_score):
            score_a, score_b = str(last_score).split("-", 1)
            if last_winner == player_b:
                last_score = f"{score_b}–{score_a}"
            else:
                last_score = f"{score_a}–{score_b}"
        score_text = f" {last_score}" if last_score else ""
        tournament = str(
            last_match.get("tournament") or "their latest meeting"
        )
        sentences.append(
            _stable_variant(
                f"{player_a}|{player_b}|latest",
                f"Most recently, {last_winner} won{score_text} at "
                f"{tournament}.",
                f"Most recently, their meeting at {tournament} ended with "
                f"a {last_winner}{score_text} victory.",
                f"Most recently, {last_winner} took the set at {tournament}"
                f"{f' by {last_score}' if last_score else ''}.",
            )
        )

    if recent_leader is not None and set_leader is not None:
        if recent_leader != set_leader:
            sentences.append(
                f"That recent swing runs against the longer-term record "
                f"and has added a new layer to the rivalry."
            )
        elif set_margin <= 2:
            sentences.append(
                f"With the historical margin still narrow, that run gives "
                f"{recent_leader} the clearest current advantage."
            )

    return " ".join(_select_rivalry_sentences(sentences))


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
    featured_rivalry = insights.get("featured_rivalry")
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
        if appearances == 0:
            opening = (
                f"{player} has no recorded tournament appearances yet."
            )
        else:
            opening = (
                f"{player} has made one recorded tournament appearance "
                f"so far."
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

    sentences = [opening, performance]

    if peak_elo <= current_elo + 0.05:
        sentences.append(
            "Their current rating also matches their career-high Elo."
        )
    else:
        peak_gap = peak_elo - current_elo
        sentences.append(
            f"Their career-high Elo is {peak_elo:.1f}, "
            f"which is {peak_gap:.1f} points above their current rating."
        )

    if titles == 0 and best_result is not None:
        placement = int(best_result)
        sentences.append(
            f"Their best tournament finish so far is "
            f"{_ordinal(placement)} place."
        )

    if longest_win_streak >= 3:
        sentences.append(
            f"Their longest winning streak stands at "
            f"{longest_win_streak} sets."
        )

    opponent_storyline: str | None = None
    if (
        nemesis
        and int(nemesis.get("matches", 0)) >= 3
        and float(nemesis.get("winrate", 100.0)) < 35.0
    ):
        opponent_storyline = (
            f"Their toughest recorded opponent has been "
            f"{nemesis['opponent']}, against whom they hold a "
            f"{nemesis['wins']}–{nemesis['losses']} record."
        )
    elif (
        featured_rivalry
        and int(featured_rivalry.get("matches", 0)) >= 3
    ):
        opponent_storyline = (
            f"Their most established rivalry is with "
            f"{featured_rivalry['opponent']}, with a "
            f"{featured_rivalry['wins']}–{featured_rivalry['losses']} "
            f"record across {featured_rivalry['matches']} sets."
        )

    if opponent_storyline:
        sentences.append(opponent_storyline)

    if best_elo_event:
        tournament = best_elo_event.get("tournament")
        change = float(best_elo_event.get("elo_change", 0.0))

        if tournament and change > 0:
            sentences.append(
                f"Their biggest Elo gain came at {tournament}, "
                f"with an increase of {change:.1f} points."
            )

    return " ".join(sentences[:6])

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
    story_context: dict[str, Any] | None = None,
) -> str:
    """Generates a rule-based recap for one tournament."""

    tournament_number = int(tournament["tournament_number"])
    tournament_name = f"WC {tournament_number:02d}"
    winner = str(tournament.get("winner") or "An unknown player")
    story_context = story_context or {}

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

    title_streak = int(story_context.get("winner_title_streak") or 0)
    previous_title = story_context.get("previous_title")
    if title_streak >= 2:
        sentences.append(
            f"It was {winner}'s {_ordinal(title_streak)} consecutive "
            f"championship."
        )
    elif (
        winner_title_number
        and winner_title_number > 1
        and previous_title
        and int(previous_title["tournament_number"]) < tournament_number - 1
    ):
        previous_title_name = (
            f"WC {int(previous_title['tournament_number']):02d}"
        )
        sentences.append(
            f"It was {winner}'s first title since {previous_title_name}, "
            f"ending a run of tournaments without a championship."
        )

    winner_previous_placement = story_context.get(
        "winner_previous_placement"
    )
    if (
        winner_previous_placement
        and winner_previous_placement.get("placement") is not None
        and int(winner_previous_placement["placement"]) > 1
    ):
        previous_number = int(
            winner_previous_placement["tournament_number"]
        )
        previous_placement = int(winner_previous_placement["placement"])
        sentences.append(
            f"The win completed a rise from {_ordinal(previous_placement)} "
            f"place at {f'WC {previous_number:02d}'}, {winner}'s previous "
            f"appearance."
        )

    podium_streak = int(story_context.get("winner_podium_streak") or 0)
    if podium_streak >= 3:
        sentences.append(
            f"The result also extended {winner}'s podium streak to "
            f"{podium_streak} consecutive appearances."
        )

    repeat_final = story_context.get("repeat_final")
    if repeat_final and runner_up:
        previous_final_name = (
            f"WC {int(repeat_final['previous_tournament']):02d}"
        )
        if str(repeat_final.get("previous_winner")) == winner:
            sentences.append(
                f"The same finalists had met at {previous_final_name}, and "
                f"{winner} prevailed again in the rematch."
            )
        else:
            sentences.append(
                f"The same finalists had met at {previous_final_name}, but "
                f"this time {winner} reversed the outcome."
            )

    defending_result = story_context.get("defending_champion_result")
    if (
        defending_champion
        and defending_champion != winner
        and defending_result
        and defending_result.get("placement") is not None
    ):
        sentences.append(
            f"Defending champion {defending_champion}'s title defence ended "
            f"in {_ordinal(int(defending_result['placement']))} place."
        )

    # Main tournament performance
    wins_leader, wins_total = _most_match_wins(matches)

    if wins_leader and wins_total:
        win_label = "set win" if wins_total == 1 else "set wins"
        if wins_leader == winner:
            sentences.append(
                f"The champion also led the field with "
                f"{wins_total} {win_label}."
            )
        else:
            sentences.append(
                f"{wins_leader} led the field with "
                f"{wins_total} {win_label}."
            )

    group_matches = [
        match
        for match in matches
        if str(match.get("stage") or "") in {"group", "group_stage"}
        and match.get("winner")
    ]
    if group_matches:
        group_records: dict[str, list[int]] = {}
        for match in group_matches:
            player_1 = str(match.get("player_1") or "")
            player_2 = str(match.get("player_2") or "")
            match_winner = str(match["winner"])
            for player_name in (player_1, player_2):
                if not player_name:
                    continue
                record = group_records.setdefault(player_name, [0, 0])
                if player_name == match_winner:
                    record[0] += 1
                else:
                    record[1] += 1
        unbeaten = [
            (player_name, record[0])
            for player_name, record in group_records.items()
            if record[0] >= 2 and record[1] == 0
        ]
        if unbeaten:
            unbeaten_player, unbeaten_wins = max(
                unbeaten,
                key=lambda item: (
                    item[0] == winner,
                    item[1],
                ),
            )
            sentences.append(
                f"{unbeaten_player} completed the Group Stage unbeaten "
                f"with a {unbeaten_wins}–0 set record."
            )

    seed_performances = []
    for participant in participants:
        seed = participant.get("seed")
        placement = participant.get("placement")
        if seed is None or placement is None:
            continue
        improvement = int(seed) - int(placement)
        if improvement >= 2:
            seed_performances.append(
                (
                    improvement,
                    str(participant["player"]),
                    int(seed),
                    int(placement),
                )
            )
    if seed_performances:
        improvement, player_name, seed, placement = max(seed_performances)
        sentences.append(
            f"{player_name} produced the strongest result relative to the "
            f"initial seed, climbing from #{seed} to "
            f"{_ordinal(placement)} place."
        )

    biggest_improvement = story_context.get("biggest_placement_improvement")
    if (
        biggest_improvement
        and str(biggest_improvement.get("player")) != winner
    ):
        improved_player = str(biggest_improvement["player"])
        previous_number = int(biggest_improvement["previous_tournament"])
        previous_placement = int(biggest_improvement["previous_placement"])
        current_placement = int(biggest_improvement["current_placement"])
        sentences.append(
            f"{improved_player} made the largest jump from a previous "
            f"appearance, improving from {_ordinal(previous_placement)} at "
            f"WC {previous_number:02d} to {_ordinal(current_placement)}."
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
                f"{biggest_gain['Players']} made the biggest Elo gain, "
                f"adding {gain:.1f} points"
            )

            if loss < 0:
                elo_sentence += (
                    f", while {biggest_loss['Players']} had the largest "
                    f"drop at {abs(loss):.1f} points."
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
    recorded_set_label = "set" if match_count == 1 else "sets"

    context_sentence = (
        f"{participant_count} players competed across "
        f"{match_count} recorded {recorded_set_label}"
    )

    if close_sets:
        set_word = "set" if close_sets == 1 else "sets"
        verb = "was" if close_sets == 1 else "were"
        context_sentence += (
            f"; {close_sets} {set_word} {verb} decided by a single game"
        )

    if third_place:
        connector = ", while" if close_sets else ";"
        context_sentence += f"{connector} {third_place} finished third"

    sentences.append(context_sentence + ".")

    selected_milestone = _select_milestone(milestones)
    if selected_milestone:
        # Avoid repeating the title milestone when the recap already contains
        # a dedicated title sentence.
        title_already_mentioned = (
            "World Championship title" in selected_milestone
            and any(
                "World Championship title" in sentence
                for sentence in sentences
            )
        )

        if not title_already_mentioned:
            sentences.append(selected_milestone)

    return " ".join(_select_tournament_sentences(sentences))

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
                f"{leader_name} also carries the strongest recent set record, "
                f"winning {best_form_wins} of the last "
                f"{best_form_matches} recorded sets."
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

    active_winning_streaks = [
        row
        for row in recent_form
        if row.get("streak_type") == "win"
        and int(row.get("streak", 0)) >= 3
    ]
    if active_winning_streaks:
        streak_leader = max(
            active_winning_streaks,
            key=lambda row: int(row["streak"]),
        )
        sentences.append(
            f"{streak_leader['player']} carries the longest active winning "
            f"streak into the tournament at "
            f"{int(streak_leader['streak'])} sets."
        )

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

        last_match = featured_rivalry.get("last_match")
        if last_match and last_match.get("winner"):
            last_winner = str(last_match["winner"])
            last_tournament = str(
                last_match.get("tournament") or "their previous meeting"
            )
            last_score = last_match.get("score")
            score_text = f" {last_score}" if last_score else ""
            sentences.append(
                f"Their latest meeting came at {last_tournament}, where "
                f"{last_winner} won{score_text}."
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

    return " ".join(_select_preview_sentences(sentences))
