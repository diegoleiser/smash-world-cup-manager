"""Head-to-head statistics and terminal presentation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from smash_stats.common import _format_percent, _percentage
from smash_stats.database import DEFAULT_DB_PATH, connect_db, resolve_player


def get_head_to_head(
    player_a_reference: str,
    player_b_reference: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """
    Calculates the head-to-head record between two players.

    Unknown scores count toward the match record when a winner is known, but not toward the game record.
    """

    with connect_db(db_path) as connection:
        player_a = resolve_player(connection, player_a_reference)
        player_b = resolve_player(connection, player_b_reference)

        player_a_id = player_a["player_id"]
        player_b_id = player_b["player_id"]

        if player_a_id == player_b_id:
            raise ValueError("A head-to-head comparison requires two different players.")

        matches = connection.execute(
            """
            SELECT
                m.match_id,
                m.tournament_id,
                t.tournament_number,
                t.tournament_date,
                m.stage,
                m.bracket_side,
                m.round_label,
                m.player_1_id,
                m.player_2_id,
                m.winner_id,
                m.player_1_score,
                m.player_2_score,
                m.score_known,
                m.walkover,
                m.completed_at,
                m.suggested_play_order
            FROM matches AS m
            JOIN tournaments AS t
              ON t.tournament_id = m.tournament_id
            WHERE
                (m.player_1_id = ? AND m.player_2_id = ?)
                OR
                (m.player_1_id = ? AND m.player_2_id = ?)
            ORDER BY
                t.tournament_date,
                t.tournament_number,
                CASE WHEN m.completed_at IS NULL THEN 1 ELSE 0 END,
                m.completed_at,
                CASE WHEN m.suggested_play_order IS NULL THEN 1 ELSE 0 END,
                m.suggested_play_order,
                m.match_id
            """,
            (
                player_a_id,
                player_b_id,
                player_b_id,
                player_a_id,
            ),
        ).fetchall()

    player_a_wins = 0
    player_b_wins = 0
    undecided_matches = 0
    player_a_games = 0
    player_b_games = 0
    matches_with_known_score = 0
    match_history: list[dict[str, Any]] = []

    for row in matches:
        if row["winner_id"] == player_a_id:
            player_a_wins += 1
        elif row["winner_id"] == player_b_id:
            player_b_wins += 1
        else:
            undecided_matches += 1

        score_known = bool(row["score_known"])
        score_a: int | None = None
        score_b: int | None = None

        player_1_score = row["player_1_score"]
        player_2_score = row["player_2_score"]

        if (
            score_known
            and player_1_score is not None
            and player_2_score is not None
            and not row["walkover"]
        ):
            if row["player_1_id"] == player_a_id:
                score_a = int(player_1_score)
                score_b = int(player_2_score)
            else:
                score_a = int(player_2_score)
                score_b = int(player_1_score)

            player_a_games += score_a
            player_b_games += score_b
            matches_with_known_score += 1

        winner_name = None
        if row["winner_id"] == player_a_id:
            winner_name = player_a["display_name"]
        elif row["winner_id"] == player_b_id:
            winner_name = player_b["display_name"]

        score_text = (
            f"{score_a}-{score_b}"
            if score_a is not None and score_b is not None
            else None
        )

        match_history.append(
            {
                "match_id": row["match_id"],
                "tournament_id": row["tournament_id"],
                "tournament": f"WM {row['tournament_number']:02d}",
                "tournament_number": row["tournament_number"],
                "date": row["tournament_date"],
                "stage": row["stage"],
                "bracket_side": row["bracket_side"],
                "round_label": row["round_label"],
                "winner": winner_name,
                "winner_id": row["winner_id"],
                "score": score_text,
                "score_known": score_text is not None,
                "walkover": bool(row["walkover"]),
            }
        )

    decided_matches = player_a_wins + player_b_wins
    games_total = player_a_games + player_b_games
    last_match = match_history[-1] if match_history else None

    return {
        "player_a": {
            "player_id": player_a_id,
            "player": player_a["display_name"],
            "wins": player_a_wins,
            "winrate": _percentage(player_a_wins, decided_matches),
            "games_won": player_a_games,
            "game_winrate": _percentage(player_a_games, games_total),
        },
        "player_b": {
            "player_id": player_b_id,
            "player": player_b["display_name"],
            "wins": player_b_wins,
            "winrate": _percentage(player_b_wins, decided_matches),
            "games_won": player_b_games,
            "game_winrate": _percentage(player_b_games, games_total),
        },
        "matches": len(matches),
        "decided_matches": decided_matches,
        "undecided_matches": undecided_matches,
        "matches_with_known_score": matches_with_known_score,
        "last_match": last_match,
        "history": match_history,
    }



def get_all_head_to_heads(
    player_reference: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """
    Calculates a player’s head-to-head record against all previous opponents.

    Only opponents with at least one match in the database are included.
    """

    with connect_db(db_path) as connection:
        player = resolve_player(connection, player_reference)
        player_id = player["player_id"]

        opponent_rows = connection.execute(
            """
            SELECT DISTINCT
                CASE
                    WHEN player_1_id = ? THEN player_2_id
                    ELSE player_1_id
                END AS opponent_id
            FROM matches
            WHERE player_1_id = ?
               OR player_2_id = ?
            """,
            (
                player_id,
                player_id,
                player_id,
            ),
        ).fetchall()

    head_to_heads: list[dict[str, Any]] = []

    for row in opponent_rows:
        opponent_id = row["opponent_id"]
        head_to_head = get_head_to_head(
            player_id,
            opponent_id,
            db_path,
        )

        player_a = head_to_head["player_a"]
        player_b = head_to_head["player_b"]

        head_to_heads.append(
            {
                "opponent_id": player_b["player_id"],
                "opponent": player_b["player"],
                "matches": head_to_head["matches"],
                "wins": player_a["wins"],
                "losses": player_b["wins"],
                "undecided_matches": head_to_head["undecided_matches"],
                "winrate": player_a["winrate"],
                "games_won": player_a["games_won"],
                "games_lost": player_b["games_won"],
                "game_winrate": player_a["game_winrate"],
                "matches_with_known_score": (
                    head_to_head["matches_with_known_score"]
                ),
                "last_match": head_to_head["last_match"],
            }
        )

    return sorted(
        head_to_heads,
        key=lambda entry: (
            -entry["matches"],
            -entry["wins"],
            entry["opponent"].casefold(),
        ),
    )


def print_all_head_to_heads(
    player_reference: str,
    head_to_heads: list[dict[str, Any]],
) -> None:
    """Gibt alle direkten Recorden eines Playerss als Tabelle aus."""

    print(f"\nHead-to-Heads for {player_reference}")
    print("=" * 92)

    if not head_to_heads:
        print("No head-to-head matches found.")
        return

    header = (
        f"{'Opponent':<15} {'Matches':>7} {'Record':>9} "
        f"{'Win Rate':>10} {'Games':>10} {'Game-WR':>10}"
    )
    print(header)
    print("-" * len(header))

    for entry in head_to_heads:
        match_record = f"{entry['wins']}-{entry['losses']}"
        game_record = f"{entry['games_won']}-{entry['games_lost']}"

        print(
            f"{entry['opponent']:<15} "
            f"{entry['matches']:>7} "
            f"{match_record:>9} "
            f"{_format_percent(entry['winrate']):>10} "
            f"{game_record:>10} "
            f"{_format_percent(entry['game_winrate']):>10}"
        )


def print_head_to_head(stats: dict[str, Any]) -> None:
    """Gibt eine direkte Playersbilanz im Terminal aus."""

    player_a = stats["player_a"]
    player_b = stats["player_b"]

    print(f"\nHead-to-Head: {player_a['player']} vs. {player_b['player']}")
    print("=" * 64)

    print("\nMatchbilanz")
    print("-" * 64)
    print(
        f"{player_a['player']}: {player_a['wins']} Wins "
        f"({_format_percent(player_a['winrate'])})"
    )
    print(
        f"{player_b['player']}: {player_b['wins']} Wins "
        f"({_format_percent(player_b['winrate'])})"
    )
    print(f"Matches insgesamt:        {stats['matches']}")
    print(f"Unentschieden/unknown:  {stats['undecided_matches']}")

    print("\nGamebilanz")
    print("-" * 64)
    print(
        f"{player_a['player']}: {player_a['games_won']} Games "
        f"({_format_percent(player_a['game_winrate'])})"
    )
    print(
        f"{player_b['player']}: {player_b['games_won']} Games "
        f"({_format_percent(player_b['game_winrate'])})"
    )
    print(f"Matches with scores:        {stats['matches_with_known_score']}")

    print("\nLetzte Begegnung")
    print("-" * 64)

    last_match = stats["last_match"]

    if last_match is None:
        print("No head-to-head matches found.")
        return

    score = last_match["score"] or "Unknown score"
    winner = last_match["winner"] or "Unknown winner"
    phase = last_match["stage"] or "Unknown stage"

    print(
        f"{last_match['tournament']} am {last_match['date']}: "
        f"{winner} gewann ({score}, {phase})"
    )

