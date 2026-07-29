"""Pure Group Stage standings and project-specific tie-break rules."""

from __future__ import annotations

from typing import Any


GROUP_MATCH_PENDING = "pending"
GROUP_MATCH_COMPLETED = "completed"
GROUP_MATCH_FORFEIT = "forfeit"
GROUP_MATCH_CANCELLED = "cancelled"

VALID_GROUP_MATCH_STATUSES = {
    GROUP_MATCH_PENDING,
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
    GROUP_MATCH_CANCELLED,
}

DECIDED_GROUP_MATCH_STATUSES = {
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
}


def _percentage(
    numerator: int,
    denominator: int,
) -> float | None:
    """Return a percentage or ``None`` when no attempts exist."""

    if denominator <= 0:
        return None

    return numerator / denominator * 100.0


def _mini_table_wins(
    player_ids: set[str],
    matches: list[dict[str, Any]],
) -> dict[str, int]:
    """Count Set wins only in decided matches between tied players."""

    wins = {
        player_id: 0
        for player_id in player_ids
    }

    for match in matches:
        if match["status"] not in DECIDED_GROUP_MATCH_STATUSES:
            continue

        player_1_id = str(match["player_1_id"])
        player_2_id = str(match["player_2_id"])

        if (
            player_1_id not in player_ids
            or player_2_id not in player_ids
        ):
            continue

        winner_id = match["winner_id"]

        if winner_id is not None:
            wins[str(winner_id)] += 1

    return wins


def _have_equal_game_opportunities(
    tied_players: list[dict[str, Any]],
    matches: list[dict[str, Any]],
) -> bool:
    """
    Return whether tied players had the same real chances to record Games.

    A normally completed Set counts as one score-bearing opportunity,
    regardless of whether it ended 2-0 or 2-1. Forfeits, cancelled Sets and
    completed Sets without a usable score do not count as such an opportunity.
    """

    opportunity_counts = {
        str(player["player_id"]): 0
        for player in tied_players
    }

    for match in matches:
        player_1_id = str(match["player_1_id"])
        player_2_id = str(match["player_2_id"])

        if (
            str(match["status"]) != GROUP_MATCH_COMPLETED
            or match.get("player_1_score") is None
            or match.get("player_2_score") is None
        ):
            continue

        if player_1_id in opportunity_counts:
            opportunity_counts[player_1_id] += 1

        if player_2_id in opportunity_counts:
            opportunity_counts[player_2_id] += 1

    return len(set(opportunity_counts.values())) <= 1


def _resolve_group_tie(
    tied_players: list[dict[str, Any]],
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Resolve equal Set-win totals using the permanent tournament rules.

    The mini-table contains only matches between the tied players. When it
    creates smaller tied subgroups, each subgroup is resolved recursively.
    If the mini-table cannot separate the players, absolute Games won precede
    Game Win Percentage when the players had equal scoring opportunities.
    With unequal opportunities, the normalized percentage comes first.
    """

    if len(tied_players) <= 1:
        return tied_players

    tied_player_ids = {
        str(player["player_id"])
        for player in tied_players
    }

    mini_wins = _mini_table_wins(
        tied_player_ids,
        matches,
    )

    mini_win_values = {
        mini_wins[str(player["player_id"])]
        for player in tied_players
    }

    if len(mini_win_values) > 1:
        groups_by_mini_wins: dict[
            int,
            list[dict[str, Any]],
        ] = {}

        for player in tied_players:
            player_id = str(player["player_id"])
            mini_win_count = mini_wins[player_id]

            player_with_tiebreak = {
                **player,
                "mini_table_wins": mini_win_count,
            }

            groups_by_mini_wins.setdefault(
                mini_win_count,
                [],
            ).append(player_with_tiebreak)

        resolved: list[dict[str, Any]] = []

        for mini_win_count in sorted(
            groups_by_mini_wins,
            reverse=True,
        ):
            subgroup = groups_by_mini_wins[
                mini_win_count
            ]

            if len(subgroup) > 1:
                subgroup = _resolve_group_tie(
                    subgroup,
                    matches,
                )

            resolved.extend(subgroup)

        return resolved

    equal_game_opportunities = _have_equal_game_opportunities(
        tied_players,
        matches,
    )

    def percentage_sort_value(player: dict[str, Any]) -> float:
        percentage = player["game_win_percentage"]
        return float(percentage) if percentage is not None else -1.0

    if equal_game_opportunities:
        return sorted(
            tied_players,
            key=lambda player: (
                -int(player["games_won"]),
                -percentage_sort_value(player),
                -float(player["initial_elo"]),
                int(player["initial_seed"]),
                str(player["player"]).casefold(),
            ),
        )

    return sorted(
        tied_players,
        key=lambda player: (
            -percentage_sort_value(player),
            -int(player["games_won"]),
            -float(player["initial_elo"]),
            int(player["initial_seed"]),
            str(player["player"]).casefold(),
        ),
    )


def calculate_group_standings(
    members: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    elo_by_player_id: dict[str, float],
) -> dict[str, Any]:
    """
    Calculate one group's ordered table and completion counters.

    A Forfeit contributes one decided Set but no Games. Cancelled matches do
    not affect player records and count as resolved for workflow completion;
    only Pending matches keep the Group Stage incomplete.
    """

    standings: dict[str, dict[str, Any]] = {}

    for member in members:
        player_id = str(member["player_id"])

        standings[player_id] = {
            "player_id": player_id,
            "player": str(member["player"]),
            "initial_seed": int(member["initial_seed"]),
            "initial_elo": elo_by_player_id.get(
                player_id,
                1000.0,
            ),
            "sets_played": 0,
            "sets_won": 0,
            "sets_lost": 0,
            "games_won": 0,
            "games_lost": 0,
            "mini_table_wins": None,
        }

    for match in matches:
        status = str(match["status"])

        if status not in DECIDED_GROUP_MATCH_STATUSES:
            continue

        player_1_id = str(match["player_1_id"])
        player_2_id = str(match["player_2_id"])
        winner_id = str(match["winner_id"])

        player_1 = standings[player_1_id]
        player_2 = standings[player_2_id]

        player_1["sets_played"] += 1
        player_2["sets_played"] += 1

        if winner_id == player_1_id:
            player_1["sets_won"] += 1
            player_2["sets_lost"] += 1
        else:
            player_2["sets_won"] += 1
            player_1["sets_lost"] += 1

        if (
            status == GROUP_MATCH_COMPLETED
            and match.get("player_1_score") is not None
            and match.get("player_2_score") is not None
        ):
            player_1_score = int(match["player_1_score"])
            player_2_score = int(match["player_2_score"])

            player_1["games_won"] += player_1_score
            player_1["games_lost"] += player_2_score
            player_2["games_won"] += player_2_score
            player_2["games_lost"] += player_1_score

    standing_rows = list(standings.values())

    for player in standing_rows:
        player["set_win_percentage"] = _percentage(
            int(player["sets_won"]),
            int(player["sets_played"]),
        )

        total_games = (
            int(player["games_won"])
            + int(player["games_lost"])
        )

        player["game_win_percentage"] = _percentage(
            int(player["games_won"]),
            total_games,
        )

    # Overall Set wins are the primary criterion. Each tied Set-win group is
    # isolated before applying the mini-table and fallback rules.
    players_by_set_wins: dict[
        int,
        list[dict[str, Any]],
    ] = {}

    for player in standing_rows:
        players_by_set_wins.setdefault(
            int(player["sets_won"]),
            [],
        ).append(player)

    ordered_players: list[dict[str, Any]] = []

    for set_win_count in sorted(
        players_by_set_wins,
        reverse=True,
    ):
        tied_players = players_by_set_wins[
            set_win_count
        ]

        if len(tied_players) > 1:
            tied_players = _resolve_group_tie(
                tied_players,
                matches,
            )

        ordered_players.extend(tied_players)

    for placement, player in enumerate(
        ordered_players,
        start=1,
    ):
        player["placement"] = placement

    total_matches = len(matches)
    decided_matches = sum(
        str(match["status"]) in DECIDED_GROUP_MATCH_STATUSES
        for match in matches
    )
    cancelled_matches = sum(
        str(match["status"]) == GROUP_MATCH_CANCELLED
        for match in matches
    )
    pending_matches = sum(
        str(match["status"]) == GROUP_MATCH_PENDING
        for match in matches
    )

    return {
        "standings": ordered_players,
        "total_matches": total_matches,
        "decided_matches": decided_matches,
        "cancelled_matches": cancelled_matches,
        "pending_matches": pending_matches,
        "complete": pending_matches == 0,
    }
