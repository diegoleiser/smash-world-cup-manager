"""Tournament Manager page presentation and workflow controls."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st

import bracket_visualization
import tournament_manager
from dashboard_pages.forecast_format import format_winners_probability
from dashboard_pages.tournament_control_center import group_ready_matches
from dashboard_pages.ui_components import (
    clickable_card_button_styles,
    compact_score_input_styles,
    dashboard_table_html,
)
from monte_carlo.artifacts import ArtifactError, load_artifact
from monte_carlo.live_service import (
    forecast_live_draft_bracket,
    forecast_live_draft_group,
)


@st.cache_resource
def _load_live_forecast_model(artifact_path: str):
    return load_artifact(Path(artifact_path)).model


@st.cache_data(show_spinner=False)
def _cached_live_group_forecast(
    db_path: str,
    draft_id: str,
    artifact_path: str,
):
    return forecast_live_draft_group(
        db_path,
        draft_id,
        _load_live_forecast_model(artifact_path),
        10_000,
        20260730,
    )


@st.cache_data(show_spinner=False)
def _cached_live_bracket_forecast(
    db_path: str,
    draft_id: str,
    artifact_path: str,
):
    return forecast_live_draft_bracket(
        db_path,
        draft_id,
        _load_live_forecast_model(artifact_path),
        10_000,
        20260730,
    )


def _render_live_group_forecast(
    *,
    db_path: str | Path,
    draft_id: str,
    artifact_path: Path,
    player_names: dict[str, str],
) -> None:
    st.markdown("### Live Forecast · Preview")
    try:
        with st.spinner("Updating qualification probabilities…"):
            forecast = _cached_live_group_forecast(
                str(db_path),
                draft_id,
                str(artifact_path),
            )
    except (
        ArtifactError,
        FileNotFoundError,
        KeyError,
        RuntimeError,
        ValueError,
    ) as exc:
        st.caption(f"Forecast unavailable: {exc}")
        return
    rows = [
        {
            "Player": player.display_name,
            "Current": (
                f"{player.current_sets_won}–{player.current_sets_lost}"
            ),
            "Projected Wins": player.expected_final_sets_won,
            "P(Winners)": format_winners_probability(
                player.winners_probability,
                player.winners_status,
            ),
            "Status": player.winners_status,
        }
        for player in sorted(
            forecast.players,
            key=lambda item: item.winners_probability,
            reverse=True,
        )
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Projected Wins": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    if forecast.match_leverage:
        st.markdown("#### Open-Set Leverage")
        leverage_rows = []
        for match in forecast.match_leverage:
            first_swing = (
                match.player_1_winners_if_win
                - match.player_1_winners_if_loss
            )
            second_swing = (
                match.player_2_winners_if_win
                - match.player_2_winners_if_loss
            )
            leverage_rows.append(
                {
                    "Set": (
                        f"{player_names.get(match.player_1_id, match.player_1_id)} "
                        f"vs {player_names.get(match.player_2_id, match.player_2_id)}"
                    ),
                    "Set Probability": (
                        match.player_1_set_win_probability * 100
                    ),
                    "P1 Winners Swing": first_swing * 100,
                    "P2 Winners Swing": second_swing * 100,
                    "_importance": max(first_swing, second_swing),
                }
            )
        leverage_frame = (
            pd.DataFrame(leverage_rows)
            .sort_values("_importance", ascending=False)
            .drop(columns="_importance")
            .head(5)
        )
        st.dataframe(
            leverage_frame,
            hide_index=True,
            width="stretch",
            column_config={
                "Set Probability": st.column_config.NumberColumn(
                    "P(first player wins)",
                    format="%.1f%%",
                ),
                "P1 Winners Swing": st.column_config.NumberColumn(
                    format="+%.1f%%",
                ),
                "P2 Winners Swing": st.column_config.NumberColumn(
                    format="+%.1f%%",
                ),
            },
        )
    st.caption(
        "10'000 simulations · completed results fixed · remaining Group "
        "Sets use frozen pre-tournament strengths · provisional UI"
    )


def _render_live_bracket_forecast(
    *,
    db_path: str | Path,
    draft_id: str,
    artifact_path: Path,
    player_names: dict[str, str],
) -> None:
    st.markdown("### Live Forecast · Preview")
    try:
        with st.spinner("Updating bracket probabilities…"):
            forecast = _cached_live_bracket_forecast(
                str(db_path),
                draft_id,
                str(artifact_path),
            )
    except (
        ArtifactError,
        FileNotFoundError,
        KeyError,
        RuntimeError,
        ValueError,
    ) as exc:
        st.caption(f"Forecast unavailable: {exc}")
        return
    if forecast.ready_matches:
        match_columns = st.columns(min(3, len(forecast.ready_matches)))
        for column, match in zip(
            match_columns,
            forecast.ready_matches[:3],
        ):
            column.metric(
                match.match_code,
                (
                    f"{player_names.get(match.player_1_id, match.player_1_id)} "
                    f"{match.player_1_win_probability:.0%}"
                ),
                help=(
                    f"Probability that "
                    f"{player_names.get(match.player_1_id, match.player_1_id)} "
                    "wins this Set."
                ),
            )
    rows = [
        {
            "Player": player_names.get(player.player_id, player.player_id),
            "P(GF)": player.grand_final_probability * 100,
            "P(Title)": player.title_probability * 100,
        }
        for player in sorted(
            forecast.players,
            key=lambda item: item.title_probability,
            reverse=True,
        )
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "P(GF)": st.column_config.NumberColumn(format="%.1f%%"),
            "P(Title)": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.caption(
        "10'000 simulations · completed Bracket Sets fixed · Day values "
        "fixed at Bracket start (neutral without a Group Stage) · "
        "provisional UI"
    )


def _draft_stage(
    *,
    draft: dict[str, Any],
    group_matches: list[dict[str, Any]],
    bracket_state: dict[str, Any],
) -> tuple[str, str]:
    """Return a concise workflow label and explanation for a draft."""

    if draft["status"] == "completed":
        return "Archived", "The tournament is in the permanent archive."

    if bracket_state["champion_name"]:
        return (
            "Ready to finalize",
            "Review placements and archive the tournament.",
        )

    if bracket_state["generated"]:
        return "Bracket", "Record the remaining double-elimination results."

    if group_matches:
        return "Group Stage", "Complete the group-stage results."

    if draft["participants"]:
        return (
            "Setup",
            "Review participants, seeding, and tournament structure.",
        )

    return "Setup", "Add participants to continue."


def _match_option_label(match: dict[str, Any]) -> str:
    player_1_name = str(
        match.get("player_1_name") or match.get("player_1") or "TBD"
    )
    player_2_name = str(
        match.get("player_2_name") or match.get("player_2") or "TBD"
    )
    group = (
        f"{match['group_name']} · Round {match['round_number']} · "
        if match.get("group_name")
        else f"{match['round_label']} · "
    )
    return f"{group}{player_1_name} vs {player_2_name}"


def _ordinal(value: int) -> str:
    """Return a compact English ordinal label."""

    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _render_group_quick_result(
    *,
    db_path: str | Path,
    draft_id: str,
    match: dict[str, Any],
) -> None:
    """Render the primary result action for the selected Group Set."""

    match_id = str(match["group_match_id"])
    player_1_name = str(match["player_1"])
    player_2_name = str(match["player_2"])
    result_type = st.segmented_control(
        "Result type",
        options=["Played", "W–L", "Cancelled"],
        default="Played",
        key=f"control_group_result_type_{match_id}",
    )
    st.markdown(
        compact_score_input_styles(
            "control_group_score_",
            separate_stepper_buttons=True,
        ),
        unsafe_allow_html=True,
    )
    with st.form(f"control_group_result_{match_id}", border=False):
        winner_id = None
        player_1_score = None
        player_2_score = None
        if result_type == "Played":
            score_columns = st.columns(2)
            player_1_score = score_columns[0].number_input(
                f"{player_1_name} score",
                min_value=0,
                value=0,
                step=1,
                key=f"control_group_score_{match_id}_player_1",
            )
            player_2_score = score_columns[1].number_input(
                f"{player_2_name} score",
                min_value=0,
                value=0,
                step=1,
                key=f"control_group_score_{match_id}_player_2",
            )
        elif result_type == "W–L":
            winner_by_name = {
                player_1_name: str(match["player_1_id"]),
                player_2_name: str(match["player_2_id"]),
            }
            winner_name = st.selectbox("Winner", options=list(winner_by_name))
            winner_id = winner_by_name[winner_name]

        submitted = st.form_submit_button(
            "Save Result",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return
    status = {
        "Played": "completed",
        "W–L": "forfeit",
        "Cancelled": "cancelled",
    }[str(result_type)]
    try:
        tournament_manager.update_draft_group_match(
            db_path,
            match_id,
            status=status,
            winner_id=winner_id,
            player_1_score=(
                int(player_1_score) if player_1_score is not None else None
            ),
            player_2_score=(
                int(player_2_score) if player_2_score is not None else None
            ),
        )
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.cache_data.clear()
        st.session_state.pop(f"control_group_choice_{draft_id}", None)
        st.rerun()


def _render_group_control_center(
    *,
    db_path: str | Path,
    draft_id: str,
    matches: list[dict[str, Any]],
    standings: list[dict[str, Any]],
    artifact_path: Path,
    player_names: dict[str, str],
) -> None:
    """Render the live Group Stage dashboard."""

    forecast = None
    forecast_error = None
    try:
        with st.spinner("Updating live probabilities…"):
            forecast = _cached_live_group_forecast(
                str(db_path),
                draft_id,
                str(artifact_path),
            )
    except (
        ArtifactError,
        FileNotFoundError,
        KeyError,
        RuntimeError,
        ValueError,
    ) as exc:
        forecast_error = str(exc)

    forecast_by_player_id = {
        player.player_id: player
        for player in (forecast.players if forecast is not None else ())
    }

    ready = group_ready_matches(matches)
    decided = sum(
        str(match["status"]) in {"completed", "forfeit", "cancelled"}
        for match in matches
    )
    st.progress(
        decided / len(matches) if matches else 0.0,
        text=f"{decided} of {len(matches)} Group Sets decided",
    )

    if ready:
        option_by_label = {
            _match_option_label(match): match for match in ready
        }
        recommended_label = next(iter(option_by_label))
        choice_key = f"control_group_choice_{draft_id}"
        selected_label = st.session_state.get(
            choice_key,
            recommended_label,
        )
        if selected_label not in option_by_label:
            selected_label = recommended_label
            st.session_state[choice_key] = recommended_label

        has_alternatives = len(option_by_label) > 1
        card_height: int | str = 470 if has_alternatives else "content"
        if has_alternatives:
            action_column, alternatives_column = st.columns([1.45, 1])
        else:
            action_column = st.container()
            alternatives_column = None

        with action_column:
            st.markdown("### Up Next")
            selected = option_by_label[selected_label]
            player_1_probability = None
            if forecast is not None:
                leverage = next(
                    (
                        item
                        for item in forecast.match_leverage
                        if {
                            item.player_1_id,
                            item.player_2_id,
                        }
                        == {
                            str(selected["player_1_id"]),
                            str(selected["player_2_id"]),
                        }
                    ),
                    None,
                )
                if leverage is not None:
                    player_1_probability = (
                        leverage.player_1_set_win_probability
                        if (
                            leverage.player_1_id
                            == str(selected["player_1_id"])
                        )
                        else 1.0 - leverage.player_1_set_win_probability
                    )
            with st.container(border=True, height=card_height):
                st.markdown(
                    (
                        '<div style="text-align:center;opacity:0.68;'
                        'font-size:0.9rem;font-weight:600;'
                        'margin:0.1rem 0 0.45rem;">'
                        f"{html.escape(str(selected['group_name']))} · "
                        f"Round {int(selected['round_number'])}"
                        '</div>'
                        '<div style="'
                        'display:grid;'
                        'grid-template-columns:1fr auto 1fr;'
                        'align-items:center;'
                        'gap:1rem;'
                        'padding:0.1rem 0 0.2rem;'
                        '">'
                        '<div style="text-align:right;font-size:2.15rem;'
                        'font-weight:800;line-height:1.1;">'
                        f"{html.escape(str(selected['player_1']))}"
                        '</div>'
                        '<div style="opacity:0.55;font-size:0.9rem;'
                        'font-weight:700;">VS</div>'
                        '<div style="text-align:left;font-size:2.15rem;'
                        'font-weight:800;line-height:1.1;">'
                        f"{html.escape(str(selected['player_2']))}"
                        '</div>'
                        '</div>'
                        + (
                            '<div style="display:grid;'
                            'grid-template-columns:1fr 1fr;gap:2rem;'
                            'margin:0.45rem 0 0.1rem;opacity:0.65;'
                            'font-size:0.82rem;">'
                            '<div style="text-align:right;">'
                            f"{player_1_probability:.1%} win chance"
                            '</div>'
                            '<div style="text-align:left;">'
                            f"{1.0 - player_1_probability:.1%} win chance"
                            '</div></div>'
                            if player_1_probability is not None
                            else ""
                        )
                    ),
                    unsafe_allow_html=True,
                )
                st.divider()
                _render_group_quick_result(
                    db_path=db_path,
                    draft_id=draft_id,
                    match=selected,
                )
        if alternatives_column is not None:
            with alternatives_column:
                st.markdown("### Other Playable Sets")
                alternative_labels = [
                    label
                    for label in option_by_label
                    if label != selected_label
                ]
                visible_alternatives = alternative_labels[:4]
                with st.container(border=True, height=card_height):
                    st.markdown(
                        clickable_card_button_styles(
                            "control_choose_group_",
                            show_focus_ring=True,
                        ),
                        unsafe_allow_html=True,
                    )
                    for label in visible_alternatives:
                        match = option_by_label[label]
                        if st.button(
                            (
                                f"**{match['player_1']}  vs  "
                                f"{match['player_2']}**  \n"
                                f"{match['group_name']} · "
                                f"Round {match['round_number']}  →"
                            ),
                            key=(
                                "control_choose_group_"
                                f"{match['group_match_id']}"
                            ),
                            width="stretch",
                        ):
                            st.session_state[choice_key] = label
                            st.rerun()
                    remaining_count = len(alternative_labels) - len(
                        visible_alternatives
                    )
                    if remaining_count:
                        st.caption(
                            f"{remaining_count} more under All Sets"
                        )
    else:
        st.success("All Group Sets are decided.")

    overview_tab, sets_tab = st.tabs(
        ["Standings & Forecast", "All Sets"]
    )
    with overview_tab:
        if forecast_error:
            st.caption(f"Forecast unavailable: {forecast_error}")
        columns = st.columns(max(1, len(standings)))
        for column, group in zip(columns, standings):
            rows: list[list[str]] = []
            row_highlights: dict[int, str] = {}
            for player in group["standings"]:
                player_forecast = forecast_by_player_id.get(
                    str(player["player_id"])
                )
                player_status = (
                    player_forecast.winners_status
                    if player_forecast is not None
                    else "Unavailable"
                )
                row_index = len(rows)
                if player_status == "Winners Locked":
                    row_highlights[row_index] = "winners"
                elif player_status == "Losers Locked":
                    row_highlights[row_index] = "losers"
                rows.append([
                        str(player["placement"]),
                        str(player["player"]),
                        (
                            f"{player['sets_won']}–{player['sets_lost']}"
                        ),
                        (
                            f"{player['games_won']}–{player['games_lost']}"
                        ),
                        (
                            format_winners_probability(
                                player_forecast.winners_probability,
                                player_forecast.winners_status,
                            )
                            if player_forecast is not None
                            else "—"
                        ),
                        player_status,
                    ]
                )
            with column:
                st.markdown(f"#### {group['group_name']}")
                st.markdown(
                    dashboard_table_html(
                        [
                            "#",
                            "Player",
                            "Sets",
                            "Games",
                            "P(Winners)",
                            "Status",
                        ],
                        rows,
                        columns=(
                            "2.5rem minmax(7rem,1.5fr) "
                            "minmax(4rem,0.65fr) minmax(4rem,0.65fr) "
                            "minmax(6rem,0.8fr) minmax(7rem,1fr)"
                        ),
                        row_highlights=row_highlights,
                        emphasis_column=1,
                    ),
                    unsafe_allow_html=True,
                )
        st.caption(
            "10'000 simulations · completed results fixed · "
            "remaining Group Sets use frozen pre-tournament strengths"
        )
    with sets_tab:
        rows = [
            [
                str(match["group_name"]),
                str(match["round_number"]),
                (
                    f"{match['player_1']} vs {match['player_2']}"
                ),
                str(match["status"]).title(),
                (
                    f"{match['player_1_score']}–{match['player_2_score']}"
                    if match["player_1_score"] is not None
                    else "—"
                ),
            ]
            for match in sorted(
                matches,
                key=lambda item: (
                    str(item["status"]) != "pending",
                    int(item["round_number"]),
                    int(item["match_number"]),
                ),
            )
        ]
        st.markdown(
            dashboard_table_html(
                ["Group", "Round", "Set", "Status", "Result"],
                rows,
                columns=(
                    "minmax(5rem,0.7fr) minmax(4rem,0.55fr) "
                    "minmax(12rem,2fr) minmax(6rem,0.8fr) "
                    "minmax(5rem,0.65fr)"
                ),
                emphasis_column=2,
            ),
            unsafe_allow_html=True,
        )


def _render_bracket_control_center(
    *,
    db_path: str | Path,
    draft_id: str,
    bracket_state: dict[str, Any],
    artifact_path: Path,
    player_names: dict[str, str],
    show_bracket_match_dialog: Callable[..., None],
    load_finalization_preview: Callable[[str], dict[str, Any]],
) -> None:
    """Render ready actions around the live Bracket visualization."""

    matches = bracket_state["matches"]
    ready = sorted(
        (
            match
            for match in matches
            if str(match["status"]) == "pending"
        ),
        key=lambda match: (
            int(match.get("suggested_play_order") or 9999),
            int(match["round_number"]),
            int(match["match_number"]),
        ),
    )
    played = int(bracket_state["played_set_count"])
    total = int(bracket_state["playable_set_count"])
    st.progress(
        played / total if total else 0.0,
        text=f"{played} of {total} Bracket Sets played",
    )
    champion_name = bracket_state["champion_name"]
    if champion_name:
        st.success(f"Champion: {champion_name}")
        try:
            finalization_preview = load_finalization_preview(draft_id)
        except ValueError as exc:
            st.warning(str(exc))
        else:
            st.markdown("### Final Standings")
            placements = finalization_preview["placements"]
            placement_counts: dict[int, int] = {}
            for placement in placements:
                placement_value = int(placement["placement"])
                placement_counts[placement_value] = (
                    placement_counts.get(placement_value, 0) + 1
                )
            medal_by_placement = {
                1: "🥇",
                2: "🥈",
                3: "🥉",
            }
            placement_rows = []
            for placement in placements:
                placement_value = int(placement["placement"])
                initial_seed = int(placement["initial_seed"])
                elo_after = float(placement["elo_after"])
                elo_change = float(placement["elo_change"])
                placement_rows.append(
                    [
                        (
                            f"{medal_by_placement.get(placement_value, '')} "
                            f"{'T-' if placement_counts[placement_value] > 1 else ''}"
                            f"{_ordinal(placement_value)}"
                        ).strip(),
                        str(placement["player"]),
                        f"Seed #{initial_seed}",
                        (
                            f"▲ {initial_seed - placement_value}"
                            if initial_seed > placement_value
                            else (
                                f"▼ {placement_value - initial_seed}"
                                if initial_seed < placement_value
                                else "= Seed"
                            )
                        ),
                        f"{elo_after:.1f} ({elo_change:+.1f})",
                    ]
                )
            st.markdown(
                dashboard_table_html(
                    [
                        "Placement",
                        "Player",
                        "Initial Seed",
                        "Seed Change",
                        "Elo (Change)",
                    ],
                    placement_rows,
                    columns=(
                        "minmax(7rem,0.8fr) minmax(12rem,2fr) "
                        "minmax(7rem,0.75fr) minmax(7rem,0.7fr) "
                        "minmax(8rem,0.85fr)"
                    ),
                    row_highlights={0: "winners"},
                    emphasis_column=1,
                ),
                unsafe_allow_html=True,
            )
            st.caption(
                "▲ finished above the initial seed · "
                "▼ finished below the initial seed"
            )
            st.warning(
                "Finalizing writes the tournament, participants, "
                "placements, and set results to the permanent archive. "
                "The draft can no longer be edited afterwards."
            )
            confirm_finalization = st.checkbox(
                (
                    f"I confirm that WC "
                    f"{finalization_preview['tournament_number']:02d} "
                    "is complete and ready for the archive."
                ),
                key=f"control_confirm_finalization_{draft_id}",
            )
            if st.button(
                "Finalize Tournament",
                type="primary",
                width="stretch",
                key=f"control_finalize_tournament_{draft_id}",
                disabled=not confirm_finalization,
            ):
                try:
                    result = tournament_manager.finalize_draft_tournament(
                        db_path,
                        draft_id,
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
                        f"{result['matches_archived']} sets were added."
                    )
                    st.rerun()

    dialog_key = f"open_bracket_match_code_{draft_id}"
    visible_codes = {
        str(match["match_code"])
        for match in matches
        if str(match["status"]) != "inactive"
    }
    open_code = st.session_state.get(dialog_key)
    if open_code not in visible_codes:
        open_code = None
        st.session_state.pop(dialog_key, None)

    forecast_by_code = {}
    if ready:
        try:
            with st.spinner("Updating bracket probabilities…"):
                forecast = _cached_live_bracket_forecast(
                    str(db_path),
                    draft_id,
                    str(artifact_path),
                )
            forecast_by_code = {
                str(match.match_code): match
                for match in forecast.ready_matches
            }
        except (
            ArtifactError,
            FileNotFoundError,
            KeyError,
            RuntimeError,
            ValueError,
        ):
            pass

    if ready:
        option_by_label = {
            _match_option_label(match): match for match in ready
        }
        choice_key = f"control_bracket_choice_{draft_id}"
        chosen_label = st.session_state.get(
            choice_key,
            next(iter(option_by_label)),
        )
        if chosen_label not in option_by_label:
            chosen_label = next(iter(option_by_label))
        chosen = option_by_label[chosen_label]
        has_alternatives = len(option_by_label) > 1
        card_height: int | str = 263 if has_alternatives else "content"
        if has_alternatives:
            action_column, alternatives_column = st.columns([1.45, 1])
        else:
            action_column = st.container()
            alternatives_column = None
        with action_column:
            st.markdown("### Up Next")
            chosen_forecast = forecast_by_code.get(
                str(chosen["match_code"])
            )
            player_1_probability = None
            if chosen_forecast is not None:
                player_1_probability = (
                    chosen_forecast.player_1_win_probability
                    if (
                        str(chosen_forecast.player_1_id)
                        == str(chosen["player_1_id"])
                    )
                    else 1.0 - chosen_forecast.player_1_win_probability
                )
            with st.container(border=True, height=card_height):
                st.markdown(
                    (
                        '<div style="text-align:center;opacity:0.68;'
                        'font-size:0.9rem;font-weight:600;'
                        'margin:0.1rem 0 0.45rem;">'
                        f"{html.escape(str(chosen['round_label']))} · "
                        f"{html.escape(str(chosen['match_code']))}"
                        '</div>'
                        '<div style="display:grid;'
                        'grid-template-columns:1fr auto 1fr;'
                        'align-items:center;gap:1rem;'
                        'padding:0.1rem 0 0.2rem;">'
                        '<div style="text-align:right;font-size:2.15rem;'
                        'font-weight:800;line-height:1.1;">'
                        f"{html.escape(str(chosen['player_1_name']))}"
                        '</div>'
                        '<div style="opacity:0.55;font-size:0.9rem;'
                        'font-weight:700;">VS</div>'
                        '<div style="text-align:left;font-size:2.15rem;'
                        'font-weight:800;line-height:1.1;">'
                        f"{html.escape(str(chosen['player_2_name']))}"
                        '</div></div>'
                        + (
                            '<div style="display:grid;'
                            'grid-template-columns:1fr 1fr;gap:2rem;'
                            'margin:0.45rem 0 0.1rem;opacity:0.65;'
                            'font-size:0.82rem;">'
                            '<div style="text-align:right;">'
                            f"{player_1_probability:.1%} win chance"
                            '</div><div style="text-align:left;">'
                            f"{1.0 - player_1_probability:.1%} win chance"
                            '</div></div>'
                            if player_1_probability is not None
                            else ""
                        )
                    ),
                    unsafe_allow_html=True,
                )
                st.divider()
                if st.button(
                    "Enter Result",
                    type="primary",
                    width="stretch",
                    key=(
                        "control_open_bracket_"
                        f"{chosen['bracket_match_id']}"
                    ),
                ):
                    st.session_state[dialog_key] = str(
                        chosen["match_code"]
                    )
                    st.rerun()
        if alternatives_column is not None:
            with alternatives_column:
                st.markdown("### Other Ready Sets")
                alternative_labels = [
                    label
                    for label in option_by_label
                    if label != chosen_label
                ]
                with st.container(border=True, height=card_height):
                    st.markdown(
                        clickable_card_button_styles(
                            "control_choose_bracket_",
                            title_font_size="1.18rem",
                        ),
                        unsafe_allow_html=True,
                    )
                    for label in alternative_labels[:2]:
                        match = option_by_label[label]
                        if st.button(
                            (
                                f"**{match['player_1_name']}  vs  "
                                f"{match['player_2_name']}**  \n"
                                f"{match['round_label']} · "
                                f"{match['match_code']}  →"
                            ),
                            key=(
                                "control_choose_bracket_"
                                f"{match['bracket_match_id']}"
                            ),
                            width="stretch",
                        ):
                            st.session_state[choice_key] = label
                            st.rerun()
                    remaining_count = len(alternative_labels) - min(
                        len(alternative_labels),
                        2,
                    )
                    if remaining_count:
                        st.caption(
                            f"{remaining_count} more in the Live Bracket"
                        )
    elif not champion_name:
        st.info("No Bracket Set is ready. An earlier result is still required.")

    st.markdown("### Final Bracket" if champion_name else "### Live Bracket")
    clicked_code = bracket_visualization.render_bracket(
        matches,
        bracket_state["routes"],
        selected_match_code=open_code,
        component_key=f"control_bracket_component_{draft_id}",
    )
    if (
        clicked_code
        and clicked_code in visible_codes
        and clicked_code != open_code
    ):
        st.session_state[dialog_key] = clicked_code
        st.rerun()

    open_code = st.session_state.get(dialog_key)
    if open_code:
        selected_match = next(
            (
                match
                for match in matches
                if str(match["match_code"]) == str(open_code)
            ),
            None,
        )
        if selected_match is not None:
            dialog_match = dict(selected_match)
            selected_forecast = forecast_by_code.get(str(open_code))
            if selected_forecast is not None:
                player_1_win_probability = (
                    selected_forecast.player_1_win_probability
                    if (
                        str(selected_forecast.player_1_id)
                        == str(selected_match["player_1_id"])
                    )
                    else 1.0 - selected_forecast.player_1_win_probability
                )
                dialog_match["player_1_win_probability"] = (
                    player_1_win_probability
                )
                st.session_state[
                    f"dialog_bracket_probability_{open_code}"
                ] = player_1_win_probability
            show_bracket_match_dialog(dialog_match, dialog_key)


def render_tournament_manager(
    *,
    db_path: str | Path,
    model_artifact_path: Path,
    load_players: Callable[..., list[dict[str, Any]]],
    load_tournaments: Callable[..., list[dict[str, Any]]],
    load_tournament_drafts: Callable[..., list[dict[str, Any]]],
    load_tournament_draft: Callable[..., dict[str, Any]],
    load_tournament_draft_groups: Callable[..., list[dict[str, Any]]],
    load_tournament_draft_group_matches: Callable[..., list[dict[str, Any]]],
    load_tournament_draft_group_standings: Callable[..., list[dict[str, Any]]],
    load_tournament_draft_global_group_ranking: Callable[..., dict[str, Any]],
    load_tournament_draft_bracket_state: Callable[..., dict[str, Any]],
    load_tournament_draft_finalization_preview: Callable[..., dict[str, Any]],
    show_bracket_match_dialog: Callable[..., None],
) -> None:
    """Creates and manages tournament drafts."""

    st.title("🛠 Tournament Manager")
    st.caption(
        "Create tournament drafts, select participants, and prepare "
        "the tournament structure."
    )

    st.subheader("Create Tournament Draft")

    existing_tournaments = load_tournaments()
    existing_numbers = [
        int(row["WC"].split()[1])
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
            index=1,
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
                db_path,
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
                f"Draft for WC {int(tournament_number):02d} created."
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
            f"WC {int(draft['tournament_number']):02d} · "
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
    forecast_player_names = {
        str(participant["player_id"]): str(participant["player"])
        for participant in draft["participants"]
    }

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

    stage_label, stage_help = _draft_stage(
        draft=draft,
        group_matches=draft_group_matches,
        bracket_state=draft_bracket_state,
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
        f"WC {int(draft['tournament_number']):02d}",
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

    st.markdown(
        (
            '<div style="display:flex;align-items:center;gap:0.65rem;'
            'margin:0.15rem 0 0.85rem;">'
            '<span style="padding:0.2rem 0.65rem;border-radius:999px;'
            'background:rgba(88,166,255,0.16);'
            'border:1px solid rgba(88,166,255,0.35);font-weight:600;">'
            f"{html.escape(stage_label)}</span>"
            f"<span>{html.escape(stage_help)}</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
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

    control_center_active = bool(
        draft_group_matches or bracket_generated
    )
    if control_center_active:
        st.markdown("## Tournament Control Center")
        show_detailed_management = st.toggle(
            "Show detailed management",
            value=False,
            key=f"show_detailed_management_{selected_draft_id}",
            help=(
                "Open the complete legacy workflow for corrections, resets, "
                "and less common administrative actions."
            ),
        )
        if (
            draft_group_matches
            and not bracket_generated
            and not show_detailed_management
        ):
            group_standings = (
                load_tournament_draft_group_standings(
                    selected_draft_id,
                )
            )
            _render_group_control_center(
                db_path=db_path,
                draft_id=selected_draft_id,
                matches=draft_group_matches,
                standings=group_standings,
                artifact_path=model_artifact_path,
                player_names=forecast_player_names,
            )
            group_complete = all(
                str(match["status"]) != "pending"
                for match in draft_group_matches
            )
            if group_complete:
                st.divider()
                st.success(
                    "Group Stage complete. Final standings and Bracket "
                    "seeds are ready."
                )
                if st.button(
                    "Generate Bracket",
                    type="primary",
                    key=f"control_generate_bracket_{selected_draft_id}",
                ):
                    try:
                        tournament_manager.generate_draft_bracket(
                            db_path,
                            selected_draft_id,
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.cache_data.clear()
                        st.rerun()
            st.caption(
                "Use “Show detailed management” for result corrections, "
                "group resets, or setup changes."
            )
            return
        if (
            bracket_generated
            and not show_detailed_management
        ):
            _render_bracket_control_center(
                db_path=db_path,
                draft_id=selected_draft_id,
                bracket_state=draft_bracket_state,
                artifact_path=model_artifact_path,
                player_names=forecast_player_names,
                show_bracket_match_dialog=show_bracket_match_dialog,
                load_finalization_preview=(
                    load_tournament_draft_finalization_preview
                ),
            )
            st.caption(
                "Use “Show detailed management” for complete Set lists, "
                "result corrections, or Bracket resets."
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
                    db_path,
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

    participants_ready = (
        len(draft["participants"]) >= 3
        and all(
            participant["manual_seed"] is not None
            for participant in draft["participants"]
        )
    )
    group_stage_complete = (
        bool(draft_group_matches)
        and all(
            match["status"] != "pending"
            for match in draft_group_matches
        )
    )
    bracket_complete = bool(
        draft_bracket_state["champion_name"]
    )

    participants_tab_label = (
        "✓ Participants & Seeding"
        if participants_ready
        else "1. Participants & Seeding"
    )
    group_tab_label = (
        "✓ Group Stage"
        if group_stage_complete
        else "2. Group Stage"
    )
    bracket_step_number = (
        3
        if draft["format_type"]
        == tournament_manager.FORMAT_GROUP_STAGE
        else 2
    )
    bracket_tab_label = (
        "✓ Double Elimination Bracket"
        if bracket_complete
        else (
            f"{bracket_step_number}. "
            "Double Elimination Bracket"
        )
    )
    workflow_tab_key = f"tournament_workflow_tab_{selected_draft_id}"
    pending_tab_key = f"pending_workflow_tab_{selected_draft_id}"

    tab_labels = [participants_tab_label]
    if draft["format_type"] == tournament_manager.FORMAT_GROUP_STAGE:
        tab_labels.append(group_tab_label)
    tab_labels.append(bracket_tab_label)

    pending_tab = st.session_state.pop(pending_tab_key, None)

    def current_label_for(
        stored_label: str | None,
    ) -> str | None:
        if stored_label is None:
            return None

        for tab_label in tab_labels:
            if (
                "Participants & Seeding" in stored_label
                and "Participants & Seeding" in tab_label
            ):
                return tab_label
            if (
                "Group Stage" in stored_label
                and "Group Stage" in tab_label
            ):
                return tab_label
            if (
                "Double Elimination Bracket" in stored_label
                and "Double Elimination Bracket" in tab_label
            ):
                return tab_label

        return None

    pending_tab = current_label_for(pending_tab)
    if pending_tab in tab_labels:
        st.session_state[workflow_tab_key] = pending_tab
    else:
        current_tab = current_label_for(
            st.session_state.get(workflow_tab_key)
        )
        st.session_state[workflow_tab_key] = (
            current_tab
            if current_tab is not None
            else participants_tab_label
        )

    workflow_tabs = st.tabs(
        tab_labels,
        key=workflow_tab_key,
        on_change="rerun",
    )
    participants_tab = workflow_tabs[0]
    if len(workflow_tabs) == 3:
        group_tab = workflow_tabs[1]
        bracket_tab = workflow_tabs[2]
    else:
        group_tab = None
        bracket_tab = workflow_tabs[1]

    with participants_tab:
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
                    "because the group sets have already been generated. "
                    "Reset the group sets to make changes."
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
                        db_path,
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
                        db_path,
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
                width="stretch",
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
                        db_path,
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
                        db_path,
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
                        db_path,
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
                    st.session_state[pending_tab_key] = (
                        group_tab_label
                        if draft["format_type"]
                        == tournament_manager.FORMAT_GROUP_STAGE
                        else bracket_tab_label
                    )
                    st.success("Seeding order saved.")
                    st.rerun()

        else:
            st.info("No participants have been added yet.")

    if draft["format_type"] == tournament_manager.FORMAT_GROUP_STAGE:
        with group_tab:
            if (
                draft["participants"]
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
                                db_path,
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
                            "until the group sets are generated."
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
                                        db_path,
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
                                        width="stretch",
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
                                        db_path,
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
                        st.markdown("### Group Sets")

                        group_matches = draft_group_matches

                        if not setup_locked:
                            if st.button(
                                "Generate Group Sets",
                                type="primary",
                                key=(
                                    f"generate_group_matches_"
                                    f"{selected_draft_id}"
                                ),
                            ):
                                try:
                                    tournament_manager.create_draft_group_matches(
                                        db_path,
                                        selected_draft_id,
                                    )
                                except ValueError as exc:
                                    st.error(str(exc))
                                else:
                                    st.cache_data.clear()
                                    st.success(
                                        "Round-robin group sets generated."
                                    )
                                    st.rerun()

                        if group_matches:
                            st.caption(
                                "Reset the group sets to unlock participants, "
                                "seeding, and group assignments."
                            )

                            playable_group_matches = [
                                match
                                for match in group_matches
                                if match["status"] != "cancelled"
                            ]
                            played_group_matches = [
                                match
                                for match in playable_group_matches
                                if match["status"]
                                in {"completed", "forfeit"}
                            ]
                            group_match_count = len(
                                playable_group_matches
                            )
                            group_played_count = len(
                                played_group_matches
                            )
                            group_progress = (
                                group_played_count
                                / group_match_count
                                if group_match_count
                                else 0.0
                            )
                            st.progress(
                                group_progress,
                                text=(
                                    f"{group_played_count} of "
                                    f"{group_match_count} group sets played"
                                ),
                            )

                            if (
                                3 <= len(draft["participants"]) <= 32
                                and draft_groups
                                and not bracket_generated
                            ):
                                _render_live_group_forecast(
                                    db_path=db_path,
                                    draft_id=selected_draft_id,
                                    artifact_path=model_artifact_path,
                                    player_names=forecast_player_names,
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
                                    width="stretch",
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
                                    f"{group_standing['total_matches']} sets "
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

                                if not bracket_generated:
                                    if st.button(
                                        "Generate Bracket",
                                        type="primary",
                                        key=(
                                            "generate_bracket_from_group_"
                                            f"{selected_draft_id}"
                                        ),
                                    ):
                                        try:
                                            result = (
                                                tournament_manager
                                                .generate_draft_bracket(
                                                    db_path,
                                                    selected_draft_id,
                                                )
                                            )
                                        except ValueError as exc:
                                            st.error(str(exc))
                                        else:
                                            st.cache_data.clear()
                                            st.session_state[
                                                pending_tab_key
                                            ] = bracket_tab_label
                                            st.success(
                                                f"{result['bracket_size']}-"
                                                "player bracket generated."
                                            )
                                            st.rerun()
                            else:
                                st.warning(
                                    "This ranking is provisional because "
                                    f"{global_ranking['pending_matches']} "
                                    "group sets are still pending."
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
                                width="stretch",
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
                            st.markdown("### Set Results")

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

                            first_pending_group_match_id = next(
                                (
                                    str(match["group_match_id"])
                                    for match in group_matches
                                    if match["status"] == "pending"
                                ),
                                None,
                            )

                            for group_name, matches in (
                                matches_by_group.items()
                            ):
                                st.markdown(f"#### {group_name}")

                                rounds: dict[
                                    tuple[str, int],
                                    list[dict[str, Any]],
                                ] = {}

                                ordered_group_matches = sorted(
                                    matches,
                                    key=lambda match: (
                                        match["status"] != "pending",
                                        int(match["round_number"]),
                                        int(match["match_number"]),
                                    ),
                                )

                                for match in ordered_group_matches:
                                    round_number = int(
                                        match["round_number"]
                                    )
                                    match_section = (
                                        "open"
                                        if match["status"] == "pending"
                                        else "played"
                                    )

                                    rounds.setdefault(
                                        (
                                            match_section,
                                            round_number,
                                        ),
                                        [],
                                    ).append(match)

                                previous_match_section = None

                                for (
                                    match_section,
                                    round_number,
                                ), round_matches in rounds.items():
                                    if (
                                        match_section
                                        != previous_match_section
                                    ):
                                        if match_section == "open":
                                            st.markdown(
                                                "##### Sets to Play"
                                            )
                                        else:
                                            if (
                                                previous_match_section
                                                is not None
                                            ):
                                                st.divider()
                                            st.markdown(
                                                "##### Played Sets"
                                            )

                                        previous_match_section = (
                                            match_section
                                        )

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
                                            f"Set {match['match_number']} · "
                                            f"{match['player_1']} vs "
                                            f"{match['player_2']} · "
                                            f"{match_state}"
                                        )

                                        with st.expander(
                                            match_label,
                                            expanded=(
                                                str(
                                                    match["group_match_id"]
                                                )
                                                == first_pending_group_match_id
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
                                                disabled=bracket_generated,
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
                                                            disabled=bracket_generated,
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
                                                            disabled=bracket_generated,
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
                                                        disabled=bracket_generated,
                                                    )

                                                    winner_id = winner_options[
                                                        selected_winner_name
                                                    ]

                                                save_result = st.form_submit_button(
                                                    "Save Result",
                                                    type="primary",
                                                    disabled=bracket_generated,
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
                                                        db_path,
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
                                                        "Set result saved."
                                                    )
                                                    st.rerun()

                            if bracket_generated:
                                st.info(
                                    "The group stage is locked because the "
                                    "bracket has already been generated. "
                                    "Reset the bracket first if you need to "
                                    "reset the group sets."
                                )

                            if st.button(
                                "Reset Group Sets",
                                type="secondary",
                                key=(
                                    f"reset_group_matches_"
                                    f"{selected_draft_id}"
                                ),
                                disabled=bracket_generated,
                            ):
                                try:
                                    tournament_manager.reset_draft_group_matches(
                                        db_path,
                                        selected_draft_id,
                                    )
                                except ValueError as exc:
                                    st.error(str(exc))
                                else:
                                    st.cache_data.clear()
                                    st.success(
                                        "Group sets reset."
                                    )
                                    st.rerun()

                else:
                    st.info(
                        "At least two participants are required "
                        "to create a group."
                    )

            else:
                st.info("No participants have been added yet.")

    with bracket_tab:
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
                        "Complete all group sets before generating "
                        "the bracket."
                    )

            if not bracket_can_be_generated:
                if st.button(
                    "Go to Group Stage",
                    key=(
                        f"go_to_group_stage_"
                        f"{selected_draft_id}"
                    ),
                ):
                    st.session_state[pending_tab_key] = (
                        group_tab_label
                    )
                    st.rerun()

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
                            db_path,
                            selected_draft_id,
                        )
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.cache_data.clear()
                    st.session_state[pending_tab_key] = bracket_tab_label
                    st.success(
                        f"{result['bracket_size']}-player bracket "
                        "generated successfully."
                    )
                    st.rerun()

        else:
            match_count = int(
                draft_bracket_state["playable_set_count"]
            )
            ready_count = int(
                draft_bracket_state["ready_set_count"]
            )
            waiting_count = int(
                draft_bracket_state["waiting_set_count"]
            )
            completed_count = int(
                draft_bracket_state["played_set_count"]
            )

            bracket_metrics = st.columns(4)

            bracket_metrics[0].metric(
                "Sets",
                match_count,
            )
            bracket_metrics[1].metric(
                "Ready",
                ready_count,
            )
            bracket_metrics[2].metric(
                "Waiting",
                waiting_count,
            )
            bracket_metrics[3].metric(
                "Played",
                completed_count,
            )

            bracket_progress = (
                completed_count / match_count
                if match_count
                else 0.0
            )
            st.progress(
                bracket_progress,
                text=(
                    f"{completed_count} of {match_count} "
                    "bracket sets played"
                ),
            )

            if (
                3 <= len(draft["participants"]) <= 32
                and (
                    draft["format_type"]
                    == tournament_manager.FORMAT_DOUBLE_ELIMINATION
                    or draft_groups
                )
                and not draft_bracket_state["champion_name"]
            ):
                _render_live_bracket_forecast(
                    db_path=db_path,
                    draft_id=selected_draft_id,
                    artifact_path=model_artifact_path,
                    player_names=forecast_player_names,
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
                        "Sets to Archive",
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
                        width="stretch",
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
                            "automatic, cancelled, or inactive bracket entries "
                            "will not be added to the archive."
                        )

                    if (
                        finalization_preview[
                            "cancelled_group_matches_omitted"
                        ]
                    ):
                        st.caption(
                            f"{finalization_preview['cancelled_group_matches_omitted']} "
                            "cancelled group sets will not be added "
                            "to the archive."
                        )

                    st.warning(
                        "Finalizing writes the tournament, participants, "
                        "placements, and set results to the permanent archive. "
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
                                    db_path,
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
                                f"{result['matches_archived']} sets "
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

            ready_matches = [
                match
                for match in bracket_matches
                if match["status"] == "pending"
            ]

            st.markdown("### Up Next")

            if ready_matches:
                ready_columns = st.columns(
                    min(3, len(ready_matches))
                )

                for index, match in enumerate(
                    ready_matches[:3]
                ):
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
                    button_label = (
                        f"{match['match_code']} · "
                        f"{player_1_name} vs {player_2_name}"
                    )

                    if ready_columns[index].button(
                        button_label,
                        key=(
                            f"open_ready_match_"
                            f"{match['bracket_match_id']}"
                        ),
                        width="stretch",
                    ):
                        st.session_state[
                            dialog_state_key
                        ] = str(match["match_code"])
                        st.rerun()
            else:
                st.caption(
                    "No set is ready right now. Complete an earlier "
                    "result to advance the bracket."
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

            st.markdown("### Set Management")

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

                    ordered_round_matches = sorted(
                        round_matches,
                        key=lambda match: (
                            {
                                "pending": 0,
                                "waiting": 1,
                                "completed": 2,
                                "forfeit": 2,
                                "bye": 2,
                                "cancelled": 2,
                            }.get(
                                str(match["status"]),
                                3,
                            ),
                            int(match["match_number"]),
                        ),
                    )

                    for match in ordered_round_matches:
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
                                    "This set is waiting for players "
                                    "from earlier rounds."
                                )

                            elif match_status == "bye":
                                st.info(
                                    f"{match['winner_name']} advances "
                                    "automatically."
                                )

                            elif match_status == "cancelled":
                                st.info(
                                    "This set has been cancelled."
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
                                            db_path,
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
                                    "dependent later bracket sets."
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
                                                db_path,
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
                                            "dependent sets were cleared."
                                        )
                                        st.rerun()

            st.warning(
                "Resetting the bracket deletes all bracket sets "
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
                        db_path,
                        selected_draft_id,
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.cache_data.clear()
                    st.success(
                        "Bracket reset successfully."
                    )
                    st.rerun()

    st.divider()
    with st.expander("Danger Zone", expanded=False):
        st.caption(
            "Destructive actions are kept separate from the "
            "tournament workflow."
        )

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
                    db_path,
                    selected_draft_id,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()
                st.success("Tournament draft deleted.")
                st.rerun()
