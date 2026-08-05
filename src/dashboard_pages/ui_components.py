"""Shared visual helpers for dashboard components."""

from __future__ import annotations

import html


def mobile_seeding_styles() -> str:
    """Keep seeding controls in one compact row on narrow screens."""

    return """
    <style>
    div[class*="st-key-mobile_seeding_row_"] {
        max-width: 46rem;
        padding: 0.28rem 0;
        border-bottom: 1px solid rgba(128, 128, 128, 0.18);
    }
    div[class*="st-key-mobile_seeding_row_"]
    [data-testid="stHorizontalBlock"] {
        display: grid !important;
        grid-template-columns: 3.5rem minmax(10rem, 1fr) 2.4rem 2.4rem;
        gap: 0.55rem !important;
        align-items: center;
    }
    div[class*="st-key-mobile_seeding_row_"]
    [data-testid="stColumn"] {
        width: auto !important;
        min-width: 0 !important;
    }
    div[class*="st-key-mobile_seeding_row_"]
    [data-testid="stMarkdownContainer"] p {
        margin: 0;
    }
    div[class*="st-key-mobile_seeding_row_"] .stButton button {
        width: 2.4rem;
        min-height: 2.25rem;
        padding: 0;
    }
    @media (max-width: 700px) {
        div[class*="st-key-mobile_seeding_row_"] {
            max-width: none;
        }
        div[class*="st-key-mobile_seeding_row_"]
        [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: 2.5rem minmax(0, 1fr) 2.4rem 2.4rem;
            gap: 0.4rem !important;
            align-items: center;
        }
    }
    </style>
    """


def internal_dashboard_link(
    label: str,
    href: str,
    *,
    class_name: str = "control-table-link",
) -> str:
    """Return an escaped same-app link for custom dashboard markup."""

    link_text = str(href)
    if not (
        link_text.startswith("?")
        or (link_text.startswith("/") and not link_text.startswith("//"))
    ):
        raise ValueError("Dashboard links must use internal URLs.")
    return (
        f'<a class="{html.escape(class_name, quote=True)}" '
        f'href="{html.escape(link_text, quote=True)}" target="_self">'
        f"{html.escape(str(label))}</a>"
    )


def archived_match_result_html(
    context_label: str,
    player_1_name: str,
    player_2_name: str,
    score_text: str,
    *,
    winner_name: str | None,
    status_label: str,
) -> str:
    """Return a compact read-only result card for an archived set."""

    player_1_color = (
        "rgb(74, 222, 128)"
        if winner_name == player_1_name
        else "rgb(250, 250, 250)"
    )
    player_2_color = (
        "rgb(74, 222, 128)"
        if winner_name == player_2_name
        else "rgb(250, 250, 250)"
    )
    return (
        '<div style="overflow:hidden;'
        'border:1px solid rgba(128,128,128,0.30);'
        'border-radius:0.8rem;">'
        '<div style="padding:0.7rem 1rem;'
        'border-bottom:1px solid rgba(128,128,128,0.24);'
        'background:rgba(128,128,128,0.08);'
        'color:rgba(250,250,250,0.58);'
        'font-size:0.75rem;font-weight:750;'
        'letter-spacing:0.035em;text-align:center;'
        'text-transform:uppercase;">'
        f"{html.escape(context_label)}"
        "</div>"
        '<div style="display:grid;'
        'grid-template-columns:1fr auto 1fr;'
        'align-items:center;gap:1rem;'
        'min-height:6.2rem;padding:1rem 1.25rem;">'
        '<div style="text-align:right;font-size:1.65rem;'
        f'font-weight:800;color:{player_1_color};">'
        f"{html.escape(player_1_name)}"
        "</div>"
        '<div style="font-size:1.6rem;font-weight:850;'
        'color:rgb(250,250,250);">'
        f"{html.escape(score_text)}"
        "</div>"
        '<div style="text-align:left;font-size:1.65rem;'
        f'font-weight:800;color:{player_2_color};">'
        f"{html.escape(player_2_name)}"
        "</div>"
        "</div>"
        '<div style="display:grid;grid-template-columns:1fr 1fr;'
        'gap:1rem;padding:0.75rem 1rem;'
        'border-top:1px solid rgba(128,128,128,0.20);'
        'background:rgba(255,255,255,0.018);'
        'color:rgba(250,250,250,0.66);font-size:0.82rem;">'
        '<div style="text-align:left;">Winner · '
        f"<strong>{html.escape(winner_name or 'Unknown')}</strong>"
        "</div>"
        '<div style="text-align:right;">Status · '
        f"<strong>{html.escape(status_label)}</strong>"
        "</div>"
        "</div></div>"
    )


def up_next_matchup_html(
    context_label: str,
    player_1_name: str,
    player_2_name: str,
    *,
    player_1_probability: float | None = None,
) -> str:
    """Return the shared live-control header for the next playable set."""

    probability_content = (
        '<div style="text-align:right;">'
        f"{player_1_probability:.1%} win chance"
        '</div><div style="text-align:left;">'
        f"{1.0 - player_1_probability:.1%} win chance"
        "</div>"
        if player_1_probability is not None
        else ""
    )
    probability_html = (
        '<div style="display:grid;grid-template-columns:1fr 1fr;'
        'gap:2rem;margin:0.45rem 0 0.1rem;opacity:0.65;'
        'font-size:0.82rem;min-height:1.25rem;">'
        f"{probability_content}"
        "</div>"
    )
    return (
        '<div style="text-align:center;opacity:0.68;'
        'font-size:0.9rem;font-weight:600;'
        'margin:0.1rem 0 0.45rem;">'
        f"{html.escape(context_label)}"
        "</div>"
        '<div style="display:grid;'
        'grid-template-columns:1fr auto 1fr;'
        'align-items:center;gap:1rem;'
        'padding:0.1rem 0 0.2rem;">'
        '<div style="text-align:right;font-size:2.15rem;'
        'font-weight:800;line-height:1.1;">'
        f"{html.escape(player_1_name)}"
        "</div>"
        '<div style="opacity:0.55;font-size:0.9rem;'
        'font-weight:700;">VS</div>'
        '<div style="text-align:left;font-size:2.15rem;'
        'font-weight:800;line-height:1.1;">'
        f"{html.escape(player_2_name)}"
        "</div></div>"
        f"{probability_html}"
    )


def compact_score_input_styles(
    key_prefix: str,
    *,
    separate_stepper_buttons: bool = False,
) -> str:
    """Return shared styles for compact score number inputs."""

    selector = f'[class*="st-key-{key_prefix}"]'
    stepper_separators = (
        f"""
    {selector} div[data-baseweb="input"] button:first-of-type {{
        border-right: 1px solid rgba(128, 128, 128, 0.28);
    }}
    {selector} div[data-baseweb="input"] button:last-of-type {{
        border-left: 1px solid rgba(128, 128, 128, 0.28);
    }}
    """
        if separate_stepper_buttons
        else ""
    )
    return f"""
    <style>
    {selector} div[data-baseweb="input"] {{
        min-height: 3.55rem;
        overflow: hidden;
        border: 1px solid rgba(128, 128, 128, 0.42);
        border-radius: 0.65rem;
        background: rgba(255, 255, 255, 0.025);
        box-shadow:
            0 1px 2px rgba(0, 0, 0, 0.25),
            0 6px 18px rgba(0, 0, 0, 0.08);
        transition:
            border-color 0.15s ease,
            box-shadow 0.15s ease;
    }}
    {selector} div[data-baseweb="input"]:focus-within {{
        border-color: var(--primary-color, rgb(255, 75, 75));
        box-shadow:
            0 0 0 2px rgba(96, 165, 250, 0.22),
            0 8px 24px rgba(59, 130, 246, 0.18);
    }}
    {selector} input {{
        padding: 0 !important;
        color: rgb(250, 250, 250) !important;
        font-size: 1.55rem !important;
        font-weight: 800 !important;
        text-align: center !important;
    }}
    {selector} div[data-baseweb="input"] button {{
        width: 3.25rem;
        min-width: 3.25rem;
        border-radius: 0;
        color: rgba(250, 250, 250, 0.68);
        transition:
            background-color 0.15s ease,
            color 0.15s ease;
    }}
    {selector} div[data-baseweb="input"] button:hover {{
        background: rgba(59, 130, 246, 0.12);
        color: rgb(250, 250, 250);
    }}
    {stepper_separators}
    {selector} label p {{
        color: rgba(250, 250, 250, 0.68);
        font-size: 0.82rem;
        font-weight: 650;
    }}
    </style>
    """


def dashboard_table_html(
    headers: list[str],
    rows: list[list[str]],
    *,
    columns: str,
    row_highlights: dict[int, str] | None = None,
    emphasis_column: int | None = None,
    cell_links: dict[tuple[int, int], str] | None = None,
    mobile_cards: bool = False,
    mobile_visible_rows: int | None = None,
    mobile_summary: str = "Show all",
    mobile_card_variant: str | None = None,
) -> str:
    """Return markup for a compact table in the dashboard visual language."""

    row_highlights = row_highlights or {}
    cell_links = cell_links or {}
    header_html = "".join(
        f"<div>{html.escape(header)}</div>" for header in headers
    )
    row_html = []
    for row_index, row in enumerate(rows):
        cells = []
        for column_index, value in enumerate(row):
            value_text = str(value)
            emphasis_class = (
                " control-table-emphasis"
                if column_index == emphasis_column
                else ""
            )
            movement_class = (
                " control-table-positive"
                if value_text.startswith("▲")
                else (
                    " control-table-negative"
                    if value_text.startswith("▼")
                    else ""
                )
            )
            cell_content = html.escape(value_text)
            cell_link = cell_links.get((row_index, column_index))
            if cell_link is not None:
                link_text = str(cell_link)
                if not (
                    link_text.startswith("?")
                    or (
                        link_text.startswith("/")
                        and not link_text.startswith("//")
                    )
                ):
                    raise ValueError(
                        "Dashboard table links must be internal query URLs."
                    )
                cell_content = internal_dashboard_link(value_text, link_text)
            cells.append(
                f'<div class="control-table-cell{emphasis_class}'
                f'{movement_class}" '
                f'data-label="{html.escape(headers[column_index], quote=True)}">'
                f"{cell_content}</div>"
            )
        highlight = row_highlights.get(row_index)
        highlight_class = (
            f" control-table-row-{highlight}" if highlight else ""
        )
        collapsed_class = (
            " control-table-mobile-collapsed"
            if mobile_visible_rows is not None
            and row_index >= mobile_visible_rows
            else ""
        )
        row_html.append(
            f'<div class="control-table-row{highlight_class}'
            f'{collapsed_class}">'
            f"{''.join(cells)}</div>"
        )

    if mobile_visible_rows is not None and mobile_visible_rows < 1:
        raise ValueError("Mobile visible rows must be positive.")
    if mobile_card_variant not in {
        None,
        "ranking",
        "tournament",
        "titles",
        "match-history",
        "standings",
        "tournament-match",
        "final-standings",
        "elo-change",
        "elo-ranking",
    }:
        raise ValueError("Unknown mobile card variant.")
    hidden_mobile_rows = (
        row_html[mobile_visible_rows:]
        if mobile_cards
        and mobile_visible_rows is not None
        and len(row_html) > mobile_visible_rows
        else []
    )
    mobile_more_html = (
        '<details class="control-table-mobile-more">'
        "<summary>"
        '<span class="control-table-show-more">'
        f"{html.escape(mobile_summary)}"
        "</span>"
        '<span class="control-table-show-less">Show less</span>'
        "</summary>"
        '<div class="control-table-mobile-more-rows">'
        f"{''.join(hidden_mobile_rows)}"
        "</div></details>"
        if hidden_mobile_rows
        else ""
    )
    table_classes = "control-table"
    if mobile_cards:
        table_classes += " control-table-mobile-cards"
    if mobile_card_variant:
        table_classes += f" control-table-mobile-{mobile_card_variant}"

    return (
        """
        <style>
        .control-table {
            overflow: hidden;
            border: 1px solid rgba(128, 128, 128, 0.30);
            border-radius: 0.8rem;
        }
        .control-table-header,
        .control-table-row {
            display: grid;
            grid-template-columns: var(--control-table-columns);
            align-items: center;
            gap: 0.8rem;
            padding: 0.7rem 1rem;
        }
        .control-table-header {
            min-height: 2.6rem;
            border-bottom: 1px solid rgba(128, 128, 128, 0.24);
            background: rgba(128, 128, 128, 0.08);
            color: rgba(250, 250, 250, 0.55);
            font-size: 0.72rem;
            font-weight: 750;
            letter-spacing: 0.035em;
            text-transform: uppercase;
        }
        .control-table-row {
            min-height: 3.65rem;
            border-bottom: 1px solid rgba(128, 128, 128, 0.20);
            transition: background-color 0.15s ease;
        }
        .control-table-row:last-child {
            border-bottom: none;
        }
        .control-table-row:hover {
            background: rgba(128, 128, 128, 0.055);
        }
        .control-table-row-winners {
            background: rgba(34, 197, 94, 0.07);
        }
        .control-table-row-losers {
            background: rgba(245, 158, 11, 0.07);
        }
        .control-table-row-participated {
            background: rgba(59, 130, 246, 0.055);
            box-shadow: inset 3px 0 rgba(96, 165, 250, 0.48);
        }
        .control-table-cell {
            min-width: 0;
            overflow: hidden;
            color: rgba(250, 250, 250, 0.76);
            font-size: 0.88rem;
            font-weight: 650;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .control-table-emphasis {
            color: rgb(250, 250, 250);
            font-size: 1.02rem;
            font-weight: 800;
        }
        .control-table-link,
        .control-table-link:link,
        .control-table-link:visited {
            color: inherit !important;
            font-weight: inherit;
            text-decoration: none !important;
        }
        .control-table-link {
            display: inline-block;
            transition: opacity 0.15s ease, transform 0.15s ease;
        }
        .control-table-link:hover {
            opacity: 0.72;
            transform: translateX(3px);
        }
        .control-table-link:focus-visible {
            border-radius: 0.25rem;
            outline: 2px solid var(--primary-color, rgb(255, 75, 75));
            outline-offset: 3px;
        }
        .control-table-positive {
            color: rgb(74, 222, 128);
        }
        .control-table-negative {
            color: rgb(248, 113, 113);
        }
        @media (max-width: 900px) {
            .control-table-scroll {
                overflow-x: auto;
            }
            .control-table {
                min-width: 46rem;
            }
        }
        @media (max-width: 700px) {
            .control-table-mobile-cards {
                min-width: 0;
                overflow: visible;
                border: none;
                border-radius: 0;
            }
            .control-table-mobile-cards .control-table-header {
                display: none;
            }
            .control-table-mobile-cards .control-table-row {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.75rem 1rem;
                min-height: 0;
                margin-bottom: 0.75rem;
                padding: 0.9rem 1rem;
                border: 1px solid rgba(128, 128, 128, 0.30);
                border-radius: 0.8rem;
                background: rgba(255, 255, 255, 0.018);
            }
            .control-table-mobile-cards .control-table-row-winners {
                background: rgba(34, 197, 94, 0.07);
                box-shadow: inset 3px 0 rgba(74, 222, 128, 0.42);
            }
            .control-table-mobile-cards .control-table-row:last-child {
                margin-bottom: 0;
                border-bottom: 1px solid rgba(128, 128, 128, 0.30);
            }
            .control-table-mobile-cards .control-table-cell {
                display: flex;
                flex-direction: column;
                gap: 0.18rem;
                overflow: visible;
                font-size: 0.9rem;
                text-overflow: clip;
                white-space: normal;
            }
            .control-table-mobile-cards .control-table-cell::before {
                content: attr(data-label);
                color: rgba(250, 250, 250, 0.52);
                font-size: 0.72rem;
                font-weight: 750;
                letter-spacing: 0.035em;
                text-transform: uppercase;
            }
            .control-table-mobile-cards .control-table-emphasis {
                grid-column: 1 / -1;
                font-size: 1.12rem;
            }
            .control-table-mobile-cards > .control-table-mobile-collapsed {
                display: none;
            }
            .control-table-mobile-more {
                margin-top: 0.15rem;
            }
            .control-table-mobile-more summary {
                padding: 0.9rem 1rem;
                border: 1px solid rgba(128, 128, 128, 0.30);
                border-radius: 0.8rem;
                background: rgba(128, 128, 128, 0.055);
                color: rgba(250, 250, 250, 0.82);
                font-size: 0.86rem;
                font-weight: 750;
                cursor: pointer;
            }
            .control-table-mobile-more[open] summary {
                order: 2;
                margin-top: 0.15rem;
            }
            .control-table-mobile-more[open] {
                display: flex;
                flex-direction: column;
            }
            .control-table-mobile-more-rows {
                padding: 0;
            }
            .control-table-show-less {
                display: none;
            }
            .control-table-mobile-more[open]
            .control-table-show-more {
                display: none;
            }
            .control-table-mobile-more[open]
            .control-table-show-less {
                display: inline;
            }
            .control-table-mobile-more-rows .control-table-row {
                display: grid;
            }
            .control-table-mobile-ranking .control-table-row {
                grid-template-columns: 3.4rem repeat(3, minmax(0, 1fr));
                grid-template-rows: auto auto;
                gap: 0.85rem 0.75rem;
                padding: 1rem;
            }
            .control-table-mobile-ranking
            .control-table-cell[data-label="Rank"] {
                order: 1;
                grid-column: 1 / 2;
                grid-row: 1 / 3;
                justify-content: center;
                color: rgba(250, 250, 250, 0.78);
                font-size: 1.15rem;
                font-weight: 800;
            }
            .control-table-mobile-ranking
            .control-table-cell[data-label="Status"] {
                order: 2;
                grid-column: 4 / 5;
                grid-row: 1 / 2;
                align-items: flex-end;
                color: rgba(250, 250, 250, 0.68);
                font-size: 0.9rem;
                text-align: right;
            }
            .control-table-mobile-ranking
            .control-table-cell[data-label="Player"] {
                order: 3;
                grid-column: 2 / 4;
                grid-row: 1 / 2;
                padding: 0;
                font-size: 1.4rem;
                line-height: 1.15;
            }
            .control-table-mobile-ranking
            .control-table-cell[data-label="Elo"] {
                order: 4;
                grid-column: 2 / 3;
                grid-row: 2 / 3;
            }
            .control-table-mobile-ranking
            .control-table-cell[data-label="Gap"] {
                order: 5;
                grid-column: 3 / 4;
                grid-row: 2 / 3;
            }
            .control-table-mobile-ranking
            .control-table-cell[data-label="Sets"] {
                order: 6;
                grid-column: 4 / 5;
                grid-row: 2 / 3;
            }
            .control-table-mobile-ranking
            .control-table-cell[data-label="Elo"],
            .control-table-mobile-ranking
            .control-table-cell[data-label="Gap"],
            .control-table-mobile-ranking
            .control-table-cell[data-label="Sets"] {
                font-size: 1.08rem;
                font-weight: 800;
            }
            .control-table-mobile-tournament .control-table-row {
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 0.9rem 0.75rem;
                padding: 1rem;
            }
            .control-table-mobile-tournament
            .control-table-cell[data-label="Tournament"] {
                order: 1;
                grid-column: 1 / 3;
                font-size: 1.18rem;
                line-height: 1.2;
            }
            .control-table-mobile-tournament
            .control-table-cell[data-label="Date"] {
                order: 2;
                grid-column: 3 / 4;
                align-items: flex-end;
                text-align: right;
            }
            .control-table-mobile-tournament
            .control-table-cell[data-label="Champion"] {
                order: 3;
                grid-column: 1 / 3;
                font-size: 1.02rem;
                font-weight: 800;
            }
            .control-table-mobile-tournament
            .control-table-cell[data-label="Players"] {
                order: 4;
                grid-column: 3 / 4;
                align-items: flex-end;
                font-size: 1.02rem;
                font-weight: 800;
                text-align: right;
            }
            .control-table-mobile-titles .control-table-row {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.8rem 1rem;
                padding: 1rem;
            }
            .control-table-mobile-titles
            .control-table-cell[data-label="Rank"] {
                order: 1;
                color: rgba(250, 250, 250, 0.68);
                font-size: 0.9rem;
            }
            .control-table-mobile-titles
            .control-table-cell[data-label="Titles"] {
                order: 2;
                align-items: flex-end;
                color: #f2c94c;
                font-size: 1.02rem;
                font-weight: 800;
                text-align: right;
            }
            .control-table-mobile-titles
            .control-table-cell[data-label="Player"] {
                order: 3;
                grid-column: 1 / -1;
                padding-top: 0.1rem;
                font-size: 1.35rem;
                line-height: 1.15;
            }
            .control-table-mobile-match-history .control-table-row {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                grid-template-rows: auto auto auto;
                gap: 0.65rem 1rem;
                padding: 0.9rem 1rem;
            }
            .control-table-mobile-match-history
            .control-table-cell[data-label="Tournament"] {
                order: 1;
                grid-column: 1 / 2;
                grid-row: 1 / 2;
                font-size: 1.15rem;
                font-weight: 800;
            }
            .control-table-mobile-match-history
            .control-table-cell[data-label="Date"] {
                order: 2;
                grid-column: 2 / 3;
                grid-row: 1 / 2;
                align-items: flex-end;
                text-align: right;
            }
            .control-table-mobile-match-history
            .control-table-cell[data-label="Round"] {
                order: 3;
                grid-column: 1 / -1;
                grid-row: 2 / 3;
                padding: 0.05rem 0;
                font-size: 1rem;
                font-weight: 750;
            }
            .control-table-mobile-match-history
            .control-table-cell[data-label="Winner"] {
                order: 4;
                grid-column: 1 / 2;
                grid-row: 3 / 4;
                font-size: 1.05rem;
                font-weight: 800;
            }
            .control-table-mobile-match-history
            .control-table-cell[data-label="Result"] {
                order: 5;
                grid-column: 2 / 3;
                grid-row: 3 / 4;
                align-items: flex-end;
                font-size: 1.05rem;
                font-weight: 800;
                text-align: right;
            }
            .control-table-mobile-standings .control-table-row {
                grid-template-columns: 3.4rem repeat(2, minmax(0, 1fr));
                grid-template-rows: auto auto;
                gap: 0.8rem 0.75rem;
                padding: 0.95rem 1rem;
            }
            .control-table-mobile-standings
            .control-table-cell[data-label="Rank"] {
                order: 1;
                grid-column: 1 / 2;
                grid-row: 1 / 3;
                justify-content: center;
                color: rgba(250, 250, 250, 0.78);
                font-size: 1.1rem;
                font-weight: 800;
            }
            .control-table-mobile-standings
            .control-table-cell[data-label="Player"] {
                order: 2;
                grid-column: 2 / -1;
                grid-row: 1 / 2;
                font-size: 1.3rem;
                line-height: 1.15;
            }
            .control-table-mobile-standings
            .control-table-cell[data-label="Set Record"] {
                order: 3;
                grid-column: 2 / 3;
                grid-row: 2 / 3;
            }
            .control-table-mobile-standings
            .control-table-cell[data-label="Game Record"] {
                order: 4;
                grid-column: 3 / 4;
                grid-row: 2 / 3;
            }
            .control-table-mobile-standings
            .control-table-cell[data-label="Set Record"],
            .control-table-mobile-standings
            .control-table-cell[data-label="Game Record"] {
                font-size: 1rem;
                font-weight: 800;
            }
            .control-table-mobile-tournament-match .control-table-row {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                grid-template-rows: auto auto auto;
                gap: 0.65rem 1rem;
                padding: 0.9rem 1rem;
            }
            .control-table-mobile-tournament-match
            .control-table-cell[data-label="Round"] {
                order: 1;
                grid-column: 1 / 2;
                grid-row: 1 / 2;
            }
            .control-table-mobile-tournament-match
            .control-table-cell[data-label="Result"] {
                order: 2;
                grid-column: 2 / 3;
                grid-row: 1 / 2;
                align-items: flex-end;
                font-size: 1.3rem;
                font-weight: 800;
                text-align: right;
            }
            .control-table-mobile-tournament-match
            .control-table-cell[data-label="Set"] {
                order: 3;
                grid-column: 1 / -1;
                grid-row: 2 / 3;
                padding: 0.05rem 0;
                font-size: 1.2rem;
                line-height: 1.2;
            }
            .control-table-mobile-tournament-match
            .control-table-cell[data-label="Winner"] {
                order: 4;
                grid-column: 1 / -1;
                grid-row: 3 / 4;
                font-size: 1rem;
                font-weight: 800;
            }
            .control-table-mobile-final-standings .control-table-row {
                grid-template-columns: 4.2rem repeat(2, minmax(0, 1fr));
                grid-template-rows: auto auto;
                gap: 0.8rem 0.75rem;
                padding: 0.95rem 1rem;
            }
            .control-table-mobile-final-standings
            .control-table-cell[data-label="Placement"] {
                order: 1;
                grid-column: 1 / 2;
                grid-row: 1 / 3;
                justify-content: center;
                font-size: 1.05rem;
                font-weight: 800;
            }
            .control-table-mobile-final-standings
            .control-table-cell[data-label="Player"] {
                order: 2;
                grid-column: 2 / -1;
                grid-row: 1 / 2;
                font-size: 1.3rem;
            }
            .control-table-mobile-final-standings
            .control-table-cell[data-label="Initial Seed"] {
                order: 3;
                grid-column: 2 / 3;
                grid-row: 2 / 3;
            }
            .control-table-mobile-final-standings
            .control-table-cell[data-label="Seed Change"] {
                order: 4;
                grid-column: 3 / 4;
                grid-row: 2 / 3;
            }
            .control-table-mobile-elo-change .control-table-row {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                grid-template-rows: auto auto;
                gap: 0.8rem 1rem;
                padding: 0.95rem 1rem;
            }
            .control-table-mobile-elo-change
            .control-table-cell[data-label="Player"] {
                order: 1;
                grid-column: 1 / 2;
                grid-row: 1 / 2;
                font-size: 1.25rem;
            }
            .control-table-mobile-elo-change
            .control-table-cell[data-label="Change"] {
                order: 2;
                grid-column: 2 / 3;
                grid-row: 1 / 2;
                align-items: flex-end;
                font-size: 1.15rem;
                font-weight: 800;
                text-align: right;
            }
            .control-table-mobile-elo-change
            .control-table-cell[data-label="Elo Before → After"] {
                order: 3;
                grid-column: 1 / 2;
                grid-row: 2 / 3;
            }
            .control-table-mobile-elo-change
            .control-table-cell[data-label="Rank"] {
                order: 4;
                grid-column: 2 / 3;
                grid-row: 2 / 3;
                align-items: flex-end;
                text-align:right;
            }
            .control-table-mobile-elo-ranking .control-table-row {
                grid-template-columns: 3.4rem repeat(2, minmax(0, 1fr));
                grid-template-rows: auto auto;
                gap: 0.8rem 0.75rem;
                padding: 0.95rem 1rem;
            }
            .control-table-mobile-elo-ranking
            .control-table-cell[data-label="Rank"] {
                order:1;
                grid-column:1 / 2;
                grid-row:1 / 3;
                justify-content:center;
                font-size:1.05rem;
                font-weight:800;
            }
            .control-table-mobile-elo-ranking
            .control-table-cell[data-label="Player"] {
                order:2;
                grid-column:2 / -1;
                grid-row:1 / 2;
                font-size:1.25rem;
            }
            .control-table-mobile-elo-ranking
            .control-table-cell[data-label="Elo"] {
                order:3;
                grid-column:2 / 3;
                grid-row:2 / 3;
                font-size:1rem;
                font-weight:800;
            }
            .control-table-mobile-elo-ranking
            .control-table-cell[data-label="Tournament"] {
                order:4;
                grid-column:3 / 4;
                grid-row:2 / 3;
                align-items:flex-end;
                text-align:right;
            }
        }
        @media (min-width: 701px) {
            .control-table-mobile-more {
                display: none;
            }
        }
        </style>
        """
        '<div class="control-table-scroll">'
        f'<div class="{table_classes}" '
        f'style="--control-table-columns:{html.escape(columns)};">'
        f'<div class="control-table-header">{header_html}</div>'
        f"{''.join(row_html)}"
        f"{mobile_more_html}"
        "</div></div>"
    )


def clickable_card_button_styles(
    key_prefix: str,
    *,
    title_font_size: str = "1.25rem",
    show_focus_ring: bool = False,
) -> str:
    """Return shared styles for Streamlit buttons presented as cards."""

    selector = f'[class*="st-key-{key_prefix}"]'
    focus_shadow = (
        "0 0 0 2px rgba(96, 165, 250, 0.22),\n"
        "            0 8px 24px rgba(59, 130, 246, 0.18)"
        if show_focus_ring
        else (
            "0 2px 5px rgba(0, 0, 0, 0.32),\n"
            "            0 8px 24px rgba(59, 130, 246, 0.18)"
        )
    )
    return f"""
    <style>
    {selector} button {{
        min-height: 4.35rem;
        padding: 0.65rem 0.9rem;
        text-align: left;
        transition:
            border-color 0.15s ease,
            box-shadow 0.15s ease,
            transform 0.15s ease;
    }}
    {selector} button:hover {{
        border-color: var(--primary-color, rgb(255, 75, 75));
        box-shadow:
            0 2px 5px rgba(0, 0, 0, 0.32),
            0 8px 24px rgba(59, 130, 246, 0.18);
        transform: translateY(-1px);
    }}
    {selector} button:focus-visible {{
        border-color: var(--primary-color, rgb(255, 75, 75));
        box-shadow:
            {focus_shadow};
        transform: translateY(-1px);
    }}
    {selector} button p {{
        width: 100%;
        color: rgba(250, 250, 250, 0.58);
        font-size: 0.78rem;
        line-height: 1.25;
        text-align: left;
    }}
    {selector} button strong {{
        display: block;
        margin-bottom: 0.2rem;
        color: rgb(250, 250, 250);
        font-size: {title_font_size};
        line-height: 1.2;
    }}
    </style>
    """
