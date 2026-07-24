"""Matchups page presentation and interaction."""

from __future__ import annotations

import html
from typing import Any, Callable

import altair as alt
import pandas as pd
import streamlit as st

import narratives
from tournament.archived_bracket import build_archived_bracket_matches


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
