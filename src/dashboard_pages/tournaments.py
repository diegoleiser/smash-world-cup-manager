"""Archived tournaments page presentation and interaction."""

from __future__ import annotations

import html
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
from tournament.group_stage_standings import calculate_group_standings


def _archived_tournament_selector_styles() -> str:
    """Return page-scoped styles for the archived tournament selector."""

    return """
    <style>
    div[class*="st-key-archived_tournament_selector"] {
        margin-bottom: 0.85rem;
        padding: 0.55rem 0.85rem 0.75rem;
        border: 1px solid rgba(128, 128, 128, 0.30);
        border-radius: 0.8rem;
        background: rgba(255, 255, 255, 0.018);
        transition:
            border-color 0.15s ease,
            background-color 0.15s ease,
            box-shadow 0.15s ease;
    }
    div[class*="st-key-archived_tournament_selector"]:hover {
        border-color: rgba(128, 128, 128, 0.48);
        background: rgba(128, 128, 128, 0.035);
    }
    div[class*="st-key-archived_tournament_selector"]:focus-within {
        border-color: var(--primary-color, rgb(255, 75, 75));
        box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.18);
    }
    div[class*="st-key-archived_tournament_selector"] label p {
        color: rgba(250, 250, 250, 0.72);
        font-size: 0.82rem;
        font-weight: 750;
    }
    div[class*="st-key-archived_tournament_selector"]
    [data-baseweb="select"] > div {
        min-height: 3.65rem !important;
        border: none !important;
        border-radius: 0.55rem !important;
        background-color: transparent !important;
        box-shadow: none !important;
    }
    div[class*="st-key-archived_tournament_selector"]
    [role="combobox"],
    div[class*="st-key-archived_tournament_selector"]
    [role="combobox"] *,
    div[class*="st-key-archived_tournament_selector"]
    [aria-haspopup="listbox"],
    div[class*="st-key-archived_tournament_selector"]
    [aria-haspopup="listbox"] *,
    div[class*="st-key-archived_tournament_selector"]
    [data-baseweb="select"] * {
        font-size: 1.75rem !important;
        font-weight: 800 !important;
        line-height: 1.2 !important;
    }
    div[class*="st-key-archived_tournament_selector"] label p {
        font-size: 0.82rem !important;
        font-weight: 750 !important;
    }
    </style>
    """


def _archived_tournament_header_html(
    tournament: dict[str, Any],
    participants: list[dict[str, Any]],
    match_count: int,
) -> str:
    """Return a compact archive header with metadata and podium."""

    podium_names: dict[int, list[str]] = {1: [], 2: [], 3: []}
    for participant in participants:
        placement = participant.get("placement")
        if placement in podium_names:
            podium_names[int(placement)].append(str(participant["player"]))

    podium_items = []
    for placement, icon, label in (
        (1, "🥇", "Champion"),
        (2, "🥈", "Runner-up"),
        (3, "🥉", "Third Place"),
    ):
        names = " · ".join(podium_names[placement]) or "–"
        podium_items.append(
            '<div class="archive-podium-item '
            f'archive-podium-{placement}">'
            f'<div class="archive-podium-label">{icon} {label}</div>'
            f'<div class="archive-podium-player">{html.escape(names)}</div>'
            "</div>"
        )

    tournament_number = int(tournament["tournament_number"])
    tournament_date = html.escape(str(tournament.get("tournament_date") or "–"))
    return f"""
    <style>
    .archive-tournament-card {{
        overflow: hidden;
        margin: 0.35rem 0 1rem;
        border: 1px solid rgba(128, 128, 128, 0.30);
        border-radius: 0.9rem;
        background: rgba(255, 255, 255, 0.018);
    }}
    .archive-tournament-main {{
        display: none;
        align-items: flex-end;
        justify-content: space-between;
        gap: 1.5rem;
        padding: 1.1rem 1.2rem 1rem;
    }}
    .archive-tournament-eyebrow {{
        margin-bottom: 0.22rem;
        color: rgba(250, 250, 250, 0.52);
        font-size: 0.72rem;
        font-weight: 750;
        letter-spacing: 0.055em;
        text-transform: uppercase;
    }}
    .archive-tournament-title {{
        color: rgb(250, 250, 250);
        font-size: 1.85rem;
        font-weight: 850;
        line-height: 1.05;
    }}
    .archive-tournament-meta {{
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 0.45rem;
    }}
    .archive-tournament-meta span {{
        padding: 0.35rem 0.62rem;
        border: 1px solid rgba(128, 128, 128, 0.24);
        border-radius: 999px;
        background: rgba(128, 128, 128, 0.065);
        color: rgba(250, 250, 250, 0.72);
        font-size: 0.8rem;
        font-weight: 650;
        white-space: nowrap;
    }}
    .archive-podium {{
        display: grid;
        grid-template-columns: minmax(0, 1.25fr) repeat(2, minmax(0, 1fr));
        background: rgba(128, 128, 128, 0.035);
    }}
    .archive-podium-item {{
        display: flex;
        min-height: 6.4rem;
        flex-direction: column;
        justify-content: center;
        min-width: 0;
        padding: 1rem 1.2rem 1.1rem;
        border-right: 1px solid rgba(128, 128, 128, 0.18);
    }}
    .archive-podium-item:last-child {{ border-right: none; }}
    .archive-podium-1 {{
        background: rgba(234, 179, 8, 0.065);
        box-shadow: inset 3px 0 rgba(250, 204, 21, 0.48);
    }}
    .archive-podium-label {{
        margin-bottom: 0.2rem;
        color: rgba(250, 250, 250, 0.52);
        font-size: 0.7rem;
        font-weight: 750;
        letter-spacing: 0.035em;
        text-transform: uppercase;
    }}
    .archive-podium-player {{
        overflow: hidden;
        color: rgb(250, 250, 250);
        font-size: 1.25rem;
        font-weight: 800;
        text-overflow: ellipsis;
        white-space: nowrap;
    }}
    .archive-podium-1 .archive-podium-player {{
        font-size: 1.55rem;
    }}
    .archive-tournament-desktop-meta {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.65rem;
        min-height: 3.15rem;
        border-top: 1px solid rgba(128, 128, 128, 0.20);
        color: rgba(250, 250, 250, 0.52);
        font-size: 0.88rem;
        font-weight: 700;
    }}
    .archive-tournament-desktop-meta span + span::before {{
        margin-right: 0.65rem;
        color: rgba(250, 250, 250, 0.24);
        content: "•";
    }}
    @media (max-width: 700px) {{
        .archive-tournament-main {{
            display: flex;
            align-items: flex-start;
            flex-direction: column;
            gap: 0.8rem;
        }}
        .archive-tournament-meta {{ justify-content: flex-start; }}
        .archive-podium {{
            grid-template-columns: 1fr;
            border-top: 1px solid rgba(128, 128, 128, 0.22);
        }}
        .archive-podium-item {{
            min-height: 0;
            padding: 0.8rem 1rem 0.9rem;
            border-right: none;
            border-bottom: 1px solid rgba(128, 128, 128, 0.18);
        }}
        .archive-podium-1 {{ box-shadow: none; }}
        .archive-podium-player {{ font-size: 1.2rem; }}
        .archive-podium-1 .archive-podium-player {{ font-size: 1.25rem; }}
        .archive-podium-item:last-child {{ border-bottom: none; }}
        .archive-tournament-desktop-meta {{ display: none; }}
    }}
    </style>
    <div class="archive-tournament-card">
      <div class="archive-tournament-main">
        <div>
          <div class="archive-tournament-eyebrow">Archived Tournament</div>
          <div class="archive-tournament-title">WC {tournament_number:02d}</div>
        </div>
        <div class="archive-tournament-meta">
          <span>{tournament_date}</span>
          <span>{len(participants)} Participants</span>
          <span>{match_count} Matches</span>
        </div>
      </div>
      <div class="archive-podium">{''.join(podium_items)}</div>
      <div class="archive-tournament-desktop-meta">
        <span>{tournament_date}</span>
        <span>{len(participants)} Participants</span>
        <span>{match_count} Matches</span>
      </div>
    </div>
    """


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


def _phase_match_table_rows(
    matches: list[dict[str, Any]],
    archived_bracket_matches: list[dict[str, Any]],
) -> list[list[str]]:
    """Build match rows without the redundant stage column."""

    return [
        row[1:]
        for row in _all_matches_table_rows(
            matches,
            archived_bracket_matches,
        )
    ]


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


def _elo_snapshot_table_data(
    snapshot: list[dict[str, Any]],
) -> tuple[list[list[str]], dict[int, str]]:
    """Build compact rows for the full post-tournament Elo ranking."""

    rows = [
        [
            f"#{int(row['rank'])}",
            str(row["player"]),
            f"{float(row['elo']):.1f}",
            "Played" if row["played_in_tournament"] else "Did not play",
        ]
        for row in snapshot
    ]
    row_highlights = {
        row_index: "participated"
        for row_index, row in enumerate(snapshot)
        if row["played_in_tournament"]
    }
    return rows, row_highlights


def _elo_ranking_expander_styles() -> str:
    """Return page-scoped styles for the archived Elo ranking expander."""

    return """
    <style>
    div[class*="st-key-archived_elo_ranking"] {
        margin-top: 1rem;
    }
    div[class*="st-key-archived_elo_ranking"] details {
        overflow: hidden;
        border: 1px solid rgba(128, 128, 128, 0.30);
        border-radius: 0.8rem;
        background: rgba(255, 255, 255, 0.018);
        transition: border-color 0.15s ease, background-color 0.15s ease;
    }
    div[class*="st-key-archived_elo_ranking"] details:hover {
        border-color: rgba(128, 128, 128, 0.48);
        background: rgba(128, 128, 128, 0.035);
    }
    div[class*="st-key-archived_elo_ranking"] details[open] {
        background: rgba(255, 255, 255, 0.012);
    }
    div[class*="st-key-archived_elo_ranking"] summary {
        min-height: 3.5rem;
        padding: 0.25rem 0.35rem;
        font-weight: 750;
    }
    </style>
    """


def _archived_group_tables(
    matches: list[dict[str, Any]],
    participants: list[dict[str, Any]],
    changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reconstruct final group tables from archived match results."""

    def group_key(match: dict[str, Any]) -> str | None:
        stage = str(match.get("stage") or "")
        if stage not in {"group", "group_stage"}:
            return None
        challonge_group_id = match.get("challonge_group_id")
        if challonge_group_id is not None:
            return f"challonge:{challonge_group_id}"
        round_label = str(match.get("round_label") or "")
        if " · " in round_label:
            return f"internal:{round_label.split(' · ', 1)[0]}"
        return "group-stage"

    group_matches = [
        match
        for match in matches
        if group_key(match) is not None
    ]
    group_ids = list(
        dict.fromkeys(str(group_key(match)) for match in group_matches)
    )
    participants_by_id = {
        str(participant["player_id"]): participant
        for participant in participants
    }
    elo_by_player_id = {
        str(change["player_id"]): float(change["Elo Before"])
        for change in changes
    }
    first_bracket_side_by_player: dict[str, str] = {}
    for match in matches:
        if str(match.get("stage") or "") not in {"knockout", "bracket"}:
            continue
        bracket_side = str(match.get("bracket_side") or "")
        for player_key in ("player_1_id", "player_2_id"):
            first_bracket_side_by_player.setdefault(
                str(match[player_key]),
                bracket_side,
            )
    winners_bracket_entrants = {
        player_id
        for player_id, bracket_side in first_bracket_side_by_player.items()
        if bracket_side == "winners"
    }
    tables = []

    for group_index, group_id in enumerate(group_ids):
        matches_in_group = [
            match
            for match in group_matches
            if group_key(match) == group_id
        ]
        member_ids = list(
            dict.fromkeys(
                str(player_id)
                for match in matches_in_group
                for player_id in (
                    match["player_1_id"],
                    match["player_2_id"],
                )
            )
        )
        members = []
        for fallback_seed, player_id in enumerate(member_ids, start=1):
            participant = participants_by_id[player_id]
            members.append(
                {
                    "player_id": player_id,
                    "player": participant["player"],
                    "initial_seed": participant.get("seed") or fallback_seed,
                }
            )

        normalized_matches = []
        for match in matches_in_group:
            if match.get("winner_id") is None:
                status = "pending"
            elif match.get("walkover"):
                status = "forfeit"
            else:
                status = "completed"
            normalized_matches.append(
                {
                    **match,
                    "status": status,
                }
            )

        standings = calculate_group_standings(
            members,
            normalized_matches,
            elo_by_player_id,
        )["standings"]
        rows = []
        for standing in standings:
            game_difference = (
                int(standing["games_won"])
                - int(standing["games_lost"])
            )
            if game_difference > 0:
                difference_text = f"▲ +{game_difference}"
            elif game_difference < 0:
                difference_text = f"▼ {game_difference}"
            else:
                difference_text = "= 0"
            rows.append(
                [
                    f"#{int(standing['placement'])}",
                    str(standing["player"]),
                    f"{standing['sets_won']}–{standing['sets_lost']}",
                    f"{standing['games_won']}–{standing['games_lost']}",
                    difference_text,
                ]
            )

        tables.append(
            {
                "name": (
                    "Group Stage"
                    if len(group_ids) == 1
                    else f"Group {chr(65 + group_index)}"
                ),
                "rows": rows,
                "highlights": {
                    row_index: "winners"
                    for row_index, standing in enumerate(standings)
                    if str(standing["player_id"])
                    in winners_bracket_entrants
                },
            }
        )

    return tables


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
    st.markdown(
        _archived_tournament_selector_styles(),
        unsafe_allow_html=True,
    )
    with st.container(key="archived_tournament_selector"):
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
    group_tables = _archived_group_tables(
        matches,
        participants,
        changes,
    )
    group_phase_matches = [
        match
        for match in matches
        if str(match.get("stage") or "") in {"group", "group_stage"}
    ]
    bracket_phase_matches = [
        match
        for match in matches
        if match not in group_phase_matches
    ]

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

    st.markdown(
        _archived_tournament_header_html(
            tournament,
            participants,
            len(matches),
        ),
        unsafe_allow_html=True,
    )

    st.info(tournament_recap)

    tab_labels = []
    if group_tables:
        tab_labels.append("Group Stage")
    tab_labels.append("Bracket")
    tab_labels.extend(["Final Results", "Elo After Tournament"])
    tab_iterator = iter(st.tabs(tab_labels))
    tab_groups = next(tab_iterator) if group_tables else None
    tab_bracket = next(tab_iterator)
    tab_overview = next(tab_iterator)
    tab_elo = next(tab_iterator)

    if tab_groups is not None:
        with tab_groups:
            st.caption(
                "Highlighted players advanced to the Winners Bracket."
            )
            for table in group_tables:
                st.subheader(table["name"])
                st.markdown(
                    dashboard_table_html(
                        [
                            "Rank",
                            "Player",
                            "Set Record",
                            "Game Record",
                            "Game Diff",
                        ],
                        table["rows"],
                        columns=(
                            "minmax(4.5rem,0.5fr) minmax(10rem,1.5fr) "
                            "minmax(7rem,0.8fr) minmax(7rem,0.8fr) "
                            "minmax(6rem,0.7fr)"
                        ),
                        row_highlights=table["highlights"],
                        emphasis_column=1,
                    ),
                    unsafe_allow_html=True,
                )

            st.divider()
            st.subheader("Group Matches")
            st.markdown(
                dashboard_table_html(
                    ["Round", "Set", "Result", "Winner"],
                    _phase_match_table_rows(
                        group_phase_matches,
                        archived_bracket_matches,
                    ),
                    columns=(
                        "minmax(8rem,1fr) minmax(14rem,2fr) "
                        "minmax(5rem,0.6fr) minmax(8rem,1fr)"
                    ),
                    emphasis_column=1,
                ),
                unsafe_allow_html=True,
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

        if bracket_phase_matches:
            st.divider()
            st.subheader("Bracket Matches")
            st.markdown(
                dashboard_table_html(
                    ["Round", "Set", "Result", "Winner"],
                    _phase_match_table_rows(
                        bracket_phase_matches,
                        archived_bracket_matches,
                    ),
                    columns=(
                        "minmax(8rem,1fr) minmax(14rem,2fr) "
                        "minmax(5rem,0.6fr) minmax(8rem,1fr)"
                    ),
                    emphasis_column=1,
                ),
                unsafe_allow_html=True,
            )
        elif not matches:
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
            snapshot_rows, snapshot_highlights = _elo_snapshot_table_data(
                snapshot
            )
            st.markdown(
                _elo_ranking_expander_styles(),
                unsafe_allow_html=True,
            )
            with st.container(key="archived_elo_ranking"):
                with st.expander("Full Elo ranking after the tournament"):
                    st.markdown(
                        dashboard_table_html(
                            ["Rank", "Player", "Elo", "Tournament"],
                            snapshot_rows,
                            columns=(
                                "minmax(4.5rem,0.5fr) "
                                "minmax(10rem,1.5fr) "
                                "minmax(6rem,0.7fr) minmax(8rem,1fr)"
                            ),
                            row_highlights=snapshot_highlights,
                            emphasis_column=1,
                        ),
                        unsafe_allow_html=True,
                    )
        elif not changes:
            st.info("No Elo data is available for this tournament.")
