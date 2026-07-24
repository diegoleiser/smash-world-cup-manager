"""Archived tournaments page presentation and interaction."""

from __future__ import annotations

import html
from typing import Any, Callable

import altair as alt
import pandas as pd
import streamlit as st

import bracket_visualization
import narratives
from tournament.archived_bracket import (
    archived_match_round_label,
    build_archived_bracket_matches,
    build_archived_bracket_routes,
)


def render_tournaments(
    *,
    load_tournaments: Callable[..., list[dict[str, Any]]],
    load_tournament_detail: Callable[..., dict[str, Any]],
    load_tournament_milestones: Callable[..., list[dict[str, Any]]],
    tournament_elo_changes: Callable[..., list[dict[str, Any]]],
    format_ordinal: Callable[[int], str],
    show_archived_match_dialog: Callable[..., None],
) -> None:
    st.title("🏆 Tournaments")
    tournaments = load_tournaments()

    if not tournaments:
        st.warning("No tournaments found.")
        return

    tournament_numbers = [int(row["WC"].split()[1]) for row in tournaments]
    selected_number = st.selectbox(
        "Select tournament",
        tournament_numbers,
        format_func=lambda number: f"WC {number:02d}",
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
        and int(row["WC"].split()[1]) <= selected_tournament_number
        for row in tournaments
    )

    previous_tournament = next(
        (
            row
            for row in tournaments
            if int(row["WC"].split()[1])
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

    st.header(f"WC {tournament['tournament_number']:02d}")
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
            st.dataframe(pd.DataFrame(match_rows), hide_index=True, width="stretch")
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
                width="stretch",
            )

            st.dataframe(
                change_df,
                hide_index=True,
                width="stretch",
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
                    width="stretch",
                    column_config={
                        "Rank": st.column_config.NumberColumn(format="%d"),
                        "Elo": st.column_config.NumberColumn(format="%.1f"),
                    },
                )
        elif not changes:
            st.info("No Elo data is available for this tournament.")
