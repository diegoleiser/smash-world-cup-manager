"""Player profile page presentation and interaction."""

from __future__ import annotations

import html
from typing import Any, Callable

import altair as alt
import pandas as pd
import streamlit as st

import narratives


def player_initials(name: str) -> str:
    """Creates compact initials for the profile avatar."""

    parts = [part for part in name.replace("-", " ").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()

def render_player_page(
    include_inactive: bool,
    *,
    load_players: Callable[..., list[dict[str, Any]]],
    load_player_profile: Callable[..., dict[str, Any]],
    load_player_timeline: Callable[..., list[dict[str, Any]]],
    load_player_history: Callable[..., list[dict[str, Any]]],
    load_player_insights: Callable[..., dict[str, Any]],
    load_elo_ranking: Callable[..., list[dict[str, Any]]],
    format_ordinal: Callable[[int], str],
) -> None:
    st.title("👤 Player profile")

    requested_player_id = st.query_params.get(
        "player_id"
    )
    requested_player = st.query_params.get(
        "player"
    )
    players = load_players(include_inactive)
    if not include_inactive:
        requested_player_is_visible = any(
            str(player["player_id"]) == requested_player_id
            or str(player["display_name"]) == requested_player
            for player in players
        )
        if not requested_player_is_visible and (
            requested_player_id is not None
            or requested_player is not None
        ):
            requested_inactive_player = next(
                (
                    player
                    for player in load_players(True)
                    if (
                        str(player["player_id"]) == requested_player_id
                        or str(player["display_name"]) == requested_player
                    )
                ),
                None,
            )
            if requested_inactive_player is not None:
                players = sorted(
                    [*players, requested_inactive_player],
                    key=lambda player: str(
                        player["display_name"]
                    ).casefold(),
                )
    if not players:
        st.warning("No players found.")
        return

    player_by_name = {
        player["display_name"]: str(player["player_id"])
        for player in players
    }
    player_name_by_id = {
        str(player["player_id"]): str(player["display_name"])
        for player in players
    }

    player_names = list(
        player_by_name
    )

    if (
        requested_player_id in player_name_by_id
        and st.session_state.get("selected_player_name")
        != player_name_by_id[requested_player_id]
    ):
        st.session_state["selected_player_name"] = (
            player_name_by_id[requested_player_id]
        )
    elif (
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
        selected_player_name = st.session_state[
            "selected_player_name"
        ]
        st.query_params.clear()
        st.query_params["player_id"] = (
            player_by_name[selected_player_name]
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
                .sort_values(
                    ["tournament_date", "tournament_number"]
                )
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
                width="stretch",
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
                .sort_values(
                    ["tournament_date", "tournament_number"]
                )
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
                width="stretch",
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
