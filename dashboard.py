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
    import smash_statistics as stats
except ImportError as exc:
    raise ImportError(
        "src/smash_statistics.py was not found. "
        "Place dashboard.py in the project root directory."
    ) from exc


DB_PATH = PROJECT_ROOT / "data" / "smash_wm.db"


st.set_page_config(
    page_title="Smash World Championship",
    page_icon="🎮",
    layout="wide",
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
            "Matchdaten": "Yes" if row["match_data_available"] else "No",
        }
        for row in rows
    ]


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
            f"{last['winner'] or 'Unknown winner'} gewann {score_text}."
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
                    <div style="opacity:0.65;font-size:0.78rem;">RANG</div>
                    <div style="font-size:1.45rem;font-weight:800;">{rank_text}</div>
                </div>
                <div>
                    <div style="opacity:0.65;font-size:0.78rem;">ELO</div>
                    <div style="font-size:1.45rem;font-weight:800;">
                        {profile.get('current_elo', 1000):.1f}
                    </div>
                </div>
                <div>
                    <div style="opacity:0.65;font-size:0.78rem;">TITEL</div>
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
    col1.metric("Peak Elo", f"{profile.get('peak_elo', 1000):.1f}")
    col2.metric("Appearances", profile["appearances"])
    col3.metric("Matches", profile["decided_matches"])
    col4.metric("Win Rate", format_percent(profile["winrate"]))

    insights = load_player_insights(player_id)

    tab_elo, tab_rank, tab_history, tab_insights = st.tabs(
        ["Elo History", "Ranking History", "Tournament History", "Insights"]
    )

    with tab_elo:
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

    with tab_insights:
        favorite = insights["favorite"]
        nemesis = insights["nemesis"]
        best_elo_event = insights["best_elo_event"]

        insight_cols = st.columns(4)
        insight_cols[0].metric(
            "Best Matchup",
            favorite["opponent"] if favorite else "–",
            (
                f"{favorite['wins']}:{favorite['losses']} · "
                f"{favorite['winrate']:.1f} %"
                if favorite else None
            ),
        )
        insight_cols[1].metric(
            "Nemesis",
            nemesis["opponent"] if nemesis else "–",
            (
                f"{nemesis['wins']}:{nemesis['losses']} · "
                f"{nemesis['winrate']:.1f} %"
                if nemesis else None
            ),
        )
        insight_cols[2].metric(
            "Longest Win Streak",
            insights["longest_win_streak"],
        )
        insight_cols[3].metric(
            "Longest Losing Streak",
            insights["longest_loss_streak"],
        )

        if best_elo_event:
            change = best_elo_event.get("elo_change", 0)
            st.info(
                f"Biggest Elo jump: **{change:+.1f}** bei "
                f"**{best_elo_event.get('tournament', 'a tournament')}**."
            )

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
            st.info("No head-to-head matches are available for player insights yet.")



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

    if h2h["last_match"]:
        last = h2h["last_match"]
        score = last["score"] or "Unknown result"
        st.info(
            f"Letztes Duell: **{last['winner'] or 'No winner'}** gewann "
            f"bei {last['tournament']} ({score})."
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
        selected_cells = selection_event.selection.cells
        if selected_cells:
            row_index, column_name = selected_cells[0]
            row_index = int(row_index)
            right_name = str(column_name)
            if (
                0 <= row_index < len(names)
                and right_name in player_ids
            ):
                selected_pair = (names[row_index], right_name)
    except (AttributeError, KeyError, TypeError):
        st.dataframe(styled, use_container_width=True)

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

    st.header(f"WM {tournament['tournament_number']:02d}")
    summary_cols = st.columns(4)
    summary_cols[0].metric("Winner", tournament["winner"] or "Unknown")
    summary_cols[1].metric("Date", tournament["tournament_date"] or "–")
    summary_cols[2].metric("Participants", len(participants))
    summary_cols[3].metric("Matches", len(matches))

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
        changes = tournament_elo_changes(
            int(tournament["tournament_number"]),
            participants,
        )

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


def main() -> None:
    require_database()

    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Section",
        ["Home", "Players", "Comparison", "H2H-Matrix", "Tournaments"],
        label_visibility="collapsed",
    )

    include_inactive = st.sidebar.checkbox(
        "Include inactive players",
        value=False,
    )

    st.sidebar.divider()
    st.sidebar.caption(f"Database: `{DB_PATH.name}`")

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
    else:
        show_tournaments()


if __name__ == "__main__":
    main()
