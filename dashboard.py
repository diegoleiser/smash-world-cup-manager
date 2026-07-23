#!/usr/bin/env python3
"""Streamlit dashboard for the Smash World Championship archive."""

from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    import bracket_visualization
    import milestones
    import narratives
    import smash_statistics as stats
    import tournament_manager as tournament_manager
    from tournament.archived_bracket import (
        archived_match_round_label,
        build_archived_bracket_matches,
        build_archived_bracket_routes,
    )
except ImportError as exc:
    raise ImportError(
        "Required files were not found in src/. "
        "Make sure bracket_visualization.py, smash_statistics.py, "
        "narratives.py, milestones.py, and tournament_manager.py exist."
    ) from exc


DB_PATH = PROJECT_ROOT / "data" / "smash_wm.db"


st.set_page_config(
    page_title="Smash World Championship",
    page_icon="🎮",
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        --mobile-table-columns: 4.5rem minmax(7rem, 1fr) minmax(6rem, 0.8fr);
        --mobile-table-gap: 0.75rem;
        --mobile-table-padding: 0.7rem 1rem;
        --mobile-table-height: 4.2rem;
    }

    [data-testid="stMetricDelta"] svg {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

def require_database() -> None:
    """Stops the app with a clear message if the database is missing."""

    if not DB_PATH.exists():
        st.error(f"Database not found: `{DB_PATH}`")
        st.info(
            "Erwartete Projektstruktur:\n\n"
            "```text\n"
            "projekt/\n"
            "├── dashboard.py\n"
            "├── data/smash_wm.db\n"
            "└── src/smash_statistics.py\n"
            "```"
        )
        st.stop()


@st.cache_data
def load_players(include_inactive: bool) -> list[dict[str, Any]]:
    """Loads players from the database."""

    with stats.connect_db(DB_PATH) as connection:
        query = """
            SELECT
                player_id,
                display_name,
                active,
                core_player
            FROM players
        """
        if not include_inactive:
            query += " WHERE active = 1"

        query += " ORDER BY display_name COLLATE NOCASE"

        return [dict(row) for row in connection.execute(query).fetchall()]


@st.cache_data
def load_elo_ranking(include_inactive: bool) -> list[dict[str, Any]]:
    return stats.get_elo_ranking(
        DB_PATH,
        active_only=not include_inactive,
    )


@st.cache_data
def load_player_profile(player_id: str) -> dict[str, Any]:
    return stats.get_player_stats(
        player_id,
        DB_PATH,
        include_elo=True,
    )


@st.cache_data
def load_player_timeline(
    player_id: str,
    include_inactive: bool = True,
) -> list[dict[str, Any]]:
    return stats.get_player_elo_timeline(
        player_id,
        DB_PATH,
        active_only=not include_inactive,
    )


@st.cache_data
def load_player_history(player_id: str) -> list[dict[str, Any]]:
    return stats.get_player_history(
        player_id,
        DB_PATH,
    )


@st.cache_data
def load_head_to_head(
    player_a_id: str,
    player_b_id: str,
) -> dict[str, Any]:
    return stats.get_head_to_head(
        player_a_id,
        player_b_id,
        DB_PATH,
    )


@st.cache_data
def load_player_insights(player_id: str) -> dict[str, Any]:
    """Calculates opponent and streak insights from the available match data."""

    players = load_players(True)
    opponent_rows: list[dict[str, Any]] = []

    for opponent in players:
        opponent_id = str(opponent["player_id"])
        if opponent_id == player_id:
            continue

        h2h = stats.get_head_to_head(player_id, opponent_id, DB_PATH)
        decided = h2h["decided_matches"]
        if decided == 0:
            continue

        opponent_rows.append(
            {
                "opponent": opponent["display_name"],
                "matches": decided,
                "wins": h2h["player_a"]["wins"],
                "losses": h2h["player_b"]["wins"],
                "winrate": h2h["player_a"]["winrate"],
            }
        )

    qualified = [row for row in opponent_rows if row["matches"] >= 3]
    pool = qualified or opponent_rows

    favorite = max(
        pool,
        key=lambda row: (row["winrate"], row["matches"]),
        default=None,
    )
    nemesis = min(
        pool,
        key=lambda row: (row["winrate"], -row["matches"]),
        default=None,
    )
    rivalry_pool = qualified or opponent_rows

    featured_rivalry = max(
        rivalry_pool,
        key=lambda row: (
            row["matches"] * 2
            - abs(row["wins"] - row["losses"]) * 3,
            row["matches"],
            -abs(row["wins"] - row["losses"]),
        ),
        default=None,
    )

    with stats.connect_db(DB_PATH) as connection:
        matches = connection.execute(
            """
            SELECT
                m.winner_id,
                t.tournament_number,
                t.tournament_date,
                m.completed_at,
                m.suggested_play_order,
                m.match_id
            FROM matches AS m
            JOIN tournaments AS t
              ON t.tournament_id = m.tournament_id
            WHERE (m.player_1_id = ? OR m.player_2_id = ?)
              AND m.winner_id IS NOT NULL
            ORDER BY
                t.tournament_date,
                t.tournament_number,
                CASE WHEN m.completed_at IS NULL THEN 1 ELSE 0 END,
                m.completed_at,
                CASE WHEN m.suggested_play_order IS NULL THEN 1 ELSE 0 END,
                m.suggested_play_order,
                m.match_id
            """,
            (player_id, player_id),
        ).fetchall()

    longest_win = longest_loss = current_win = current_loss = 0
    for match in matches:
        if str(match["winner_id"]) == player_id:
            current_win += 1
            current_loss = 0
            longest_win = max(longest_win, current_win)
        else:
            current_loss += 1
            current_win = 0
            longest_loss = max(longest_loss, current_loss)

    timeline = stats.get_player_elo_timeline(player_id, DB_PATH)
    player_changes: list[dict[str, Any]] = []
    for previous, current in zip(timeline, timeline[1:]):
        change = round(float(current["elo_exact"]) - float(previous["elo_exact"]), 1)
        if current.get("played_in_tournament"):
            player_changes.append(
                {
                    "tournament": current["tournament"],
                    "elo_change": change,
                }
            )

    best_elo_event = max(
        player_changes,
        key=lambda entry: entry["elo_change"],
        default=None,
    )

    return {
        "favorite": favorite,
        "featured_rivalry": featured_rivalry,
        "nemesis": nemesis,
        "longest_win_streak": longest_win,
        "longest_loss_streak": longest_loss,
        "best_elo_event": best_elo_event,
        "opponents": sorted(
            opponent_rows,
            key=lambda row: (-row["matches"], row["opponent"].casefold()),
        ),
    }

@st.cache_data
def load_tournament_preview_data() -> dict[str, Any]:
    """Collects ranking, form, title, and rivalry data for the next preview."""

    players = load_players(False)
    ranking = load_elo_ranking(False)

    if not players or not ranking:
        return {}

    active_ids = {
        str(player["player_id"])
        for player in players
    }
    player_names = {
        str(player["player_id"]): str(player["display_name"])
        for player in players
    }

    with stats.connect_db(DB_PATH) as connection:
        latest_tournament = connection.execute(
            """
            SELECT
                t.tournament_number,
                winner.display_name AS winner
            FROM tournaments AS t
            LEFT JOIN players AS winner
              ON winner.player_id = t.winner_id
            ORDER BY t.tournament_number DESC
            LIMIT 1
            """
        ).fetchone()

        title_rows = connection.execute(
            """
            SELECT
                p.player_id,
                p.display_name AS player,
                COUNT(t.tournament_id) AS titles
            FROM players AS p
            LEFT JOIN tournaments AS t
              ON t.winner_id = p.player_id
            WHERE p.active = 1
            GROUP BY
                p.player_id,
                p.display_name
            ORDER BY
                titles DESC,
                p.display_name COLLATE NOCASE
            """
        ).fetchall()

        match_rows = connection.execute(
            """
            SELECT
                m.player_1_id,
                m.player_2_id,
                m.winner_id,
                t.tournament_number,
                t.tournament_date,
                m.completed_at,
                m.suggested_play_order,
                m.match_id
            FROM matches AS m
            JOIN tournaments AS t
              ON t.tournament_id = m.tournament_id
            WHERE m.winner_id IS NOT NULL
            ORDER BY
                t.tournament_date DESC,
                t.tournament_number DESC,
                CASE WHEN m.completed_at IS NULL THEN 1 ELSE 0 END,
                m.completed_at DESC,
                CASE WHEN m.suggested_play_order IS NULL THEN 1 ELSE 0 END,
                m.suggested_play_order DESC,
                m.match_id DESC
            """
        ).fetchall()

    titles = [
        {
            "player_id": str(row["player_id"]),
            "player": str(row["player"]),
            "titles": int(row["titles"] or 0),
        }
        for row in title_rows
        if str(row["player_id"]) in active_ids
    ]

    recent_form: list[dict[str, Any]] = []

    for player_id in active_ids:
        player_matches = [
            row
            for row in match_rows
            if (
                str(row["player_1_id"]) == player_id
                or str(row["player_2_id"]) == player_id
            )
        ][:10]

        recent_wins = sum(
            str(row["winner_id"]) == player_id
            for row in player_matches
        )
        recent_losses = len(player_matches) - recent_wins

        current_streak = 0
        streak_type: str | None = None

        for row in player_matches:
            won = str(row["winner_id"]) == player_id
            result_type = "win" if won else "loss"

            if streak_type is None:
                streak_type = result_type

            if result_type != streak_type:
                break

            current_streak += 1

        timeline = load_player_timeline(player_id)

        if len(timeline) >= 4:
            recent_elo_change = (
                float(timeline[-1]["elo_exact"])
                - float(timeline[-4]["elo_exact"])
            )
        elif len(timeline) >= 2:
            recent_elo_change = (
                float(timeline[-1]["elo_exact"])
                - float(timeline[0]["elo_exact"])
            )
        else:
            recent_elo_change = 0.0

        recent_form.append(
            {
                "player_id": player_id,
                "player": player_names[player_id],
                "matches": len(player_matches),
                "wins": recent_wins,
                "losses": recent_losses,
                "winrate": (
                    recent_wins / len(player_matches) * 100.0
                    if player_matches
                    else None
                ),
                "streak_type": streak_type,
                "streak": current_streak,
                "elo_change_last_three": recent_elo_change,
            }
        )

    featured_rivalry: dict[str, Any] | None = None
    rivalry_score = float("-inf")

    ranked_players = [
        entry
        for entry in ranking
        if str(entry["player_id"]) in active_ids
    ]

    for left_index, left in enumerate(ranked_players):
        for right in ranked_players[left_index + 1:]:
            left_id = str(left["player_id"])
            right_id = str(right["player_id"])

            h2h = stats.get_head_to_head(
                left_id,
                right_id,
                DB_PATH,
            )

            decided = int(h2h["decided_matches"])
            if decided < 3:
                continue

            left_wins = int(h2h["player_a"]["wins"])
            right_wins = int(h2h["player_b"]["wins"])
            margin = abs(left_wins - right_wins)

            # Rewards frequent, close rivalries involving highly ranked players.
            score = (
                decided * 2
                - margin * 3
                - int(left["rank"])
                - int(right["rank"])
            )

            if score > rivalry_score:
                rivalry_score = score
                featured_rivalry = {
                    "player_a": str(left["player"]),
                    "player_b": str(right["player"]),
                    "wins_a": left_wins,
                    "wins_b": right_wins,
                    "matches": decided,
                    "last_match": h2h.get("last_match"),
                }

    return {
        "ranking": ranked_players,
        "titles": titles,
        "defending_champion": (
            str(latest_tournament["winner"])
            if latest_tournament and latest_tournament["winner"]
            else None
        ),
        "latest_tournament": (
            f"WM {int(latest_tournament['tournament_number']):02d}"
            if latest_tournament
            else None
        ),
        "recent_form": recent_form,
        "featured_rivalry": featured_rivalry,
    }

@st.cache_data
def load_h2h_matrix(include_inactive: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Loads match records and win rates for all visible player pairs."""

    players = load_players(include_inactive)
    names = [player["display_name"] for player in players]
    ids = {player["display_name"]: str(player["player_id"]) for player in players}

    records = pd.DataFrame("—", index=names, columns=names)
    winrates = pd.DataFrame(float("nan"), index=names, columns=names)

    for index, left_name in enumerate(names):
        for right_name in names[index + 1:]:
            h2h = stats.get_head_to_head(ids[left_name], ids[right_name], DB_PATH)
            left_wins = h2h["player_a"]["wins"]
            right_wins = h2h["player_b"]["wins"]
            records.loc[left_name, right_name] = f"{left_wins}:{right_wins}"
            records.loc[right_name, left_name] = f"{right_wins}:{left_wins}"
            decided = left_wins + right_wins
            if decided:
                winrates.loc[left_name, right_name] = left_wins / decided
                winrates.loc[right_name, left_name] = right_wins / decided

    records.index.name = "Players"
    return records, winrates


@st.cache_data
def load_tournament_detail(tournament_number: int) -> dict[str, Any]:
    """Loads participants, placements, and matches for a tournament."""

    with stats.connect_db(DB_PATH) as connection:
        tournament = connection.execute(
            """
            SELECT
                t.tournament_id,
                t.tournament_number,
                t.tournament_date,
                t.match_data_available,
                winner.display_name AS winner
            FROM tournaments AS t
            LEFT JOIN players AS winner
              ON winner.player_id = t.winner_id
            WHERE t.tournament_number = ?
            """,
            (tournament_number,),
        ).fetchone()

        if tournament is None:
            raise ValueError(f"WC {tournament_number:02d} was not found.")

        participants = connection.execute(
            """
            SELECT
                p.player_id,
                p.display_name AS player,
                tp.seed,
                tp.placement
            FROM tournament_participants AS tp
            JOIN players AS p
              ON p.player_id = tp.player_id
            WHERE tp.tournament_id = ?
            ORDER BY
                CASE WHEN tp.placement IS NULL THEN 1 ELSE 0 END,
                tp.placement,
                p.display_name COLLATE NOCASE
            """,
            (tournament["tournament_id"],),
        ).fetchall()

        matches = connection.execute(
            """
            SELECT
                m.match_id,
                m.stage,
                m.round_label,
                m.bracket_side,
                m.challonge_match_id,
                m.challonge_identifier,
                m.challonge_round,
                m.suggested_play_order,
                m.player_1_id,
                p1.display_name AS player_1,
                m.player_2_id,
                p2.display_name AS player_2,
                m.winner_id,
                winner.display_name AS winner,
                m.player_1_score,
                m.player_2_score,
                m.score_known,
                m.walkover,
                m.completed_at
            FROM matches AS m
            JOIN players AS p1 ON p1.player_id = m.player_1_id
            JOIN players AS p2 ON p2.player_id = m.player_2_id
            LEFT JOIN players AS winner ON winner.player_id = m.winner_id
            WHERE m.tournament_id = ?
            ORDER BY
                CASE WHEN m.completed_at IS NULL THEN 1 ELSE 0 END,
                m.completed_at,
                CASE WHEN m.suggested_play_order IS NULL THEN 1 ELSE 0 END,
                m.suggested_play_order,
                m.match_id
            """,
            (tournament["tournament_id"],),
        ).fetchall()

    timeline = stats.get_elo_ranking_timeline(DB_PATH, active_only=False)
    elo_snapshot = [
        entry for entry in timeline
        if entry["tournament_number"] == tournament_number
    ]

    return {
        "tournament": dict(tournament),
        "participants": [dict(row) for row in participants],
        "matches": [dict(row) for row in matches],
        "elo_snapshot": sorted(elo_snapshot, key=lambda entry: entry["rank"]),
    }


@st.cache_data
def load_tournaments() -> list[dict[str, Any]]:
    """Loads a compact tournament overview."""

    with stats.connect_db(DB_PATH) as connection:
        rows = connection.execute(
            """
            SELECT
                t.tournament_id,
                t.tournament_number,
                t.tournament_date,
                winner.display_name AS winner,
                COUNT(DISTINCT tp.player_id) AS participants,
                COUNT(DISTINCT m.match_id) AS matches,
                t.match_data_available
            FROM tournaments AS t
            LEFT JOIN players AS winner
              ON winner.player_id = t.winner_id
            LEFT JOIN tournament_participants AS tp
              ON tp.tournament_id = t.tournament_id
            LEFT JOIN matches AS m
              ON m.tournament_id = t.tournament_id
            GROUP BY
                t.tournament_id,
                t.tournament_number,
                t.tournament_date,
                winner.display_name,
                t.match_data_available
            ORDER BY t.tournament_number DESC
            """
        ).fetchall()

    return [
        {
            "WM": f"WM {row['tournament_number']:02d}",
            "Date": row["tournament_date"],
            "Winner": row["winner"] or "Unknown",
            "Participants": row["participants"] or 0,
            "Matches": row["matches"] or 0,
            "Match data": "Yes" if row["match_data_available"] else "No",
        }
        for row in rows
    ]

@st.cache_data
def load_tournament_milestones(
    tournament_number: int,
) -> list[str]:
    """Loads milestones reached at a tournament."""

    return milestones.detect_tournament_milestones(
        DB_PATH,
        tournament_number,
    )


def format_percent(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f} %"


def format_placement(value: int | None) -> str:
    return "–" if value is None else f"{value}."



@st.cache_data
def load_database_quality() -> dict[str, Any]:
    """Loads archive completeness metrics."""

    with stats.connect_db(DB_PATH) as connection:
        tournaments = int(
            connection.execute(
                "SELECT COUNT(*) FROM tournaments"
            ).fetchone()[0]
        )
        players = int(
            connection.execute(
                "SELECT COUNT(*) FROM players"
            ).fetchone()[0]
        )
        active_players = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM players
                WHERE active = 1
                """
            ).fetchone()[0]
        )
        matches = int(
            connection.execute(
                "SELECT COUNT(*) FROM matches"
            ).fetchone()[0]
        )
        champions = int(
            connection.execute(
                """
                SELECT COUNT(DISTINCT winner_id)
                FROM tournaments
                WHERE winner_id IS NOT NULL
                """
            ).fetchone()[0]
        )

    return {
        "tournaments": tournaments,
        "players": players,
        "active_players": active_players,
        "matches": matches,
        "champions": champions,
    }

@st.cache_data
def load_tournament_drafts() -> list[dict[str, Any]]:
    """Loads all active tournament drafts."""

    return tournament_manager.list_drafts(DB_PATH)


@st.cache_data
def load_tournament_draft(draft_id: str) -> dict[str, Any]:
    """Loads one tournament draft with its participants."""

    return tournament_manager.get_draft(
        DB_PATH,
        draft_id,
    )

@st.cache_data
def load_tournament_draft_groups(
    draft_id: str,
) -> list[dict[str, Any]]:
    """Loads group assignments for one tournament draft."""

    return tournament_manager.get_draft_groups(
        DB_PATH,
        draft_id,
    )

@st.cache_data
def load_tournament_draft_group_matches(
    draft_id: str,
) -> list[dict[str, Any]]:
    """Loads group-stage matches for one tournament draft."""

    return tournament_manager.get_draft_group_matches(
        DB_PATH,
        draft_id,
    )

@st.cache_data
def load_tournament_draft_group_standings(
    draft_id: str,
) -> list[dict[str, Any]]:
    """Loads calculated group standings for one tournament draft."""

    return tournament_manager.get_draft_group_standings(
        DB_PATH,
        draft_id,
    )

@st.cache_data
def load_tournament_draft_global_group_ranking(
    draft_id: str,
) -> dict[str, Any]:
    """Loads the global group-stage ranking for one draft."""

    return tournament_manager.get_draft_global_group_ranking(
        DB_PATH,
        draft_id,
    )

@st.cache_data
def load_tournament_draft_bracket_state(
    draft_id: str,
) -> dict[str, Any]:
    """Loads the generated bracket and its current state."""

    return tournament_manager.get_draft_bracket_state(
        DB_PATH,
        draft_id,
    )

@st.cache_data
def load_tournament_draft_finalization_preview(
    draft_id: str,
) -> dict[str, Any]:
    """Loads the archive preview for a completed tournament draft."""

    return tournament_manager.get_draft_finalization_preview(
        DB_PATH,
        draft_id,
    )

def show_home(include_inactive: bool) -> None:
    st.title("🎮 Smash World Championship")
    st.caption(
        "Current ranking and overview of the private "
        "World Championship archive"
    )

    quality = load_database_quality()

    st.subheader("📊 Archive Summary")

    archive_summary_html = (
        "<div class='archive-summary-grid' style='"
        "display:grid;"
        "grid-template-columns:repeat(4, 1fr);"
        "align-items:stretch;"
        "border:1px solid rgba(128,128,128,0.32);"
        "border-radius:0.8rem;"
        "overflow:hidden;"
        "'>"

        "<div class='archive-summary-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "align-items:center;"
        "justify-content:center;"
        "min-height:9rem;"
        "padding:1rem;"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:750;"
        "opacity:0.65;"
        "letter-spacing:0.04em;"
        "min-height:1.2rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        "TOURNAMENTS"
        "</div>"
        "<div style='"
        "font-size:2.35rem;"
        "font-weight:800;"
        "line-height:1;"
        "margin-top:0.65rem;"
        "min-height:2.5rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        f"{quality['tournaments']}"
        "</div>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:650;"
        "opacity:0.62;"
        "margin-top:0.55rem;"
        "min-height:1.1rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "white-space:nowrap;"
        "'>"
        "Archived events"
        "</div>"
        "</div>"

        "<div class='archive-summary-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "align-items:center;"
        "justify-content:center;"
        "min-height:9rem;"
        "padding:1rem;"
        "border-left:1px solid rgba(128,128,128,0.22);"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:750;"
        "opacity:0.65;"
        "letter-spacing:0.04em;"
        "min-height:1.2rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        "PLAYERS"
        "</div>"
        "<div style='"
        "font-size:2.35rem;"
        "font-weight:800;"
        "line-height:1;"
        "margin-top:0.65rem;"
        "min-height:2.5rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        f"{quality['players']}"
        "</div>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:650;"
        "opacity:0.62;"
        "margin-top:0.55rem;"
        "min-height:1.1rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "white-space:nowrap;"
        "'>"
        f"{quality['active_players']} active"
        "</div>"
        "</div>"

        "<div class='archive-summary-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "align-items:center;"
        "justify-content:center;"
        "min-height:9rem;"
        "padding:1rem;"
        "border-left:1px solid rgba(128,128,128,0.22);"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:750;"
        "opacity:0.65;"
        "letter-spacing:0.04em;"
        "min-height:1.2rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        "SETS"
        "</div>"
        "<div style='"
        "font-size:2.35rem;"
        "font-weight:800;"
        "line-height:1;"
        "margin-top:0.65rem;"
        "min-height:2.5rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        f"{quality['matches']}"
        "</div>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:650;"
        "opacity:0.62;"
        "margin-top:0.55rem;"
        "min-height:1.1rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "white-space:nowrap;"
        "'>"
        "Archived sets"
        "</div>"
        "</div>"

        "<div class='archive-summary-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "align-items:center;"
        "justify-content:center;"
        "min-height:9rem;"
        "padding:1rem;"
        "border-left:1px solid rgba(128,128,128,0.22);"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:750;"
        "opacity:0.65;"
        "letter-spacing:0.04em;"
        "min-height:1.2rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        "CHAMPIONS"
        "</div>"
        "<div style='"
        "font-size:2.35rem;"
        "font-weight:800;"
        "line-height:1;"
        "margin-top:0.65rem;"
        "min-height:2.5rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        f"{quality['champions']}"
        "</div>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:650;"
        "opacity:0.62;"
        "margin-top:0.55rem;"
        "min-height:1.1rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "white-space:nowrap;"
        "'>"
        "Different winners"
        "</div>"
        "</div>"

        "</div>"
    )

    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            .archive-summary-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            }

            .archive-summary-card {
                min-width: 0;
            }

            .archive-summary-card:nth-child(3) {
                border-left: none !important;
                border-top: 1px solid rgba(128,128,128,0.22);
            }

            .archive-summary-card:nth-child(4) {
                border-top: 1px solid rgba(128,128,128,0.22);
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        archive_summary_html,
        unsafe_allow_html=True,
    )

    ranking = load_elo_ranking(
        include_inactive
    )

    if not ranking:
        st.warning(
            "No rated Elo matches found yet."
        )
        return

    leader = ranking[0]

    tournaments = load_tournaments()

    current_champion = (
        tournaments[0]["Winner"]
        if tournaments
        else "–"
    )

    latest_tournament = (
        tournaments[0]["WM"]
        if tournaments
        else "–"
    )

    if tournaments:
        title_counts = (
            pd.DataFrame(tournaments)["Winner"]
            .value_counts()
        )

        most_titles_player = str(
            title_counts.index[0]
        )

        most_titles_count = int(
            title_counts.iloc[0]
        )
    else:
        most_titles_player = "–"
        most_titles_count = 0

    st.divider()
    st.subheader("Current Overview")

    title_label = (
        "Title"
        if most_titles_count == 1
        else "Titles"
    )

    current_overview_html = (
       "<div class='current-overview-grid' style='"
        "display:grid;"
        "grid-template-columns:repeat(3, minmax(0, 1fr));"
        "gap:1rem;"
        "'>"

        "<div class='current-overview-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "min-height:10rem;"
        "padding:1.2rem 1.35rem;"
        "border:1px solid rgba(128,128,128,0.32);"
        "border-radius:0.8rem;"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:700;"
        "opacity:0.65;"
        "letter-spacing:0.03em;"
        "'>"
        "CURRENT NO. 1"
        "</div>"
        "<div style='"
        "font-size:1.9rem;"
        "font-weight:800;"
        "margin-top:1.25rem;"
        "line-height:1.15;"
        "'>"
        f"{html.escape(str(leader['player']))}"
        "</div>"
        "<div style='"
        "font-size:0.95rem;"
        "font-weight:700;"
        "margin-top:auto;"
        "padding-top:1rem;"
        "'>"
        f"#{leader['rank']} · {leader['elo']:.1f} Elo"
        "</div>"
        "</div>"

        "<div class='current-overview-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "min-height:10rem;"
        "padding:1.2rem 1.35rem;"
        "border:1px solid rgba(128,128,128,0.32);"
        "border-radius:0.8rem;"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:700;"
        "opacity:0.65;"
        "letter-spacing:0.03em;"
        "'>"
        "CURRENT CHAMPION"
        "</div>"
        "<div style='"
        "font-size:1.9rem;"
        "font-weight:800;"
        "margin-top:1.25rem;"
        "line-height:1.15;"
        "'>"
        f"{html.escape(str(current_champion))}"
        "</div>"
        "<div style='"
        "font-size:0.95rem;"
        "font-weight:700;"
        "margin-top:auto;"
        "padding-top:1rem;"
        "'>"
        f"Winner of {html.escape(str(latest_tournament))}"
        "</div>"
        "</div>"

        "<div class='current-overview-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "min-height:10rem;"
        "padding:1.2rem 1.35rem;"
        "border:1px solid rgba(128,128,128,0.32);"
        "border-radius:0.8rem;"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:700;"
        "opacity:0.65;"
        "letter-spacing:0.03em;"
        "'>"
        "MOST TITLES"
        "</div>"
        "<div style='"
        "font-size:1.9rem;"
        "font-weight:800;"
        "margin-top:1.25rem;"
        "line-height:1.15;"
        "'>"
        f"{html.escape(str(most_titles_player))}"
        "</div>"
        "<div style='"
        "font-size:0.95rem;"
        "font-weight:700;"
        "margin-top:auto;"
        "padding-top:1rem;"
        "'>"
        f"{most_titles_count} {title_label}"
        "</div>"
        "</div>"

        "</div>"
    )

    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            .current-overview-grid {
                grid-template-columns: 1fr !important;
            }

            .current-overview-card {
                min-width: 0;
            }

            .current-overview-card > div {
                overflow-wrap: normal;
                word-break: normal;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        current_overview_html,
        unsafe_allow_html=True,
    )

    preview_data = load_tournament_preview_data()

    preview_text = narratives.generate_tournament_preview(
        preview_data,
    )

    preview_ranking = preview_data.get("ranking") or []
    featured_rivalry = preview_data.get("featured_rivalry")

    favorite = (
        preview_ranking[0]
        if preview_ranking
        else None
    )

    main_challenger = (
        preview_ranking[1]
        if len(preview_ranking) >= 2
        else None
    )

    if favorite:
        favorite_name = str(
            favorite.get("player") or "–"
        )
        favorite_detail = (
            f"#{favorite.get('rank', '–')} · "
            f"{float(favorite.get('elo') or 1000.0):.1f} Elo"
        )
    else:
        favorite_name = "–"
        favorite_detail = "No ranking available"

    if main_challenger:
        challenger_name = str(
            main_challenger.get("player") or "–"
        )
        challenger_detail = (
            f"#{main_challenger.get('rank', '–')} · "
            f"{float(main_challenger.get('elo') or 1000.0):.1f} Elo"
        )
    else:
        challenger_name = "–"
        challenger_detail = "No challenger available"

    if featured_rivalry:
        rivalry_name = (
            f"{featured_rivalry['player_a']} vs "
            f"{featured_rivalry['player_b']}"
        )

        rivalry_detail = (
            f"{featured_rivalry['wins_a']}–"
            f"{featured_rivalry['wins_b']} all-time"
        )
    else:
        rivalry_name = "–"
        rivalry_detail = "No featured rivalry"

    st.divider()
    st.subheader("🔮 Next Tournament Preview")

    preview_cards_html = (
        "<style>"
        ".preview-card-grid {"
        "display:grid;"
        "grid-template-columns:repeat(3, minmax(0, 1fr));"
        "gap:1rem;"
        "margin-top:0;"
        "}"
        ".preview-card {"
        "display:flex;"
        "flex-direction:column;"
        "min-height:7.5rem;"
        "padding:1rem 1.15rem;"
        "border:1px solid rgba(128,128,128,0.30);"
        "border-radius:0.8rem;"
        "}"
        ".preview-card-label {"
        "font-size:0.78rem;"
        "font-weight:750;"
        "opacity:0.62;"
        "letter-spacing:0.04em;"
        "}"
        ".preview-card-value {"
        "font-size:1.45rem;"
        "font-weight:800;"
        "line-height:1.15;"
        "margin-top:0.8rem;"
        "}"
        ".preview-card-detail {"
        "font-size:0.9rem;"
        "font-weight:650;"
        "opacity:0.68;"
        "margin-top:auto;"
        "padding-top:0.8rem;"
        "}"
        "@media (max-width:800px) {"
        ".preview-card-grid {"
        "grid-template-columns:1fr;"
        "}"
        "}"
        "</style>"

        "<div class='preview-card-grid'>"

        "<div class='preview-card'>"
        "<div class='preview-card-label'>"
        "ELO FAVORITE"
        "</div>"
        "<div class='preview-card-value'>"
        f"{html.escape(favorite_name)}"
        "</div>"
        "<div class='preview-card-detail'>"
        f"{html.escape(favorite_detail)}"
        "</div>"
        "</div>"

        "<div class='preview-card'>"
        "<div class='preview-card-label'>"
        "MAIN CHALLENGER"
        "</div>"
        "<div class='preview-card-value'>"
        f"{html.escape(challenger_name)}"
        "</div>"
        "<div class='preview-card-detail'>"
        f"{html.escape(challenger_detail)}"
        "</div>"
        "</div>"

        "<div class='preview-card'>"
        "<div class='preview-card-label'>"
        "FEATURED RIVALRY"
        "</div>"
        "<div class='preview-card-value'>"
        f"{html.escape(rivalry_name)}"
        "</div>"
        "<div class='preview-card-detail'>"
        f"{html.escape(rivalry_detail)}"
        "</div>"
        "</div>"

        "</div>"
    )

    preview_sentences = [
        sentence.strip()
        for sentence in preview_text.split(". ")
        if sentence.strip()
    ]

    preview_paragraphs: list[str] = []

    for index in range(
        0,
        len(preview_sentences),
        2,
    ):
        paragraph_sentences = (
            preview_sentences[index:index + 2]
        )

        paragraph = ". ".join(
            paragraph_sentences
        )

        if not paragraph.endswith("."):
            paragraph += "."

        preview_paragraphs.append(
            (
                "<p style='"
                "margin:0 0 0.9rem 0;"
                "'>"
                f"{html.escape(paragraph)}"
                "</p>"
            )
        )

    preview_text_html = "".join(
        preview_paragraphs
    )

    st.markdown(
        (
            "<style>"
            ".tournament-outlook {"
            "display:grid;"
            "grid-template-columns:9rem minmax(0, 1fr);"
            "gap:2rem;"
            "align-items:start;"
            "padding:1.5rem 1.7rem;"
            "border-radius:0.8rem;"
            "background:rgba(28,74,112,0.55);"
            "border:1px solid rgba(70,150,220,0.18);"
            "}"
            ".tournament-outlook-label {"
            "font-size:0.78rem;"
            "font-weight:750;"
            "letter-spacing:0.04em;"
            "opacity:0.72;"
            "padding-top:0.15rem;"
            "}"
            ".tournament-outlook-text {"
            "font-size:1rem;"
            "line-height:1.75;"
            "}"
            ".tournament-outlook-text p:last-child {"
            "margin-bottom:0 !important;"
            "}"
            "@media (max-width:800px) {"
            ".tournament-outlook {"
            "grid-template-columns:1fr;"
            "gap:0.75rem;"
            "padding:1.25rem 1.4rem;"
            "}"
            "}"
            "</style>"

            "<div class='tournament-outlook'>"
            "<div class='tournament-outlook-label'>"
            "TOURNAMENT<br>OUTLOOK"
            "</div>"
            "<div class='tournament-outlook-text'>"
            f"{preview_text_html}"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        (
            "<div style='"
            "margin-top:1.6rem;"
            "margin-bottom:0.75rem;"
            "font-size:1.35rem;"
            "font-weight:800;"
            "'>"
            "Preview Highlights"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        preview_cards_html,
        unsafe_allow_html=True,
    )

    st.divider()
    st.subheader("Current Elo Ranking")

    leader_elo = float(ranking[0]["elo"])

    ranking_rows_html: list[str] = []

    rank_icons = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
    }

    for entry in ranking:
        rank = int(entry["rank"])
        player_name = str(entry["player"])
        player_profile_url = (
            "?page=Players&player="
            f"{quote(player_name)}"
        )
        elo = float(entry["elo"])
        rated_sets = int(entry["rated_matches"])
        active = bool(entry["active"])

        rank_display = (
            f"{rank_icons.get(rank, '')} #{rank}".strip()
        )

        elo_gap = leader_elo - elo

        if rank == 1:
            gap_text = "Leader"
            gap_color = "#3fb950"
        else:
            gap_text = f"−{elo_gap:.1f}"
            gap_color = "rgba(255,255,255,0.58)"

        status_text = (
            "Active"
            if active
            else "Inactive"
        )

        status_color = (
            "#3fb950"
            if active
            else "rgba(255,255,255,0.45)"
        )

        top_rank_style = (
            "background:rgba(34,197,94,0.07);"
            if rank == 1
            else ""
        )

        ranking_rows_html.append(
            (
                "<div class='elo-ranking-row' "
                f"style='{top_rank_style}'>"

                "<div class='elo-ranking-rank'>"
                f"{html.escape(rank_display)}"
                "</div>"

                "<div class='elo-ranking-player'>"
                "<a class='elo-ranking-player-link' "
                f"href='{html.escape(player_profile_url)}' "
                "target='_self'>"
                f"{html.escape(player_name)}"
                "</a>"
                "</div>"

                "<div class='elo-ranking-value'>"
                f"{elo:.1f} Elo"
                "</div>"

                "<div class='elo-ranking-gap' "
                f"style='color:{gap_color};'>"
                f"{html.escape(gap_text)}"
                "</div>"

                "<div class='elo-ranking-sets'>"
                f"{rated_sets} sets"
                "</div>"

                "<div class='elo-ranking-status' "
                f"style='color:{status_color};'>"
                f"{status_text}"
                "</div>"

                "</div>"
            )
        )

    ranking_list_html = (
        "<style>"
        ".elo-ranking-list {"
        "border:1px solid rgba(128,128,128,0.30);"
        "border-radius:0.8rem;"
        "overflow:hidden;"
        "}"

        ".elo-ranking-row {"
        "display:grid;"
        "grid-template-columns:5.5rem minmax(8rem,2fr) "
        "minmax(7rem,1fr) minmax(5rem,0.8fr) "
        "minmax(5rem,0.8fr) minmax(5rem,0.8fr);"
        "align-items:center;"
        "min-height:4.2rem;"
        "padding:0.7rem 1rem;"
        "border-bottom:1px solid rgba(128,128,128,0.20);"
        "gap:0.75rem;"
        "}"

        ".elo-ranking-row:last-child {"
        "border-bottom:none;"
        "}"

        ".elo-ranking-rank {"
        "font-weight:800;"
        "text-align:right;"
        "}"

        ".elo-ranking-player {"
        "font-size:1.1rem;"
        "font-weight:800;"
        "}"

        ".elo-ranking-player-link,"
        ".elo-ranking-player-link:link,"
        ".elo-ranking-player-link:visited,"
        ".elo-ranking-player-link:hover,"
        ".elo-ranking-player-link:active,"
        ".elo-ranking-player-link:focus {"
        "color:inherit !important;"
        "text-decoration:none !important;"
        "}"

        ".elo-ranking-player-link {"
        "display:inline-block;"
        "font-weight:800;"
        "transition:opacity 0.15s ease, transform 0.15s ease;"
        "}"

        ".elo-ranking-player-link:hover {"
        "opacity:0.72;"
        "transform:translateX(3px);"
        "}"

        ".elo-ranking-player-link:focus {"
        "outline:none;"
        "}"

        ".elo-ranking-value {"
        "font-weight:750;"
        "text-align:right;"
        "}"

        ".elo-ranking-gap,"
        ".elo-ranking-sets,"
        ".elo-ranking-status {"
        "font-size:0.88rem;"
        "font-weight:700;"
        "text-align:center;"
        "}"

        "@media (max-width:768px) {"

        ".elo-ranking-row {"
        "grid-template-columns:var(--mobile-table-columns);"
        "gap:var(--mobile-table-gap);"
        "padding:var(--mobile-table-padding);"
        "min-height:var(--mobile-table-height);"
        "}"

        ".elo-ranking-rank {"
        "padding-right:1.9rem;"
        "white-space:nowrap;"
        "}"

        ".elo-ranking-gap,"
        ".elo-ranking-sets,"
        ".elo-ranking-status {"
        "display:none;"
        "}"

        "}"
        "</style>"

        "<div class='elo-ranking-list'>"
        f"{''.join(ranking_rows_html)}"
        "</div>"
    )

    st.markdown(
        ranking_list_html,
        unsafe_allow_html=True,
    )

    st.markdown(
        (
            "<div style='"
            "margin-top:2rem;"
            "margin-bottom:0.75rem;"
            "font-size:1.5rem;"
            "font-weight:800;"
            "'>"
            "Elo History"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    elo_history_rows: list[dict[str, Any]] = []

    for entry in ranking:
        player_id = str(entry["player_id"])
        player_name = str(entry["player"])

        timeline = load_player_timeline(
            player_id
        )

        for timeline_entry in timeline:
            elo_history_rows.append(
                {
                    **timeline_entry,
                    "Players": player_name,
                }
            )

    if elo_history_rows:
        elo_history_df = pd.DataFrame(
            elo_history_rows
        ).sort_values(
            [
                "Players",
                "tournament_number",
            ]
        )

        tournament_order = (
            elo_history_df[
                [
                    "tournament",
                    "tournament_number",
                ]
            ]
            .drop_duplicates()
            .sort_values("tournament_number")[
                "tournament"
            ]
            .tolist()
        )

        segment_rows: list[dict[str, Any]] = []

        for player_name, player_rows in elo_history_df.groupby(
            "Players",
            sort=False,
        ):
            ordered_rows = (
                player_rows
                .sort_values("tournament_number")
                .to_dict("records")
            )

            for previous, current in zip(
                ordered_rows,
                ordered_rows[1:],
            ):
                segment_rows.append(
                    {
                        "Players": player_name,
                        "start_tournament": previous["tournament"],
                        "end_tournament": current["tournament"],
                        "start_elo": previous["elo"],
                        "end_elo": current["elo"],
                        "segment_type": (
                            "Played"
                            if bool(current["played_in_tournament"])
                            else "Did not participate"
                        ),
                    }
                )

        segment_df = pd.DataFrame(segment_rows)

        player_hover = alt.selection_point(
            fields=["Players"],
            on="pointerover",
            empty=True,
            clear="pointerout",
        )

        solid_segments = (
            alt.Chart(
                segment_df[
                    segment_df["segment_type"] == "Played"
                ]
            )
            .mark_rule(
                strokeWidth=2,
            )
            .encode(
                x=alt.X(
                    "start_tournament:N",
                    title="Tournament",
                    sort=tournament_order,
                ),
                x2="end_tournament:N",
                y=alt.Y(
                    "start_elo:Q",
                    title="Elo",
                    scale=alt.Scale(
                        zero=False,
                    ),
                ),
                y2="end_elo:Q",
                color=alt.Color(
                    "Players:N",
                    title=None,
                    legend=alt.Legend(
                        orient="right",
                        symbolType="circle",
                        symbolSize=100,
                    ),
                ),
                opacity=alt.condition(
                    player_hover,
                    alt.value(1.0),
                    alt.value(0.12),
                ),
                size=alt.condition(
                    player_hover,
                    alt.value(3.2),
                    alt.value(1.4),
                ),
            )
        )

        dashed_segments = (
            alt.Chart(
                segment_df[
                    segment_df["segment_type"]
                    == "Did not participate"
                ]
            )
            .mark_rule(
                strokeDash=[6, 4],
            )
            .encode(
                x=alt.X(
                    "start_tournament:N",
                    title="Tournament",
                    sort=tournament_order,
                ),
                x2="end_tournament:N",
                y=alt.Y(
                    "start_elo:Q",
                    title="Elo",
                    scale=alt.Scale(
                        zero=False,
                    ),
                ),
                y2="end_elo:Q",
                color=alt.Color(
                    "Players:N",
                    title=None,
                ),
                opacity=alt.condition(
                    player_hover,
                    alt.value(1.0),
                    alt.value(0.12),
                ),
                size=alt.condition(
                    player_hover,
                    alt.value(3.2),
                    alt.value(1.4),
                ),
            )
        )

        played_points = (
            alt.Chart(
                elo_history_df[
                    elo_history_df["played_in_tournament"]
                ]
            )
            .mark_point(
                filled=True,
                strokeWidth=2,
            )
            .encode(
                x=alt.X(
                    "tournament:N",
                    title="Tournament",
                    sort=tournament_order,
                ),
                y=alt.Y(
                    "elo:Q",
                    title="Elo",
                    scale=alt.Scale(
                        zero=False,
                    ),
                ),
                color=alt.Color(
                    "Players:N",
                    legend=None,
                ),
                opacity=alt.condition(
                    player_hover,
                    alt.value(1.0),
                    alt.value(0.12),
                ),
                size=alt.condition(
                    player_hover,
                    alt.value(90),
                    alt.value(45),
                ),
                tooltip=[
                    alt.Tooltip(
                        "Players:N",
                        title="Player",
                    ),
                    alt.Tooltip(
                        "tournament:N",
                        title="Tournament",
                    ),
                    alt.Tooltip(
                        "tournament_date:N",
                        title="Date",
                    ),
                    alt.Tooltip(
                        "elo:Q",
                        title="Elo",
                        format=".1f",
                    ),
                    alt.Tooltip(
                        "rank:Q",
                        title="Rank",
                    ),
                    alt.Tooltip(
                        "played_in_tournament:N",
                        title="Participated",
                    ),
                ],
            )
        )

        missed_points = (
            alt.Chart(
                elo_history_df[
                    ~elo_history_df["played_in_tournament"]
                ]
            )
            .mark_point(
                filled=False,
                strokeWidth=2.5,
            )
            .encode(
                x=alt.X(
                    "tournament:N",
                    title="Tournament",
                    sort=tournament_order,
                ),
                y=alt.Y(
                    "elo:Q",
                    title="Elo",
                    scale=alt.Scale(
                        zero=False,
                    ),
                ),
                color=alt.Color(
                    "Players:N",
                    legend=None,
                ),
                opacity=alt.condition(
                    player_hover,
                    alt.value(1.0),
                    alt.value(0.12),
                ),
                size=alt.condition(
                    player_hover,
                    alt.value(90),
                    alt.value(45),
                ),
                tooltip=[
                    alt.Tooltip(
                        "Players:N",
                        title="Player",
                    ),
                    alt.Tooltip(
                        "tournament:N",
                        title="Tournament",
                    ),
                    alt.Tooltip(
                        "tournament_date:N",
                        title="Date",
                    ),
                    alt.Tooltip(
                        "elo:Q",
                        title="Elo",
                        format=".1f",
                    ),
                    alt.Tooltip(
                        "rank:Q",
                        title="Rank",
                    ),
                    alt.Tooltip(
                        "played_in_tournament:N",
                        title="Participated",
                    ),
                ],
            )
        )

        solid_hover_targets = (
            alt.Chart(
                segment_df[
                    segment_df["segment_type"] == "Played"
                ]
            )
            .mark_rule(
                strokeWidth=14,
                opacity=0.001,
            )
            .encode(
                x=alt.X(
                    "start_tournament:N",
                    sort=tournament_order,
                ),
                x2="end_tournament:N",
                y=alt.Y(
                    "start_elo:Q",
                    scale=alt.Scale(
                        zero=False,
                    ),
                ),
                y2="end_elo:Q",
                detail="Players:N",
            )
        )

        dashed_hover_targets = (
            alt.Chart(
                segment_df[
                    segment_df["segment_type"]
                    == "Did not participate"
                ]
            )
            .mark_rule(
                strokeWidth=14,
                opacity=0.001,
            )
            .encode(
                x=alt.X(
                    "start_tournament:N",
                    sort=tournament_order,
                ),
                x2="end_tournament:N",
                y=alt.Y(
                    "start_elo:Q",
                    scale=alt.Scale(
                        zero=False,
                    ),
                ),
                y2="end_elo:Q",
                detail="Players:N",
            )
        )

        hover_targets = (
            solid_hover_targets
            + dashed_hover_targets
        ).add_params(
            player_hover
        )

        elo_history_chart = (
            solid_segments
            + dashed_segments
            + hover_targets
            + played_points
            + missed_points
        ).properties(
            height=560,
        )

        st.altair_chart(
            elo_history_chart,
            use_container_width=True,
        )

        st.caption(
            "Dashed segments and hollow points indicate tournaments "
            "in which the player did not participate."
        )

    else:
        st.info(
            "No Elo history is available yet."
        )

    st.divider()
    st.subheader(
        "🏆 Tournament Overview"
    )

    if tournaments:
        tournament_df = pd.DataFrame(
            [
                {
                    "Tournament": (
                        f"World Championship "
                        f"{int(tournament['WM'].split()[1]):02d}"
                    ),
                    "Date": tournament["Date"],
                    "Champion": tournament["Winner"],
                    "Players": (
                        tournament["Participants"]
                        if tournament["Participants"] > 0
                        else None
                    ),
                }
                for tournament in tournaments
            ]
        )

        tournament_rows_html: list[str] = []

        for _, row in tournament_df.iterrows():
            tournament_name = str(row["Tournament"])
            champion = str(row["Champion"])

            raw_date = row["Date"]

            if pd.notna(raw_date):
                formatted_date = pd.to_datetime(
                    raw_date
                ).strftime("%d %b %Y")
            else:
                formatted_date = "–"

            players_value = row["Players"]

            if pd.isna(players_value):
                players_text = "–"
            else:
                players_text = str(
                    int(players_value)
                )

            tournament_rows_html.append(
                (
                    "<div class='tournament-overview-row'>"

                    "<div class='tournament-overview-name'>"
                    f"{html.escape(tournament_name)}"
                    "</div>"

                    "<div class='tournament-overview-date'>"
                    f"{html.escape(formatted_date)}"
                    "</div>"

                    "<div class='tournament-overview-champion'>"
                    f"{html.escape(champion)}"
                    "</div>"

                    "<div class='tournament-overview-players'>"
                    f"{html.escape(players_text)}"
                    "</div>"

                    "</div>"
                )
            )

        tournament_overview_html = (
            "<style>"

            ".tournament-overview-list {"
            "width:100%;"
            "border:1px solid rgba(128,128,128,0.30);"
            "border-radius:0.8rem;"
            "overflow:hidden;"
            "}"

            ".tournament-overview-header,"
            ".tournament-overview-row {"
            "display:grid;"
            "grid-template-columns:minmax(15rem,1.4fr) "
            "minmax(10rem,0.9fr) "
            "minmax(12rem,1.2fr) "
            "minmax(5rem,0.45fr);"
            "align-items:center;"
            "gap:0.75rem;"
            "padding:0.7rem 1rem;"
            "}"

            ".tournament-overview-header {"
            "min-height:3.2rem;"
            "background:rgba(128,128,128,0.08);"
            "border-bottom:1px solid rgba(128,128,128,0.24);"
            "font-size:0.78rem;"
            "font-weight:750;"
            "letter-spacing:0.04em;"
            "opacity:0.68;"
            "text-transform:uppercase;"
            "}"

            ".tournament-overview-row {"
            "min-height:4.2rem;"
            "border-bottom:1px solid rgba(128,128,128,0.20);"
            "}"
            "border:1px solid rgba(128,128,128,0.30);"
            "border-radius:0.8rem;"
            "overflow:hidden;"
            "}"

            ".tournament-overview-header,"
            ".tournament-overview-row {"
            "display:grid;"
            "grid-template-columns:7rem 10rem minmax(12rem,18rem) 5rem;"
            "align-items:center;"
            "gap:1.25rem;"
            "padding:0.75rem 1rem;"
            "}"

            ".tournament-overview-header {"
            "min-height:3rem;"
            "background:rgba(128,128,128,0.08);"
            "border-bottom:1px solid rgba(128,128,128,0.24);"
            "font-size:0.78rem;"
            "font-weight:750;"
            "letter-spacing:0.04em;"
            "opacity:0.68;"
            "text-transform:uppercase;"
            "}"

            ".tournament-overview-row {"
            "min-height:3.6rem;"
            "border-bottom:1px solid rgba(128,128,128,0.20);"
            "}"

            ".tournament-overview-row:last-child {"
            "border-bottom:none;"
            "}"

            ".tournament-overview-name {"
            "font-size:1.1rem;"
            "font-weight:800;"
            "}"

            ".tournament-overview-date {"
            "font-size:0.88rem;"
            "font-weight:700;"
            "opacity:0.68;"
            "}"

            ".tournament-overview-champion {"
            "font-size:1.1rem;"
            "font-weight:800;"
            "}"

            ".tournament-overview-players {"
            "font-weight:750;"
            "text-align:right;"
            "}"
            ".tournament-overview-header-players {"
            "text-align:right;"
            "}"

            "@media (max-width:768px) {"

            ".tournament-overview-header,"
            ".tournament-overview-row {"
            "grid-template-columns:var(--mobile-table-columns);"
            "gap:var(--mobile-table-gap);"
            "padding:var(--mobile-table-padding);"
            "min-height:var(--mobile-table-height);"
            "}"

            ".tournament-overview-date,"
            ".tournament-overview-header-date {"
            "display:none;"
            "}"

            ".tournament-overview-header-name {"
            "white-space:nowrap;"
            "}"

            ".tournament-overview-name {"
            "font-size:0.95rem;"
            "}"

            ".tournament-overview-champion,"
            ".tournament-overview-header-champion {"
            "text-align:center;"
            "}"

            ".tournament-overview-champion {"
            "font-size:0.98rem;"
            "min-width:0;"
            "overflow:hidden;"
            "text-overflow:ellipsis;"
            "white-space:nowrap;"
            "}"

            ".tournament-overview-players,"
            ".tournament-overview-header-players {"
            "text-align:right;"
            "}"

            "}"

            "</style>"

            "<div class='tournament-overview-list'>"

            "<div class='tournament-overview-header'>"
            "<div class='tournament-overview-header-name'>"
            "Tournament"
            "</div>"
            "<div class='tournament-overview-header-date'>"
            "Date"
            "</div>"
            "<div class='tournament-overview-header-champion'>"
            "Champion"
            "</div>"
            "<div class='tournament-overview-header-players'>"
            "Players"
            "</div>"
            "</div>"

            f"{''.join(tournament_rows_html)}"

            "</div>"
        )

        st.markdown(
            tournament_overview_html,
            unsafe_allow_html=True,
        )

        st.markdown(
            (
                "<div style='"
                "margin-top:2rem;"
                "margin-bottom:0.75rem;"
                "font-size:1.5rem;"
                "font-weight:800;"
                "'>"
                "Title Leaders"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        title_counts = (
            tournament_df["Champion"]
            .value_counts()
            .rename_axis("Player")
            .reset_index(name="Titles")
        )

        title_counts["Rank"] = (
            title_counts["Titles"]
            .rank(
                method="min",
                ascending=False,
            )
            .astype(int)
        )

        title_rows_html: list[str] = []

        title_icons = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        for _, row in title_counts.iterrows():
            rank = int(row["Rank"])
            player = str(row["Player"])
            titles = int(row["Titles"])

            title_label = (
                "Title"
                if titles == 1
                else "Titles"
            )

            rank_text = (
                f"{title_icons.get(rank, '')} #{rank}".strip()
            )

            title_rows_html.append(
                (
                    "<div class='title-leader-row'>"
                    "<div class='title-leader-rank'>"
                    f"{html.escape(rank_text)}"
                    "</div>"
                    "<div class='title-leader-player'>"
                    f"{html.escape(player)}"
                    "</div>"
                    "<div class='title-leader-count'>"
                    f"{titles} {title_label}"
                    "</div>"
                    "</div>"
                )
            )

        title_leaders_html = (
            "<style>"

            ".title-leader-list {"
            "border:1px solid rgba(128,128,128,0.30);"
            "border-radius:0.8rem;"
            "overflow:hidden;"
            "}"

            ".title-leader-row {"
            "display:grid;"
            "grid-template-columns:5.5rem minmax(8rem,2fr) "
            "minmax(7rem,1fr);"
            "align-items:center;"
            "min-height:4.2rem;"
            "padding:0.7rem 1rem;"
            "border-bottom:1px solid rgba(128,128,128,0.20);"
            "gap:0.75rem;"
            "}"

            ".title-leader-row:last-child {"
            "border-bottom:none;"
            "}"

            ".title-leader-rank {"
            "font-weight:800;"
            "text-align:right;"
            "}"

            ".title-leader-player {"
            "font-size:1.1rem;"
            "font-weight:800;"
            "}"

            ".title-leader-count {"
            "font-weight:750;"
            "text-align:right;"
            "}"

            "@media (max-width:768px) {"

            ".title-leader-row {"
            "grid-template-columns:var(--mobile-table-columns);"
            "gap:var(--mobile-table-gap);"
            "padding:var(--mobile-table-padding);"
            "min-height:var(--mobile-table-height);"
            "}"

            ".title-leader-rank {"
            "padding-right:1.9rem;"
            "white-space:nowrap;"
            "}"

            "}"

            "</style>"

            "<div class='title-leader-list'>"
            f"{''.join(title_rows_html)}"
            "</div>"
        )

        st.markdown(
            title_leaders_html,
            unsafe_allow_html=True,
        )

    else:
        st.info(
            "No tournaments are available yet."
        )


def player_initials(name: str) -> str:
    """Creates compact initials for the profile avatar."""

    parts = [part for part in name.replace("-", " ").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def tournament_elo_changes(
    tournament_number: int,
    participants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Calculates Elo and ranking changes for tournament participants."""

    changes: list[dict[str, Any]] = []

    for participant in participants:
        player_id = str(participant["player_id"])
        timeline = load_player_timeline(player_id)
        current_index = next(
            (
                index
                for index, entry in enumerate(timeline)
                if int(entry["tournament_number"]) == tournament_number
            ),
            None,
        )
        if current_index is None:
            continue

        current = timeline[current_index]
        previous = timeline[current_index - 1] if current_index > 0 else None
        elo_before = (
            float(previous["elo_exact"])
            if previous is not None
            else 1000.0
        )
        elo_after = float(current["elo_exact"])
        rank_before = (
            int(previous["rank"])
            if previous is not None and previous.get("rank") is not None
            else None
        )
        rank_after = (
            int(current["rank"])
            if current.get("rank") is not None
            else None
        )

        changes.append(
            {
                "Players": str(participant["player"]),
                "Elo Before": elo_before,
                "Elo After": elo_after,
                "Elo Change": elo_after - elo_before,
                "Rank Before": rank_before,
                "Rank After": rank_after,
            }
        )

    return sorted(
        changes,
        key=lambda row: float(row["Elo Change"]),
        reverse=True,
    )


def show_player_page(include_inactive: bool) -> None:
    st.title("👤 Player profile")

    players = load_players(include_inactive)
    if not players:
        st.warning("No players found.")
        return

    player_by_name = {
        player["display_name"]: str(player["player_id"])
        for player in players
    }

    player_names = list(
        player_by_name
    )

    requested_player = st.query_params.get(
        "player"
    )

    if (
        requested_player in player_by_name
        and st.session_state.get("selected_player_name")
        != requested_player
    ):
        st.session_state["selected_player_name"] = (
            requested_player
        )

    if (
        st.session_state.get("selected_player_name")
        not in player_by_name
    ):
        st.session_state["selected_player_name"] = (
            player_names[0]
        )

    def update_selected_player_url() -> None:
        st.query_params["page"] = "Players"
        st.query_params["player"] = (
            st.session_state["selected_player_name"]
        )



    st.markdown(
        """
        <style>
        div[data-testid="stSelectbox"] {
            margin-bottom:0.25rem;
        }

        div[data-testid="stSelectbox"] label {
            font-size:0.95rem;
            font-weight:800;
            letter-spacing:0.02em;
            opacity:0.88;
            margin-bottom:0.45rem;
        }

        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div {
            min-height:3.7rem;
            border-radius:0.7rem;
            border-color:rgba(128,128,128,0.34);
            background:rgba(128,128,128,0.07);
            font-size:1.1rem;
            font-weight:750;
        }

        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div:hover {
            border-color:rgba(128,128,128,0.48);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


    selected_name = st.selectbox(
        "Select player",
        options=player_names,
        key="selected_player_name",
        on_change=update_selected_player_url,
    )

    st.divider()



    player_id = player_by_name[selected_name]

    profile = load_player_profile(player_id)
    timeline = load_player_timeline(
        player_id,
        include_inactive,
    )
    history = load_player_history(player_id)

    ranking = load_elo_ranking(include_inactive)
    current_rank = next(
        (
            entry["rank"]
            for entry in ranking
            if str(entry["player_id"]) == player_id
        ),
        None,
    )

    safe_name = html.escape(str(profile["player"]))
    initials = html.escape(player_initials(str(profile["player"])))
    rank_text = f"#{current_rank}" if current_rank is not None else "–"

    current_elo = float(profile.get("current_elo") or 1000.0)
    peak_elo = float(profile.get("peak_elo") or 1000.0)

    title_count = int(
        profile.get("titles") or 0
    )

    title_text = (
        "World Champion"
        if title_count == 1
        else "World Championships"
    )

    selected_player_data = next(
        (
            player
            for player in players
            if str(player["player_id"]) == player_id
        ),
        {},
    )

    player_status = (
        "Active player"
        if bool(selected_player_data.get("active"))
        else "Inactive player"
    )

    status_class = (
        "player-header-status-active"
        if bool(selected_player_data.get("active"))
        else "player-header-status-inactive"
    )

    player_header_html = (
        "<style>"

        ".player-profile-header {"
        "display:grid;"
        "grid-template-columns:auto minmax(12rem, 1fr) auto;"
        "align-items:center;"
        "gap:1.5rem;"
        "min-height:9rem;"
        "padding:1.3rem 1.5rem;"
        "margin:0.1rem 0 1.25rem 0;"
        "border:1px solid rgba(128,128,128,0.28);"
        "border-radius:1rem;"
        "}"

        ".player-profile-avatar {"
        "width:5rem;"
        "height:5rem;"
        "border-radius:50%;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "background:rgba(128,128,128,0.18);"
        "font-size:1.65rem;"
        "font-weight:800;"
        "flex:0 0 auto;"
        "}"

        ".player-profile-name {"
        "font-size:2rem;"
        "font-weight:800;"
        "line-height:1.1;"
        "}"

        ".player-profile-meta {"
        "display:flex;"
        "align-items:center;"
        "gap:0.65rem;"
        "flex-wrap:wrap;"
        "margin-top:0.7rem;"
        "}"

        ".player-profile-status {"
        "display:inline-flex;"
        "align-items:center;"
        "padding:0.25rem 0.55rem;"
        "border-radius:999px;"
        "font-size:0.75rem;"
        "font-weight:750;"
        "}"

        ".player-header-status-active {"
        "color:#3fb950;"
        "background:rgba(63,185,80,0.10);"
        "border:1px solid rgba(63,185,80,0.22);"
        "}"

        ".player-header-status-inactive {"
        "color:rgba(255,255,255,0.58);"
        "background:rgba(128,128,128,0.08);"
        "border:1px solid rgba(128,128,128,0.20);"
        "}"

        ".player-profile-description {"
        "font-size:0.9rem;"
        "font-weight:650;"
        "opacity:0.62;"
        "}"

        ".player-profile-current-stats {"
        "display:grid;"
        "grid-template-columns:repeat(3, minmax(7rem, auto));"
        "align-items:center;"
        "}"

        ".player-profile-current-stat {"
        "min-width:6.5rem;"
        "padding:0.4rem 1rem;"
        "text-align:center;"
        "border-left:1px solid rgba(128,128,128,0.22);"
        "}"

        ".player-profile-current-stat:first-child {"
        "border-left:none;"
        "}"

        ".player-profile-current-label {"
        "font-size:0.72rem;"
        "font-weight:750;"
        "letter-spacing:0.04em;"
        "opacity:0.58;"
        "}"

        ".player-profile-current-value {"
        "font-size:1.55rem;"
        "font-weight:800;"
        "line-height:1;"
        "margin-top:0.55rem;"
        "}"

        "@media (max-width:1050px) {"

        ".player-profile-header {"
        "grid-template-columns:auto minmax(0, 1fr);"
        "}"

        ".player-profile-current-stats {"
        "grid-column:1 / -1;"
        "width:100%;"
        "margin-top:0.25rem;"
        "padding-top:1rem;"
        "border-top:1px solid rgba(128,128,128,0.20);"
        "grid-template-columns:repeat(3, minmax(0, 1fr));"
        "}"

        ".player-profile-current-stat {"
        "min-width:0;"
        "padding:0.4rem 0.75rem;"
        "}"

        ".player-profile-current-label {"
        "white-space:nowrap;"
        "}"

        ".player-profile-current-value {"
        "white-space:nowrap;"
        "}"

        "}"

        "@media (max-width:520px) {"

        ".player-profile-header {"
        "grid-template-columns:1fr;"
        "text-align:center;"
        "}"

        ".player-profile-avatar {"
        "margin:auto;"
        "}"

        ".player-profile-meta {"
        "justify-content:center;"
        "}"

        ".player-profile-current-stat {"
        "min-width:0;"
        "padding:0.4rem 0.5rem;"
        "}"

        "}"

        "</style>"

        "<div class='player-profile-header'>"

        "<div class='player-profile-avatar'>"
        f"{initials}"
        "</div>"

        "<div class='player-profile-identity'>"
        "<div class='player-profile-name'>"
        f"{safe_name}"
        "</div>"

        "<div class='player-profile-meta'>"
        "<span class='player-profile-status "
        f"{status_class}'>"
        f"{html.escape(player_status)}"
        "</span>"

        "<span class='player-profile-description'>"
        f"{title_count} {html.escape(title_text)}"
        "</span>"
        "</div>"
        "</div>"

        "<div class='player-profile-current-stats'>"

        "<div class='player-profile-current-stat'>"
        "<div class='player-profile-current-label'>"
        "CURRENT RANK"
        "</div>"
        "<div class='player-profile-current-value'>"
        f"{html.escape(rank_text)}"
        "</div>"
        "</div>"

        "<div class='player-profile-current-stat'>"
        "<div class='player-profile-current-label'>"
        "CURRENT ELO"
        "</div>"
        "<div class='player-profile-current-value'>"
        f"{current_elo:.1f}"
        "</div>"
        "</div>"

        "<div class='player-profile-current-stat'>"
        "<div class='player-profile-current-label'>"
        "TITLES"
        "</div>"
        "<div class='player-profile-current-value'>"
        f"{title_count}"
        "</div>"
        "</div>"

        "</div>"
        "</div>"
    )

    st.markdown(
        player_header_html,
        unsafe_allow_html=True,
    )

    appearances = int(
        profile.get("appearances") or 0
    )

    decided_matches = int(
        profile.get("decided_matches") or 0
    )

    winrate = profile.get(
        "winrate"
    )

    winrate_text = (
        f"{float(winrate):.1f}%"
        if winrate is not None
        else "–"
    )

    career_overview_html = (
        "<style>"

        ".career-overview-strip {"
        "display:grid;"
        "grid-template-columns:repeat(4, minmax(0, 1fr));"
        "border:1px solid rgba(128,128,128,0.28);"
        "border-radius:0.8rem 0.8rem 0 0;"
        "overflow:hidden;"
        "margin:0;"
        "}"

        ".career-overview-item {"
        "display:flex;"
        "flex-direction:column;"
        "align-items:center;"
        "justify-content:center;"
        "min-height:7rem;"
        "padding:0.9rem 1rem;"
        "text-align:center;"
        "border-left:1px solid rgba(128,128,128,0.20);"
        "}"

        ".career-overview-item:first-child {"
        "border-left:none;"
        "}"

        ".career-overview-label {"
        "font-size:0.74rem;"
        "font-weight:750;"
        "letter-spacing:0.04em;"
        "opacity:0.58;"
        "text-transform:uppercase;"
        "}"

        ".career-overview-value {"
        "font-size:1.7rem;"
        "font-weight:800;"
        "line-height:1;"
        "margin-top:0.75rem;"
        "}"

        ".career-overview-detail {"
        "font-size:0.76rem;"
        "font-weight:650;"
        "opacity:0.52;"
        "margin-top:0.5rem;"
        "}"

        ".career-overview-peak {"
        "background:rgba(242,201,76,0.04);"
        "}"

        ".career-overview-peak "
        ".career-overview-value {"
        "color:#f2c94c;"
        "}"

        "@media (max-width:800px) {"

        ".career-overview-strip {"
        "grid-template-columns:repeat(2, minmax(0, 1fr));"
        "}"

        ".career-overview-item:nth-child(3) {"
        "border-left:none;"
        "border-top:1px solid rgba(128,128,128,0.20);"
        "}"

        ".career-overview-item:nth-child(4) {"
        "border-top:1px solid rgba(128,128,128,0.20);"
        "}"

        "}"

        "@media (max-width:520px) {"

        ".career-overview-strip {"
        "grid-template-columns:1fr;"
        "}"

        ".career-overview-item {"
        "border-left:none;"
        "border-top:1px solid rgba(128,128,128,0.20);"
        "}"

        ".career-overview-item:first-child {"
        "border-top:none;"
        "}"

        "}"

        "</style>"

        "<div class='career-overview-strip'>"

        "<div class='career-overview-item "
        "career-overview-peak'>"
        "<div class='career-overview-label'>"
        "PEAK ELO"
        "</div>"
        "<div class='career-overview-value'>"
        f"{peak_elo:.1f}"
        "</div>"
        "<div class='career-overview-detail'>"
        "Career high"
        "</div>"
        "</div>"

        "<div class='career-overview-item'>"
        "<div class='career-overview-label'>"
        "APPEARANCES"
        "</div>"
        "<div class='career-overview-value'>"
        f"{appearances}"
        "</div>"
        "<div class='career-overview-detail'>"
        "Tournaments"
        "</div>"
        "</div>"

        "<div class='career-overview-item'>"
        "<div class='career-overview-label'>"
        "SETS"
        "</div>"
        "<div class='career-overview-value'>"
        f"{decided_matches}"
        "</div>"
        "<div class='career-overview-detail'>"
        "Recorded"
        "</div>"
        "</div>"

        "<div class='career-overview-item'>"
        "<div class='career-overview-label'>"
        "WIN RATE"
        "</div>"
        "<div class='career-overview-value'>"
        f"{html.escape(winrate_text)}"
        "</div>"
        "<div class='career-overview-detail'>"
        "Career"
        "</div>"
        "</div>"

        "</div>"
    )

    st.markdown(
        career_overview_html,
        unsafe_allow_html=True,
    )

    insights = load_player_insights(player_id)



    career_summary = narratives.generate_player_summary(
        profile,
        insights,
        current_rank,
    )

    summary_sentences = [
        sentence.strip()
        for sentence in career_summary.split(". ")
        if sentence.strip()
    ]

    summary_paragraphs: list[str] = []

    for index in range(
        0,
        len(summary_sentences),
        2,
    ):
        paragraph_sentences = (
            summary_sentences[index:index + 2]
        )

        paragraph = ". ".join(
            paragraph_sentences
        )

        if not paragraph.endswith("."):
            paragraph += "."

        summary_paragraphs.append(
            (
                "<p style='"
                "margin:0 0 0.9rem 0;"
                "'>"
                f"{html.escape(paragraph)}"
                "</p>"
            )
        )

    career_summary_text_html = "".join(
        summary_paragraphs
    )

    st.markdown(
        (
            "<style>"

            ".player-career-summary {"
            "display:grid;"
            "grid-template-columns:7rem minmax(0, 1fr);"
            "gap:1.5rem;"
            "align-items:start;"
            "padding:1.25rem 1.45rem;"
            "margin:0 0 1rem 0;"
            "border-radius:0 0 0.8rem 0.8rem;"
            "background:rgba(28,74,112,0.55);"
            "border:1px solid rgba(70,150,220,0.18);"
            "border-top:none;"
            "}"

            ".player-career-summary-label {"
            "font-size:0.78rem;"
            "font-weight:750;"
            "letter-spacing:0.04em;"
            "opacity:0.72;"
            "padding-top:0.15rem;"
            "}"

            ".player-career-summary-text {"
            "font-size:1rem;"
            "line-height:1.75;"
            "}"

            ".player-career-summary-text p:last-child {"
            "margin-bottom:0 !important;"
            "}"

            "@media (max-width:800px) {"

            ".player-career-summary {"
            "grid-template-columns:1fr;"
            "gap:0.75rem;"
            "padding:1.25rem 1.4rem;"
            "}"

            "}"

            "</style>"

            "<div class='player-career-summary'>"

            "<div class='player-career-summary-label'>"
            "CAREER<br>SUMMARY"
            "</div>"

            "<div class='player-career-summary-text'>"
            f"{career_summary_text_html}"
            "</div>"

            "</div>"
        ),
        unsafe_allow_html=True,
    )




    featured_rivalry = insights.get(
        "featured_rivalry"
    )
    nemesis = insights.get(
        "nemesis"
    )

    if featured_rivalry:
        rivalry_name = str(
            featured_rivalry["opponent"]
        )
        rivalry_record = (
            f"{featured_rivalry['wins']}–"
            f"{featured_rivalry['losses']} all-time"
        )
        rivalry_detail = (
            f"{featured_rivalry['matches']} sets"
        )
    else:
        rivalry_name = "–"
        rivalry_record = "No rivalry available"
        rivalry_detail = "–"

    if nemesis:
        nemesis_name = str(
            nemesis["opponent"]
        )
        nemesis_record = (
            f"{nemesis['wins']}–"
            f"{nemesis['losses']} record"
        )
        nemesis_detail = (
            f"{nemesis['winrate']:.1f}% win rate"
        )
    else:
        nemesis_name = "–"
        nemesis_record = "No nemesis available"
        nemesis_detail = "–"

    win_streak = int(
        insights["longest_win_streak"]
    )

    loss_streak = int(
        insights["longest_loss_streak"]
    )




    player_insights_html = (
        "<style>"

        ".player-insight-grid {"
        "display:grid;"
        "grid-template-columns:repeat(2, minmax(0, 1fr));"
        "gap:1rem;"
        "margin-top:1rem;"
        "margin-bottom:1.25rem;"
        "}"

        ".player-matchup-card {"
        "display:flex;"
        "flex-direction:column;"
        "min-height:8rem;"
        "padding:1.15rem 1.25rem;"
        "border:1px solid rgba(128,128,128,0.30);"
        "border-radius:0.8rem;"
        "}"

        ".player-rivalry-card {"
        "border-color:rgba(70,150,220,0.25);"
        "background:rgba(70,150,220,0.035);"
        "}"

        ".player-nemesis-card {"
        "border-color:rgba(248,81,73,0.30);"
        "background:rgba(248,81,73,0.045);"
        "}"

        ".player-insight-label {"
        "font-size:0.76rem;"
        "font-weight:750;"
        "letter-spacing:0.04em;"
        "opacity:0.62;"
        "text-transform:uppercase;"
        "}"

        ".player-insight-value {"
        "font-size:1.55rem;"
        "font-weight:800;"
        "line-height:1.15;"
        "margin-top:0.9rem;"
        "}"

        ".player-insight-record {"
        "font-size:0.95rem;"
        "font-weight:750;"
        "margin-top:auto;"
        "padding-top:0.8rem;"
        "}"

        ".player-insight-detail {"
        "font-size:0.8rem;"
        "font-weight:650;"
        "opacity:0.58;"
        "margin-top:0.2rem;"
        "}"

        ".player-streak-strip {"
        "grid-column:1 / -1;"
        "display:grid;"
        "grid-template-columns:repeat(2, minmax(0, 1fr));"
        "border:1px solid rgba(128,128,128,0.30);"
        "border-radius:0.8rem;"
        "overflow:hidden;"
        "}"

        ".player-streak-item {"
        "display:grid;"
        "grid-template-columns:minmax(0, 1fr) auto;"
        "align-items:center;"
        "gap:1rem;"
        "min-height:6rem;"
        "padding:1rem 1.25rem;"
        "}"

        ".player-streak-item + "
        ".player-streak-item {"
        "border-left:1px solid rgba(128,128,128,0.22);"
        "}"

        ".player-streak-description {"
        "font-size:0.82rem;"
        "font-weight:650;"
        "opacity:0.58;"
        "margin-top:0.25rem;"
        "}"

        ".player-streak-value {"
        "font-size:1.9rem;"
        "font-weight:800;"
        "line-height:1;"
        "}"

        ".player-win-streak-value {"
        "color:#3fb950;"
        "}"

        ".player-loss-streak-value {"
        "color:#f85149;"
        "}"

        "@media (max-width:750px) {"

        ".player-insight-grid {"
        "grid-template-columns:1fr;"
        "}"

        ".player-streak-strip {"
        "grid-column:auto;"
        "grid-template-columns:1fr;"
        "}"

        ".player-streak-item + "
        ".player-streak-item {"
        "border-left:none;"
        "border-top:1px solid rgba(128,128,128,0.22);"
        "}"

        "}"

        "</style>"

        "<div class='player-insight-grid'>"

        "<div class='player-matchup-card "
        "player-rivalry-card'>"
        "<div class='player-insight-label'>"
        "FEATURED RIVALRY"
        "</div>"
        "<div class='player-insight-value'>"
        f"{html.escape(rivalry_name)}"
        "</div>"
        "<div class='player-insight-record'>"
        f"{html.escape(rivalry_record)}"
        "</div>"
        "<div class='player-insight-detail'>"
        f"{html.escape(rivalry_detail)}"
        "</div>"
        "</div>"

        "<div class='player-matchup-card "
        "player-nemesis-card'>"
        "<div class='player-insight-label'>"
        "NEMESIS"
        "</div>"
        "<div class='player-insight-value'>"
        f"{html.escape(nemesis_name)}"
        "</div>"
        "<div class='player-insight-record'>"
        f"{html.escape(nemesis_record)}"
        "</div>"
        "<div class='player-insight-detail'>"
        f"{html.escape(nemesis_detail)}"
        "</div>"
        "</div>"

        "<div class='player-streak-strip'>"

        "<div class='player-streak-item'>"
        "<div>"
        "<div class='player-insight-label'>"
        "LONGEST WIN STREAK"
        "</div>"
        "<div class='player-streak-description'>"
        "Consecutive set wins"
        "</div>"
        "</div>"
        "<div class='player-streak-value "
        "player-win-streak-value'>"
        f"{win_streak}"
        "</div>"
        "</div>"

        "<div class='player-streak-item'>"
        "<div>"
        "<div class='player-insight-label'>"
        "LONGEST LOSING STREAK"
        "</div>"
        "<div class='player-streak-description'>"
        "Consecutive set losses"
        "</div>"
        "</div>"
        "<div class='player-streak-value "
        "player-loss-streak-value'>"
        f"{loss_streak}"
        "</div>"
        "</div>"

        "</div>"
        "</div>"
    )

    st.markdown(
        player_insights_html,
        unsafe_allow_html=True,
    )







    tab_elo, tab_rank, tab_history, tab_opponents = st.tabs(
        ["Elo History", "Ranking History", "Tournament History", "Opponent Records"]
    )

    with tab_elo:
        best_elo_event = insights["best_elo_event"]

        if best_elo_event:
            change = float(
                best_elo_event.get(
                    "elo_change",
                    0,
                )
            )

            jump_tournament = str(
                best_elo_event.get(
                    "tournament",
                    "Unknown tournament",
                )
            )

            elo_jump_html = (
                "<style>"

                ".elo-jump-highlight {"
                "display:flex;"
                "align-items:center;"
                "justify-content:space-between;"
                "gap:1rem;"
                "padding:0.9rem 1.1rem;"
                "margin:0.35rem 0 1rem 0;"
                "border:1px solid rgba(70,150,220,0.24);"
                "border-radius:0.8rem;"
                "background:rgba(70,150,220,0.045);"
                "}"

                ".elo-jump-label {"
                "font-size:0.76rem;"
                "font-weight:750;"
                "letter-spacing:0.04em;"
                "opacity:0.62;"
                "text-transform:uppercase;"
                "}"

                ".elo-jump-detail {"
                "font-size:0.82rem;"
                "font-weight:650;"
                "opacity:0.58;"
                "margin-top:0.2rem;"
                "}"

                ".elo-jump-value {"
                "font-size:1.45rem;"
                "font-weight:800;"
                "color:#5b9bd5;"
                "white-space:nowrap;"
                "}"

                "@media (max-width:560px) {"

                ".elo-jump-highlight {"
                "align-items:flex-start;"
                "flex-direction:column;"
                "}"

                "}"

                "</style>"

                "<div class='elo-jump-highlight'>"

                "<div>"
                "<div class='elo-jump-label'>"
                "BIGGEST ELO JUMP"
                "</div>"
                "<div class='elo-jump-detail'>"
                f"Recorded at {html.escape(jump_tournament)}"
                "</div>"
                "</div>"

                "<div class='elo-jump-value'>"
                f"{change:+.1f}"
                "</div>"

                "</div>"
            )

            st.markdown(
                elo_jump_html,
                unsafe_allow_html=True,
            )




        if timeline:
            timeline_df = (
                pd.DataFrame(timeline)
                .sort_values("tournament_number")
                .reset_index(drop=True)
            )

            tournament_order = (
                timeline_df["tournament"]
                .tolist()
            )

            elo_segment_rows: list[
                dict[str, Any]
            ] = []

            timeline_records = (
                timeline_df.to_dict("records")
            )

            for previous, current in zip(
                timeline_records,
                timeline_records[1:],
            ):
                elo_segment_rows.append(
                    {
                        "start_tournament":
                            previous["tournament"],
                        "end_tournament":
                            current["tournament"],
                        "start_elo":
                            previous["elo"],
                        "end_elo":
                            current["elo"],
                        "segment_type": (
                            "Played"
                            if bool(
                                current[
                                    "played_in_tournament"
                                ]
                            )
                            else "Did not participate"
                        ),
                    }
                )

            elo_segment_df = pd.DataFrame(
                elo_segment_rows
            )

            peak_row = timeline_df.loc[
                timeline_df["elo"].idxmax()
            ]
            peak_elo_raw: Any = peak_row["elo"]
            peak_elo_value = float(peak_elo_raw)

            player_chart_color = "#83c9ff"

            solid_elo_segments = (
                alt.Chart(
                    elo_segment_df[
                        elo_segment_df[
                            "segment_type"
                        ] == "Played"
                    ]
                )
                .mark_rule(
                    strokeWidth=3,
                    color=player_chart_color,
                )
                .encode(
                    x=alt.X(
                        "start_tournament:N",
                        title="Tournament",
                        sort=tournament_order,
                    ),
                    x2="end_tournament:N",
                    y=alt.Y(
                        "start_elo:Q",
                        title="Elo",
                        scale=alt.Scale(
                            zero=False,
                        ),
                    ),
                    y2="end_elo:Q",
                )
            )

            dashed_elo_segments = (
                alt.Chart(
                    elo_segment_df[
                        elo_segment_df[
                            "segment_type"
                        ]
                        == "Did not participate"
                    ]
                )
                .mark_rule(
                    strokeWidth=3,
                    strokeDash=[7, 5],
                    color=player_chart_color,
                )
                .encode(
                    x=alt.X(
                        "start_tournament:N",
                        title="Tournament",
                        sort=tournament_order,
                    ),
                    x2="end_tournament:N",
                    y=alt.Y(
                        "start_elo:Q",
                        title="Elo",
                        scale=alt.Scale(
                            zero=False,
                        ),
                    ),
                    y2="end_elo:Q",
                )
            )

            played_elo_points = (
                alt.Chart(
                    timeline_df[
                        timeline_df[
                            "played_in_tournament"
                        ]
                    ]
                )
                .mark_point(
                    filled=True,
                    size=95,
                    color=player_chart_color,
                    strokeWidth=2,
                )
                .encode(
                    x=alt.X(
                        "tournament:N",
                        title="Tournament",
                        sort=tournament_order,
                    ),
                    y=alt.Y(
                        "elo:Q",
                        title="Elo",
                        scale=alt.Scale(
                            zero=False,
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip(
                            "tournament:N",
                            title="Tournament",
                        ),
                        alt.Tooltip(
                            "tournament_date:N",
                            title="Date",
                        ),
                        alt.Tooltip(
                            "elo:Q",
                            title="Elo",
                            format=".1f",
                        ),
                        alt.Tooltip(
                            "rank:Q",
                            title="Rank",
                        ),
                        alt.Tooltip(
                            "played_in_tournament:N",
                            title="Participated",
                        ),
                    ],
                )
            )

            missed_elo_points = (
                alt.Chart(
                    timeline_df[
                        ~timeline_df[
                            "played_in_tournament"
                        ]
                    ]
                )
                .mark_point(
                    filled=False,
                    size=95,
                    strokeWidth=3,
                    color=player_chart_color,
                )
                .encode(
                    x=alt.X(
                        "tournament:N",
                        title="Tournament",
                        sort=tournament_order,
                    ),
                    y=alt.Y(
                        "elo:Q",
                        title="Elo",
                        scale=alt.Scale(
                            zero=False,
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip(
                            "tournament:N",
                            title="Tournament",
                        ),
                        alt.Tooltip(
                            "tournament_date:N",
                            title="Date",
                        ),
                        alt.Tooltip(
                            "elo:Q",
                            title="Elo",
                            format=".1f",
                        ),
                        alt.Tooltip(
                            "rank:Q",
                            title="Rank",
                        ),
                        alt.Tooltip(
                            "played_in_tournament:N",
                            title="Participated",
                        ),
                    ],
                )
            )

            peak_elo_point = (
                alt.Chart(
                    pd.DataFrame(
                        [
                            {
                                "tournament":
                                    peak_row[
                                        "tournament"
                                    ],
                                "elo":
                                    float(
                                        peak_elo_value
                                    ),
                                "label": (
                                    f"Peak Elo: "
                                    f"{float(peak_elo_value):.1f}"
                                ),
                            }
                        ]
                    )
                )
                .mark_point(
                    filled=False,
                    size=165,
                    stroke="#f2c94c",
                    strokeWidth=3.5,
                )
                .encode(
                    x=alt.X(
                        "tournament:N",
                        sort=tournament_order,
                    ),
                    y=alt.Y(
                        "elo:Q",
                        scale=alt.Scale(
                            zero=False,
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip(
                            "label:N",
                            title=None,
                        ),
                    ],
                )
            )

            elo_chart = (
                solid_elo_segments
                + dashed_elo_segments
                + played_elo_points
                + missed_elo_points
                + peak_elo_point
            ).properties(
                height=500,
            )

            peak_elo_summary_html = (
                "<style>"

                ".elo-summary-grid {"
                "display:grid;"
                "grid-template-columns:repeat(2, minmax(0, 1fr));"
                "gap:1rem;"
                "margin:0.5rem 0 1.25rem 0;"
                "}"

                ".elo-summary-card {"
                "display:flex;"
                "align-items:center;"
                "justify-content:space-between;"
                "gap:1rem;"
                "min-height:5rem;"
                "padding:1rem 1.15rem;"
                "border:1px solid rgba(128,128,128,0.28);"
                "border-radius:0.8rem;"
                "background:rgba(128,128,128,0.035);"
                "}"

                ".elo-summary-label {"
                "font-size:0.76rem;"
                "font-weight:750;"
                "letter-spacing:0.04em;"
                "opacity:0.58;"
                "text-transform:uppercase;"
                "}"

                ".elo-summary-detail {"
                "font-size:0.82rem;"
                "font-weight:650;"
                "opacity:0.58;"
                "margin-top:0.25rem;"
                "}"

                ".elo-summary-value {"
                "font-size:1.75rem;"
                "font-weight:800;"
                "line-height:1;"
                "white-space:nowrap;"
                "}"

                ".elo-summary-highlight {"
                "border-color:rgba(242,201,76,0.28);"
                "background:rgba(242,201,76,0.045);"
                "}"

                ".elo-summary-highlight "
                ".elo-summary-value {"
                "color:#f2c94c;"
                "}"

                "@media (max-width:650px) {"

                ".elo-summary-grid {"
                "grid-template-columns:1fr;"
                "}"

                "}"

                "</style>"

                "<div class='elo-summary-grid'>"

                "<div class='elo-summary-card "
                "elo-summary-highlight'>"
                "<div>"
                "<div class='elo-summary-label'>"
                "PEAK ELO"
                "</div>"
                "<div class='elo-summary-detail'>"
                "Highest career rating"
                "</div>"
                "</div>"
                "<div class='elo-summary-value'>"
                f"{peak_elo_value:.1f}"
                "</div>"
                "</div>"

                "<div class='elo-summary-card'>"
                "<div>"
                "<div class='elo-summary-label'>"
                "PEAK REACHED AT"
                "</div>"
                "<div class='elo-summary-detail'>"
                "First tournament at this rating"
                "</div>"
                "</div>"
                "<div class='elo-summary-value'>"
                f"{html.escape(str(peak_row['tournament']))}"
                "</div>"
                "</div>"

                "</div>"
            )

            st.markdown(
                peak_elo_summary_html,
                unsafe_allow_html=True,
            )



            st.altair_chart(
                elo_chart,
                use_container_width=True,
            )

            st.caption(
                "Dashed segments and hollow points indicate "
                "tournaments in which the player did not participate."
            )

        else:
            st.info(
                "No Elo history is available for this player yet."
            )

    with tab_rank:
        if timeline:
            timeline_df = (
                pd.DataFrame(timeline)
                .sort_values("tournament_number")
                .reset_index(drop=True)
            )

            tournament_order = (
                timeline_df["tournament"]
                .tolist()
            )

            max_rank = int(
                timeline_df["rank"].max()
            )

            min_rank = int(
                timeline_df["rank"].min()
            )

            axis_top = max(
                1,
                min_rank - 1,
            )

            axis_bottom = (
                max_rank + 1
            )

            rank_segment_rows: list[
                dict[str, Any]
            ] = []

            timeline_records = (
                timeline_df.to_dict("records")
            )

            for previous, current in zip(
                timeline_records,
                timeline_records[1:],
            ):
                rank_segment_rows.append(
                    {
                        "start_tournament":
                            previous["tournament"],
                        "end_tournament":
                            current["tournament"],
                        "start_rank":
                            previous["rank"],
                        "end_rank":
                            current["rank"],
                        "segment_type": (
                            "Played"
                            if bool(
                                current[
                                    "played_in_tournament"
                                ]
                            )
                            else "Did not participate"
                        ),
                    }
                )

            rank_segment_df = pd.DataFrame(
                rank_segment_rows
            )

            best_rank_row = timeline_df.loc[
                timeline_df["rank"].idxmin()
            ]

            best_rank_raw: Any = best_rank_row["rank"]
            best_rank_value = int(best_rank_raw)

            rank_scale = alt.Scale(
                domain=[
                    axis_bottom + 0.5,
                    axis_top - 0.5,
                ],
            )

            rank_axis = alt.Axis(
                values=list(
                    range(
                        axis_top,
                        axis_bottom + 1,
                    )
                ),
                format="d",
                tickMinStep=1,
                labelOverlap=False,
            )

            player_chart_color = "#83c9ff"

            solid_rank_segments = (
                alt.Chart(
                    rank_segment_df[
                        rank_segment_df[
                            "segment_type"
                        ] == "Played"
                    ]
                )
                .mark_rule(
                    strokeWidth=3,
                    color=player_chart_color,
                )
                .encode(
                    x=alt.X(
                        "start_tournament:N",
                        title="Tournament",
                        sort=tournament_order,
                    ),
                    x2="end_tournament:N",
                    y=alt.Y(
                        "start_rank:Q",
                        title="Rank",
                        scale=rank_scale,
                        axis=rank_axis,
                    ),
                    y2="end_rank:Q",
                )
            )

            dashed_rank_segments = (
                alt.Chart(
                    rank_segment_df[
                        rank_segment_df[
                            "segment_type"
                        ]
                        == "Did not participate"
                    ]
                )
                .mark_rule(
                    strokeWidth=3,
                    strokeDash=[7, 5],
                    color=player_chart_color,
                )
                .encode(
                    x=alt.X(
                        "start_tournament:N",
                        title="Tournament",
                        sort=tournament_order,
                    ),
                    x2="end_tournament:N",
                    y=alt.Y(
                        "start_rank:Q",
                        title="Rank",
                        scale=rank_scale,
                        axis=rank_axis,
                    ),
                    y2="end_rank:Q",
                )
            )

            played_rank_points = (
                alt.Chart(
                    timeline_df[
                        timeline_df[
                            "played_in_tournament"
                        ]
                    ]
                )
                .mark_point(
                    filled=True,
                    size=95,
                    color=player_chart_color,
                    strokeWidth=2,
                )
                .encode(
                    x=alt.X(
                        "tournament:N",
                        title="Tournament",
                        sort=tournament_order,
                    ),
                    y=alt.Y(
                        "rank:Q",
                        title="Rank",
                        scale=rank_scale,
                        axis=rank_axis,
                    ),
                    tooltip=[
                        alt.Tooltip(
                            "tournament:N",
                            title="Tournament",
                        ),
                        alt.Tooltip(
                            "tournament_date:N",
                            title="Date",
                        ),
                        alt.Tooltip(
                            "rank:Q",
                            title="Rank",
                        ),
                        alt.Tooltip(
                            "elo:Q",
                            title="Elo",
                            format=".1f",
                        ),
                        alt.Tooltip(
                            "played_in_tournament:N",
                            title="Participated",
                        ),
                    ],
                )
            )

            missed_rank_points = (
                alt.Chart(
                    timeline_df[
                        ~timeline_df[
                            "played_in_tournament"
                        ]
                    ]
                )
                .mark_point(
                    filled=False,
                    size=95,
                    strokeWidth=3,
                    color=player_chart_color,
                )
                .encode(
                    x=alt.X(
                        "tournament:N",
                        title="Tournament",
                        sort=tournament_order,
                    ),
                    y=alt.Y(
                        "rank:Q",
                        title="Rank",
                        scale=rank_scale,
                        axis=rank_axis,
                    ),
                    tooltip=[
                        alt.Tooltip(
                            "tournament:N",
                            title="Tournament",
                        ),
                        alt.Tooltip(
                            "tournament_date:N",
                            title="Date",
                        ),
                        alt.Tooltip(
                            "rank:Q",
                            title="Rank",
                        ),
                        alt.Tooltip(
                            "elo:Q",
                            title="Elo",
                            format=".1f",
                        ),
                        alt.Tooltip(
                            "played_in_tournament:N",
                            title="Participated",
                        ),
                    ],
                )
            )

            best_rank_point = (
                alt.Chart(
                    pd.DataFrame(
                        [
                            {
                                "tournament":
                                    best_rank_row[
                                        "tournament"
                                    ],
                                "rank":
                                    int(
                                        best_rank_value
                                    ),
                                "label": (
                                    f"Best rank: "
                                    f"#{int(best_rank_value)}"
                                ),
                            }
                        ]
                    )
                )
                .mark_point(
                    filled=False,
                    size=165,
                    stroke="#f2c94c",
                    strokeWidth=3.5,
                )
                .encode(
                    x=alt.X(
                        "tournament:N",
                        sort=tournament_order,
                    ),
                    y=alt.Y(
                        "rank:Q",
                        scale=rank_scale,
                        axis=rank_axis,
                    ),
                    tooltip=[
                        alt.Tooltip(
                            "label:N",
                            title=None,
                        ),
                    ],
                )
            )

            rank_chart = (
                solid_rank_segments
                + dashed_rank_segments
                + played_rank_points
                + missed_rank_points
                + best_rank_point
            ).properties(
                height=500,
            )

            best_rank_summary_html = (
                "<style>"

                ".rank-summary-grid {"
                "display:grid;"
                "grid-template-columns:repeat(2, minmax(0, 1fr));"
                "gap:1rem;"
                "margin:0.5rem 0 1.25rem 0;"
                "}"

                ".rank-summary-card {"
                "display:flex;"
                "align-items:center;"
                "justify-content:space-between;"
                "gap:1rem;"
                "min-height:5rem;"
                "padding:1rem 1.15rem;"
                "border:1px solid rgba(128,128,128,0.28);"
                "border-radius:0.8rem;"
                "background:rgba(128,128,128,0.035);"
                "}"

                ".rank-summary-label {"
                "font-size:0.76rem;"
                "font-weight:750;"
                "letter-spacing:0.04em;"
                "opacity:0.58;"
                "text-transform:uppercase;"
                "}"

                ".rank-summary-detail {"
                "font-size:0.82rem;"
                "font-weight:650;"
                "opacity:0.58;"
                "margin-top:0.25rem;"
                "}"

                ".rank-summary-value {"
                "font-size:1.75rem;"
                "font-weight:800;"
                "line-height:1;"
                "white-space:nowrap;"
                "}"

                ".rank-summary-highlight {"
                "border-color:rgba(242,201,76,0.28);"
                "background:rgba(242,201,76,0.045);"
                "}"

                ".rank-summary-highlight "
                ".rank-summary-value {"
                "color:#f2c94c;"
                "}"

                "@media (max-width:650px) {"

                ".rank-summary-grid {"
                "grid-template-columns:1fr;"
                "}"

                "}"

                "</style>"

                "<div class='rank-summary-grid'>"

                "<div class='rank-summary-card "
                "rank-summary-highlight'>"
                "<div>"
                "<div class='rank-summary-label'>"
                "BEST CAREER RANK"
                "</div>"
                "<div class='rank-summary-detail'>"
                "Highest historical position"
                "</div>"
                "</div>"
                "<div class='rank-summary-value'>"
                f"#{best_rank_value}"
                "</div>"
                "</div>"

                "<div class='rank-summary-card'>"
                "<div>"
                "<div class='rank-summary-label'>"
                "FIRST REACHED AT"
                "</div>"
                "<div class='rank-summary-detail'>"
                "First tournament at this rank"
                "</div>"
                "</div>"
                "<div class='rank-summary-value'>"
                f"{html.escape(str(best_rank_row['tournament']))}"
                "</div>"
                "</div>"

                "</div>"
            )

            st.markdown(
                best_rank_summary_html,
                unsafe_allow_html=True,
            )

            st.altair_chart(
                rank_chart,
                use_container_width=True,
            )

            st.caption(
                "Rank 1 is shown at the top. Dashed segments and "
                "hollow points indicate missed tournaments."
            )

        else:
            st.info(
                "No ranking history is available for this player yet."
            )


    with tab_history:
        if history:
            tournament_history_rows: list[str] = []

            for entry in reversed(history):
                tournament_name = str(
                    entry["tournament"]
                )

                if entry.get("date"):
                    formatted_date = pd.to_datetime(
                        entry["date"]
                    ).strftime("%d %b %Y")
                else:
                    formatted_date = "–"

                placement = entry.get(
                    "placement"
                )

                if placement is None:
                    placement_text = "–"
                else:
                    placement_text = format_ordinal(
                        int(placement)
                    )

                wins = int(
                    entry.get("wins") or 0
                )
                losses = int(
                    entry.get("losses") or 0
                )

                record_text = (
                    f"{wins}–{losses}"
                )

                won_tournament = bool(
                    entry.get("won_tournament")
                )

                tournament_winner = str(
                    entry.get("winner") or "Unknown"
                )

                if won_tournament:
                    placement_text = "Champion"
                    tournament_icon = "🏆"
                    row_class = (
                        "player-tournament-row "
                        "player-tournament-title-row"
                    )
                    result_class = (
                        "player-tournament-placement "
                        "player-tournament-champion"
                    )
                else:
                    tournament_icon = ""
                    row_class = (
                        "player-tournament-row"
                    )
                    result_class = (
                        "player-tournament-placement"
                    )

                tournament_history_rows.append(
                    (
                        f"<div class='{row_class}'>"

                        "<div class='player-tournament-main'>"
                        "<div class='player-tournament-name'>"
                        f"{html.escape(tournament_icon)} "
                        f"{html.escape(tournament_name)}"
                        "</div>"
                        "<div class='player-tournament-date'>"
                        f"{html.escape(formatted_date)}"
                        "</div>"
                        "</div>"

                        f"<div class='{result_class}'>"
                        f"{html.escape(placement_text)}"
                        "</div>"

                        "<div class='player-tournament-record'>"
                        "<div class='player-tournament-record-value'>"
                        f"{html.escape(record_text)}"
                        "</div>"
                        "<div class='player-tournament-record-label'>"
                        "Record"
                        "</div>"
                        "</div>"

                        "<div class='player-tournament-winner'>"
                        "<div class='player-tournament-winner-label'>"
                        "TOURNAMENT CHAMPION"
                        "</div>"
                        "<div class='player-tournament-winner-name'>"
                        f"{html.escape(tournament_winner)}"
                        "</div>"
                        "</div>"

                        "</div>"
                    )
                )

            tournament_history_html = (
                "<style>"

                ".player-tournament-list {"
                "width:100%;"
                "max-width:78rem;"
                "margin:0 auto;"
                "border:1px solid rgba(128,128,128,0.30);"
                "border-radius:0.8rem;"
                "overflow:hidden;"
                "}"

                ".player-tournament-row {"
                "display:grid;"
                "grid-template-columns:repeat(4, minmax(0, 1fr));"
                "align-items:center;"
                "gap:0.75rem;"
                "min-height:4.4rem;"
                "padding:0.75rem 1rem;"
                "border-bottom:"
                "1px solid rgba(128,128,128,0.20);"
                "}"

                ".player-tournament-row:last-child {"
                "border-bottom:none;"
                "}"

                ".player-tournament-title-row {"
                "background:rgba(212,175,55,0.08);"
                "border-left:3px solid rgba(255,205,70,0.75);"
                "padding-left:calc(1.1rem - 3px);"
                "}"

                ".player-tournament-main {"
                "text-align:left;"
                "}"


                ".player-tournament-name {"
                "font-size:1.08rem;"
                "font-weight:800;"
                "}"

                ".player-tournament-date {"
                "font-size:0.82rem;"
                "font-weight:650;"
                "opacity:0.58;"
                "margin-top:0.2rem;"
                "}"

                ".player-tournament-placement {"
                "font-size:1.02rem;"
                "font-weight:750;"
                "text-align:center;"
                "}"

                ".player-tournament-champion {"
                "color:#f2c94c;"
                "}"

                ".player-tournament-record {"
                "text-align:center;"
                "}"

                ".player-tournament-record-value {"
                "font-size:1.05rem;"
                "font-weight:800;"
                "}"

                ".player-tournament-record-label {"
                "font-size:0.72rem;"
                "font-weight:700;"
                "letter-spacing:0.04em;"
                "opacity:0.52;"
                "text-transform:uppercase;"
                "margin-top:0.15rem;"
                "}"

                ".player-tournament-winner {"
                "text-align:right;"
                "}"

                ".player-tournament-winner-label {"
                "font-size:0.7rem;"
                "font-weight:700;"
                "letter-spacing:0.04em;"
                "opacity:0.52;"
                "}"

                ".player-tournament-winner-name {"
                "font-size:0.98rem;"
                "font-weight:750;"
                "margin-top:0.18rem;"
                "}"

                "@media (max-width:1100px) {"

                ".player-tournament-row {"
                "grid-template-columns:repeat(4, minmax(0, 1fr));"
                "gap:0.45rem;"
                "padding:0.7rem 0.8rem;"
                "}"

                ".player-tournament-winner-label {"
                "font-size:0.58rem;"
                "}"

                ".player-tournament-winner-name {"
                "font-size:0.88rem;"
                "}"

                "}"

                "@media (max-width:700px) {"

                ".player-tournament-row {"
                "grid-template-columns:repeat(4, minmax(0, 1fr));"
                "gap:0.35rem;"
                "min-height:5rem;"
                "padding:0.8rem 0.7rem;"
                "}"

                ".player-tournament-name {"
                "font-size:1.05rem;"
                "}"

                ".player-tournament-date {"
                "font-size:0.76rem;"
                "}"

                ".player-tournament-placement {"
                "font-size:1rem;"
                "text-align:center;"
                "}"

                ".player-tournament-record-value {"
                "font-size:1rem;"
                "}"

                ".player-tournament-record-label {"
                "font-size:0.62rem;"
                "}"

                ".player-tournament-winner-label {"
                "display:none;"
                "}"

                ".player-tournament-winner-name {"
                "font-size:0.92rem;"
                "white-space:nowrap;"
                "overflow:hidden;"
                "text-overflow:ellipsis;"
                "}"

                "}"

                "</style>"

                "<div class='player-tournament-list'>"
                f"{''.join(tournament_history_rows)}"
                "</div>"
            )

            st.markdown(
                tournament_history_html,
                unsafe_allow_html=True,
            )

        else:
            st.info(
                "No tournament appearances found."
            )

    with tab_opponents:
        if insights["opponents"]:
            st.subheader(
                "Records Against All Opponents"
            )

            opponent_rows_html: list[str] = []

            for row in insights["opponents"]:
                opponent_name = str(
                    row["opponent"]
                )

                wins = int(
                    row["wins"]
                )
                losses = int(
                    row["losses"]
                )
                matches = int(
                    row["matches"]
                )
                winrate = float(
                    row["winrate"]
                )

                record_text = (
                    f"{wins}–{losses}"
                )

                match_label = (
                    "set"
                    if matches == 1
                    else "sets"
                )

                if wins > losses:
                    result_class = (
                        "opponent-record-positive"
                    )
                    result_label = (
                        "Winning record"
                    )
                    bar_color = "#3fb950"

                elif wins < losses:
                    result_class = (
                        "opponent-record-negative"
                    )
                    result_label = (
                        "Losing record"
                    )
                    bar_color = "#f85149"

                else:
                    result_class = (
                        "opponent-record-even"
                    )
                    result_label = (
                        "Even record"
                    )
                    bar_color = (
                        "rgba(255,255,255,0.48)"
                    )

                progress_width = max(
                    0.0,
                    min(
                        winrate,
                        100.0,
                    ),
                )

                opponent_rows_html.append(
                    (
                        "<div class='opponent-record-row'>"

                        "<div class='opponent-record-main'>"
                        "<div class='opponent-record-name'>"
                        f"{html.escape(opponent_name)}"
                        "</div>"
                        "<div class='opponent-record-summary "
                        f"{result_class}'>"
                        f"{html.escape(result_label)}"
                        "</div>"
                        "</div>"

                        "<div class='opponent-record-score'>"
                        "<div class='opponent-record-score-value'>"
                        f"{html.escape(record_text)}"
                        "</div>"
                        "<div class='opponent-record-label'>"
                        "RECORD"
                        "</div>"
                        "</div>"

                        "<div class='opponent-record-matches'>"
                        "<div class='opponent-record-matches-value'>"
                        f"{matches}"
                        "</div>"
                        "<div class='opponent-record-label'>"
                        f"{html.escape(match_label.upper())}"
                        "</div>"
                        "</div>"

                        "<div class='opponent-record-rate'>"
                        "<div class='opponent-record-rate-top'>"
                        "<span>"
                        f"{winrate:.1f}%"
                        "</span>"
                        "</div>"

                        "<div class='opponent-record-bar'>"
                        "<div class='opponent-record-bar-fill' "
                        f"style='width:{progress_width:.1f}%;"
                        f"background:{bar_color};'>"
                        "</div>"
                        "</div>"

                        "<div class='opponent-record-label'>"
                        "WIN RATE"
                        "</div>"
                        "</div>"

                        "</div>"
                    )
                )

            opponent_records_html = (
                "<style>"

                ".opponent-record-list {"
                "width:100%;"
                "max-width:78rem;"
                "margin:0 auto;"
                "border:1px solid rgba(128,128,128,0.30);"
                "border-radius:0.8rem;"
                "overflow:hidden;"
                "}"

                ".opponent-record-row {"
                "display:grid;"
                "grid-template-columns:repeat(4, minmax(0, 1fr));"
                "align-items:center;"
                "gap:0.6rem;"
                "min-height:5rem;"
                "padding:0.9rem 1.1rem;"
                "border-bottom:"
                "1px solid rgba(128,128,128,0.20);"
                "}"

                ".opponent-record-row:last-child {"
                "border-bottom:none;"
                "}"

                ".opponent-record-name {"
                "font-size:1.1rem;"
                "font-weight:800;"
                "}"

                ".opponent-record-summary {"
                "font-size:0.8rem;"
                "font-weight:700;"
                "margin-top:0.2rem;"
                "}"

                ".opponent-record-positive {"
                "color:#3fb950;"
                "}"

                ".opponent-record-negative {"
                "color:#f85149;"
                "}"

                ".opponent-record-even {"
                "color:rgba(255,255,255,0.60);"
                "}"

                ".opponent-record-score,"
                ".opponent-record-matches {"
                "text-align:center;"
                "}"

                ".opponent-record-main {"
                "text-align:left;"
                "}"

                ".opponent-record-rate {"
                "text-align:right;"
                "}"

                ".opponent-record-score-value,"
                ".opponent-record-matches-value {"
                "font-size:1.1rem;"
                "font-weight:800;"
                "}"

                ".opponent-record-label {"
                "font-size:0.7rem;"
                "font-weight:700;"
                "letter-spacing:0.04em;"
                "opacity:0.52;"
                "margin-top:0.15rem;"
                "}"

                ".opponent-record-rate {"
                "text-align:right;"
                "}"

                ".opponent-record-rate-top {"
                "font-size:1.02rem;"
                "font-weight:800;"
                "}"

                ".opponent-record-bar {"
                "height:0.42rem;"
                "margin-top:0.45rem;"
                "border-radius:999px;"
                "overflow:hidden;"
                "background:rgba(128,128,128,0.20);"
                "}"

                ".opponent-record-bar-fill {"
                "height:100%;"
                "border-radius:999px;"
                "}"

                "@media (max-width:1100px) {"

                ".opponent-record-row {"
                "grid-template-columns:repeat(4, minmax(0, 1fr));"
                "gap:0.45rem;"
                "padding:0.8rem 0.9rem;"
                "}"

                "}"

                "@media (max-width:700px) {"

                ".opponent-record-row {"
                "grid-template-columns:repeat(4, minmax(0, 1fr));"
                "gap:0.35rem;"
                "min-height:5.2rem;"
                "padding:0.8rem 0.7rem;"
                "}"

                ".opponent-record-name {"
                "font-size:1.05rem;"
                "}"

                ".opponent-record-summary {"
                "font-size:0.76rem;"
                "}"

                ".opponent-record-score-value,"
                ".opponent-record-matches-value,"
                ".opponent-record-rate-top {"
                "font-size:1rem;"
                "}"

                ".opponent-record-label {"
                "font-size:0.62rem;"
                "}"

                ".opponent-record-bar {"
                "height:0.36rem;"
                "margin-top:0.35rem;"
                "}"

                ".opponent-record-main {"
                "min-width:0;"
                "}"

                ".opponent-record-name {"
                "white-space:nowrap;"
                "overflow:hidden;"
                "text-overflow:ellipsis;"
                "}"

                ".opponent-record-rate {"
                "min-width:0;"
                "}"

                "}"

                ".opponent-record-footer {"
                "padding:0.7rem 1.1rem;"
                "border-top:1px solid rgba(128,128,128,0.20);"
                "background:rgba(128,128,128,0.04);"
                "font-size:0.78rem;"
                "font-weight:650;"
                "opacity:0.58;"
                "}"

                "</style>"

                "<div class='opponent-record-list'>"
                f"{''.join(opponent_rows_html)}"

                "<div class='opponent-record-footer'>"
                "Ordered by number of sets played."
                "</div>"

                "</div>"
            )

            st.markdown(
                opponent_records_html,
                unsafe_allow_html=True,
            )


        else:
            st.info(
                "No opponent records are available for this player yet."
            )

def show_matchups(include_inactive: bool) -> None:
    st.title("🤝 Matchups")
    st.caption(
        "Select a matchup in the head-to-head matrix to open the "
        "full player comparison."
    )

    players = load_players(include_inactive)

    if len(players) < 2:
        st.warning(
            "At least two players are required for a matchup."
        )
        return

    player_by_name = {
        str(player["display_name"]): str(player["player_id"])
        for player in players
    }

    names = list(player_by_name)

    records, winrates = load_h2h_matrix(
        include_inactive
    )

    if records.empty:
        st.warning(
            "No players were found for the matrix."
        )
        return

    def cell_style(value: Any) -> str:
        if pd.isna(value):
            return ""

        if value > 0.5:
            return (
                "background-color: "
                "rgba(46, 160, 67, 0.28); "
                "font-weight: 600;"
            )

        if value < 0.5:
            return (
                "background-color: "
                "rgba(248, 81, 73, 0.25); "
                "font-weight: 600;"
            )

        return (
            "background-color: "
            "rgba(139, 148, 158, 0.22); "
            "font-weight: 600;"
        )

    styled = records.style.apply(
        lambda row: [
            cell_style(
                winrates.loc[
                    str(row.name),
                    str(column),
                ]
            )
            for column in records.columns
        ],
        axis=1,
    )

    selected_pair: tuple[str, str] | None = None

    try:
        selection_event = st.dataframe(
            styled,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-cell",
            key="matchups_matrix_selection",
        )

        selection_state = selection_event.get(
            "selection",
            {},
        )

        selected_cells = selection_state.get(
            "cells",
            [],
        )

        if selected_cells:
            row_index, column_name = (
                selected_cells[0]
            )

            row_index = int(row_index)
            right_name = str(column_name)

            if (
                0 <= row_index < len(names)
                and right_name in player_by_name
            ):
                left_name = names[row_index]

                if left_name != right_name:
                    selected_pair = (
                        left_name,
                        right_name,
                    )

    except (
        AttributeError,
        KeyError,
        TypeError,
    ):
        st.dataframe(
            styled,
            use_container_width=True,
        )

    st.caption(
        "Green = winning record, red = losing record, "
        "grey = tied record."
    )

    if selected_pair is None:
        st.info(
            "Select a matchup in the matrix to open "
            "the comparison."
        )
        return

    left_name, right_name = selected_pair

    st.divider()

    left_id = player_by_name[left_name]
    right_id = player_by_name[right_name]

    left_profile = load_player_profile(left_id)
    right_profile = load_player_profile(right_id)
    left_timeline = load_player_timeline(left_id)
    right_timeline = load_player_timeline(right_id)
    h2h = load_head_to_head(left_id, right_id)

    full_ranking = load_elo_ranking(True)
    ranks = {
        str(entry["player_id"]): entry["rank"]
        for entry in full_ranking
    }

    left_rank = ranks.get(left_id)
    right_rank = ranks.get(right_id)

    header_left, header_score, header_right = st.columns(
        [4, 3, 4]
    )

    left_titles = int(
        left_profile.get("titles") or 0
    )
    right_titles = int(
        right_profile.get("titles") or 0
    )

    left_title_label = (
        "Title"
        if left_titles == 1
        else "Titles"
    )
    right_title_label = (
        "Title"
        if right_titles == 1
        else "Titles"
    )

    with header_left:
        st.markdown(f"## {left_name}")
        st.markdown(
            (
                "<div style='"
                "font-size:1rem;"
                "font-weight:600;"
                "opacity:0.65;"
                "'>"
                f"#{left_rank or '–'} · "
                f"{float(left_profile.get('current_elo') or 1000.0):.1f} Elo · "
                f"{left_titles} {left_title_label}"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

    with header_score:
        st.markdown(
            (
                "<div style='text-align:center;'>"
                "<div style='font-size:0.9rem; opacity:0.7;'>"
                "HEAD-TO-HEAD"
                "</div>"
                "<div style='font-size:2.5rem; font-weight:800;'>"
                f"{h2h['player_a']['wins']} : "
                f"{h2h['player_b']['wins']}"
                "</div>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

    with header_right:
        st.markdown(
            f"<h2 style='text-align:right;'>{right_name}</h2>",
            unsafe_allow_html=True,
        )
        st.markdown(
            (
                "<div style='"
                "text-align:right;"
                "font-size:1rem;"
                "font-weight:600;"
                "opacity:0.65;"
                "'>"
                f"#{right_rank or '–'} · "
                f"{float(right_profile.get('current_elo') or 1000.0):.1f} Elo · "
                f"{right_titles} {right_title_label}"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

    categories = [
        (
            "Peak Elo",
            left_profile.get("peak_elo"),
            right_profile.get("peak_elo"),
            False,
            lambda value: f"{value:.1f}" if value is not None else "–",
        ),
        (
            "Appearances",
            left_profile.get("appearances", 0),
            right_profile.get("appearances", 0),
            False,
            lambda value: str(value),
        ),
        (
            "Match Wins",
            left_profile.get("wins", 0),
            right_profile.get("wins", 0),
            False,
            lambda value: str(value),
        ),
        (
            "Win Rate",
            left_profile.get("winrate"),
            right_profile.get("winrate"),
            False,
            lambda value: f"{value:.1f} %" if value is not None else "–",
        ),
        (
            "Best Placement",
            left_profile.get("best_result"),
            right_profile.get("best_result"),
            True,
            lambda value: f"{value}." if value is not None else "–",
        ),
        (
            "Average Placement",
            left_profile.get("average_result"),
            right_profile.get("average_result"),
            True,
            lambda value: f"{value:.2f}" if value is not None else "–",
        ),
    ]

    last_match = h2h.get("last_match")

    if last_match:
        last_result = (
            last_match.get("score")
            or "Unknown result"
        )

        last_meeting = (
            f"{last_match.get('winner') or 'Unknown'} "
            f"{last_result}"
        )
    else:
        last_meeting = "–"

    streak_player = "–"
    streak_text = "–"

    recent_history = list(
        reversed(h2h.get("history") or [])
    )

    if recent_history:
        latest_winner = recent_history[0].get(
            "winner"
        )

        streak_count = 0

        for match in recent_history:
            if match.get("winner") != latest_winner:
                break

            streak_count += 1

        if latest_winner:
            streak_player = str(latest_winner)
            streak_text = f"W{streak_count}"

    rivalry_summary = (
        narratives.generate_rivalry_summary(h2h)
    )

    summary_parts = [
        rivalry_summary,
    ]

    if last_match:
        score = (
            last_match.get("score")
            or "Unknown result"
        )

        summary_parts.append(
            (
                f"Last meeting: "
                f"{last_match.get('winner') or 'Unknown'} "
                f"won at "
                f"{last_match.get('tournament') or 'an unknown tournament'} "
                f"({score})."
            )
        )

    st.info(
        " ".join(summary_parts)
    )

    tab_overview, tab_history, tab_matches = st.tabs(
        [
            "Overview",
            "Elo & Ranking",
            "Match History",
        ]
    )

    with tab_overview:
        st.subheader("Head-to-Head Details")

        detail_cols = st.columns(3)

        detail_cols[0].metric(
            "Games Record",
            (
                f"{h2h['player_a']['games_won']}–"
                f"{h2h['player_b']['games_won']}"
            ),
        )

        detail_cols[1].metric(
            "Current Streak",
            streak_player,
            streak_text,
            delta_color="off",
        )

        detail_cols[2].metric(
            "Last Meeting",
            last_meeting,
        )

        st.subheader("Career Comparison")

        comparison_rows_html = []

        for (
            label,
            left_value,
            right_value,
            lower_is_better,
            formatter,
        ) in categories:
            left_better = False
            right_better = False

            if (
                left_value is not None
                and right_value is not None
                and left_value != right_value
            ):
                if lower_is_better:
                    left_better = left_value < right_value
                else:
                    left_better = left_value > right_value

                right_better = not left_better

            left_style = (
                "background:rgba(34,197,94,0.12);"
                "font-weight:750;"
                if left_better
                else ""
            )

            right_style = (
                "background:rgba(34,197,94,0.12);"
                "font-weight:750;"
                if right_better
                else ""
            )

            comparison_rows_html.append(
                (
                    "<div class='comparison-cell comparison-value' "
                    f"style='{left_style}'>"
                    f"{html.escape(formatter(left_value))}"
                    "</div>"
                    "<div class='comparison-cell comparison-label'>"
                    f"{html.escape(label)}"
                    "</div>"
                    "<div class='comparison-cell comparison-value' "
                    f"style='{right_style}'>"
                    f"{html.escape(formatter(right_value))}"
                    "</div>"
                )
            )

        comparison_table_html = (
            "<style>"
            ".comparison-grid {"
            "display:grid;"
            "grid-template-columns:1fr 1fr 1fr;"
            "overflow:hidden;"
            "border:1px solid rgba(128,128,128,0.28);"
            "border-radius:0.8rem;"
            "}"
            ".comparison-cell {"
            "min-height:3.4rem;"
            "display:flex;"
            "align-items:center;"
            "padding:0.75rem 1rem;"
            "border-bottom:1px solid rgba(128,128,128,0.22);"
            "}"
            ".comparison-cell:nth-last-child(-n+3) {"
            "border-bottom:none;"
            "}"
            ".comparison-cell:not(:nth-child(3n)) {"
            "border-right:1px solid rgba(128,128,128,0.22);"
            "}"
            ".comparison-header {"
            "min-height:3rem;"
            "font-weight:700;"
            "opacity:0.7;"
            "background:rgba(128,128,128,0.08);"
            "}"
            ".comparison-label {"
            "justify-content:center;"
            "text-align:center;"
            "font-weight:650;"
            "}"
            ".comparison-value {"
            "font-size:1.05rem;"
            "}"
            ".comparison-value:nth-child(3n) {"
            "justify-content:flex-end;"
            "text-align:right;"
            "}"
            "</style>"
            "<div class='comparison-grid'>"
            "<div class='comparison-cell comparison-header'>"
            f"{html.escape(left_name)}"
            "</div>"
            "<div class='comparison-cell comparison-header comparison-label'>"
            "Category"
            "</div>"
            "<div class='comparison-cell comparison-header' "
            "style='justify-content:flex-end;'>"
            f"{html.escape(right_name)}"
            "</div>"
            f"{''.join(comparison_rows_html)}"
            "</div>"
        )

        st.markdown(
            comparison_table_html,
            unsafe_allow_html=True,
        )

        st.caption(
            "The better value in each category is highlighted."
        )

    with tab_history:
        st.subheader("Combined Elo History")
        timeline_rows = []
        for player_name, player_timeline in (
            (left_name, left_timeline),
            (right_name, right_timeline),
        ):
            for entry in player_timeline:
                timeline_rows.append(
                    {
                        **entry,
                        "Players": player_name,
                    }
                )

        if timeline_rows:
            elo_df = pd.DataFrame(timeline_rows)
            elo_chart = (
                alt.Chart(elo_df)
                .mark_line(point=True)
                .encode(
                    x=alt.X(
                        "tournament:N",
                        title="Tournament",
                        sort=alt.SortField(
                            field="tournament_number",
                            order="ascending",
                        ),
                    ),
                    y=alt.Y(
                        "elo:Q",
                        title="Elo",
                        scale=alt.Scale(zero=False),
                    ),
                    color=alt.Color("Players:N", title=None),
                    strokeDash=alt.condition(
                        "datum.played_in_tournament",
                        alt.value([1, 0]),
                        alt.value([5, 4]),
                    ),
                    tooltip=[
                        alt.Tooltip("Players:N"),
                        alt.Tooltip("tournament:N", title="Tournament"),
                        alt.Tooltip("elo:Q", title="Elo", format=".1f"),
                        alt.Tooltip("rank:Q", title="Rank"),
                        alt.Tooltip(
                            "played_in_tournament:N",
                            title="Participated",
                        ),
                    ],
                )
                .properties(height=460)
            )
            st.altair_chart(elo_chart, use_container_width=True)
            st.caption(
                "Dashed segments indicate tournaments in which the player did not participate."
            )
        else:
            st.info("No Elo history is available for these players yet.")

        st.subheader("Combined Ranking History")
        rank_rows = []
        for player_name, player_timeline in (
            (left_name, left_timeline),
            (right_name, right_timeline),
        ):
            for entry in player_timeline:
                rank_rows.append(
                    {
                        **entry,
                        "Players": player_name,
                    }
                )

        if rank_rows:
            rank_df = pd.DataFrame(rank_rows)
            max_rank = int(rank_df["rank"].max())

            rank_chart = (
                alt.Chart(rank_df)
                .mark_line(point=True)
                .encode(
                    x=alt.X(
                        "tournament:N",
                        title="Tournament",
                        sort=alt.SortField(
                            field="tournament_number",
                            order="ascending",
                        ),
                    ),
                    y=alt.Y(
                        "rank:Q",
                        title="Rank",
                        scale=alt.Scale(
                            domain=[max_rank + 0.5, 0.5],
                        ),
                        axis=alt.Axis(
                            values=list(range(1, max_rank + 1)),
                            format="d",
                            tickMinStep=1,
                            labelOverlap=False,
                        ),
                    ),
                    color=alt.Color("Players:N", title=None),
                    tooltip=[
                        alt.Tooltip("Players:N"),
                        alt.Tooltip("tournament:N", title="Tournament"),
                        alt.Tooltip("rank:Q", title="Rank"),
                        alt.Tooltip("elo:Q", title="Elo", format=".1f"),
                    ],
                )
                .properties(height=460)
            )
            st.altair_chart(rank_chart, use_container_width=True)
            st.caption("Rank 1 is displayed at the top.")
        else:
            st.info("No ranking history is available for these players yet.")

    with tab_matches:
        if h2h["history"]:
            match_rows = []

            bracket_labels_by_tournament: dict[
                int,
                dict[str, str],
            ] = {}

            for match in reversed(h2h["history"]):
                tournament_number = int(
                    match["tournament_number"]
                )

                if match["stage"] == "knockout":
                    if (
                        tournament_number
                        not in bracket_labels_by_tournament
                    ):
                        tournament_detail = (
                            load_tournament_detail(
                                tournament_number
                            )
                        )

                        tournament_bracket_matches = (
                            build_archived_bracket_matches(
                                tournament_detail["matches"]
                            )
                        )

                        bracket_labels_by_tournament[
                            tournament_number
                        ] = {
                            str(bracket_match["bracket_match_id"]):
                                str(bracket_match["round_label"])
                            for bracket_match
                            in tournament_bracket_matches
                        }

                    round_text = (
                        bracket_labels_by_tournament[
                            tournament_number
                        ].get(
                            str(match["match_id"]),
                            str(
                                match["round_label"]
                                or "Knockout"
                            ),
                        )
                    )

                else:
                    raw_round = (
                        match["round_label"]
                        or match.get("challonge_round")
                    )

                    if match["stage"] == "group" and raw_round is not None:
                        round_text = f"Group Round {raw_round}"
                    else:
                        round_text = str(
                            raw_round
                            or match["stage"]
                            or "–"
                        )

                match_rows.append(
                    {
                        "Tournament": match["tournament"],
                        "Date": (
                            pd.to_datetime(
                                match["date"]
                            ).strftime("%d %b %Y")
                            if match["date"]
                            else "–"
                        ),
                        "Round": round_text,
                        "Winner": (
                            match["winner"]
                            or "Pending"
                        ),
                        "Result": (
                            match["score"]
                            or "–"
                        ),
                    }
                )

            st.dataframe(
                pd.DataFrame(match_rows),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No head-to-head matches available.")

@st.dialog(
    "Archived Match",
    width="medium",
)
def show_archived_match_dialog(
    match: dict[str, Any],
    tournament_number: int,
    dialog_state_key: str,
) -> None:
    """Show read-only details for one archived bracket match."""

    player_1_name = str(
        match.get("player_1_name") or "Unknown"
    )
    player_2_name = str(
        match.get("player_2_name") or "Unknown"
    )

    st.markdown(
        f"### {match['match_code']}"
    )

    st.caption(
        f"WM {tournament_number:02d} · "
        f"{match['round_label']}"
    )

    player_1_score = match.get(
        "player_1_score"
    )
    player_2_score = match.get(
        "player_2_score"
    )

    if (
        player_1_score is not None
        and player_2_score is not None
    ):
        score_text = (
            f"{player_1_score}–{player_2_score}"
        )
    elif match.get("status") == "forfeit":
        score_text = "W–L"
    else:
        score_text = "–"

    st.markdown(
        (
            '<div style="'
            'display:grid;'
            'grid-template-columns:1fr auto 1fr;'
            'align-items:center;'
            'gap:1rem;'
            'margin:1rem 0 1.25rem 0;'
            '">'
            '<div style="'
            'text-align:right;'
            'font-size:1.6rem;'
            'font-weight:750;'
            '">'
            f'{html.escape(player_1_name)}'
            '</div>'
            '<div style="'
            'font-size:1.4rem;'
            'font-weight:800;'
            '">'
            f'{html.escape(score_text)}'
            '</div>'
            '<div style="'
            'text-align:left;'
            'font-size:1.6rem;'
            'font-weight:750;'
            '">'
            f'{html.escape(player_2_name)}'
            '</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )

    winner_name = match.get(
        "winner_name"
    )

    detail_cols = st.columns(2)

    detail_cols[0].metric(
        "Winner",
        winner_name or "Unknown",
    )

    detail_cols[1].metric(
        "Status",
        {
            "completed": "Played",
            "forfeit": "W–L",
            "waiting": "Waiting",
        }.get(
            str(match.get("status")),
            str(match.get("status") or "Unknown").title(),
        ),
    )

    if st.button(
        "Close",
        use_container_width=True,
        key=(
            f"close_archived_match_"
            f"{match['bracket_match_id']}"
        ),
    ):
        st.session_state.pop(
            dialog_state_key,
            None,
        )
        st.rerun()

def format_ordinal(value: int) -> str:
    """Format an integer as an English ordinal."""

    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {
            1: "st",
            2: "nd",
            3: "rd",
        }.get(
            value % 10,
            "th",
        )

    return f"{value}{suffix}"

def show_tournaments() -> None:
    st.title("🏆 Tournaments")
    tournaments = load_tournaments()

    if not tournaments:
        st.warning("No tournaments found.")
        return

    tournament_numbers = [int(row["WM"].split()[1]) for row in tournaments]
    selected_number = st.selectbox(
        "Select tournament",
        tournament_numbers,
        format_func=lambda number: f"WM {number:02d}",
    )
    detail = load_tournament_detail(int(selected_number))
    tournament = detail["tournament"]
    participants = detail["participants"]
    matches = detail["matches"]
    archived_bracket_matches = build_archived_bracket_matches(
        matches
    )

    selected_tournament_number = int(tournament["tournament_number"])
    winner = tournament.get("winner")

    winner_title_number = sum(
        row["Winner"] == winner
        and int(row["WM"].split()[1]) <= selected_tournament_number
        for row in tournaments
    )

    previous_tournament = next(
        (
            row
            for row in tournaments
            if int(row["WM"].split()[1])
            == selected_tournament_number - 1
        ),
        None,
    )

    defending_champion = (
        previous_tournament["Winner"]
        if previous_tournament
        else None
    )

    changes = tournament_elo_changes(
        selected_tournament_number,
        participants,
    )

    tournament_milestones = load_tournament_milestones(
        selected_tournament_number,
    )

    tournament_recap = narratives.generate_tournament_summary(
        tournament,
        participants,
        matches,
        changes,
        winner_title_number=winner_title_number,
        defending_champion=defending_champion,
        milestones=tournament_milestones,
    )

    st.header(f"WM {tournament['tournament_number']:02d}")
    summary_cols = st.columns(3)
    summary_cols[0].metric(
        "Date",
        tournament["tournament_date"] or "–",
    )
    summary_cols[1].metric(
        "Participants",
        len(participants),
    )
    summary_cols[2].metric(
        "Matches",
        len(matches),
    )

    podium = {row["placement"]: row["player"] for row in participants if row["placement"] in (1, 2, 3)}
    if podium:
        podium_cols = st.columns(3)
        podium_cols[0].metric("🥇 1st Place", podium.get(1, "–"))
        podium_cols[1].metric("🥈 2nd Place", podium.get(2, "–"))
        podium_cols[2].metric("🥉 3rd Place", podium.get(3, "–"))

    st.info(tournament_recap)

    (
        tab_bracket,
        tab_overview,
        tab_matches,
        tab_elo,
    ) = st.tabs(
        [
            "Bracket",
            "Participants & Results",
            "All Matches",
            "Elo After Tournament",
        ]
    )

    with tab_overview:
        st.subheader("Final Standings")

        placement_counts: dict[int, int] = {}

        for participant in participants:
            placement = participant["placement"]

            if placement is None:
                continue

            placement_number = int(placement)

            placement_counts[placement_number] = (
                placement_counts.get(
                    placement_number,
                    0,
                )
                + 1
            )

        placement_icons = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        for participant in participants:
            placement = participant["placement"]
            seed = participant["seed"]

            if placement is None:
                placement_text = "–"
                placement_number = None
            else:
                placement_number = int(placement)

                ordinal = format_ordinal(
                    placement_number
                )

                if placement_counts.get(
                    placement_number,
                    0,
                ) > 1:
                    ordinal = f"T-{ordinal}"

                icon = placement_icons.get(
                    placement_number,
                    "",
                )

                placement_text = (
                    f"{icon} {ordinal}".strip()
                )

            if seed is None:
                seed_text = "Not seeded"
                seed_performance = "–"
                performance_color = "rgba(255,255,255,0.62)"

            else:
                seed_number = int(seed)
                seed_text = f"Seed #{seed_number}"

                if placement_number is None:
                    seed_performance = "–"
                    performance_color = "rgba(255,255,255,0.62)"

                elif placement_number < seed_number:
                    improvement = (
                        seed_number
                        - placement_number
                    )

                    seed_performance = (
                        f"▲ {improvement}"
                    )

                    performance_color = "#3fb950"

                elif placement_number > seed_number:
                    decline = (
                        placement_number
                        - seed_number
                    )

                    seed_performance = (
                        f"▼ {decline}"
                    )

                    performance_color = "#f85149"

                else:
                    seed_performance = "= Seed"
                    performance_color = "rgba(255,255,255,0.62)"

            with st.container(border=True):
                st.markdown(
                    (
                        "<div style='"
                        "display:grid;"
                        "grid-template-columns:1.4fr 3.5fr 1.8fr 1.5fr;"
                        "align-items:center;"
                        "min-height:5.2rem;"
                        "gap:1rem;"
                        "'>"

                        "<div style='"
                        "display:flex;"
                        "align-items:center;"
                        "justify-content:flex-end;"
                        "text-align:right;"
                        "font-size:1.55rem;"
                        "font-weight:800;"
                        "padding-right:0.5rem;"
                        "'>"
                        f"{html.escape(placement_text)}"
                        "</div>"

                        "<div style='"
                        "display:flex;"
                        "align-items:center;"
                        "justify-content:flex-start;"
                        "text-align:left;"
                        "font-size:1.55rem;"
                        "font-weight:800;"
                        "padding-left:0.5rem;"
                        "'>"
                        f"{html.escape(str(participant['player']))}"
                        "</div>"

                        "<div style='"
                        "display:flex;"
                        "align-items:center;"
                        "justify-content:center;"
                        "text-align:center;"
                        "font-size:1rem;"
                        "font-weight:700;"
                        "'>"
                        f"{html.escape(seed_text)}"
                        "</div>"

                        "<div style='"
                        "display:flex;"
                        "align-items:center;"
                        "justify-content:center;"
                        "text-align:center;"
                        "font-size:1rem;"
                        "font-weight:800;"
                        f"color:{performance_color};"
                        "'>"
                        f"{html.escape(seed_performance)}"
                        "</div>"

                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )

        st.caption(
            "▲ finished above the initial seed · "
            "▼ finished below the initial seed"
        )

    with tab_bracket:
        archived_bracket_routes = (
            build_archived_bracket_routes(
                matches,
                archived_bracket_matches,
            )
        )

        if archived_bracket_matches:
            dialog_state_key = (
                f"open_archived_match_"
                f"{selected_tournament_number}"
            )

            visible_match_codes = {
                str(match["match_code"])
                for match in archived_bracket_matches
            }

            open_match_code = (
                st.session_state.get(
                    dialog_state_key
                )
            )

            if (
                open_match_code
                not in visible_match_codes
            ):
                open_match_code = None

                st.session_state.pop(
                    dialog_state_key,
                    None,
                )

            clicked_match_code = (
                bracket_visualization.render_bracket(
                    archived_bracket_matches,
                    archived_bracket_routes,
                    selected_match_code=open_match_code,
                    component_key=(
                        f"archive_bracket_"
                        f"{selected_tournament_number}"
                    ),
                )
            )

            if (
                clicked_match_code
                and clicked_match_code
                in visible_match_codes
                and clicked_match_code
                != open_match_code
            ):
                st.session_state[
                    dialog_state_key
                ] = clicked_match_code

                st.rerun()

            if open_match_code:
                selected_archived_match = next(
                    (
                        match
                        for match
                        in archived_bracket_matches
                        if str(match["match_code"])
                        == str(open_match_code)
                    ),
                    None,
                )

                if selected_archived_match:
                    show_archived_match_dialog(
                        selected_archived_match,
                        selected_tournament_number,
                        dialog_state_key,
                    )
                else:
                    st.session_state.pop(
                        dialog_state_key,
                        None,
                    )

            st.caption(
                "Archived bracket reconstructed from "
                "Challonge round and match data."
            )

        else:
            st.info(
                "No knockout bracket data is available "
                "for this tournament."
            )

    with tab_matches:
        if matches:
            match_rows = []
            for match in matches:
                if match["score_known"] and match["player_1_score"] is not None:
                    score = f"{match['player_1_score']}:{match['player_2_score']}"
                else:
                    score = "–"
                match_rows.append(
                    {
                        "Stage": match["stage"] or "–",
                        "Round": archived_match_round_label(
                            match,
                            archived_bracket_matches,
                        ),
                        "Player 1": match["player_1"],
                        "Player 2": match["player_2"],
                        "Result": score,
                        "Winner": match["winner"] or "Pending",
                    }
                )
            st.dataframe(pd.DataFrame(match_rows), hide_index=True, use_container_width=True)
        else:
            st.info("No match data is stored for this tournament.")

    with tab_elo:
        if changes:
            biggest_gain = changes[0]
            biggest_loss = changes[-1]
            metric_cols = st.columns(3)
            metric_cols[0].metric(
                "Biggest Elo Gain",
                biggest_gain["Players"],
                f"{biggest_gain['Elo Change']:+.1f}",
            )
            metric_cols[1].metric(
                "Biggest Elo Loss",
                biggest_loss["Players"],
                f"{biggest_loss['Elo Change']:-.1f}",
                delta_color="normal",
            )
            metric_cols[2].metric(
                "Elo Changes",
                len(changes),
            )

            change_df = pd.DataFrame(changes)
            change_chart = (
                alt.Chart(change_df)
                .mark_bar()
                .encode(
                    x=alt.X(
                        "Elo Change:Q",
                        title="Elo Change",
                    ),
                    y=alt.Y(
                        "Players:N",
                        title=None,
                        sort="-x",
                    ),
                    color=alt.condition(
                        "datum['Elo Change'] >= 0",
                        alt.value("#2ea043"),
                        alt.value("#f85149"),
                    ),
                    tooltip=[
                        alt.Tooltip("Players:N"),
                        alt.Tooltip(
                            "Elo Before:Q",
                            format=".1f",
                        ),
                        alt.Tooltip(
                            "Elo After:Q",
                            format=".1f",
                        ),
                        alt.Tooltip(
                            "Elo Change:Q",
                            format="+.1f",
                        ),
                        alt.Tooltip("Rank Before:Q"),
                        alt.Tooltip("Rank After:Q"),
                    ],
                )
                .properties(height=max(280, len(changes) * 38))
            )
            zero_rule = (
                alt.Chart(pd.DataFrame({"x": [0]}))
                .mark_rule(opacity=0.45)
                .encode(x="x:Q")
            )
            st.altair_chart(
                change_chart + zero_rule,
                use_container_width=True,
            )

            st.dataframe(
                change_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Elo Before": st.column_config.NumberColumn(format="%.1f"),
                    "Elo After": st.column_config.NumberColumn(format="%.1f"),
                    "Elo Change": st.column_config.NumberColumn(
                        format="%+.1f"
                    ),
                    "Rank Before": st.column_config.NumberColumn(format="%d"),
                    "Rank After": st.column_config.NumberColumn(format="%d"),
                },
            )

        snapshot = detail["elo_snapshot"]
        if snapshot:
            with st.expander("Full Elo ranking after the tournament"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Rank": row["rank"],
                                "Players": row["player"],
                                "Elo": row["elo"],
                                "Participated": (
                                    "Yes"
                                    if row["played_in_tournament"]
                                    else "No"
                                ),
                            }
                            for row in snapshot
                        ]
                    ),
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Rank": st.column_config.NumberColumn(format="%d"),
                        "Elo": st.column_config.NumberColumn(format="%.1f"),
                    },
                )
        elif not changes:
            st.info("No Elo data is available for this tournament.")


@st.dialog(
    "Edit Bracket Match",
    width="medium",
)
def show_bracket_match_dialog(
    match: dict[str, Any],
    dialog_state_key: str,
) -> None:
    """Display controls for one bracket match."""

    player_1_name = (
        str(match["player_1_name"])
        if match["player_1_name"]
        else "TBD"
    )

    player_2_name = (
        str(match["player_2_name"])
        if match["player_2_name"]
        else "TBD"
    )

    match_status = str(match["status"])
    match_code = str(match["match_code"])

    status_display = {
        "waiting": "Waiting",
        "pending": "Ready",
        "completed": "Played",
        "forfeit": "W–L",
        "bye": "Bye",
        "cancelled": "Cancelled",
    }.get(
        match_status,
        match_status.title(),
    )

    st.markdown(f"### {match_code}")

    st.markdown(
        (
            '<div style="'
            'display:grid;'
            'grid-template-columns:1fr auto 1fr;'
            'align-items:center;'
            'gap:1rem;'
            'margin:0.5rem 0 1.25rem 0;'
            '">'
            '<div style="'
            'text-align:right;'
            'font-size:1.6rem;'
            'font-weight:750;'
            '">'
            f'{html.escape(player_1_name)}'
            '</div>'
            '<div style="'
            'opacity:0.55;'
            'font-size:0.9rem;'
            'font-weight:700;'
            '">'
            'VS'
            '</div>'
            '<div style="'
            'text-align:left;'
            'font-size:1.6rem;'
            'font-weight:750;'
            '">'
            f'{html.escape(player_2_name)}'
            '</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )

    st.caption(f"Status: {status_display}")

    if match_status == "waiting":
        st.info(
            "This match is waiting for players from earlier rounds."
        )
        return

    if match_status == "bye":
        st.info(
            f"{match['winner_name']} advances automatically."
        )
        return

    if match_status == "pending":
        result_type = st.radio(
            "Result type",
            options=[
                "Played",
                "W–L",
                "Cancelled",
            ],
            horizontal=True,
            key=(
                f"dialog_result_type_"
                f"{match['bracket_match_id']}"
            ),
        )

        with st.form(
            f"dialog_bracket_match_"
            f"{match['bracket_match_id']}"
        ):
            winner_id = None
            player_1_score = None
            player_2_score = None

            if result_type == "Played":
                score_cols = st.columns(2)

                with score_cols[0]:
                    player_1_score = st.number_input(
                        f"{player_1_name} score",
                        min_value=0,
                        value=0,
                        step=1,
                    )

                with score_cols[1]:
                    player_2_score = st.number_input(
                        f"{player_2_name} score",
                        min_value=0,
                        value=0,
                        step=1,
                    )

            elif result_type == "W–L":
                winner_options = {
                    player_1_name: str(
                        match["player_1_id"]
                    ),
                    player_2_name: str(
                        match["player_2_id"]
                    ),
                }

                selected_winner_name = st.selectbox(
                    "Winner",
                    options=list(winner_options),
                )

                winner_id = winner_options[
                    selected_winner_name
                ]

            save_result = st.form_submit_button(
                "Save Result",
                type="primary",
                use_container_width=True,
            )

        if save_result:
            if result_type == "Played":
                if player_1_score == player_2_score:
                    st.error(
                        "A played match cannot end in a tie."
                    )
                    return

                result_status = "completed"

            elif result_type == "W–L":
                result_status = "forfeit"

            else:
                result_status = "cancelled"

            try:
                tournament_manager.update_draft_bracket_match(
                    DB_PATH,
                    str(match["bracket_match_id"]),
                    status=result_status,
                    winner_id=winner_id,
                    player_1_score=(
                        int(player_1_score)
                        if player_1_score is not None
                        else None
                    ),
                    player_2_score=(
                        int(player_2_score)
                        if player_2_score is not None
                        else None
                    ),
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()

                st.session_state.pop(
                    dialog_state_key,
                    None,
                )

                st.rerun()

        return

    if match_status in {
        "completed",
        "forfeit",
        "cancelled",
    }:
        if (
            match_status == "completed"
            and match["player_1_score"] is not None
            and match["player_2_score"] is not None
        ):
            st.success(
                f"Result: "
                f"{match['player_1_score']}–"
                f"{match['player_2_score']}"
            )

        elif match_status == "forfeit":
            st.success("Result: W–L")

        elif match_status == "cancelled":
            st.info("This match was cancelled.")

        if match["winner_name"]:
            st.write(
                f"Winner: **{match['winner_name']}**"
            )

        st.warning(
            "Resetting this result also clears dependent "
            "later bracket matches."
        )

        confirm_reset = st.checkbox(
            "I understand that dependent results will be cleared.",
            key=(
                f"dialog_confirm_reset_"
                f"{match['bracket_match_id']}"
            ),
        )

        if st.button(
            "Reset Result",
            type="secondary",
            disabled=not confirm_reset,
            use_container_width=True,
            key=(
                f"dialog_reset_result_"
                f"{match['bracket_match_id']}"
            ),
        ):
            try:
                tournament_manager.reset_draft_bracket_match_result(
                    DB_PATH,
                    str(match["bracket_match_id"]),
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()

                st.session_state.pop(
                    dialog_state_key,
                    None,
                )

                st.rerun()

def show_tournament_manager() -> None:
    """Creates and manages tournament drafts."""

    st.title("🛠 Tournament Manager")
    st.caption(
        "Create tournament drafts, select participants, and prepare "
        "the tournament structure."
    )

    st.subheader("Create Tournament Draft")

    existing_tournaments = load_tournaments()
    existing_numbers = [
        int(row["WM"].split()[1])
        for row in existing_tournaments
    ]

    existing_drafts = load_tournament_drafts()
    draft_numbers = [
        int(draft["tournament_number"])
        for draft in existing_drafts
    ]

    highest_number = max(
        existing_numbers + draft_numbers,
        default=0,
    )
    suggested_number = highest_number + 1

    format_label = st.radio(
        "Tournament format",
        options=[
            "Group Stage → Double Elimination",
            "Double Elimination Only",
        ],
        key="new_draft_format",
    )

    if format_label == "Group Stage → Double Elimination":
        format_type = tournament_manager.FORMAT_GROUP_STAGE

        entry_label = st.radio(
            "Bracket entry",
            options=[
                "All players start in Winners Bracket",
                "Lower seeds start in Losers Bracket",
            ],
            key="new_draft_entry_mode",
        )

        if entry_label == "Lower seeds start in Losers Bracket":
            bracket_entry_mode = (
                tournament_manager.ENTRY_SPLIT_BY_GROUP_SEED
            )
        else:
            bracket_entry_mode = (
                tournament_manager.ENTRY_ALL_WINNERS
            )

    else:
        format_type = tournament_manager.FORMAT_DOUBLE_ELIMINATION
        bracket_entry_mode = tournament_manager.ENTRY_ALL_WINNERS

        st.info(
            "All players start in the Winners Bracket "
            "in a double-elimination-only tournament."
        )

    with st.form("create_tournament_draft"):
        tournament_number = st.number_input(
            "Tournament number",
            min_value=1,
            value=suggested_number,
            step=1,
        )

        tournament_date = st.date_input(
            "Tournament date",
            value=None,
        )

        create_submitted = st.form_submit_button(
            "Create Draft",
            type="primary",
        )

    if create_submitted:
        date_text = (
            tournament_date.isoformat()
            if tournament_date is not None
            else None
        )

        try:
            tournament_manager.create_draft(
                DB_PATH,
                tournament_number=int(tournament_number),
                tournament_date=date_text,
                format_type=format_type,
                bracket_entry_mode=bracket_entry_mode,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.cache_data.clear()
            st.success(
                f"Draft for WM {int(tournament_number):02d} created."
            )
            st.rerun()

    st.divider()
    st.subheader("Existing Drafts")

    drafts = load_tournament_drafts()

    if not drafts:
        st.info("No tournament drafts exist yet.")
        return

    draft_by_label = {
        (
            f"WM {int(draft['tournament_number']):02d} · "
            f"{draft['participant_count']} participants · "
            f"{draft['status']}"
        ): str(draft["draft_id"])
        for draft in drafts
    }

    selected_label = st.selectbox(
        "Select draft",
        options=list(draft_by_label),
    )
    selected_draft_id = draft_by_label[selected_label]

    draft = load_tournament_draft(selected_draft_id)

    if (
        draft["format_type"]
        == tournament_manager.FORMAT_GROUP_STAGE
    ):
        draft_groups = load_tournament_draft_groups(
            selected_draft_id,
        )

        draft_group_matches = (
            load_tournament_draft_group_matches(
                selected_draft_id,
            )
        )
    else:
        draft_groups = []
        draft_group_matches = []

    draft_bracket_state = (
        load_tournament_draft_bracket_state(
            selected_draft_id,
        )
    )

    bracket_generated = bool(
        draft_bracket_state["generated"]
    )

    setup_locked = bool(
        draft_group_matches
        or bracket_generated
    )

    format_display = {
        tournament_manager.FORMAT_GROUP_STAGE:
            "Group Stage → Double Elimination",
        tournament_manager.FORMAT_DOUBLE_ELIMINATION:
            "Double Elimination Only",
    }

    entry_display = {
        tournament_manager.ENTRY_ALL_WINNERS:
            "All players start in Winners Bracket",
        tournament_manager.ENTRY_SPLIT_BY_GROUP_SEED:
            "Lower seeds may start in Losers Bracket",
    }

    detail_cols = st.columns(4)
    detail_cols[0].metric(
        "Tournament",
        f"WM {int(draft['tournament_number']):02d}",
    )
    detail_cols[1].metric(
        "Date",
        draft["tournament_date"] or "Not set",
    )
    detail_cols[2].metric(
        "Format",
        format_display[draft["format_type"]],
    )
    detail_cols[3].metric(
        "Participants",
        len(draft["participants"]),
    )

    st.caption(
        f"Bracket entry: "
        f"{entry_display[draft['bracket_entry_mode']]}"
    )

    if draft["status"] == "completed":
        st.success(
            "This tournament has been finalized and added "
            "to the permanent archive."
        )
        st.info(
            "Open the Tournaments page to view the archived "
            "results and statistics."
        )
        return

    with st.expander("Edit Tournament Details"):
        current_draft_date = (
            pd.to_datetime(
                draft["tournament_date"]
            ).date()
            if draft["tournament_date"]
            else None
        )

        with st.form(
            f"edit_draft_details_{selected_draft_id}"
        ):
            edited_tournament_date = st.date_input(
                "Tournament date",
                value=current_draft_date,
            )

            save_draft_details = (
                st.form_submit_button(
                    "Save Tournament Details",
                    type="primary",
                )
            )

        if save_draft_details:
            date_text = (
                edited_tournament_date.isoformat()
                if edited_tournament_date is not None
                else None
            )

            try:
                tournament_manager.update_draft_date(
                    DB_PATH,
                    selected_draft_id,
                    date_text,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()
                st.success(
                    "Tournament details updated."
                )
                st.rerun()

    st.subheader("Participants")

    if setup_locked:
        if bracket_generated:
            st.info(
                "Participants and seeding are locked because the bracket "
                "has already been generated. Reset the bracket to make "
                "changes."
            )
        else:
            st.info(
                "Participants, seeding, and group assignments are locked "
                "because the group matches have already been generated. "
                "Reset the group matches to make changes."
            )

    all_players = load_players(True)
    existing_player_ids = {
        str(participant["player_id"])
        for participant in draft["participants"]
    }

    available_players = [
        player
        for player in all_players
        if str(player["player_id"]) not in existing_player_ids
    ]

    if setup_locked:
        st.caption(
            "New participants cannot be added while the groups are locked."
        )

    elif available_players:
        player_by_name = {
            str(player["display_name"]): str(player["player_id"])
            for player in available_players
        }

        with st.form("add_draft_participant"):
            selected_player_name = st.selectbox(
                "Add player",
                options=list(player_by_name),
            )

            if (
                draft["format_type"]
                == tournament_manager.FORMAT_DOUBLE_ELIMINATION
            ):
                next_seed = len(draft["participants"]) + 1

                st.info(
                    f"The player will initially be added as seed {next_seed}. "
                    "The order can be adjusted afterwards."
                )

                manual_seed = next_seed
                group_seed = None
                bracket_seed = next_seed
                starts_in = "winners"

            else:
                st.info(
                    "The player will be included the next time the initial "
                    "seeding is generated."
                )

                manual_seed = None
                group_seed = None
                bracket_seed = None
                starts_in = "winners"

            add_submitted = st.form_submit_button(
                "Add Participant"
            )

        if add_submitted:
            try:
                tournament_manager.add_participant(
                    DB_PATH,
                    selected_draft_id,
                    player_by_name[selected_player_name],
                    manual_seed=(
                        int(manual_seed)
                        if manual_seed is not None
                        else None
                    ),
                    group_seed=group_seed,
                    bracket_seed=bracket_seed,
                    starts_in=starts_in,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()
                st.rerun()
    else:
        st.info("All existing players are already in this draft.")

    with st.expander("Create New Player"):
        with st.form(
            f"create_player_{selected_draft_id}",
            clear_on_submit=True,
        ):
            new_player_name = st.text_input(
                "Player name",
                placeholder="Enter the player's display name",
                disabled=setup_locked,
            )

            new_player_notes = st.text_area(
                "Notes",
                placeholder="Optional notes",
                disabled=setup_locked,
            )

            option_cols = st.columns(2)

            with option_cols[0]:
                new_player_active = st.checkbox(
                    "Active player",
                    value=True,
                    disabled=setup_locked,
                )

            with option_cols[1]:
                new_player_core = st.checkbox(
                    "Core player",
                    value=False,
                    disabled=setup_locked,
                )

            create_player_submitted = st.form_submit_button(
                "Create Player and Add to Draft",
                type="primary",
                disabled=setup_locked,
            )

        if create_player_submitted:
            try:
                tournament_manager.create_player_and_add_to_draft(
                    DB_PATH,
                    selected_draft_id,
                    new_player_name,
                    active=new_player_active,
                    core_player=new_player_core,
                    notes=new_player_notes,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()
                st.success(
                    f"{new_player_name.strip()} was created and "
                    "added to the draft."
                )
                st.rerun()

    if draft["participants"]:
        participant_rows = []

        for participant in draft["participants"]:
            participant_rows.append(
                {
                    "Player": participant["player"],
                    "Initial Seed": participant["manual_seed"],
                    "Starts In": participant["starts_in"].title(),
                }
            )

        st.dataframe(
            pd.DataFrame(participant_rows),
            hide_index=True,
            use_container_width=True,
        )

        remove_player_by_name = {
            str(participant["player"]): str(participant["player_id"])
            for participant in draft["participants"]
        }

        remove_name = st.selectbox(
            "Remove participant",
            options=list(remove_player_by_name),
            disabled=setup_locked,
        )

        if st.button(
            "Remove Selected Participant",
            type="secondary",
            disabled=setup_locked,
        ):
            try:
                tournament_manager.remove_participant(
                    DB_PATH,
                    selected_draft_id,
                    remove_player_by_name[remove_name],
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()
                st.rerun()

        st.subheader("Initial Seeding")

        st.caption(
            "Generate a suggested order from player activity and Elo, "
            "then fine-tune it manually."
        )

        if st.button(
            "Generate Seeding from Elo",
            key=f"generate_seeding_{selected_draft_id}",
            disabled=setup_locked,
        ):
            try:
                tournament_manager.apply_automatic_seeding(
                    DB_PATH,
                    selected_draft_id,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                order_state_key = (
                    f"participant_order_{selected_draft_id}"
                )

                if order_state_key in st.session_state:
                    del st.session_state[order_state_key]

                st.cache_data.clear()
                st.success("Automatic seeding generated.")
                st.rerun()

        st.caption(
            "Active players are seeded first by Elo. Inactive returning "
            "players follow, and new players are placed last. "
            "Use the arrows to fine-tune the order."
        )

        ordered_participants = sorted(
            draft["participants"],
            key=lambda participant: (
                participant["manual_seed"]
                if participant["manual_seed"] is not None
                else 9999,
                str(participant["player"]).casefold(),
            ),
        )

        order_state_key = (
            f"participant_order_{selected_draft_id}"
        )

        stored_ids = [
            str(participant["player_id"])
            for participant in ordered_participants
        ]

        if (
            order_state_key not in st.session_state
            or set(st.session_state[order_state_key])
            != set(stored_ids)
        ):
            st.session_state[order_state_key] = stored_ids

        participant_by_id = {
            str(participant["player_id"]): participant
            for participant in draft["participants"]
        }

        current_order = st.session_state[order_state_key]

        for index, player_id in enumerate(current_order):
            participant = participant_by_id[player_id]

            seed_col, player_col, up_col, down_col = st.columns(
                [1, 6, 1, 1]
            )

            seed_col.markdown(f"**#{index + 1}**")
            player_col.write(participant["player"])

            move_up = up_col.button(
                "↑",
                key=(
                    f"move_up_{selected_draft_id}_"
                    f"{player_id}"
                ),
                disabled=setup_locked or index == 0,
            )

            move_down = down_col.button(
                "↓",
                key=(
                    f"move_down_{selected_draft_id}_"
                    f"{player_id}"
                ),
                disabled=(
                    setup_locked
                    or index == len(current_order) - 1
                ),
            )

            if move_up:
                current_order[index - 1], current_order[index] = (
                    current_order[index],
                    current_order[index - 1],
                )
                st.session_state[order_state_key] = current_order
                st.rerun()

            if move_down:
                current_order[index], current_order[index + 1] = (
                    current_order[index + 1],
                    current_order[index],
                )
                st.session_state[order_state_key] = current_order
                st.rerun()

        if st.button(
            "Save Seeding Order",
            type="primary",
            key=f"save_order_{selected_draft_id}",
            disabled=setup_locked,
        ):
            try:
                tournament_manager.save_participant_order(
                    DB_PATH,
                    selected_draft_id,
                    list(st.session_state[order_state_key]),
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()
                st.session_state[order_state_key] = list(
                    st.session_state[order_state_key]
                )
                st.success("Seeding order saved.")
                st.rerun()

        if (
            draft["format_type"]
            == tournament_manager.FORMAT_GROUP_STAGE
        ):
            st.divider()
            st.subheader("Group Stage")

            groups = draft_groups

            participant_count = len(draft["participants"])
            max_group_count = participant_count // 2

            if max_group_count >= 1:
                default_group_count = (
                    len(groups)
                    if groups
                    else 1
                )

                group_count = st.number_input(
                    "Number of groups",
                    min_value=1,
                    max_value=max_group_count,
                    value=min(
                        default_group_count,
                        max_group_count,
                    ),
                    step=1,
                    key=f"group_count_{selected_draft_id}",
                    disabled=setup_locked,

                )

                st.caption(
                    "Players are distributed by snake seeding. "
                    "Each group must contain at least two players."
                )

                if st.button(
                    (
                        "Recreate Groups"
                        if groups
                        else "Create Groups"
                    ),
                    type="primary",
                    key=f"create_groups_{selected_draft_id}",
                    disabled=setup_locked,
                ):
                    try:
                        tournament_manager.create_draft_groups(
                            DB_PATH,
                            selected_draft_id,
                            int(group_count),
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.cache_data.clear()
                        st.success(
                            "Groups created using snake seeding."
                        )
                        st.rerun()

                if groups and not setup_locked:
                    st.caption(
                        "You can still adjust or recreate the groups "
                        "until the group matches are generated."
                    )

                if groups:
                    if len(groups) > 1 and not setup_locked:
                        st.markdown("#### Move Player")

                        group_by_name = {
                            str(group["group_name"]): str(group["group_id"])
                            for group in groups
                        }

                        player_group_lookup = {
                            str(member["player_id"]): {
                                "player": str(member["player"]),
                                "group_id": str(group["group_id"]),
                                "group_name": str(group["group_name"]),
                            }
                            for group in groups
                            for member in group["members"]
                        }

                        movable_player_by_label = {
                            (
                                f"{data['player']} · "
                                f"{data['group_name']}"
                            ): player_id
                            for player_id, data
                            in player_group_lookup.items()
                        }

                        selected_move_label = st.selectbox(
                            "Player",
                            options=list(movable_player_by_label),
                            key=f"move_group_player_{selected_draft_id}",
                        )

                        selected_move_player_id = (
                            movable_player_by_label[
                                selected_move_label
                            ]
                        )

                        current_group_id = (
                            player_group_lookup[
                                selected_move_player_id
                            ]["group_id"]
                        )

                        available_target_groups = {
                            name: group_id
                            for name, group_id in group_by_name.items()
                            if group_id != current_group_id
                        }

                        selected_target_group_name = st.selectbox(
                            "Move to",
                            options=list(available_target_groups),
                            key=f"move_target_group_{selected_draft_id}",
                        )

                        if st.button(
                            "Move Player",
                            key=f"move_group_member_{selected_draft_id}",
                        ):
                            try:
                                tournament_manager.move_draft_group_member(
                                    DB_PATH,
                                    selected_draft_id,
                                    selected_move_player_id,
                                    available_target_groups[
                                        selected_target_group_name
                                    ],
                                )
                            except ValueError as exc:
                                st.error(str(exc))
                            else:
                                st.cache_data.clear()
                                st.success(
                                    "Player moved to the selected group."
                                )
                                st.rerun()

                    group_columns = st.columns(len(groups))

                    for column, group in zip(
                        group_columns,
                        groups,
                    ):
                        with column:
                            st.markdown(
                                f"### {group['group_name']}"
                            )

                            if group["members"]:
                                group_rows = [
                                    {
                                        "Position": member[
                                            "group_position"
                                        ],
                                        "Initial Seed": member[
                                            "manual_seed"
                                        ],
                                        "Player": member["player"],
                                    }
                                    for member in group["members"]
                                ]

                                st.dataframe(
                                    pd.DataFrame(group_rows),
                                    hide_index=True,
                                    use_container_width=True,
                                    column_config={
                                        "Position":
                                            st.column_config.NumberColumn(
                                                format="%d",
                                            ),
                                        "Initial Seed":
                                            st.column_config.NumberColumn(
                                                format="%d",
                                            ),
                                    },
                                )
                            else:
                                st.info(
                                    "No players assigned."
                                )

                    if not setup_locked:
                        st.warning(
                            "Resetting the groups deletes all current "
                            "group assignments."
                        )

                        confirm_group_reset = st.checkbox(
                            "I understand that the current group "
                            "assignments will be deleted.",
                            key=(
                                f"confirm_group_reset_"
                                f"{selected_draft_id}"
                            ),
                        )

                        if st.button(
                            "Reset Groups",
                            type="secondary",
                            key=(
                                f"reset_groups_"
                                f"{selected_draft_id}"
                            ),
                            disabled=not confirm_group_reset,
                        ):
                            try:
                                tournament_manager.reset_draft_groups(
                                    DB_PATH,
                                    selected_draft_id,
                                )
                            except ValueError as exc:
                                st.error(str(exc))
                            else:
                                order_state_key = (
                                    f"participant_order_"
                                    f"{selected_draft_id}"
                                )

                                if order_state_key in st.session_state:
                                    del st.session_state[
                                        order_state_key
                                    ]

                                st.cache_data.clear()
                                st.success(
                                    "Group assignments reset."
                                )
                                st.rerun()

                    st.divider()
                    st.markdown("### Group Matches")

                    group_matches = draft_group_matches

                    if not setup_locked:
                        if st.button(
                            "Generate Group Matches",
                            type="primary",
                            key=(
                                f"generate_group_matches_"
                                f"{selected_draft_id}"
                            ),
                        ):
                            try:
                                tournament_manager.create_draft_group_matches(
                                    DB_PATH,
                                    selected_draft_id,
                                )
                            except ValueError as exc:
                                st.error(str(exc))
                            else:
                                st.cache_data.clear()
                                st.success(
                                    "Round-robin group matches generated."
                                )
                                st.rerun()

                    if group_matches:
                        st.caption(
                            "Reset the group matches to unlock participants, "
                            "seeding, and group assignments."
                        )

                        group_standings = (
                            load_tournament_draft_group_standings(
                                selected_draft_id,
                            )
                        )

                        st.markdown("### Current Standings")

                        for group_standing in group_standings:
                            st.markdown(
                                f"#### {group_standing['group_name']}"
                            )

                            standing_rows = []

                            for player in group_standing["standings"]:
                                set_rate = (
                                    player["set_win_percentage"]
                                )
                                game_rate = (
                                    player["game_win_percentage"]
                                )

                                standing_rows.append(
                                    {
                                        "Pos.": player["placement"],
                                        "Player": player["player"],
                                        "Sets": (
                                            f"{player['sets_won']}–"
                                            f"{player['sets_lost']}"
                                        ),
                                        "Set Win %": set_rate,
                                        "Games": (
                                            f"{player['games_won']}–"
                                            f"{player['games_lost']}"
                                        ),
                                        "Game Win %": game_rate,
                                    }
                                )

                            st.dataframe(
                                pd.DataFrame(standing_rows),
                                hide_index=True,
                                use_container_width=True,
                                column_config={
                                    "Pos.":
                                        st.column_config.NumberColumn(
                                            format="%d",
                                        ),
                                    "Set Win %":
                                        st.column_config.NumberColumn(
                                            format="%.1f %%",
                                        ),
                                    "Game Win %":
                                        st.column_config.NumberColumn(
                                            format="%.1f %%",
                                        ),
                                },
                            )

                            st.caption(
                                f"{group_standing['decided_matches']} of "
                                f"{group_standing['total_matches']} matches "
                                "decided"
                            )

                        global_ranking = (
                            load_tournament_draft_global_group_ranking(
                                selected_draft_id,
                            )
                        )

                        st.markdown("### Global Group Ranking")

                        if global_ranking["complete"]:
                            st.success(
                                "The group stage is complete. "
                                "The bracket seeding is final."
                            )
                        else:
                            st.warning(
                                "This ranking is provisional because "
                                f"{global_ranking['pending_matches']} "
                                "group matches are still pending."
                            )

                        global_ranking_rows = []

                        for player in global_ranking["ranking"]:
                            set_rate = player[
                                "set_win_percentage"
                            ]
                            game_rate = player[
                                "game_win_percentage"
                            ]

                            global_ranking_rows.append(
                                {
                                    "Seed": player["global_seed"],
                                    "Player": player["player"],
                                    "Group": player["group_name"],
                                    "Group Place": (
                                        player["group_placement"]
                                    ),
                                    "Set Win %": set_rate,
                                    "Game Win %": game_rate,
                                    "Bracket": (
                                        "Winners"
                                        if player["starts_in"]
                                        == "winners"
                                        else "Losers"
                                    ),
                                }
                            )

                        st.dataframe(
                            pd.DataFrame(global_ranking_rows),
                            hide_index=True,
                            use_container_width=True,
                            column_config={
                                "Seed":
                                    st.column_config.NumberColumn(
                                        format="%d",
                                    ),
                                "Group Place":
                                    st.column_config.NumberColumn(
                                        format="%d",
                                    ),
                                "Set Win %":
                                    st.column_config.NumberColumn(
                                        format="%.1f %%",
                                    ),
                                "Game Win %":
                                    st.column_config.NumberColumn(
                                        format="%.1f %%",
                                    ),
                            },
                        )

                        bracket_col_1, bracket_col_2, bracket_col_3 = (
                            st.columns(3)
                        )

                        bracket_col_1.metric(
                            "Bracket Size",
                            global_ranking["bracket_size"],
                        )

                        bracket_col_2.metric(
                            "Winners Bracket",
                            global_ranking["winners_count"],
                        )

                        bracket_col_3.metric(
                            "Losers Bracket",
                            global_ranking["losers_count"],
                        )

                        st.caption(
                            "Global order: group placement, set-win "
                            "percentage, game-win percentage, games won, "
                            "pre-tournament Elo, and initial seed."
                        )

                        st.divider()
                        st.markdown("### Match Results")

                        matches_by_group: dict[
                            str,
                            list[dict[str, Any]],
                        ] = {}

                        for match in group_matches:
                            group_name = str(match["group_name"])

                            matches_by_group.setdefault(
                                group_name,
                                [],
                            ).append(match)

                        for group_name, matches in (
                            matches_by_group.items()
                        ):
                            st.markdown(f"#### {group_name}")

                            rounds: dict[
                                int,
                                list[dict[str, Any]],
                            ] = {}

                            for match in matches:
                                round_number = int(
                                    match["round_number"]
                                )

                                rounds.setdefault(
                                    round_number,
                                    [],
                                ).append(match)

                            for round_number, round_matches in (
                                rounds.items()
                            ):
                                st.markdown(
                                    f"**Round {round_number}**"
                                )

                                for match in round_matches:
                                    status_display = {
                                        "pending": "Pending",
                                        "completed": "Played",
                                        "forfeit": "W–L",
                                        "cancelled": "Cancelled",
                                    }.get(
                                        str(match["status"]),
                                        str(match["status"]),
                                    )

                                    if (
                                        match["status"] == "completed"
                                        and match["player_1_score"]
                                        is not None
                                        and match["player_2_score"]
                                        is not None
                                    ):
                                        result = (
                                            f"{match['player_1_score']}"
                                            f"–"
                                            f"{match['player_2_score']}"
                                        )
                                    elif match["status"] == "forfeit":
                                        result = "W–L"
                                    else:
                                        result = "–"

                                    match_state = (
                                        result
                                        if result != "–"
                                        else status_display
                                    )

                                    match_label = (
                                        f"Match {match['match_number']} · "
                                        f"{match['player_1']} vs "
                                        f"{match['player_2']} · "
                                        f"{match_state}"
                                    )

                                    with st.expander(
                                        match_label,
                                        expanded=(
                                            match["status"] == "pending"
                                        ),
                                    ):
                                        player_1_name = str(match["player_1"])
                                        player_2_name = str(match["player_2"])

                                        st.markdown(
                                            (
                                                '<div style="'
                                                'display:grid;'
                                                'grid-template-columns:1fr auto 1fr;'
                                                'align-items:center;'
                                                'gap:1rem;'
                                                'margin:0.25rem 0 1rem 0;'
                                                '">'
                                                '<div style="'
                                                'text-align:right;'
                                                'font-size:1.65rem;'
                                                'font-weight:750;'
                                                '">'
                                                f'{html.escape(player_1_name)}'
                                                '</div>'
                                                '<div style="'
                                                'opacity:0.55;'
                                                'font-size:0.9rem;'
                                                'font-weight:700;'
                                                '">'
                                                'VS'
                                                '</div>'
                                                '<div style="'
                                                'text-align:left;'
                                                'font-size:1.65rem;'
                                                'font-weight:750;'
                                                '">'
                                                f'{html.escape(player_2_name)}'
                                                '</div>'
                                                '</div>'
                                            ),
                                            unsafe_allow_html=True,
                                        )

                                        summary_parts = [
                                            f"**Status:** {status_display}",
                                        ]

                                        if result != "–":
                                            summary_parts.append(f"**Result:** {result}")

                                        if match["winner"]:
                                            summary_parts.append(
                                                f"**Winner:** {match['winner']}"
                                            )

                                        st.caption(" · ".join(summary_parts))

                                        status_options = [
                                            "Pending",
                                            "Played",
                                            "W–L",
                                            "Cancelled",
                                        ]

                                        status_by_label = {
                                            "Pending":
                                                tournament_manager
                                                .GROUP_MATCH_PENDING,
                                            "Played":
                                                tournament_manager
                                                .GROUP_MATCH_COMPLETED,
                                            "W–L":
                                                tournament_manager
                                                .GROUP_MATCH_FORFEIT,
                                            "Cancelled":
                                                tournament_manager
                                                .GROUP_MATCH_CANCELLED,
                                        }

                                        label_by_status = {
                                            value: key
                                            for key, value
                                            in status_by_label.items()
                                        }

                                        current_status_label = (
                                            label_by_status.get(
                                                str(match["status"]),
                                                "Pending",
                                            )
                                        )

                                        status_key = (
                                            f"group_match_status_{match['group_match_id']}"
                                        )

                                        selected_status_label = st.selectbox(
                                            "Status",
                                            options=status_options,
                                            index=status_options.index(
                                                current_status_label
                                            ),
                                            key=status_key,
                                        )

                                        selected_status = status_by_label[
                                            selected_status_label
                                        ]

                                        with st.form(
                                            f"edit_group_match_{match['group_match_id']}"
                                        ):
                                            winner_id = None
                                            player_1_score = None
                                            player_2_score = None

                                            if selected_status in {
                                                tournament_manager.GROUP_MATCH_PENDING,
                                                tournament_manager.GROUP_MATCH_COMPLETED,
                                            }:
                                                score_cols = st.columns(2)

                                                with score_cols[0]:
                                                    player_1_score = st.number_input(
                                                        f"{match['player_1']} score",
                                                        min_value=0,
                                                        value=int(
                                                            match["player_1_score"]
                                                            if match["player_1_score"] is not None
                                                            else 0
                                                        ),
                                                        step=1,
                                                        key=(
                                                            f"group_match_p1_score_"
                                                            f"{match['group_match_id']}"
                                                        ),
                                                    )

                                                with score_cols[1]:
                                                    player_2_score = st.number_input(
                                                        f"{match['player_2']} score",
                                                        min_value=0,
                                                        value=int(
                                                            match["player_2_score"]
                                                            if match["player_2_score"] is not None
                                                            else 0
                                                        ),
                                                        step=1,
                                                        key=(
                                                            f"group_match_p2_score_"
                                                            f"{match['group_match_id']}"
                                                        ),
                                                    )

                                            elif (
                                                selected_status
                                                == tournament_manager.GROUP_MATCH_FORFEIT
                                            ):
                                                winner_options = {
                                                    str(match["player_1"]): str(
                                                        match["player_1_id"]
                                                    ),
                                                    str(match["player_2"]): str(
                                                        match["player_2_id"]
                                                    ),
                                                }

                                                current_winner_name = (
                                                    str(match["winner"])
                                                    if match["winner"]
                                                    else str(match["player_1"])
                                                )

                                                winner_names = list(winner_options)

                                                selected_winner_name = st.selectbox(
                                                    "Winner",
                                                    options=winner_names,
                                                    index=(
                                                        winner_names.index(current_winner_name)
                                                        if current_winner_name in winner_names
                                                        else 0
                                                    ),
                                                    key=(
                                                        f"group_match_winner_"
                                                        f"{match['group_match_id']}"
                                                    ),
                                                )

                                                winner_id = winner_options[
                                                    selected_winner_name
                                                ]

                                            save_result = st.form_submit_button(
                                                "Save Result",
                                                type="primary",
                                            )

                                        if save_result:
                                            if (
                                                selected_status
                                                == tournament_manager.GROUP_MATCH_PENDING
                                                and player_1_score is not None
                                                and player_2_score is not None
                                                and player_1_score != player_2_score
                                            ):
                                                selected_status = (
                                                    tournament_manager.GROUP_MATCH_COMPLETED
                                                )
                                            try:
                                                tournament_manager.update_draft_group_match(
                                                    DB_PATH,
                                                    str(
                                                        match[
                                                            "group_match_id"
                                                        ]
                                                    ),
                                                    status=selected_status,
                                                    winner_id=winner_id,
                                                    player_1_score=(
                                                        int(player_1_score)
                                                        if player_1_score
                                                        is not None
                                                        else None
                                                    ),
                                                    player_2_score=(
                                                        int(player_2_score)
                                                        if player_2_score
                                                        is not None
                                                        else None
                                                    ),
                                                )
                                            except ValueError as exc:
                                                st.error(str(exc))
                                            else:
                                                st.cache_data.clear()
                                                st.success(
                                                    "Match result saved."
                                                )
                                                st.rerun()

                        if st.button(
                            "Reset Group Matches",
                            type="secondary",
                            key=(
                                f"reset_group_matches_"
                                f"{selected_draft_id}"
                            ),
                        ):
                            try:
                                tournament_manager.reset_draft_group_matches(
                                    DB_PATH,
                                    selected_draft_id,
                                )
                            except ValueError as exc:
                                st.error(str(exc))
                            else:
                                st.cache_data.clear()
                                st.success(
                                    "Group matches reset."
                                )
                                st.rerun()

            else:
                st.info(
                    "At least two participants are required "
                    "to create a group."
                )

    else:
        st.info("No participants have been added yet.")

    st.divider()
    st.subheader("Double Elimination Bracket")

    bracket_can_be_generated = True

    if len(draft["participants"]) < 3:
        bracket_can_be_generated = False
        st.warning(
            "At least 3 participants are required to generate "
            "a double-elimination bracket."
        )

    if (
        draft["format_type"]
        == tournament_manager.FORMAT_GROUP_STAGE
    ):
        if not draft_groups:
            bracket_can_be_generated = False
            st.info(
                "Create the tournament groups before generating "
                "the bracket."
            )
        else:
            global_ranking = (
                load_tournament_draft_global_group_ranking(
                    selected_draft_id,
                )
            )

            if not global_ranking["complete"]:
                bracket_can_be_generated = False
                st.info(
                    "Complete all group matches before generating "
                    "the bracket."
                )

    if not bracket_generated:
        if st.button(
            "Generate Bracket",
            type="primary",
            key=f"generate_bracket_{selected_draft_id}",
            disabled=not bracket_can_be_generated,
        ):
            try:
                result = (
                    tournament_manager.generate_draft_bracket(
                        DB_PATH,
                        selected_draft_id,
                    )
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()
                st.success(
                    f"{result['bracket_size']}-player bracket "
                    f"generated with "
                    f"{result['matches_created']} matches."
                )
                st.rerun()

    else:
        bracket_metrics = st.columns(4)

        bracket_metrics[0].metric(
            "Matches",
            draft_bracket_state["match_count"],
        )
        bracket_metrics[1].metric(
            "Ready",
            draft_bracket_state["pending_count"],
        )
        bracket_metrics[2].metric(
            "Waiting",
            draft_bracket_state["waiting_count"],
        )
        bracket_metrics[3].metric(
            "Completed",
            draft_bracket_state["completed_count"],
        )

        if draft_bracket_state["champion_name"]:
            st.success(
                f"Champion: "
                f"{draft_bracket_state['champion_name']}"
            )

        if draft_bracket_state["champion_name"]:
            st.markdown("### Finalize Tournament")

            try:
                finalization_preview = (
                    load_tournament_draft_finalization_preview(
                        selected_draft_id,
                    )
                )
            except ValueError as exc:
                st.warning(str(exc))
            else:
                finalization_cols = st.columns(4)

                finalization_cols[0].metric(
                    "Champion",
                    finalization_preview["champion_name"],
                )
                finalization_cols[1].metric(
                    "Participants",
                    finalization_preview["participant_count"],
                )
                finalization_cols[2].metric(
                    "Matches to Archive",
                    finalization_preview["matches_to_archive"],
                )
                finalization_cols[3].metric(
                    "Tournament",
                    (
                        f"WC "
                        f"{finalization_preview['tournament_number']:02d}"
                    ),
                )

                st.markdown("#### Final Placements")

                placement_rows = [
                    {
                        "Placement": placement["placement"],
                        "Player": placement["player"],
                        "Seed": placement["seed"],
                    }
                    for placement
                    in finalization_preview["placements"]
                ]

                st.dataframe(
                    pd.DataFrame(placement_rows),
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Placement":
                            st.column_config.NumberColumn(
                                format="%d",
                            ),
                        "Seed":
                            st.column_config.NumberColumn(
                                format="%d",
                            ),
                    },
                )

                if (
                    finalization_preview[
                        "automatic_bracket_matches_omitted"
                    ]
                ):
                    st.caption(
                        f"{finalization_preview['automatic_bracket_matches_omitted']} "
                        "automatic, cancelled, or inactive bracket matches "
                        "will not be added to the archive."
                    )

                if (
                    finalization_preview[
                        "cancelled_group_matches_omitted"
                    ]
                ):
                    st.caption(
                        f"{finalization_preview['cancelled_group_matches_omitted']} "
                        "cancelled group matches will not be added "
                        "to the archive."
                    )

                st.warning(
                    "Finalizing writes the tournament, participants, "
                    "placements, and match results to the permanent archive. "
                    "The draft can no longer be edited afterwards."
                )

                confirm_finalization = st.checkbox(
                    (
                        f"I confirm that WC "
                        f"{finalization_preview['tournament_number']:02d} "
                        "is complete and ready for the archive."
                    ),
                    key=(
                        f"confirm_tournament_finalization_"
                        f"{selected_draft_id}"
                    ),
                )

                if st.button(
                    "Finalize Tournament",
                    type="primary",
                    key=(
                        f"finalize_tournament_"
                        f"{selected_draft_id}"
                    ),
                    disabled=not confirm_finalization,
                ):
                    try:
                        result = (
                            tournament_manager
                            .finalize_draft_tournament(
                                DB_PATH,
                                selected_draft_id,
                            )
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(
                            "The tournament could not be finalized: "
                            f"{exc}"
                        )
                    else:
                        st.cache_data.clear()
                        st.success(
                            f"WC {result['tournament_number']:02d} "
                            f"was archived successfully. "
                            f"{result['matches_archived']} matches "
                            "were added."
                        )
                        st.rerun()

        bracket_matches = draft_bracket_state["matches"]

        visible_match_codes = {
            str(match["match_code"])
            for match in bracket_matches
            if match["status"] != "inactive"
        }

        dialog_state_key = (
            f"open_bracket_match_code_"
            f"{selected_draft_id}"
        )

        open_match_code = st.session_state.get(
            dialog_state_key
        )

        if open_match_code not in visible_match_codes:
            open_match_code = None
            st.session_state.pop(
                dialog_state_key,
                None,
            )

        st.markdown("### Bracket View")

        clicked_match_code = (
            bracket_visualization.render_bracket(
                bracket_matches,
                draft_bracket_state["routes"],
                selected_match_code=open_match_code,
                component_key=(
                    f"bracket_component_"
                    f"{selected_draft_id}"
                ),
            )
        )

        if (
            clicked_match_code
            and clicked_match_code in visible_match_codes
            and clicked_match_code != open_match_code
        ):
            st.session_state[
                dialog_state_key
            ] = clicked_match_code

            st.rerun()

        if open_match_code:
            selected_dialog_match = next(
                (
                    match
                    for match in bracket_matches
                    if str(match["match_code"])
                    == str(open_match_code)
                ),
                None,
            )

            if selected_dialog_match is not None:
                show_bracket_match_dialog(
                    selected_dialog_match,
                    dialog_state_key,
                )
            else:
                st.session_state.pop(
                    dialog_state_key,
                    None,
                )

        st.markdown("### Match Management")

        visible_bracket_matches = [
            match
            for match in bracket_matches
            if match["status"] != "inactive"
        ]

        matches_by_side: dict[
            str,
            list[dict[str, Any]],
        ] = {
            "winners": [],
            "losers": [],
            "finals": [],
        }

        for match in visible_bracket_matches:
            bracket_side = str(match["bracket_side"])

            matches_by_side.setdefault(
                bracket_side,
                [],
            ).append(match)

        side_labels = {
            "winners": "Winners Bracket",
            "losers": "Losers Bracket",
            "finals": "Finals",
        }

        for bracket_side in (
            "winners",
            "losers",
            "finals",
        ):
            side_matches = matches_by_side.get(
                bracket_side,
                [],
            )

            if not side_matches:
                continue

            st.markdown(
                f"### {side_labels[bracket_side]}"
            )

            matches_by_round: dict[
                tuple[int, str],
                list[dict[str, Any]],
            ] = {}

            for match in side_matches:
                round_key = (
                    int(match["round_number"]),
                    str(match["round_label"]),
                )

                matches_by_round.setdefault(
                    round_key,
                    [],
                ).append(match)

            for (
                round_number,
                round_label,
            ), round_matches in matches_by_round.items():
                st.markdown(f"#### {round_label}")

                for match in round_matches:
                    player_1_name = (
                        str(match["player_1_name"])
                        if match["player_1_name"]
                        else "TBD"
                    )

                    player_2_name = (
                        str(match["player_2_name"])
                        if match["player_2_name"]
                        else "TBD"
                    )

                    match_status = str(match["status"])

                    status_display = {
                        "waiting": "Waiting",
                        "pending": "Ready",
                        "completed": "Played",
                        "forfeit": "W–L",
                        "bye": "Bye",
                        "cancelled": "Cancelled",
                    }.get(
                        match_status,
                        match_status.title(),
                    )

                    if (
                        match_status == "completed"
                        and match["player_1_score"] is not None
                        and match["player_2_score"] is not None
                    ):
                        result_display = (
                            f"{match['player_1_score']}"
                            f"–"
                            f"{match['player_2_score']}"
                        )

                    elif match_status == "forfeit":
                        result_display = "W–L"

                    elif match_status == "bye":
                        result_display = "Bye"

                    else:
                        result_display = status_display

                    match_label = (
                        f"{match['match_code']} · "
                        f"{player_1_name} vs {player_2_name} · "
                        f"{result_display}"
                    )

                    with st.expander(
                        match_label,
                        expanded=False,
                    ):
                        st.markdown(
                            (
                                '<div style="'
                                'display:grid;'
                                'grid-template-columns:1fr auto 1fr;'
                                'align-items:center;'
                                'gap:1rem;'
                                'margin:0.25rem 0 1rem 0;'
                                '">'
                                '<div style="'
                                'text-align:right;'
                                'font-size:1.5rem;'
                                'font-weight:750;'
                                '">'
                                f'{html.escape(player_1_name)}'
                                '</div>'
                                '<div style="'
                                'opacity:0.55;'
                                'font-size:0.9rem;'
                                'font-weight:700;'
                                '">'
                                'VS'
                                '</div>'
                                '<div style="'
                                'text-align:left;'
                                'font-size:1.5rem;'
                                'font-weight:750;'
                                '">'
                                f'{html.escape(player_2_name)}'
                                '</div>'
                                '</div>'
                            ),
                            unsafe_allow_html=True,
                        )

                        summary_parts = [
                            f"**Status:** {status_display}",
                        ]

                        if (
                            match["winner_name"]
                            is not None
                        ):
                            summary_parts.append(
                                f"**Winner:** "
                                f"{match['winner_name']}"
                            )

                        if (
                            match_status == "completed"
                            and match["player_1_score"]
                            is not None
                            and match["player_2_score"]
                            is not None
                        ):
                            summary_parts.append(
                                f"**Result:** "
                                f"{match['player_1_score']}–"
                                f"{match['player_2_score']}"
                            )

                        st.caption(
                            " · ".join(summary_parts)
                        )

                        if match_status == "waiting":
                            st.info(
                                "This match is waiting for players "
                                "from earlier rounds."
                            )

                        elif match_status == "bye":
                            st.info(
                                f"{match['winner_name']} advances "
                                "automatically."
                            )

                        elif match_status == "cancelled":
                            st.info(
                                "This match has been cancelled."
                            )

                        elif match_status == "pending":
                            result_type = st.radio(
                                "Result type",
                                options=[
                                    "Played",
                                    "W–L",
                                    "Cancelled",
                                ],
                                horizontal=True,
                                key=(
                                    f"bracket_result_type_"
                                    f"{match['bracket_match_id']}"
                                ),
                            )

                            with st.form(
                                f"edit_bracket_match_"
                                f"{match['bracket_match_id']}"
                            ):
                                winner_id = None
                                player_1_score = None
                                player_2_score = None

                                if result_type == "Played":
                                    score_cols = st.columns(2)

                                    with score_cols[0]:
                                        player_1_score = (
                                            st.number_input(
                                                f"{player_1_name} score",
                                                min_value=0,
                                                value=0,
                                                step=1,
                                                key=(
                                                    f"bracket_p1_score_"
                                                    f"{match['bracket_match_id']}"
                                                ),
                                            )
                                        )

                                    with score_cols[1]:
                                        player_2_score = (
                                            st.number_input(
                                                f"{player_2_name} score",
                                                min_value=0,
                                                value=0,
                                                step=1,
                                                key=(
                                                    f"bracket_p2_score_"
                                                    f"{match['bracket_match_id']}"
                                                ),
                                            )
                                        )

                                elif result_type == "W–L":
                                    winner_options = {
                                        player_1_name: str(
                                            match["player_1_id"]
                                        ),
                                        player_2_name: str(
                                            match["player_2_id"]
                                        ),
                                    }

                                    selected_winner_name = (
                                        st.selectbox(
                                            "Winner",
                                            options=list(
                                                winner_options
                                            ),
                                            key=(
                                                f"bracket_winner_"
                                                f"{match['bracket_match_id']}"
                                            ),
                                        )
                                    )

                                    winner_id = winner_options[
                                        selected_winner_name
                                    ]

                                save_bracket_result = (
                                    st.form_submit_button(
                                        "Save Result",
                                        type="primary",
                                    )
                                )

                            if save_bracket_result:
                                if result_type == "Played":
                                    result_status = "completed"

                                elif result_type == "W–L":
                                    result_status = "forfeit"

                                else:
                                    result_status = "cancelled"

                                try:
                                    tournament_manager.update_draft_bracket_match(
                                        DB_PATH,
                                        str(
                                            match[
                                                "bracket_match_id"
                                            ]
                                        ),
                                        status=result_status,
                                        winner_id=winner_id,
                                        player_1_score=(
                                            int(player_1_score)
                                            if player_1_score
                                            is not None
                                            else None
                                        ),
                                        player_2_score=(
                                            int(player_2_score)
                                            if player_2_score
                                            is not None
                                            else None
                                        ),
                                    )
                                except ValueError as exc:
                                    st.error(str(exc))
                                else:
                                    st.cache_data.clear()
                                    st.success(
                                        "Bracket result saved."
                                    )
                                    st.rerun()

                        elif match_status in {
                            "completed",
                            "forfeit",
                            "cancelled",
                        }:
                            st.warning(
                                "Resetting this result also clears all "
                                "dependent later bracket matches."
                            )

                            confirm_result_reset = st.checkbox(
                                "I understand that dependent bracket "
                                "results will be cleared.",
                                key=(
                                    f"confirm_bracket_match_reset_"
                                    f"{match['bracket_match_id']}"
                                ),
                            )

                            if st.button(
                                "Reset Result",
                                type="secondary",
                                key=(
                                    f"reset_bracket_match_"
                                    f"{match['bracket_match_id']}"
                                ),
                                disabled=not confirm_result_reset,
                            ):
                                try:
                                    result = (
                                        tournament_manager
                                        .reset_draft_bracket_match_result(
                                            DB_PATH,
                                            str(
                                                match[
                                                    "bracket_match_id"
                                                ]
                                            ),
                                        )
                                    )
                                except ValueError as exc:
                                    st.error(str(exc))
                                else:
                                    st.cache_data.clear()
                                    st.success(
                                        f"{result['match_code']} reset. "
                                        f"{result['matches_cleared']} "
                                        "dependent matches were cleared."
                                    )
                                    st.rerun()

        st.warning(
            "Resetting the bracket deletes all bracket matches "
            "and results. Group-stage results are preserved."
        )

        confirm_bracket_reset = st.checkbox(
            "I understand that all bracket results will be deleted.",
            key=f"confirm_bracket_reset_{selected_draft_id}",
        )

        if st.button(
            "Reset Bracket",
            type="secondary",
            key=f"reset_bracket_{selected_draft_id}",
            disabled=not confirm_bracket_reset,
        ):
            try:
                result = tournament_manager.reset_draft_bracket(
                    DB_PATH,
                    selected_draft_id,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()
                st.success(
                    f"Bracket reset: "
                    f"{result['matches_deleted']} matches deleted."
                )
                st.rerun()

    st.divider()
    st.subheader("Danger Zone")

    confirm_delete = st.checkbox(
        "I understand that this permanently deletes the draft.",
        key=f"confirm_delete_{selected_draft_id}",
    )

    if st.button(
        "Delete Draft",
        type="primary",
        disabled=not confirm_delete,
    ):
        try:
            tournament_manager.delete_draft(
                DB_PATH,
                selected_draft_id,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.cache_data.clear()
            st.success("Tournament draft deleted.")
            st.rerun()

def clear_navigation_query_params() -> None:
    """Clears direct-link parameters after manual sidebar navigation."""

    st.query_params.clear()

def main() -> None:
    require_database()

    st.sidebar.title("Navigation")
    page_options = [
        "Home",
        "Players",
        "Matchups",
        "Tournaments",
        "Tournament Manager",
    ]

    requested_page = st.query_params.get(
        "page"
    )

    if (
        requested_page in page_options
        and st.session_state.get("navigation_page")
        != requested_page
    ):
        st.session_state["navigation_page"] = requested_page

    page = st.sidebar.radio(
        "Section",
        page_options,
        key="navigation_page",
        label_visibility="collapsed",
        on_change=clear_navigation_query_params,
    )

    include_inactive = st.sidebar.checkbox(
        "Include inactive players",
        value=False,
    )

    st.sidebar.divider()
    st.sidebar.caption(f"Database: `{DB_PATH.name}`")
    st.sidebar.caption("Version 0.1.0")

    if st.sidebar.button("Reload data"):
        st.cache_data.clear()
        st.rerun()

    if page == "Home":
        show_home(include_inactive)
    elif page == "Players":
        show_player_page(include_inactive)
    elif page == "Matchups":
        show_matchups(include_inactive)
    elif page == "Tournaments":
        show_tournaments()
    elif page == "Tournament Manager":
        show_tournament_manager()


if __name__ == "__main__":
    main()
