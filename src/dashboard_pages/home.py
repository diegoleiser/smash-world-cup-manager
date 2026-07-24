"""Home page presentation, rankings, and archive overview."""

from __future__ import annotations

import html
from typing import Any, Callable
from urllib.parse import quote

import altair as alt
import pandas as pd
import streamlit as st

import narratives
from dashboard_pages.timeline_order import (
    chronological_tournament_labels,
)


def render_home(
    include_inactive: bool,
    *,
    load_tournament_preview_data: Callable[..., dict[str, Any]],
    load_elo_ranking: Callable[..., list[dict[str, Any]]],
    load_player_timeline: Callable[..., list[dict[str, Any]]],
    load_tournaments: Callable[..., list[dict[str, Any]]],
    load_database_quality: Callable[..., dict[str, Any]],
) -> None:
    st.title("🎮 Smash World Championship")
    st.caption(
        "Current ranking and overview of the private "
        "World Championship archive"
    )

    quality = load_database_quality()

    st.subheader("📊 Archive Summary")

    archive_summary_html = (
        "<div class='archive-summary-grid' style='"
        "display:grid;"
        "grid-template-columns:repeat(4, 1fr);"
        "align-items:stretch;"
        "border:1px solid rgba(128,128,128,0.32);"
        "border-radius:0.8rem;"
        "overflow:hidden;"
        "'>"

        "<div class='archive-summary-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "align-items:center;"
        "justify-content:center;"
        "min-height:9rem;"
        "padding:1rem;"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:750;"
        "opacity:0.65;"
        "letter-spacing:0.04em;"
        "min-height:1.2rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        "TOURNAMENTS"
        "</div>"
        "<div style='"
        "font-size:2.35rem;"
        "font-weight:800;"
        "line-height:1;"
        "margin-top:0.65rem;"
        "min-height:2.5rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        f"{quality['tournaments']}"
        "</div>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:650;"
        "opacity:0.62;"
        "margin-top:0.55rem;"
        "min-height:1.1rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "white-space:nowrap;"
        "'>"
        "Archived events"
        "</div>"
        "</div>"

        "<div class='archive-summary-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "align-items:center;"
        "justify-content:center;"
        "min-height:9rem;"
        "padding:1rem;"
        "border-left:1px solid rgba(128,128,128,0.22);"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:750;"
        "opacity:0.65;"
        "letter-spacing:0.04em;"
        "min-height:1.2rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        "PLAYERS"
        "</div>"
        "<div style='"
        "font-size:2.35rem;"
        "font-weight:800;"
        "line-height:1;"
        "margin-top:0.65rem;"
        "min-height:2.5rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        f"{quality['players']}"
        "</div>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:650;"
        "opacity:0.62;"
        "margin-top:0.55rem;"
        "min-height:1.1rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "white-space:nowrap;"
        "'>"
        f"{quality['active_players']} active"
        "</div>"
        "</div>"

        "<div class='archive-summary-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "align-items:center;"
        "justify-content:center;"
        "min-height:9rem;"
        "padding:1rem;"
        "border-left:1px solid rgba(128,128,128,0.22);"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:750;"
        "opacity:0.65;"
        "letter-spacing:0.04em;"
        "min-height:1.2rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        "SETS"
        "</div>"
        "<div style='"
        "font-size:2.35rem;"
        "font-weight:800;"
        "line-height:1;"
        "margin-top:0.65rem;"
        "min-height:2.5rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        f"{quality['matches']}"
        "</div>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:650;"
        "opacity:0.62;"
        "margin-top:0.55rem;"
        "min-height:1.1rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "white-space:nowrap;"
        "'>"
        "Archived sets"
        "</div>"
        "</div>"

        "<div class='archive-summary-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "align-items:center;"
        "justify-content:center;"
        "min-height:9rem;"
        "padding:1rem;"
        "border-left:1px solid rgba(128,128,128,0.22);"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:750;"
        "opacity:0.65;"
        "letter-spacing:0.04em;"
        "min-height:1.2rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        "CHAMPIONS"
        "</div>"
        "<div style='"
        "font-size:2.35rem;"
        "font-weight:800;"
        "line-height:1;"
        "margin-top:0.65rem;"
        "min-height:2.5rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "'>"
        f"{quality['champions']}"
        "</div>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:650;"
        "opacity:0.62;"
        "margin-top:0.55rem;"
        "min-height:1.1rem;"
        "display:flex;"
        "align-items:center;"
        "justify-content:center;"
        "white-space:nowrap;"
        "'>"
        "Different winners"
        "</div>"
        "</div>"

        "</div>"
    )

    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            .archive-summary-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            }

            .archive-summary-card {
                min-width: 0;
            }

            .archive-summary-card:nth-child(3) {
                border-left: none !important;
                border-top: 1px solid rgba(128,128,128,0.22);
            }

            .archive-summary-card:nth-child(4) {
                border-top: 1px solid rgba(128,128,128,0.22);
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        archive_summary_html,
        unsafe_allow_html=True,
    )

    ranking = load_elo_ranking(
        include_inactive
    )

    if not ranking:
        st.warning(
            "No rated Elo matches found yet."
        )
        return

    leader = ranking[0]

    tournaments = load_tournaments()

    current_champion = (
        tournaments[0]["Winner"]
        if tournaments
        else "–"
    )

    latest_tournament = (
        tournaments[0]["WM"]
        if tournaments
        else "–"
    )

    if tournaments:
        title_counts = (
            pd.DataFrame(tournaments)["Winner"]
            .value_counts()
        )

        most_titles_player = str(
            title_counts.index[0]
        )

        most_titles_count = int(
            title_counts.iloc[0]
        )
    else:
        most_titles_player = "–"
        most_titles_count = 0

    st.divider()
    st.subheader("Current Overview")

    title_label = (
        "Title"
        if most_titles_count == 1
        else "Titles"
    )

    current_overview_html = (
       "<div class='current-overview-grid' style='"
        "display:grid;"
        "grid-template-columns:repeat(3, minmax(0, 1fr));"
        "gap:1rem;"
        "'>"

        "<div class='current-overview-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "min-height:10rem;"
        "padding:1.2rem 1.35rem;"
        "border:1px solid rgba(128,128,128,0.32);"
        "border-radius:0.8rem;"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:700;"
        "opacity:0.65;"
        "letter-spacing:0.03em;"
        "'>"
        "CURRENT NO. 1"
        "</div>"
        "<div style='"
        "font-size:1.9rem;"
        "font-weight:800;"
        "margin-top:1.25rem;"
        "line-height:1.15;"
        "'>"
        f"{html.escape(str(leader['player']))}"
        "</div>"
        "<div style='"
        "font-size:0.95rem;"
        "font-weight:700;"
        "margin-top:auto;"
        "padding-top:1rem;"
        "'>"
        f"#{leader['rank']} · {leader['elo']:.1f} Elo"
        "</div>"
        "</div>"

        "<div class='current-overview-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "min-height:10rem;"
        "padding:1.2rem 1.35rem;"
        "border:1px solid rgba(128,128,128,0.32);"
        "border-radius:0.8rem;"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:700;"
        "opacity:0.65;"
        "letter-spacing:0.03em;"
        "'>"
        "CURRENT CHAMPION"
        "</div>"
        "<div style='"
        "font-size:1.9rem;"
        "font-weight:800;"
        "margin-top:1.25rem;"
        "line-height:1.15;"
        "'>"
        f"{html.escape(str(current_champion))}"
        "</div>"
        "<div style='"
        "font-size:0.95rem;"
        "font-weight:700;"
        "margin-top:auto;"
        "padding-top:1rem;"
        "'>"
        f"Winner of {html.escape(str(latest_tournament))}"
        "</div>"
        "</div>"

        "<div class='current-overview-card' style='"
        "display:flex;"
        "flex-direction:column;"
        "min-height:10rem;"
        "padding:1.2rem 1.35rem;"
        "border:1px solid rgba(128,128,128,0.32);"
        "border-radius:0.8rem;"
        "'>"
        "<div style='"
        "font-size:0.82rem;"
        "font-weight:700;"
        "opacity:0.65;"
        "letter-spacing:0.03em;"
        "'>"
        "MOST TITLES"
        "</div>"
        "<div style='"
        "font-size:1.9rem;"
        "font-weight:800;"
        "margin-top:1.25rem;"
        "line-height:1.15;"
        "'>"
        f"{html.escape(str(most_titles_player))}"
        "</div>"
        "<div style='"
        "font-size:0.95rem;"
        "font-weight:700;"
        "margin-top:auto;"
        "padding-top:1rem;"
        "'>"
        f"{most_titles_count} {title_label}"
        "</div>"
        "</div>"

        "</div>"
    )

    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            .current-overview-grid {
                grid-template-columns: 1fr !important;
            }

            .current-overview-card {
                min-width: 0;
            }

            .current-overview-card > div {
                overflow-wrap: normal;
                word-break: normal;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        current_overview_html,
        unsafe_allow_html=True,
    )

    preview_data = load_tournament_preview_data()

    preview_text = narratives.generate_tournament_preview(
        preview_data,
    )

    preview_ranking = preview_data.get("ranking") or []
    featured_rivalry = preview_data.get("featured_rivalry")

    favorite = (
        preview_ranking[0]
        if preview_ranking
        else None
    )

    main_challenger = (
        preview_ranking[1]
        if len(preview_ranking) >= 2
        else None
    )

    if favorite:
        favorite_name = str(
            favorite.get("player") or "–"
        )
        favorite_detail = (
            f"#{favorite.get('rank', '–')} · "
            f"{float(favorite.get('elo') or 1000.0):.1f} Elo"
        )
    else:
        favorite_name = "–"
        favorite_detail = "No ranking available"

    if main_challenger:
        challenger_name = str(
            main_challenger.get("player") or "–"
        )
        challenger_detail = (
            f"#{main_challenger.get('rank', '–')} · "
            f"{float(main_challenger.get('elo') or 1000.0):.1f} Elo"
        )
    else:
        challenger_name = "–"
        challenger_detail = "No challenger available"

    if featured_rivalry:
        rivalry_name = (
            f"{featured_rivalry['player_a']} vs "
            f"{featured_rivalry['player_b']}"
        )

        rivalry_detail = (
            f"{featured_rivalry['wins_a']}–"
            f"{featured_rivalry['wins_b']} all-time"
        )
    else:
        rivalry_name = "–"
        rivalry_detail = "No featured rivalry"

    st.divider()
    st.subheader("🔮 Next Tournament Preview")

    preview_cards_html = (
        "<style>"
        ".preview-card-grid {"
        "display:grid;"
        "grid-template-columns:repeat(3, minmax(0, 1fr));"
        "gap:1rem;"
        "margin-top:0;"
        "}"
        ".preview-card {"
        "display:flex;"
        "flex-direction:column;"
        "min-height:7.5rem;"
        "padding:1rem 1.15rem;"
        "border:1px solid rgba(128,128,128,0.30);"
        "border-radius:0.8rem;"
        "}"
        ".preview-card-label {"
        "font-size:0.78rem;"
        "font-weight:750;"
        "opacity:0.62;"
        "letter-spacing:0.04em;"
        "}"
        ".preview-card-value {"
        "font-size:1.45rem;"
        "font-weight:800;"
        "line-height:1.15;"
        "margin-top:0.8rem;"
        "}"
        ".preview-card-detail {"
        "font-size:0.9rem;"
        "font-weight:650;"
        "opacity:0.68;"
        "margin-top:auto;"
        "padding-top:0.8rem;"
        "}"
        "@media (max-width:800px) {"
        ".preview-card-grid {"
        "grid-template-columns:1fr;"
        "}"
        "}"
        "</style>"

        "<div class='preview-card-grid'>"

        "<div class='preview-card'>"
        "<div class='preview-card-label'>"
        "ELO FAVORITE"
        "</div>"
        "<div class='preview-card-value'>"
        f"{html.escape(favorite_name)}"
        "</div>"
        "<div class='preview-card-detail'>"
        f"{html.escape(favorite_detail)}"
        "</div>"
        "</div>"

        "<div class='preview-card'>"
        "<div class='preview-card-label'>"
        "MAIN CHALLENGER"
        "</div>"
        "<div class='preview-card-value'>"
        f"{html.escape(challenger_name)}"
        "</div>"
        "<div class='preview-card-detail'>"
        f"{html.escape(challenger_detail)}"
        "</div>"
        "</div>"

        "<div class='preview-card'>"
        "<div class='preview-card-label'>"
        "FEATURED RIVALRY"
        "</div>"
        "<div class='preview-card-value'>"
        f"{html.escape(rivalry_name)}"
        "</div>"
        "<div class='preview-card-detail'>"
        f"{html.escape(rivalry_detail)}"
        "</div>"
        "</div>"

        "</div>"
    )

    preview_sentences = [
        sentence.strip()
        for sentence in preview_text.split(". ")
        if sentence.strip()
    ]

    preview_paragraphs: list[str] = []

    for index in range(
        0,
        len(preview_sentences),
        2,
    ):
        paragraph_sentences = (
            preview_sentences[index:index + 2]
        )

        paragraph = ". ".join(
            paragraph_sentences
        )

        if not paragraph.endswith("."):
            paragraph += "."

        preview_paragraphs.append(
            (
                "<p style='"
                "margin:0 0 0.9rem 0;"
                "'>"
                f"{html.escape(paragraph)}"
                "</p>"
            )
        )

    preview_text_html = "".join(
        preview_paragraphs
    )

    st.markdown(
        (
            "<style>"
            ".tournament-outlook {"
            "display:grid;"
            "grid-template-columns:9rem minmax(0, 1fr);"
            "gap:2rem;"
            "align-items:start;"
            "padding:1.5rem 1.7rem;"
            "border-radius:0.8rem;"
            "background:rgba(28,74,112,0.55);"
            "border:1px solid rgba(70,150,220,0.18);"
            "}"
            ".tournament-outlook-label {"
            "font-size:0.78rem;"
            "font-weight:750;"
            "letter-spacing:0.04em;"
            "opacity:0.72;"
            "padding-top:0.15rem;"
            "}"
            ".tournament-outlook-text {"
            "font-size:1rem;"
            "line-height:1.75;"
            "}"
            ".tournament-outlook-text p:last-child {"
            "margin-bottom:0 !important;"
            "}"
            "@media (max-width:800px) {"
            ".tournament-outlook {"
            "grid-template-columns:1fr;"
            "gap:0.75rem;"
            "padding:1.25rem 1.4rem;"
            "}"
            "}"
            "</style>"

            "<div class='tournament-outlook'>"
            "<div class='tournament-outlook-label'>"
            "TOURNAMENT<br>OUTLOOK"
            "</div>"
            "<div class='tournament-outlook-text'>"
            f"{preview_text_html}"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        (
            "<div style='"
            "margin-top:1.6rem;"
            "margin-bottom:0.75rem;"
            "font-size:1.35rem;"
            "font-weight:800;"
            "'>"
            "Preview Highlights"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        preview_cards_html,
        unsafe_allow_html=True,
    )

    st.divider()
    st.subheader("Current Elo Ranking")

    leader_elo = float(ranking[0]["elo"])

    ranking_rows_html: list[str] = []

    rank_icons = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
    }

    for entry in ranking:
        rank = int(entry["rank"])
        player_name = str(entry["player"])
        player_profile_url = (
            "?page=Players&player="
            f"{quote(player_name)}"
        )
        elo = float(entry["elo"])
        rated_sets = int(entry["rated_matches"])
        active = bool(entry["active"])

        rank_display = (
            f"{rank_icons.get(rank, '')} #{rank}".strip()
        )

        elo_gap = leader_elo - elo

        if rank == 1:
            gap_text = "Leader"
            gap_color = "#3fb950"
        else:
            gap_text = f"−{elo_gap:.1f}"
            gap_color = "rgba(255,255,255,0.58)"

        status_text = (
            "Active"
            if active
            else "Inactive"
        )

        status_color = (
            "#3fb950"
            if active
            else "rgba(255,255,255,0.45)"
        )

        top_rank_style = (
            "background:rgba(34,197,94,0.07);"
            if rank == 1
            else ""
        )

        ranking_rows_html.append(
            (
                "<div class='elo-ranking-row' "
                f"style='{top_rank_style}'>"

                "<div class='elo-ranking-rank'>"
                f"{html.escape(rank_display)}"
                "</div>"

                "<div class='elo-ranking-player'>"
                "<a class='elo-ranking-player-link' "
                f"href='{html.escape(player_profile_url)}' "
                "target='_self'>"
                f"{html.escape(player_name)}"
                "</a>"
                "</div>"

                "<div class='elo-ranking-value'>"
                f"{elo:.1f} Elo"
                "</div>"

                "<div class='elo-ranking-gap' "
                f"style='color:{gap_color};'>"
                f"{html.escape(gap_text)}"
                "</div>"

                "<div class='elo-ranking-sets'>"
                f"{rated_sets} sets"
                "</div>"

                "<div class='elo-ranking-status' "
                f"style='color:{status_color};'>"
                f"{status_text}"
                "</div>"

                "</div>"
            )
        )

    ranking_list_html = (
        "<style>"
        ".elo-ranking-list {"
        "border:1px solid rgba(128,128,128,0.30);"
        "border-radius:0.8rem;"
        "overflow:hidden;"
        "}"

        ".elo-ranking-row {"
        "display:grid;"
        "grid-template-columns:5.5rem minmax(8rem,2fr) "
        "minmax(7rem,1fr) minmax(5rem,0.8fr) "
        "minmax(5rem,0.8fr) minmax(5rem,0.8fr);"
        "align-items:center;"
        "min-height:4.2rem;"
        "padding:0.7rem 1rem;"
        "border-bottom:1px solid rgba(128,128,128,0.20);"
        "gap:0.75rem;"
        "}"

        ".elo-ranking-row:last-child {"
        "border-bottom:none;"
        "}"

        ".elo-ranking-rank {"
        "font-weight:800;"
        "text-align:right;"
        "}"

        ".elo-ranking-player {"
        "font-size:1.1rem;"
        "font-weight:800;"
        "}"

        ".elo-ranking-player-link,"
        ".elo-ranking-player-link:link,"
        ".elo-ranking-player-link:visited,"
        ".elo-ranking-player-link:hover,"
        ".elo-ranking-player-link:active,"
        ".elo-ranking-player-link:focus {"
        "color:inherit !important;"
        "text-decoration:none !important;"
        "}"

        ".elo-ranking-player-link {"
        "display:inline-block;"
        "font-weight:800;"
        "transition:opacity 0.15s ease, transform 0.15s ease;"
        "}"

        ".elo-ranking-player-link:hover {"
        "opacity:0.72;"
        "transform:translateX(3px);"
        "}"

        ".elo-ranking-player-link:focus {"
        "outline:none;"
        "}"

        ".elo-ranking-value {"
        "font-weight:750;"
        "text-align:right;"
        "}"

        ".elo-ranking-gap,"
        ".elo-ranking-sets,"
        ".elo-ranking-status {"
        "font-size:0.88rem;"
        "font-weight:700;"
        "text-align:center;"
        "}"

        "@media (max-width:768px) {"

        ".elo-ranking-row {"
        "grid-template-columns:var(--mobile-table-columns);"
        "gap:var(--mobile-table-gap);"
        "padding:var(--mobile-table-padding);"
        "min-height:var(--mobile-table-height);"
        "}"

        ".elo-ranking-rank {"
        "padding-right:1.9rem;"
        "white-space:nowrap;"
        "}"

        ".elo-ranking-gap,"
        ".elo-ranking-sets,"
        ".elo-ranking-status {"
        "display:none;"
        "}"

        "}"
        "</style>"

        "<div class='elo-ranking-list'>"
        f"{''.join(ranking_rows_html)}"
        "</div>"
    )

    st.markdown(
        ranking_list_html,
        unsafe_allow_html=True,
    )

    st.markdown(
        (
            "<div style='"
            "margin-top:2rem;"
            "margin-bottom:0.75rem;"
            "font-size:1.5rem;"
            "font-weight:800;"
            "'>"
            "Elo History"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    elo_history_rows: list[dict[str, Any]] = []

    for entry in ranking:
        player_id = str(entry["player_id"])
        player_name = str(entry["player"])

        timeline = load_player_timeline(
            player_id
        )

        for timeline_entry in timeline:
            elo_history_rows.append(
                {
                    **timeline_entry,
                    "Players": player_name,
                }
            )

    if elo_history_rows:
        elo_history_df = pd.DataFrame(
            elo_history_rows
        ).sort_values(
            [
                "Players",
                "tournament_date",
                "tournament_number",
            ]
        )

        tournament_order = chronological_tournament_labels(
            elo_history_rows
        )

        segment_rows: list[dict[str, Any]] = []

        for player_name, player_rows in elo_history_df.groupby(
            "Players",
            sort=False,
        ):
            ordered_rows = (
                player_rows
                .sort_values("tournament_number")
                .to_dict("records")
            )

            for previous, current in zip(
                ordered_rows,
                ordered_rows[1:],
            ):
                segment_rows.append(
                    {
                        "Players": player_name,
                        "start_tournament": previous["tournament"],
                        "end_tournament": current["tournament"],
                        "start_elo": previous["elo"],
                        "end_elo": current["elo"],
                        "segment_type": (
                            "Played"
                            if bool(current["played_in_tournament"])
                            else "Did not participate"
                        ),
                    }
                )

        segment_df = pd.DataFrame(segment_rows)

        player_hover = alt.selection_point(
            fields=["Players"],
            on="pointerover",
            empty=True,
            clear="pointerout",
        )

        solid_segments = (
            alt.Chart(
                segment_df[
                    segment_df["segment_type"] == "Played"
                ]
            )
            .mark_rule(
                strokeWidth=2,
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
                color=alt.Color(
                    "Players:N",
                    title=None,
                    legend=alt.Legend(
                        orient="right",
                        symbolType="circle",
                        symbolSize=100,
                    ),
                ),
                opacity=alt.condition(
                    player_hover,
                    alt.value(1.0),
                    alt.value(0.12),
                ),
                size=alt.condition(
                    player_hover,
                    alt.value(3.2),
                    alt.value(1.4),
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
                strokeDash=[6, 4],
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
                color=alt.Color(
                    "Players:N",
                    title=None,
                ),
                opacity=alt.condition(
                    player_hover,
                    alt.value(1.0),
                    alt.value(0.12),
                ),
                size=alt.condition(
                    player_hover,
                    alt.value(3.2),
                    alt.value(1.4),
                ),
            )
        )

        played_points = (
            alt.Chart(
                elo_history_df[
                    elo_history_df["played_in_tournament"]
                ]
            )
            .mark_point(
                filled=True,
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
                color=alt.Color(
                    "Players:N",
                    legend=None,
                ),
                opacity=alt.condition(
                    player_hover,
                    alt.value(1.0),
                    alt.value(0.12),
                ),
                size=alt.condition(
                    player_hover,
                    alt.value(90),
                    alt.value(45),
                ),
                tooltip=[
                    alt.Tooltip(
                        "Players:N",
                        title="Player",
                    ),
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

        missed_points = (
            alt.Chart(
                elo_history_df[
                    ~elo_history_df["played_in_tournament"]
                ]
            )
            .mark_point(
                filled=False,
                strokeWidth=2.5,
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
                color=alt.Color(
                    "Players:N",
                    legend=None,
                ),
                opacity=alt.condition(
                    player_hover,
                    alt.value(1.0),
                    alt.value(0.12),
                ),
                size=alt.condition(
                    player_hover,
                    alt.value(90),
                    alt.value(45),
                ),
                tooltip=[
                    alt.Tooltip(
                        "Players:N",
                        title="Player",
                    ),
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

        solid_hover_targets = (
            alt.Chart(
                segment_df[
                    segment_df["segment_type"] == "Played"
                ]
            )
            .mark_rule(
                strokeWidth=14,
                opacity=0.001,
            )
            .encode(
                x=alt.X(
                    "start_tournament:N",
                    sort=tournament_order,
                ),
                x2="end_tournament:N",
                y=alt.Y(
                    "start_elo:Q",
                    scale=alt.Scale(
                        zero=False,
                    ),
                ),
                y2="end_elo:Q",
                detail="Players:N",
            )
        )

        dashed_hover_targets = (
            alt.Chart(
                segment_df[
                    segment_df["segment_type"]
                    == "Did not participate"
                ]
            )
            .mark_rule(
                strokeWidth=14,
                opacity=0.001,
            )
            .encode(
                x=alt.X(
                    "start_tournament:N",
                    sort=tournament_order,
                ),
                x2="end_tournament:N",
                y=alt.Y(
                    "start_elo:Q",
                    scale=alt.Scale(
                        zero=False,
                    ),
                ),
                y2="end_elo:Q",
                detail="Players:N",
            )
        )

        hover_targets = (
            solid_hover_targets
            + dashed_hover_targets
        ).add_params(
            player_hover
        )

        elo_history_chart = (
            solid_segments
            + dashed_segments
            + hover_targets
            + played_points
            + missed_points
        ).properties(
            height=560,
        )

        st.altair_chart(
            elo_history_chart,
            use_container_width=True,
        )

        st.caption(
            "Dashed segments and hollow points indicate tournaments "
            "in which the player did not participate."
        )

    else:
        st.info(
            "No Elo history is available yet."
        )

    st.divider()
    st.subheader(
        "🏆 Tournament Overview"
    )

    if tournaments:
        tournament_df = pd.DataFrame(
            [
                {
                    "Tournament": (
                        f"World Championship "
                        f"{int(tournament['WM'].split()[1]):02d}"
                    ),
                    "Date": tournament["Date"],
                    "Champion": tournament["Winner"],
                    "Players": (
                        tournament["Participants"]
                        if tournament["Participants"] > 0
                        else None
                    ),
                }
                for tournament in tournaments
            ]
        )

        tournament_rows_html: list[str] = []

        for _, row in tournament_df.iterrows():
            tournament_name = str(row["Tournament"])
            champion = str(row["Champion"])

            raw_date = row["Date"]

            if pd.notna(raw_date):
                formatted_date = pd.to_datetime(
                    raw_date
                ).strftime("%d %b %Y")
            else:
                formatted_date = "–"

            players_value = row["Players"]

            if pd.isna(players_value):
                players_text = "–"
            else:
                players_text = str(
                    int(players_value)
                )

            tournament_rows_html.append(
                (
                    "<div class='tournament-overview-row'>"

                    "<div class='tournament-overview-name'>"
                    f"{html.escape(tournament_name)}"
                    "</div>"

                    "<div class='tournament-overview-date'>"
                    f"{html.escape(formatted_date)}"
                    "</div>"

                    "<div class='tournament-overview-champion'>"
                    f"{html.escape(champion)}"
                    "</div>"

                    "<div class='tournament-overview-players'>"
                    f"{html.escape(players_text)}"
                    "</div>"

                    "</div>"
                )
            )

        tournament_overview_html = (
            "<style>"

            ".tournament-overview-list {"
            "width:100%;"
            "border:1px solid rgba(128,128,128,0.30);"
            "border-radius:0.8rem;"
            "overflow:hidden;"
            "}"

            ".tournament-overview-header,"
            ".tournament-overview-row {"
            "display:grid;"
            "grid-template-columns:minmax(15rem,1.4fr) "
            "minmax(10rem,0.9fr) "
            "minmax(12rem,1.2fr) "
            "minmax(5rem,0.45fr);"
            "align-items:center;"
            "gap:0.75rem;"
            "padding:0.7rem 1rem;"
            "}"

            ".tournament-overview-header {"
            "min-height:3.2rem;"
            "background:rgba(128,128,128,0.08);"
            "border-bottom:1px solid rgba(128,128,128,0.24);"
            "font-size:0.78rem;"
            "font-weight:750;"
            "letter-spacing:0.04em;"
            "opacity:0.68;"
            "text-transform:uppercase;"
            "}"

            ".tournament-overview-row {"
            "min-height:4.2rem;"
            "border-bottom:1px solid rgba(128,128,128,0.20);"
            "}"
            "border:1px solid rgba(128,128,128,0.30);"
            "border-radius:0.8rem;"
            "overflow:hidden;"
            "}"

            ".tournament-overview-header,"
            ".tournament-overview-row {"
            "display:grid;"
            "grid-template-columns:7rem 10rem minmax(12rem,18rem) 5rem;"
            "align-items:center;"
            "gap:1.25rem;"
            "padding:0.75rem 1rem;"
            "}"

            ".tournament-overview-header {"
            "min-height:3rem;"
            "background:rgba(128,128,128,0.08);"
            "border-bottom:1px solid rgba(128,128,128,0.24);"
            "font-size:0.78rem;"
            "font-weight:750;"
            "letter-spacing:0.04em;"
            "opacity:0.68;"
            "text-transform:uppercase;"
            "}"

            ".tournament-overview-row {"
            "min-height:3.6rem;"
            "border-bottom:1px solid rgba(128,128,128,0.20);"
            "}"

            ".tournament-overview-row:last-child {"
            "border-bottom:none;"
            "}"

            ".tournament-overview-name {"
            "font-size:1.1rem;"
            "font-weight:800;"
            "}"

            ".tournament-overview-date {"
            "font-size:0.88rem;"
            "font-weight:700;"
            "opacity:0.68;"
            "}"

            ".tournament-overview-champion {"
            "font-size:1.1rem;"
            "font-weight:800;"
            "}"

            ".tournament-overview-players {"
            "font-weight:750;"
            "text-align:right;"
            "}"
            ".tournament-overview-header-players {"
            "text-align:right;"
            "}"

            "@media (max-width:768px) {"

            ".tournament-overview-header,"
            ".tournament-overview-row {"
            "grid-template-columns:var(--mobile-table-columns);"
            "gap:var(--mobile-table-gap);"
            "padding:var(--mobile-table-padding);"
            "min-height:var(--mobile-table-height);"
            "}"

            ".tournament-overview-date,"
            ".tournament-overview-header-date {"
            "display:none;"
            "}"

            ".tournament-overview-header-name {"
            "white-space:nowrap;"
            "}"

            ".tournament-overview-name {"
            "font-size:0.95rem;"
            "}"

            ".tournament-overview-champion,"
            ".tournament-overview-header-champion {"
            "text-align:center;"
            "}"

            ".tournament-overview-champion {"
            "font-size:0.98rem;"
            "min-width:0;"
            "overflow:hidden;"
            "text-overflow:ellipsis;"
            "white-space:nowrap;"
            "}"

            ".tournament-overview-players,"
            ".tournament-overview-header-players {"
            "text-align:right;"
            "}"

            "}"

            "</style>"

            "<div class='tournament-overview-list'>"

            "<div class='tournament-overview-header'>"
            "<div class='tournament-overview-header-name'>"
            "Tournament"
            "</div>"
            "<div class='tournament-overview-header-date'>"
            "Date"
            "</div>"
            "<div class='tournament-overview-header-champion'>"
            "Champion"
            "</div>"
            "<div class='tournament-overview-header-players'>"
            "Players"
            "</div>"
            "</div>"

            f"{''.join(tournament_rows_html)}"

            "</div>"
        )

        st.markdown(
            tournament_overview_html,
            unsafe_allow_html=True,
        )

        st.markdown(
            (
                "<div style='"
                "margin-top:2rem;"
                "margin-bottom:0.75rem;"
                "font-size:1.5rem;"
                "font-weight:800;"
                "'>"
                "Title Leaders"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        title_counts = (
            tournament_df["Champion"]
            .value_counts()
            .rename_axis("Player")
            .reset_index(name="Titles")
        )

        title_counts["Rank"] = (
            title_counts["Titles"]
            .rank(
                method="min",
                ascending=False,
            )
            .astype(int)
        )

        title_rows_html: list[str] = []

        title_icons = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        for _, row in title_counts.iterrows():
            rank = int(row["Rank"])
            player = str(row["Player"])
            titles = int(row["Titles"])

            title_label = (
                "Title"
                if titles == 1
                else "Titles"
            )

            rank_text = (
                f"{title_icons.get(rank, '')} #{rank}".strip()
            )

            title_rows_html.append(
                (
                    "<div class='title-leader-row'>"
                    "<div class='title-leader-rank'>"
                    f"{html.escape(rank_text)}"
                    "</div>"
                    "<div class='title-leader-player'>"
                    f"{html.escape(player)}"
                    "</div>"
                    "<div class='title-leader-count'>"
                    f"{titles} {title_label}"
                    "</div>"
                    "</div>"
                )
            )

        title_leaders_html = (
            "<style>"

            ".title-leader-list {"
            "border:1px solid rgba(128,128,128,0.30);"
            "border-radius:0.8rem;"
            "overflow:hidden;"
            "}"

            ".title-leader-row {"
            "display:grid;"
            "grid-template-columns:5.5rem minmax(8rem,2fr) "
            "minmax(7rem,1fr);"
            "align-items:center;"
            "min-height:4.2rem;"
            "padding:0.7rem 1rem;"
            "border-bottom:1px solid rgba(128,128,128,0.20);"
            "gap:0.75rem;"
            "}"

            ".title-leader-row:last-child {"
            "border-bottom:none;"
            "}"

            ".title-leader-rank {"
            "font-weight:800;"
            "text-align:right;"
            "}"

            ".title-leader-player {"
            "font-size:1.1rem;"
            "font-weight:800;"
            "}"

            ".title-leader-count {"
            "font-weight:750;"
            "text-align:right;"
            "}"

            "@media (max-width:768px) {"

            ".title-leader-row {"
            "grid-template-columns:var(--mobile-table-columns);"
            "gap:var(--mobile-table-gap);"
            "padding:var(--mobile-table-padding);"
            "min-height:var(--mobile-table-height);"
            "}"

            ".title-leader-rank {"
            "padding-right:1.9rem;"
            "white-space:nowrap;"
            "}"

            "}"

            "</style>"

            "<div class='title-leader-list'>"
            f"{''.join(title_rows_html)}"
            "</div>"
        )

        st.markdown(
            title_leaders_html,
            unsafe_allow_html=True,
        )

    else:
        st.info(
            "No tournaments are available yet."
        )
