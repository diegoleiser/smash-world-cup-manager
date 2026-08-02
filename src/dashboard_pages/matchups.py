"""Matchups page presentation and interaction."""

from __future__ import annotations

import html
from typing import Any, Callable

import altair as alt
import pandas as pd
import streamlit as st

import narratives
from dashboard_pages.navigation_routes import (
    player_profile_url,
    tournament_archive_url,
)
from dashboard_pages.ui_components import dashboard_table_html
from tournament.archived_bracket import build_archived_bracket_matches


def _build_combined_history_chart(
    rows: list[dict[str, Any]],
    *,
    value_field: str,
    value_title: str,
    tournament_order: list[str],
    reverse_rank_axis: bool = False,
) -> alt.LayerChart:
    """Build a two-player timeline using the Home-page visual language."""

    history_df = pd.DataFrame(rows)
    order_by_tournament = {
        tournament: position
        for position, tournament in enumerate(tournament_order)
    }
    history_df["_tournament_order"] = history_df["tournament"].map(
        order_by_tournament
    )
    history_df = history_df.sort_values(
        ["Players", "_tournament_order"]
    )

    segment_rows: list[dict[str, Any]] = []
    for player_name, player_rows in history_df.groupby(
        "Players",
        sort=False,
    ):
        ordered_rows = player_rows.to_dict("records")
        for previous, current in zip(
            ordered_rows,
            ordered_rows[1:],
        ):
            segment_rows.append(
                {
                    "Players": player_name,
                    "start_tournament": previous["tournament"],
                    "end_tournament": current["tournament"],
                    "start_value": previous[value_field],
                    "end_value": current[value_field],
                    "segment_type": (
                        "Played"
                        if bool(current["played_in_tournament"])
                        else "Did not participate"
                    ),
                }
            )

    segment_df = pd.DataFrame(segment_rows)
    if segment_df.empty:
        segment_df = pd.DataFrame(
            columns=[
                "Players",
                "start_tournament",
                "end_tournament",
                "start_value",
                "end_value",
                "segment_type",
            ]
        )

    if reverse_rank_axis:
        max_value = int(history_df[value_field].max())
        value_scale = alt.Scale(
            domain=[max_value + 0.5, 0.5],
        )
        value_axis = alt.Axis(
            values=list(range(1, max_value + 1)),
            format="d",
            tickMinStep=1,
            labelOverlap=False,
        )
    else:
        value_scale = alt.Scale(zero=False)
        value_axis = alt.Axis()

    def value_encoding(field: str) -> alt.Y:
        return alt.Y(
            f"{field}:Q",
            title=value_title,
            scale=value_scale,
            axis=value_axis,
        )

    solid_segments = (
        alt.Chart(
            segment_df[
                segment_df["segment_type"] == "Played"
            ]
        )
        .mark_rule(strokeWidth=2)
        .encode(
            x=alt.X(
                "start_tournament:N",
                title="Tournament",
                sort=tournament_order,
            ),
            x2="end_tournament:N",
            y=value_encoding("start_value"),
            y2="end_value:Q",
            color=alt.Color(
                "Players:N",
                title=None,
                legend=alt.Legend(
                    orient="right",
                    symbolType="circle",
                    symbolSize=100,
                ),
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
            strokeWidth=2,
            strokeDash=[6, 4],
        )
        .encode(
            x=alt.X(
                "start_tournament:N",
                title="Tournament",
                sort=tournament_order,
            ),
            x2="end_tournament:N",
            y=value_encoding("start_value"),
            y2="end_value:Q",
            color=alt.Color("Players:N", title=None),
        )
    )

    tooltip = [
        alt.Tooltip("Players:N", title="Player"),
        alt.Tooltip("tournament:N", title="Tournament"),
        alt.Tooltip("tournament_date:N", title="Date"),
        alt.Tooltip(
            f"{value_field}:Q",
            title=value_title,
            format=".1f" if value_field == "elo" else "d",
        ),
        alt.Tooltip(
            "played_in_tournament:N",
            title="Participated",
        ),
    ]

    played_points = (
        alt.Chart(
            history_df[
                history_df["played_in_tournament"]
            ]
        )
        .mark_point(
            filled=True,
            strokeWidth=2,
            size=90,
        )
        .encode(
            x=alt.X(
                "tournament:N",
                title="Tournament",
                sort=tournament_order,
            ),
            y=value_encoding(value_field),
            color=alt.Color("Players:N", legend=None),
            tooltip=tooltip,
        )
    )

    missed_points = (
        alt.Chart(
            history_df[
                ~history_df["played_in_tournament"]
            ]
        )
        .mark_point(
            filled=False,
            strokeWidth=2.5,
            size=90,
        )
        .encode(
            x=alt.X(
                "tournament:N",
                title="Tournament",
                sort=tournament_order,
            ),
            y=value_encoding(value_field),
            color=alt.Color("Players:N", legend=None),
            tooltip=tooltip,
        )
    )

    return (
        solid_segments
        + dashed_segments
        + played_points
        + missed_points
    ).properties(height=460)


def render_matchups(
    include_inactive: bool,
    *,
    load_players: Callable[..., list[dict[str, Any]]],
    load_h2h_matrix: Callable[..., tuple[pd.DataFrame, pd.DataFrame]],
    load_player_profile: Callable[..., dict[str, Any]],
    load_player_timeline: Callable[..., list[dict[str, Any]]],
    load_head_to_head: Callable[..., dict[str, Any]],
    load_elo_ranking: Callable[..., list[dict[str, Any]]],
    load_tournament_detail: Callable[..., dict[str, Any]],
) -> None:
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
            width="stretch",
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
            width="stretch",
        )

    st.caption(
        "Green = winning record, red = losing record, "
        "grey = tied record."
    )

    if selected_pair is None:
        st.info(
            "Choose a non-diagonal cell to compare the player in that "
            "row with the player in that column. The full head-to-head, "
            "career summary, and combined timelines will open below."
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

    matchup_header_html = (
        "<style>"
        ".matchup-header-card {"
        "display:grid;"
        "grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);"
        "align-items:center;"
        "gap:1.25rem;"
        "padding:1.25rem 1.4rem;"
        "border:1px solid rgba(128,128,128,0.28);"
        "border-radius:0.9rem 0.9rem 0 0;"
        "}"
        ".matchup-player-name {"
        "font-size:2rem;"
        "font-weight:800;"
        "line-height:1.1;"
        "}"
        ".matchup-player-right {text-align:right;}"
        ".matchup-player-meta {"
        "margin-top:0.55rem;"
        "font-size:0.88rem;"
        "font-weight:650;"
        "opacity:0.62;"
        "}"
        ".matchup-score {text-align:center;}"
        ".matchup-score-label {"
        "font-size:0.72rem;"
        "font-weight:750;"
        "letter-spacing:0.04em;"
        "opacity:0.58;"
        "}"
        ".matchup-score-value {"
        "margin-top:0.35rem;"
        "font-size:2.5rem;"
        "font-weight:850;"
        "line-height:1;"
        "white-space:nowrap;"
        "}"
        "@media (max-width:700px) {"
        ".matchup-header-card {"
        "gap:0.65rem;"
        "padding:1rem 0.85rem;"
        "}"
        ".matchup-player-name {font-size:1.35rem;}"
        ".matchup-player-meta {"
        "font-size:0.72rem;"
        "line-height:1.45;"
        "}"
        ".matchup-score-label {font-size:0.64rem;}"
        ".matchup-score-value {font-size:1.9rem;}"
        "}"
        "</style>"
        "<div class='matchup-header-card'>"
        "<div class='matchup-player'>"
        "<div class='matchup-player-name'>"
        f"{html.escape(left_name)}"
        "</div>"
        "<div class='matchup-player-meta'>"
        f"#{left_rank or '–'} · "
        f"{float(left_profile.get('current_elo') or 1000.0):.1f} Elo<br>"
        f"{left_titles} {html.escape(left_title_label)}"
        "</div></div>"
        "<div class='matchup-score'>"
        "<div class='matchup-score-label'>HEAD-TO-HEAD</div>"
        "<div class='matchup-score-value'>"
        f"{h2h['player_a']['wins']} : {h2h['player_b']['wins']}"
        "</div></div>"
        "<div class='matchup-player matchup-player-right'>"
        "<div class='matchup-player-name'>"
        f"{html.escape(right_name)}"
        "</div>"
        "<div class='matchup-player-meta'>"
        f"#{right_rank or '–'} · "
        f"{float(right_profile.get('current_elo') or 1000.0):.1f} Elo<br>"
        f"{right_titles} {html.escape(right_title_label)}"
        "</div></div></div>"
    )
    st.markdown(matchup_header_html, unsafe_allow_html=True)

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
        last_winner = str(
            last_match.get("winner") or "Unknown"
        )
        last_score = last_match.get("score")
        if last_score and "-" in str(last_score):
            left_score, right_score = str(last_score).split("-", 1)
            winner_score, loser_score = (
                (right_score, left_score)
                if last_winner == right_name
                else (left_score, right_score)
            )
            last_meeting = (
                f"{last_winner} won {winner_score}–{loser_score}"
            )
        else:
            last_meeting = f"{last_winner} won"
        last_meeting_context = str(
            last_match.get("tournament") or "Unknown tournament"
        )
    else:
        last_meeting = "–"
        last_meeting_context = "No previous meeting"

    streak_player = "–"
    streak_count = 0

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

    rivalry_summary_html = (
        "<style>"
        ".rivalry-summary {"
        "display:grid;"
        "grid-template-columns:8rem minmax(0,1fr);"
        "gap:1.5rem;"
        "align-items:start;"
        "padding:1.25rem 1.45rem;"
        "margin:0 0 1rem 0;"
        "border:1px solid rgba(70,150,220,0.18);"
        "border-top:none;"
        "border-radius:0 0 0.8rem 0.8rem;"
        "background:rgba(28,74,112,0.55);"
        "}"
        ".rivalry-summary-label {"
        "padding-top:0.15rem;"
        "font-size:0.78rem;"
        "font-weight:750;"
        "letter-spacing:0.04em;"
        "opacity:0.72;"
        "}"
        ".rivalry-summary-text {"
        "font-size:1rem;"
        "line-height:1.75;"
        "}"
        "@media (max-width:700px) {"
        ".rivalry-summary {"
        "grid-template-columns:1fr;"
        "gap:0.75rem;"
        "padding:1.15rem 1.25rem;"
        "}"
        "}"
        "</style>"
        "<div class='rivalry-summary'>"
        "<div class='rivalry-summary-label'>"
        "RIVALRY<br>SUMMARY"
        "</div>"
        "<div class='rivalry-summary-text'>"
        f"{html.escape(' '.join(summary_parts))}"
        "</div></div>"
    )
    st.markdown(
        rivalry_summary_html,
        unsafe_allow_html=True,
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
        detail_html = (
            "<style>"
            ".matchup-detail-grid {"
            "display:grid;"
            "grid-template-columns:repeat(3,minmax(0,1fr));"
            "overflow:hidden;"
            "border:1px solid rgba(128,128,128,0.28);"
            "border-radius:0.8rem;"
            "}"
            ".matchup-detail-item {"
            "min-width:0;"
            "padding:1rem 1.1rem;"
            "border-left:1px solid rgba(128,128,128,0.22);"
            "}"
            ".matchup-detail-item:first-child {border-left:none;}"
            ".matchup-detail-label {"
            "font-size:0.72rem;"
            "font-weight:750;"
            "letter-spacing:0.04em;"
            "opacity:0.58;"
            "text-transform:uppercase;"
            "}"
            ".matchup-detail-value {"
            "margin-top:0.45rem;"
            "font-size:1.35rem;"
            "font-weight:800;"
            "line-height:1.2;"
            "}"
            ".matchup-detail-note {"
            "margin-top:0.25rem;"
            "font-size:0.78rem;"
            "font-weight:700;"
            "opacity:0.58;"
            "}"
            "@media (max-width:700px) {"
            ".matchup-detail-grid {grid-template-columns:1fr;}"
            ".matchup-detail-item {"
            "display:grid;"
            "grid-template-columns:minmax(0,1fr) auto;"
            "align-items:center;"
            "gap:0.25rem 1rem;"
            "padding:0.9rem 1rem;"
            "border-left:none;"
            "border-top:1px solid rgba(128,128,128,0.22);"
            "}"
            ".matchup-detail-item:first-child {border-top:none;}"
            ".matchup-detail-value {"
            "grid-column:2;"
            "grid-row:1 / 3;"
            "margin-top:0;"
            "font-size:1.2rem;"
            "text-align:right;"
            "}"
            ".matchup-detail-note {margin-top:0;}"
            "}"
            "</style>"
        "<div class='matchup-detail-grid'>"
        "<div class='matchup-detail-item'>"
        "<div class='matchup-detail-label'>Games Won</div>"
        "<div class='matchup-detail-value'>"
        f"{h2h['player_a']['games_won']}–{h2h['player_b']['games_won']}"
        "</div>"
        "<div class='matchup-detail-note'>"
        f"{html.escape(left_name)} – {html.escape(right_name)}"
        "</div></div>"
        "<div class='matchup-detail-item'>"
        "<div class='matchup-detail-label'>Current Set Streak</div>"
        "<div class='matchup-detail-value'>"
        f"{html.escape(streak_player)} · "
        f"{streak_count} {'win' if streak_count == 1 else 'wins'}"
        "</div>"
        "<div class='matchup-detail-note'>"
        "Consecutive set wins"
        "</div></div>"
        "<div class='matchup-detail-item'>"
        "<div class='matchup-detail-label'>Last Meeting</div>"
        "<div class='matchup-detail-value'>"
        f"{html.escape(last_meeting)}"
        "</div>"
        "<div class='matchup-detail-note'>"
        f"{html.escape(last_meeting_context)}"
        "</div></div></div>"
        )
        st.markdown(detail_html, unsafe_allow_html=True)

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
            tournament_order = (
                elo_df[
                    [
                        "tournament",
                        "tournament_date",
                        "tournament_number",
                    ]
                ]
                .drop_duplicates()
                .sort_values(
                    ["tournament_date", "tournament_number"]
                )["tournament"]
                .tolist()
            )
            elo_chart = _build_combined_history_chart(
                timeline_rows,
                value_field="elo",
                value_title="Elo",
                tournament_order=tournament_order,
            )
            st.altair_chart(elo_chart, width="stretch")
            st.caption(
                "Dashed segments and hollow points indicate tournaments "
                "in which the player did not participate."
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
            tournament_order = (
                rank_df[
                    [
                        "tournament",
                        "tournament_date",
                        "tournament_number",
                    ]
                ]
                .drop_duplicates()
                .sort_values(
                    ["tournament_date", "tournament_number"]
                )["tournament"]
                .tolist()
            )

            rank_chart = _build_combined_history_chart(
                rank_rows,
                value_field="rank",
                value_title="Rank",
                tournament_order=tournament_order,
                reverse_rank_axis=True,
            )
            st.altair_chart(rank_chart, width="stretch")
            st.caption(
                "Rank 1 is displayed at the top. Dashed segments and "
                "hollow points indicate tournaments in which the player "
                "did not participate."
            )
        else:
            st.info("No ranking history is available for these players yet.")

    with tab_matches:
        if h2h["history"]:
            match_rows = []
            match_links: dict[tuple[int, int], str] = {}

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

                row_index = len(match_rows)
                match_rows.append(
                    [
                        match["tournament"],
                        (
                            pd.to_datetime(
                                match["date"]
                            ).strftime("%d %b %Y")
                            if match["date"]
                            else "–"
                        ),
                        round_text,
                        (
                            match["winner"]
                            or "Pending"
                        ),
                        (
                            match["score"]
                            or "–"
                        ),
                    ]
                )
                match_links[(row_index, 0)] = tournament_archive_url(
                    tournament_number
                )
                if match.get("winner_id"):
                    match_links[(row_index, 3)] = player_profile_url(
                        str(match["winner_id"])
                    )

            st.markdown(
                dashboard_table_html(
                    ["Tournament", "Date", "Round", "Winner", "Result"],
                    match_rows,
                    columns="1fr 1fr 1.5fr 1.2fr 0.7fr",
                    emphasis_column=3,
                    cell_links=match_links,
                    mobile_cards=True,
                    mobile_card_variant="match-history",
                ),
                unsafe_allow_html=True,
            )
        else:
            st.info("No head-to-head matches available.")
