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
    from dashboard_pages import home as home_page
    from dashboard_pages import matchups as matchups_page
    from dashboard_pages import monte_carlo as monte_carlo_page
    from dashboard_pages import player as player_page
    from dashboard_pages import tournaments as tournaments_page
    from dashboard_pages import tournament_manager as tournament_manager_page
    from dashboard_pages.ui_components import (
        archived_match_result_html,
        compact_score_input_styles,
    )
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
MODEL_ARTIFACT_PATH = (
    PROJECT_ROOT / "data" / "model_artifacts" / "combined_v0.2"
)


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
            f"WC {int(latest_tournament['tournament_number']):02d}"
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
                m.challonge_group_id,
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
                winner.player_id AS winner_id,
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
                winner.player_id,
                winner.display_name,
                t.match_data_available
            ORDER BY t.tournament_number DESC
            """
        ).fetchall()

    return [
        {
            "WC": f"WC {row['tournament_number']:02d}",
            "Date": row["tournament_date"],
            "Winner": row["winner"] or "Unknown",
            "Winner ID": row["winner_id"],
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
    """Render the Home page through its focused page module."""

    home_page.render_home(
        include_inactive,
        load_tournament_preview_data=load_tournament_preview_data,
        load_elo_ranking=load_elo_ranking,
        load_player_timeline=load_player_timeline,
        load_tournaments=load_tournaments,
        load_database_quality=load_database_quality,
    )




def tournament_elo_changes(
    tournament_number: int,
    participants: list[dict[str, Any]],
    include_inactive: bool,
) -> list[dict[str, Any]]:
    """Calculates Elo and ranking changes for tournament participants."""

    changes: list[dict[str, Any]] = []

    for participant in participants:
        player_id = str(participant["player_id"])
        timeline = load_player_timeline(
            player_id,
            include_inactive=include_inactive,
        )
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
                "player_id": player_id,
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
    """Render the Player page through its focused page module."""

    player_page.render_player_page(
        include_inactive,
        load_players=load_players,
        load_player_profile=load_player_profile,
        load_player_timeline=load_player_timeline,
        load_player_history=load_player_history,
        load_player_insights=load_player_insights,
        load_elo_ranking=load_elo_ranking,
        format_ordinal=format_ordinal,
    )

def show_matchups(include_inactive: bool) -> None:
    """Render the Matchups page through its focused page module."""

    matchups_page.render_matchups(
        include_inactive,
        load_players=load_players,
        load_h2h_matrix=load_h2h_matrix,
        load_player_profile=load_player_profile,
        load_player_timeline=load_player_timeline,
        load_head_to_head=load_head_to_head,
        load_elo_ranking=load_elo_ranking,
        load_tournament_detail=load_tournament_detail,
    )

@st.dialog(
    "Archived Match",
    width="medium",
    dismissible=False,
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

    winner_name = match.get(
        "winner_name"
    )
    status_label = {
            "completed": "Played",
            "forfeit": "W–L",
            "waiting": "Waiting",
    }.get(
        str(match.get("status")),
        str(match.get("status") or "Unknown").title(),
    )
    st.markdown(
        archived_match_result_html(
            (
                f"WC {tournament_number:02d} · "
                f"{match['round_label']} · {match['match_code']}"
            ),
            player_1_name,
            player_2_name,
            score_text,
            winner_name=(str(winner_name) if winner_name else None),
            status_label=status_label,
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="height:0.65rem;"></div>',
        unsafe_allow_html=True,
    )

    if st.button(
        "Close",
        width="stretch",
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

def show_tournaments(include_inactive: bool) -> None:
    """Render the Tournaments page through its focused page module."""

    tournaments_page.render_tournaments(
        include_inactive=include_inactive,
        load_tournaments=load_tournaments,
        load_tournament_detail=load_tournament_detail,
        load_tournament_milestones=load_tournament_milestones,
        tournament_elo_changes=tournament_elo_changes,
        format_ordinal=format_ordinal,
        show_archived_match_dialog=show_archived_match_dialog,
    )


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
    player_1_win_probability = match.get(
        "player_1_win_probability",
        st.session_state.get(
            f"dialog_bracket_probability_{match_code}"
        ),
    )

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
            + (
                '<div style="'
                'display:grid;'
                'grid-template-columns:1fr 1fr;'
                'gap:2rem;'
                'margin:-0.75rem 0 1.25rem;'
                'color:rgba(250,250,250,0.58);'
                'font-size:0.82rem;'
                '">'
                '<div style="text-align:right;">'
                f"{float(player_1_win_probability):.1%} win chance"
                '</div>'
                '<div style="text-align:left;">'
                f"{1.0 - float(player_1_win_probability):.1%} "
                'win chance'
                '</div>'
                '</div>'
                if player_1_win_probability is not None
                else ""
            )
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
        result_type = st.segmented_control(
            "Result type",
            options=[
                "Played",
                "W–L",
                "Cancelled",
            ],
            default="Played",
            key=(
                f"dialog_result_type_"
                f"{match['bracket_match_id']}"
            ),
        )
        st.markdown(
            compact_score_input_styles("dialog_bracket_score_"),
            unsafe_allow_html=True,
        )

        with st.form(
            f"dialog_bracket_match_"
            f"{match['bracket_match_id']}",
            border=False,
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
                        key=(
                            "dialog_bracket_score_"
                            f"{match['bracket_match_id']}_player_1"
                        ),
                    )

                with score_cols[1]:
                    player_2_score = st.number_input(
                        f"{player_2_name} score",
                        min_value=0,
                        value=0,
                        step=1,
                        key=(
                            "dialog_bracket_score_"
                            f"{match['bracket_match_id']}_player_2"
                        ),
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
                width="stretch",
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
            width="stretch",
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
    """Render Tournament Manager through its focused page module."""

    tournament_manager_page.render_tournament_manager(
        db_path=DB_PATH,
        model_artifact_path=MODEL_ARTIFACT_PATH,
        load_players=load_players,
        load_tournaments=load_tournaments,
        load_tournament_drafts=load_tournament_drafts,
        load_tournament_draft=load_tournament_draft,
        load_tournament_draft_groups=load_tournament_draft_groups,
        load_tournament_draft_group_matches=(
            load_tournament_draft_group_matches
        ),
        load_tournament_draft_group_standings=(
            load_tournament_draft_group_standings
        ),
        load_tournament_draft_global_group_ranking=(
            load_tournament_draft_global_group_ranking
        ),
        load_tournament_draft_bracket_state=(
            load_tournament_draft_bracket_state
        ),
        load_tournament_draft_finalization_preview=(
            load_tournament_draft_finalization_preview
        ),
        show_bracket_match_dialog=show_bracket_match_dialog,
    )

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
        "Monte Carlo",
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
        show_tournaments(include_inactive)
    elif page == "Tournament Manager":
        show_tournament_manager()
    elif page == "Monte Carlo":
        monte_carlo_page.render_monte_carlo(
            artifact_path=MODEL_ARTIFACT_PATH,
            load_players=load_players,
            load_elo_ranking=load_elo_ranking,
        )


if __name__ == "__main__":
    main()
