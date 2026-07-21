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
def load_player_timeline(player_id: str) -> list[dict[str, Any]]:
    return stats.get_player_elo_timeline(
        player_id,
        DB_PATH,
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
                m.stage,
                m.round_label,
                m.bracket_side,
                p1.display_name AS player_1,
                p2.display_name AS player_2,
                winner.display_name AS winner,
                m.player_1_score,
                m.player_2_score,
                m.score_known,
                m.walkover,
                m.completed_at,
                m.suggested_play_order,
                m.match_id
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
        matches = int(
            connection.execute(
                "SELECT COUNT(*) FROM matches"
            ).fetchone()[0]
        )
        scores_present = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM matches
                WHERE score_known = 1
                  AND player_1_score IS NOT NULL
                  AND player_2_score IS NOT NULL
                """
            ).fetchone()[0]
        )

    score_rate = (scores_present / matches * 100.0) if matches else 0.0
    return {
        "tournaments": tournaments,
        "players": players,
        "matches": matches,
        "scores_present": scores_present,
        "score_rate": score_rate,
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
    st.caption("Current ranking and overview of the private World Championship archive")

    quality = load_database_quality()
    st.subheader("📊 Database")
    quality_cols = st.columns(4)
    quality_cols[0].metric("Tournaments", quality["tournaments"])
    quality_cols[1].metric("Players", quality["players"])
    quality_cols[2].metric("Matches", quality["matches"])
    quality_cols[3].metric(
        "Scores Available",
        f"{quality['score_rate']:.1f} %",
        f"{quality['scores_present']} von {quality['matches']}",
    )

    ranking = load_elo_ranking(include_inactive)

    if not ranking:
        st.warning("No rated Elo matches found yet.")
        return

    leader = ranking[0]
    total_matches = sum(entry["rated_matches"] for entry in ranking) // 2

    col1, col2, col3 = st.columns(3)
    col1.metric("Current No. 1", leader["player"])
    col2.metric("No. 1 Elo", f"{leader['elo']:.1f}")
    col3.metric("Rated Matches", total_matches)

    preview_data = load_tournament_preview_data()
    preview_text = narratives.generate_tournament_preview(
        preview_data,
    )

    st.subheader("🔮 Next Tournament Preview")
    st.info(preview_text)

    st.subheader("Current Elo Ranking")

    ranking_df = pd.DataFrame(
        [
            {
                "Rank": entry["rank"],
                "Players": entry["player"],
                "Elo": entry["elo"],
                "Rated Matches": entry["rated_matches"],
                "Status": "Active" if entry["active"] else "Inactive",
            }
            for entry in ranking
        ]
    )

    st.dataframe(
        ranking_df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Rank": st.column_config.NumberColumn(format="%d"),
            "Elo": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    chart = (
        alt.Chart(ranking_df)
        .mark_bar()
        .encode(
            x=alt.X("Elo:Q", scale=alt.Scale(zero=False), title="Elo"),
            y=alt.Y("Players:N", sort="-x", title=None),
            tooltip=["Rank", "Players", alt.Tooltip("Elo:Q", format=".1f")],
        )
        .properties(height=max(260, len(ranking_df) * 36))
    )
    st.altair_chart(chart, use_container_width=True)



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


def show_h2h_drilldown(
    left_name: str,
    right_name: str,
    player_ids: dict[str, str],
) -> None:
    """Shows details and match history for a selected player pair."""

    if left_name == right_name:
        st.info("Select two different players.")
        return

    h2h = load_head_to_head(
        player_ids[left_name],
        player_ids[right_name],
    )

    st.subheader(f"{left_name} vs. {right_name}")
    cols = st.columns(4)
    cols[0].metric(f"Wins {left_name}", h2h["player_a"]["wins"])
    cols[1].metric(f"Wins {right_name}", h2h["player_b"]["wins"])
    cols[2].metric(
        f"Win Rate {left_name}",
        format_percent(h2h["player_a"]["winrate"]),
    )
    cols[3].metric("Head-to-Head Matches", h2h["decided_matches"])

    if h2h["last_match"]:
        last = h2h["last_match"]
        round_text = last["round_label"] or last["stage"] or "Unknown round"
        score_text = last["score"] or "–"
        st.info(
            f"**{last['tournament']} · {round_text}** — "
            f"{last['winner'] or 'Unknown winner'} won {score_text}."
        )

    if h2h["history"]:
        rows = []
        for match in reversed(h2h["history"]):
            rows.append(
                {
                    "Tournament": match["tournament"],
                    "Date": match["date"],
                    "Round": (
                        match["round_label"]
                        or match["stage"]
                        or "–"
                    ),
                    "Winner": match["winner"] or "Pending",
                    "Result": match["score"] or "–",
                }
            )
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("These two players have not faced each other yet.")


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

    selected_name = st.selectbox(
        "Select player",
        options=list(player_by_name),
    )
    player_id = player_by_name[selected_name]

    profile = load_player_profile(player_id)
    timeline = load_player_timeline(player_id)
    history = load_player_history(player_id)

    ranking = load_elo_ranking(True)
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

    st.markdown(
        f"""
        <div style="
            display:flex;
            align-items:center;
            gap:1.25rem;
            padding:1.25rem 1.4rem;
            margin:0.5rem 0 1.25rem 0;
            border:1px solid rgba(128,128,128,0.25);
            border-radius:1rem;
        ">
            <div style="
                width:4.5rem;
                height:4.5rem;
                border-radius:50%;
                display:flex;
                align-items:center;
                justify-content:center;
                background:rgba(128,128,128,0.18);
                font-size:1.55rem;
                font-weight:800;
                flex:0 0 auto;
            ">{initials}</div>
            <div style="flex:1;">
                <div style="font-size:1.65rem;font-weight:800;">{safe_name}</div>
                <div style="opacity:0.72;margin-top:0.15rem;">
                    Smash World Championship player profile
                </div>
            </div>
            <div style="display:flex;gap:1.75rem;text-align:center;flex-wrap:wrap;">
                <div>
                    <div style="opacity:0.65;font-size:0.78rem;">RANK</div>
                    <div style="font-size:1.45rem;font-weight:800;">{rank_text}</div>
                </div>
                <div>
                    <div style="opacity:0.65;font-size:0.78rem;">ELO</div>
                    <div style="font-size:1.45rem;font-weight:800;">
                        {current_elo:.1f}
                    </div>
                </div>
                <div>
                    <div style="opacity:0.65;font-size:0.78rem;">TITLES</div>
                    <div style="font-size:1.45rem;font-weight:800;">
                        {profile['titles']}
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Peak Elo",
        f"{float(profile.get('peak_elo') or 1000.0):.1f}",
    )
    col2.metric("Appearances", profile["appearances"])
    col3.metric("Matches", profile["decided_matches"])
    col4.metric("Win Rate", format_percent(profile["winrate"]))

    insights = load_player_insights(player_id)

    favorite = insights["favorite"]
    nemesis = insights["nemesis"]

    insight_cols = st.columns(4)

    insight_cols[0].metric(
        "Best Matchup",
        favorite["opponent"] if favorite else "–",
        (
            f"{favorite['wins']}:{favorite['losses']} · "
            f"{favorite['winrate']:.1f} %"
            if favorite else None
        ),
        delta_color="normal",
    )

    insight_cols[1].metric(
        "Nemesis",
        nemesis["opponent"] if nemesis else "–",
        (
            f"{nemesis['wins']}:{nemesis['losses']} · "
            f"{nemesis['winrate']:.1f} %"
            if nemesis else None
        ),
        delta_color="inverse",
    )

    insight_cols[2].metric(
        "Longest Win Streak",
        insights["longest_win_streak"],
    )

    insight_cols[3].metric(
        "Longest Losing Streak",
        insights["longest_loss_streak"],
    )

    career_summary = narratives.generate_player_summary(
        profile,
        insights,
        current_rank,
    )

    st.info(career_summary)

    tab_elo, tab_rank, tab_history, tab_opponents = st.tabs(
        ["Elo History", "Ranking History", "Tournament History", "Opponent Records"]
    )

    with tab_elo:
        best_elo_event = insights["best_elo_event"]
 
        if best_elo_event:
            change = best_elo_event.get("elo_change", 0)
            st.info(
                f"Biggest Elo jump: **{change:+.1f}** at "
                f"**{best_elo_event.get('tournament', 'a tournament')}**."
            )

        if timeline:
            timeline_df = pd.DataFrame(timeline)
            elo_chart = (
                alt.Chart(timeline_df)
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
                    tooltip=[
                        alt.Tooltip("tournament:N", title="Tournament"),
                        alt.Tooltip("tournament_date:N", title="Date"),
                        alt.Tooltip("elo:Q", title="Elo", format=".1f"),
                        alt.Tooltip("rank:Q", title="Rank"),
                        alt.Tooltip(
                            "played_in_tournament:N",
                            title="Participated",
                        ),
                    ],
                )
                .properties(height=430)
            )
            st.altair_chart(elo_chart, use_container_width=True)
        else:
            st.info("No Elo history is available for this player yet.")

    with tab_rank:
        if timeline:
            timeline_df = pd.DataFrame(timeline)
            max_rank = int(timeline_df["rank"].max())

            rank_chart = (
                alt.Chart(timeline_df)
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
                    tooltip=[
                        alt.Tooltip("tournament:N", title="Tournament"),
                        alt.Tooltip("rank:Q", title="Rank"),
                        alt.Tooltip("elo:Q", title="Elo", format=".1f"),
                    ],
                )
                .properties(height=430)
            )
            st.altair_chart(rank_chart, use_container_width=True)
            st.caption("Rank 1 is displayed at the top of the chart.")
        else:
            st.info("No ranking history is available for this player yet.")

    with tab_history:
        if history:
            history_df = pd.DataFrame(
                [
                    {
                        "Tournament": entry["tournament"],
                        "Date": entry["date"],
                        "Placement": format_placement(entry["placement"]),
                        "Winner": entry["winner"],
                        "Record": f"{entry['wins']}–{entry['losses']}",
                        "Titles": "🏆" if entry["won_tournament"] else "",
                    }
                    for entry in reversed(history)
                ]
            )
            st.dataframe(
                history_df,
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No tournament appearances found.")

    with tab_opponents:
        if insights["opponents"]:
            st.subheader("Records Against All Opponents")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Opponent": row["opponent"],
                            "Record": f"{row['wins']}:{row['losses']}",
                            "Matches": row["matches"],
                            "Win Rate": row["winrate"],
                        }
                        for row in insights["opponents"]
                    ]
                ),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Win Rate": st.column_config.NumberColumn(format="%.1f %%"),
                },
            )
        else:
            st.info("No opponent records are available for this player yet.")



def comparison_value(
    left: float | int | None,
    right: float | int | None,
    *,
    lower_is_better: bool = False,
) -> tuple[str, str]:
    """Returns markers for the better comparison value."""

    if left is None or right is None or left == right:
        return "", ""

    left_better = left < right if lower_is_better else left > right
    return ("●", "") if left_better else ("", "●")


def show_comparison(include_inactive: bool) -> None:
    st.title("🤝 Player Comparison")
    st.caption(
        "Career statistics, head-to-head matches, and Elo and ranking development "
        "for two players"
    )

    players = load_players(include_inactive)
    if len(players) < 2:
        st.warning("At least two players are required for a comparison.")
        return

    names = [player["display_name"] for player in players]
    player_by_name = {
        player["display_name"]: str(player["player_id"])
        for player in players
    }

    default_right = 1 if len(names) > 1 else 0
    select_left, versus, select_right = st.columns([5, 1, 5])

    with select_left:
        left_name = str(
            st.selectbox(
                "Player 1",
                names,
                index=0,
                key="comparison_left",
            )
        )

    with versus:
        st.markdown(
            "<div style='text-align:center; padding-top:2rem; "
            "font-size:1.5rem; font-weight:700;'>VS</div>",
            unsafe_allow_html=True,
        )

    with select_right:
        right_options = [name for name in names if name != left_name]
        preferred_right = names[default_right]
        right_index = (
            right_options.index(preferred_right)
            if preferred_right in right_options
            else 0
        )
        right_name = str(
            st.selectbox(
                "Player 2",
                right_options,
                index=right_index,
                key="comparison_right",
            )
        )

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

    st.divider()
    header_left, header_score, header_right = st.columns([4, 3, 4])

    with header_left:
        st.markdown(f"## {left_name}")
        st.metric(
            "Current Elo",
            f"{left_profile.get('current_elo', 1000):.1f}",
        )

    with header_score:
        st.markdown(
            "<div style='text-align:center; margin-top:0.5rem;'>"
            "<div style='font-size:0.9rem; opacity:0.7;'>HEAD-TO-HEAD</div>"
            f"<div style='font-size:2.5rem; font-weight:800;'>"
            f"{h2h['player_a']['wins']} : {h2h['player_b']['wins']}"
            "</div></div>",
            unsafe_allow_html=True,
        )

    with header_right:
        st.markdown(
            f"<h2 style='text-align:right;'>{right_name}</h2>",
            unsafe_allow_html=True,
        )
        st.metric(
            "Current Elo",
            f"{right_profile.get('current_elo', 1000):.1f}",
        )

    categories = [
        (
            "Current Elo",
            left_profile.get("current_elo"),
            right_profile.get("current_elo"),
            False,
            lambda value: f"{value:.1f}" if value is not None else "–",
        ),
        (
            "Peak Elo",
            left_profile.get("peak_elo"),
            right_profile.get("peak_elo"),
            False,
            lambda value: f"{value:.1f}" if value is not None else "–",
        ),
        (
            "Current Rank",
            left_rank,
            right_rank,
            True,
            lambda value: f"#{value}" if value is not None else "–",
        ),
        (
            "Titles",
            left_profile.get("titles", 0),
            right_profile.get("titles", 0),
            False,
            lambda value: str(value),
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

    rows = []
    for label, left_value, right_value, lower_is_better, formatter in categories:
        left_mark, right_mark = comparison_value(
            left_value,
            right_value,
            lower_is_better=lower_is_better,
        )
        rows.append(
            {
                left_name: (
                    f"{left_mark} {formatter(left_value)}".strip()
                ),
                "Category": label,
                right_name: (
                    f"{formatter(right_value)} {right_mark}".strip()
                ),
            }
        )

    st.subheader("Career Comparison")
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            left_name: st.column_config.TextColumn(width="medium"),
            "Category": st.column_config.TextColumn(width="medium"),
            right_name: st.column_config.TextColumn(width="medium"),
        },
    )
    st.caption("● marks the better value in each category.")

    st.subheader("Head-to-Head")
    h2h_cols = st.columns(4)
    h2h_cols[0].metric(
        f"Wins {left_name}",
        h2h["player_a"]["wins"],
    )
    h2h_cols[1].metric(
        f"Wins {right_name}",
        h2h["player_b"]["wins"],
    )
    h2h_cols[2].metric(
        f"Games {left_name}",
        h2h["player_a"]["games_won"],
    )
    h2h_cols[3].metric(
        f"Games {right_name}",
        h2h["player_b"]["games_won"],
    )

    rivalry_summary = narratives.generate_rivalry_summary(h2h)
    st.info(rivalry_summary)

    if h2h["last_match"]:
        last = h2h["last_match"]
        score = last["score"] or "Unknown result"
        st.info(
            f"Last set: **{last['winner'] or 'No winner'}** won "
            f"at {last['tournament']} ({score})."
        )
    elif not h2h["history"]:
        st.info("These two players have not faced each other yet.")

    tab_elo, tab_rank, tab_matches = st.tabs(
        ["Combined Elo History", "Combined Ranking History", "Head-to-Head Matches"]
    )

    with tab_elo:
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

    with tab_rank:
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
            for match in reversed(h2h["history"]):
                round_text = match["round_label"] or match["stage"] or "–"
                match_rows.append(
                    {
                        "Tournament": match["tournament"],
                        "Date": match["date"],
                        "Round": round_text,
                        "Winner": match["winner"] or "Pending",
                        "Result": match["score"] or "–",
                    }
                )

            st.dataframe(
                pd.DataFrame(match_rows),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No head-to-head matches available.")


def show_h2h_matrix(include_inactive: bool) -> None:
    st.title("🧩 Head-to-Head Matrix")
    st.caption(
        "Each cell shows the row player’s record against the column player. "
        "Select a cell to open all matches."
    )

    players = load_players(include_inactive)
    player_ids = {
        str(player["display_name"]): str(player["player_id"])
        for player in players
    }
    names = list(player_ids)

    records, winrates = load_h2h_matrix(include_inactive)
    if records.empty:
        st.warning("No players found for the matrix.")
        return

    def cell_style(value: Any) -> str:
        if pd.isna(value):
            return ""
        if value > 0.5:
            return "background-color: rgba(46, 160, 67, 0.28); font-weight: 600;"
        if value < 0.5:
            return "background-color: rgba(248, 81, 73, 0.25); font-weight: 600;"
        return "background-color: rgba(139, 148, 158, 0.22); font-weight: 600;"

    styled = records.style.apply(
        lambda row: [
            cell_style(winrates.loc[str(row.name), str(column)])
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
            key="h2h_matrix_selection",
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
            row_index, column_name = selected_cells[0]
            row_index = int(row_index)
            right_name = str(column_name)

            if (
                0 <= row_index < len(names)
                and right_name in player_ids
            ):
                selected_pair = (
                    names[row_index],
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

    st.divider()
    st.subheader("Open matchup")

    if selected_pair is None:
        select_left, select_right = st.columns(2)
        with select_left:
            left_name = str(
                st.selectbox(
                    "Row player",
                    names,
                    key="matrix_left_player",
                )
            )
        with select_right:
            right_options = [name for name in names if name != left_name]
            right_name = str(
                st.selectbox(
                    "Column player",
                    right_options,
                    key="matrix_right_player",
                )
            )
    else:
        left_name, right_name = selected_pair
        st.success(f"Selected cell: **{left_name} vs. {right_name}**")

    show_h2h_drilldown(left_name, right_name, player_ids)


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
    summary_cols = st.columns(4)
    summary_cols[0].metric("Winner", tournament["winner"] or "Unknown")
    summary_cols[1].metric("Date", tournament["tournament_date"] or "–")
    summary_cols[2].metric("Participants", len(participants))
    summary_cols[3].metric("Matches", len(matches))

    st.info(tournament_recap)

    podium = {row["placement"]: row["player"] for row in participants if row["placement"] in (1, 2, 3)}
    if podium:
        podium_cols = st.columns(3)
        podium_cols[0].metric("🥇 1st Place", podium.get(1, "–"))
        podium_cols[1].metric("🥈 2nd Place", podium.get(2, "–"))
        podium_cols[2].metric("🥉 3rd Place", podium.get(3, "–"))

    tab_overview, tab_matches, tab_elo, tab_archive = st.tabs(
        ["Participants & Results", "All Matches", "Elo After Tournament", "Tournament Archive"]
    )

    with tab_overview:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Placement": row["placement"],
                        "Players": row["player"],
                        "Seed": row["seed"],
                    }
                    for row in participants
                ]
            ),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Placement": st.column_config.NumberColumn(format="%d"),
                "Seed": st.column_config.NumberColumn(format="%d"),
            },
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
                        "Round": match["round_label"] or "–",
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

    with tab_archive:
        tournament_df = pd.DataFrame(tournaments)
        st.dataframe(tournament_df, hide_index=True, use_container_width=True)
        winners = (
            tournament_df["Winner"]
            .value_counts()
            .rename_axis("Players")
            .reset_index(name="Titles")
        )
        chart = (
            alt.Chart(winners)
            .mark_bar()
            .encode(
                x=alt.X("Titles:Q", title="Titles", axis=alt.Axis(tickMinStep=1)),
                y=alt.Y("Players:N", sort="-x", title=None),
                tooltip=["Players", "Titles"],
            )
            .properties(height=max(240, len(winners) * 38))
        )
        st.altair_chart(chart, use_container_width=True)

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

def main() -> None:
    require_database()

    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Section",
        [
            "Home",
            "Players",
            "Comparison",
            "H2H-Matrix",
            "Tournaments",
            "Tournament Manager",
        ],
        label_visibility="collapsed",
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
    elif page == "Comparison":
        show_comparison(include_inactive)
    elif page == "H2H-Matrix":
        show_h2h_matrix(include_inactive)
    elif page == "Tournaments":
        show_tournaments()
    elif page == "Tournament Manager":
        show_tournament_manager()


if __name__ == "__main__":
    main()
