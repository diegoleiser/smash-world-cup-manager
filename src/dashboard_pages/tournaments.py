"""Archived tournaments page presentation and interaction."""

from __future__ import annotations

from typing import Any, Callable

import altair as alt
import pandas as pd
import streamlit as st

import bracket_visualization
import narratives
from dashboard_pages.ui_components import dashboard_table_html
from tournament.archived_bracket import (
    archived_match_round_label,
    build_archived_bracket_matches,
    build_archived_bracket_routes,
)


def _final_standings_table_data(
    participants: list[dict[str, Any]],
    format_ordinal: Callable[[int], str],
) -> tuple[list[list[str]], dict[int, str]]:
    """Build display rows and highlights for archived final standings."""

    placement_counts: dict[int, int] = {}
    for participant in participants:
        placement = participant["placement"]
        if placement is not None:
            placement_number = int(placement)
            placement_counts[placement_number] = (
                placement_counts.get(placement_number, 0) + 1
            )

    placement_icons = {1: "🥇", 2: "🥈", 3: "🥉"}
    rows = []
    row_highlights = {}
    for row_index, participant in enumerate(participants):
        placement = participant["placement"]
        seed = participant["seed"]
        if placement is None:
            placement_text = "–"
            placement_number = None
        else:
            placement_number = int(placement)
            ordinal = format_ordinal(placement_number)
            if placement_counts.get(placement_number, 0) > 1:
                ordinal = f"T-{ordinal}"
            icon = placement_icons.get(placement_number, "")
            placement_text = f"{icon} {ordinal}".strip()
            if placement_number == 1:
                row_highlights[row_index] = "winners"

        if seed is None:
            seed_text = "Not seeded"
            seed_performance = "–"
        else:
            seed_number = int(seed)
            seed_text = f"Seed #{seed_number}"
            if placement_number is None:
                seed_performance = "–"
            elif placement_number < seed_number:
                seed_performance = f"▲ {seed_number - placement_number}"
            elif placement_number > seed_number:
                seed_performance = f"▼ {placement_number - seed_number}"
            else:
                seed_performance = "= Seed"

        rows.append(
            [
                placement_text,
                str(participant["player"]),
                seed_text,
                seed_performance,
            ]
        )

    return rows, row_highlights


def _all_matches_table_rows(
    matches: list[dict[str, Any]],
    archived_bracket_matches: list[dict[str, Any]],
    *,
    format_round: Callable[..., str] = archived_match_round_label,
) -> list[list[str]]:
    """Build compact rows for the archived all-matches table."""

    rows = []
    for match in matches:
        if match["score_known"] and match["player_1_score"] is not None:
            score = f"{match['player_1_score']}:{match['player_2_score']}"
        else:
            score = "–"
        rows.append(
            [
                str(match["stage"] or "–"),
                str(format_round(match, archived_bracket_matches)),
                f"{match['player_1']} vs {match['player_2']}",
                score,
                str(match["winner"] or "Pending"),
            ]
        )
    return rows


def _elo_change_table_rows(
    changes: list[dict[str, Any]],
) -> list[list[str]]:
    """Build compact before/after rows for archived Elo changes."""

    rows = []
    for change in changes:
        elo_change = float(change["Elo Change"])
        if elo_change > 0:
            change_text = f"▲ {elo_change:+.1f}"
        elif elo_change < 0:
            change_text = f"▼ {elo_change:+.1f}"
        else:
            change_text = "= 0.0"

        rank_before = change["Rank Before"]
        rank_after = change["Rank After"]
        rank_before_text = (
            f"#{int(rank_before)}" if rank_before is not None else "Unranked"
        )
        rank_after_text = (
            f"#{int(rank_after)}" if rank_after is not None else "Unranked"
        )
        rows.append(
            [
                str(change["Players"]),
                (
                    f"{float(change['Elo Before']):.1f} → "
                    f"{float(change['Elo After']):.1f}"
                ),
                change_text,
                f"{rank_before_text} → {rank_after_text}",
            ]
        )
    return rows


def render_tournaments(
    *,
    include_inactive: bool,
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
        include_inactive=include_inactive,
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
        standings_rows, standings_highlights = _final_standings_table_data(
            participants,
            format_ordinal,
        )
        st.markdown(
            dashboard_table_html(
                ["Placement", "Player", "Initial Seed", "Seed Change"],
                standings_rows,
                columns=(
                    "minmax(7rem,0.85fr) minmax(12rem,2fr) "
                    "minmax(7rem,0.8fr) minmax(7rem,0.75fr)"
                ),
                row_highlights=standings_highlights,
                emphasis_column=1,
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
            match_rows = _all_matches_table_rows(
                matches,
                archived_bracket_matches,
            )
            st.markdown(
                dashboard_table_html(
                    ["Stage", "Round", "Set", "Result", "Winner"],
                    match_rows,
                    columns=(
                        "minmax(6rem,0.7fr) minmax(8rem,1fr) "
                        "minmax(14rem,2fr) minmax(5rem,0.6fr) "
                        "minmax(8rem,1fr)"
                    ),
                    emphasis_column=2,
                ),
                unsafe_allow_html=True,
            )
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

            st.markdown(
                dashboard_table_html(
                    ["Player", "Elo Before → After", "Change", "Rank"],
                    _elo_change_table_rows(changes),
                    columns=(
                        "minmax(10rem,1.4fr) minmax(11rem,1.2fr) "
                        "minmax(6rem,0.7fr) minmax(10rem,1fr)"
                    ),
                    emphasis_column=0,
                ),
                unsafe_allow_html=True,
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
