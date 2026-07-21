#!/usr/bin/env python3
"""Render double-elimination brackets as HTML for Streamlit."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from typing import Any

import streamlit.components.v1 as components


MATCH_CARD_WIDTH = 230
MATCH_CARD_HEIGHT = 108
ROUND_GAP = 70
MATCH_GAP = 28
MATCH_PITCH = MATCH_CARD_HEIGHT + MATCH_GAP


def _format_player_name(
    value: Any,
) -> str:
    """Return a safe player label for one bracket slot."""

    if value is None:
        return "TBD"

    cleaned = str(value).strip()

    if not cleaned:
        return "TBD"

    return cleaned


def _format_score(
    match: dict[str, Any],
    player_number: int,
) -> str:
    """Return the displayed score for one player."""

    score_key = (
        "player_1_score"
        if player_number == 1
        else "player_2_score"
    )

    score = match.get(score_key)

    if score is None:
        return ""

    return str(score)


def _get_status_label(
    status: str,
) -> str:
    """Return a readable label for one match status."""

    return {
        "waiting": "Waiting",
        "pending": "Ready",
        "completed": "Played",
        "forfeit": "W–L",
        "bye": "Bye",
        "cancelled": "Cancelled",
        "inactive": "Inactive",
    }.get(
        status,
        status.title(),
    )


def _render_player_row(
    *,
    player_name: str,
    score: str,
    is_winner: bool,
) -> str:
    """Render one player row inside a bracket card."""

    winner_class = " match-player-winner" if is_winner else ""

    safe_name = html.escape(player_name)
    safe_score = html.escape(score)

    return (
        f'<div class="match-player{winner_class}">'
        f'<span class="match-player-name">{safe_name}</span>'
        f'<span class="match-player-score">{safe_score}</span>'
        "</div>"
    )


def _render_match_card(
    match: dict[str, Any],
) -> str:
    """Render one bracket match card."""

    player_1_name = _format_player_name(
        match.get("player_1_name")
    )
    player_2_name = _format_player_name(
        match.get("player_2_name")
    )

    player_1_score = _format_score(
        match,
        1,
    )
    player_2_score = _format_score(
        match,
        2,
    )

    winner_id = (
        str(match["winner_id"])
        if match.get("winner_id") is not None
        else None
    )

    player_1_id = (
        str(match["player_1_id"])
        if match.get("player_1_id") is not None
        else None
    )

    player_2_id = (
        str(match["player_2_id"])
        if match.get("player_2_id") is not None
        else None
    )

    player_1_is_winner = (
        winner_id is not None
        and player_1_id == winner_id
    )

    player_2_is_winner = (
        winner_id is not None
        and player_2_id == winner_id
    )

    status = str(
        match.get("status") or "waiting"
    )

    safe_match_code = html.escape(
        str(match.get("match_code") or "")
    )

    safe_status = html.escape(
        _get_status_label(status)
    )

    return (
        f'<div class="match-card" '
        f'data-match-code="{safe_match_code}">'
        '<div class="match-header">'
        f'<span class="match-code">{safe_match_code}</span>'
        f'<span class="match-status match-status-{html.escape(status)}">'
        f"{safe_status}"
        "</span>"
        "</div>"
        + _render_player_row(
            player_name=player_1_name,
            score=player_1_score,
            is_winner=player_1_is_winner,
        )
        + _render_player_row(
            player_name=player_2_name,
            score=player_2_score,
            is_winner=player_2_is_winner,
        )
        + "</div>"
    )


def _group_matches_by_round(
    matches: list[dict[str, Any]],
) -> list[tuple[int, str, list[dict[str, Any]]]]:
    """Group and sort matches by round."""

    rounds: dict[
        tuple[int, str],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for match in matches:
        status = str(
            match.get("status") or ""
        )

        if status == "inactive":
            continue

        round_number = int(
            match.get("round_number") or 0
        )

        round_label = str(
            match.get("round_label") or f"Round {round_number}"
        )

        rounds[
            (
                round_number,
                round_label,
            )
        ].append(match)

    grouped_rounds = []

    for (
        round_number,
        round_label,
    ), round_matches in sorted(
        rounds.items(),
        key=lambda item: item[0][0],
    ):
        sorted_matches = sorted(
            round_matches,
            key=lambda match: int(
                match.get("match_number") or 0
            ),
        )

        grouped_rounds.append(
            (
                round_number,
                round_label,
                sorted_matches,
            )
        )

    return grouped_rounds


def _render_bracket_section(
    *,
    section_key: str,
    title: str,
    matches: list[dict[str, Any]],
) -> str:
    """Render one bracket side with vertically aligned rounds."""

    grouped_rounds = _group_matches_by_round(
        matches
    )

    if not grouped_rounds:
        return ""

    maximum_match_count = max(
        len(round_matches)
        for (
            _round_number,
            _round_label,
            round_matches,
        ) in grouped_rounds
    )

    round_area_height = (
        maximum_match_count
        * MATCH_PITCH
    )

    round_columns = []

    for (
        _round_number,
        round_label,
        round_matches,
    ) in grouped_rounds:
        match_count = len(round_matches)

        slot_span = (
            maximum_match_count
            / match_count
        )

        cards = []

        for match_index, match in enumerate(
            round_matches
        ):
            center_y = (
                (
                    match_index
                    + 0.5
                )
                * slot_span
                * MATCH_PITCH
            )

            top_position = (
                center_y
                - MATCH_CARD_HEIGHT / 2
            )

            cards.append(
                (
                    '<div class="match-wrapper" '
                    f'style="top: {top_position:.1f}px;">'
                    f"{_render_match_card(match)}"
                    "</div>"
                )
            )

        round_columns.append(
            '<div class="bracket-round">'
            f'<div class="round-title">{html.escape(round_label)}</div>'
            '<div class="round-matches" '
            f'style="height: {round_area_height}px;">'
            + "".join(cards)
            + "</div>"
            "</div>"
        )

    return (
        '<section class="bracket-section" '
        f'data-section-key="{html.escape(section_key)}">'
        f"<h2>{html.escape(title)}</h2>"
        '<div class="bracket-rounds">'
        + "".join(round_columns)
        + "</div>"
        "</section>"
    )


def build_bracket_html(
    matches: list[dict[str, Any]],
    routes: list[dict[str, Any]],
) -> str:
    """Build the complete bracket HTML document."""

    matches_by_side: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    match_side_by_code: dict[str, str] = {}

    for match in matches:
        bracket_side = str(
            match.get("bracket_side") or ""
        )
        match_code = str(
            match.get("match_code") or ""
        )

        matches_by_side[bracket_side].append(
            match
        )
        match_side_by_code[match_code] = (
            bracket_side
        )

    winners_html = _render_bracket_section(
        section_key="winners",
        title="Winners Bracket",
        matches=matches_by_side.get(
            "winners",
            [],
        ),
    )

    losers_html = _render_bracket_section(
        section_key="losers",
        title="Losers Bracket",
        matches=matches_by_side.get(
            "losers",
            [],
        ),
    )

    finals_html = _render_bracket_section(
        section_key="finals",
        title="Finals",
        matches=matches_by_side.get(
            "finals",
            [],
        ),
    )

    route_data = []

    for route in routes:
        source_code = str(
            route.get("source_code") or ""
        )
        target_code = str(
            route.get("target_code") or ""
        )

        source_side = match_side_by_code.get(
            source_code
        )
        target_side = match_side_by_code.get(
            target_code
        )

        route_data.append(
            {
                "sourceCode": source_code,
                "targetCode": target_code,
                "sourceOutcome": str(
                    route.get("source_outcome")
                    or ""
                ),
                "targetSlot": int(
                    route.get("target_slot")
                    or 1
                ),
                "sameSection": (
                    source_side == target_side
                ),
            }
        )

    existing_route_pairs = {
        (
            route["sourceCode"],
            route["targetCode"],
        )
        for route in route_data
    }

    if (
        "GF" in match_side_by_code
        and "GFR" in match_side_by_code
        and ("GF", "GFR") not in existing_route_pairs
    ):
        route_data.append(
            {
                "sourceCode": "GF",
                "targetCode": "GFR",
                "sourceOutcome": "winner",
                "targetSlot": 1,
                "sameSection": True,
            }
        )

    route_json = json.dumps(
        route_data,
        ensure_ascii=False,
    )

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">

        <style>
            * {{
                box-sizing: border-box;
            }}

            html,
            body {{
                margin: 0;
                padding: 0;
                background: transparent;
                font-family:
                    -apple-system,
                    BlinkMacSystemFont,
                    "Segoe UI",
                    sans-serif;
                color: #f1f3f5;
            }}

            .bracket-root {{
                overflow-x: auto;
                padding: 0.25rem 0 1rem 0;
            }}

            .bracket-canvas {{
                position: relative;
                display: flex;
                align-items: flex-start;
                gap: {ROUND_GAP}px;
                min-width: max-content;
            }}

            .bracket-main,
            .bracket-finals {{
                position: relative;
                z-index: 2;
                flex: 0 0 auto;
            }}

            .bracket-finals {{
                margin-top: 0;
            }}

            .global-bracket-lines {{
                position: absolute;
                z-index: 1;
                inset: 0;
                width: 100%;
                height: 100%;
                overflow: visible;
                pointer-events: none;
            }}

            .bracket-section {{
                position: relative;
                min-width: max-content;
                margin-bottom: 2.5rem;
            }}

            .bracket-section h2 {{
                position: relative;
                z-index: 3;
                margin: 0 0 0.85rem 0;
                font-size: 1.15rem;
                font-weight: 750;
            }}

            .bracket-rounds {{
                position: relative;
                z-index: 2;
                display: flex;
                align-items: flex-start;
                gap: {ROUND_GAP}px;
            }}

            .bracket-round {{
                width: {MATCH_CARD_WIDTH}px;
                flex: 0 0 {MATCH_CARD_WIDTH}px;
            }}

            .round-title {{
                min-height: 2rem;
                margin-bottom: 0.5rem;
                padding-bottom: 0.45rem;
                border-bottom:
                    1px solid rgba(255, 255, 255, 0.14);
                font-size: 0.85rem;
                font-weight: 700;
                opacity: 0.8;
            }}

            .round-matches {{
                position: relative;
            }}

            .match-wrapper {{
                position: absolute;
                left: 0;
                width: 100%;
            }}

            .match-card {{
                position: relative;
                height: {MATCH_CARD_HEIGHT}px;
                z-index: 3;
                overflow: hidden;
                border:
                    1px solid rgba(255, 255, 255, 0.18);
                border-radius: 0.65rem;
                background: #1b1f24;
                box-shadow:
                    0 1px 2px rgba(0, 0, 0, 0.25),
                    0 6px 18px rgba(0, 0, 0, 0.08);
            }}

            .match-header {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 0.75rem;
                padding: 0.42rem 0.65rem;
                border-bottom:
                    1px solid rgba(255, 255, 255, 0.10);
                background:
                    rgba(255, 255, 255, 0.035);
            }}

            .match-code {{
                font-size: 0.76rem;
                font-weight: 800;
                letter-spacing: 0.03em;
                opacity: 0.82;
            }}

            .match-status {{
                font-size: 0.68rem;
                font-weight: 750;
                opacity: 0.72;
            }}

            .match-status-pending {{
                color: #4ade80;
                opacity: 1;
            }}

            .match-status-completed,
            .match-status-forfeit {{
                color: #60a5fa;
                opacity: 1;
            }}

            .match-status-bye {{
                color: #c084fc;
                opacity: 1;
            }}

            .match-status-cancelled {{
                color: #f87171;
                opacity: 1;
            }}

            .match-player {{
                display: grid;
                grid-template-columns:
                    minmax(0, 1fr) auto;
                align-items: center;
                gap: 0.75rem;
                min-height: 2.25rem;
                padding: 0.5rem 0.65rem;
            }}

            .match-player + .match-player {{
                border-top:
                    1px solid rgba(255, 255, 255, 0.08);
            }}

            .match-player-name {{
                overflow: hidden;
                font-size: 0.88rem;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}

            .match-player-score {{
                min-width: 1rem;
                text-align: right;
                font-size: 0.9rem;
                font-weight: 800;
            }}

            .match-player-winner {{
                background:
                    rgba(34, 197, 94, 0.11);
            }}

            .match-player-winner
            .match-player-name {{
                font-weight: 750;
            }}

            .bracket-lines {{
                position: absolute;
                z-index: 1;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                overflow: visible;
                pointer-events: none;
            }}

            .bracket-line {{
                fill: none;
                stroke:
                    rgba(148, 163, 184, 0.7);
                stroke-width: 2;
                vector-effect:
                    non-scaling-stroke;
            }}

            .bracket-line-loser {{
                stroke:
                    rgba(248, 113, 113, 0.68);
                stroke-dasharray: 5 4;
            }}
        </style>
    </head>

    <body>
        <div class="bracket-root">
            <div class="bracket-canvas">
                <div class="bracket-main">
                    {winners_html}
                    {losers_html}
                </div>

                <div class="bracket-finals">
                    {finals_html}
                </div>

                <svg class="global-bracket-lines"></svg>
            </div>
        </div>

        <script>
            const routes = {route_json};

            function getCard(matchCode) {{
                return document.querySelector(
                    '.match-card[data-match-code="'
                    + CSS.escape(matchCode)
                    + '"]'
                );
            }}

            function ensureSvg(section) {{
                let svg = section.querySelector(
                    ':scope > .bracket-lines'
                );

                if (!svg) {{
                    svg = document.createElementNS(
                        'http://www.w3.org/2000/svg',
                        'svg'
                    );

                    svg.setAttribute(
                        'class',
                        'bracket-lines'
                    );

                    section.appendChild(svg);
                }}

                svg.innerHTML = '';

                const sectionRect =
                    section.getBoundingClientRect();

                svg.setAttribute(
                    'viewBox',
                    '0 0 '
                    + sectionRect.width
                    + ' '
                    + sectionRect.height
                );

                svg.setAttribute(
                    'width',
                    sectionRect.width
                );

                svg.setAttribute(
                    'height',
                    sectionRect.height
                );

                return svg;
            }}

            function drawRoute(
                svg,
                section,
                route,
                sourceCard,
                targetCard
            ) {{
                const sectionRect =
                    section.getBoundingClientRect();

                const sourceRect =
                    sourceCard.getBoundingClientRect();

                const targetRect =
                    targetCard.getBoundingClientRect();

                const startX =
                    sourceRect.right
                    - sectionRect.left;

                const startY =
                    sourceRect.top
                    - sectionRect.top
                    + sourceRect.height / 2;

                const endX =
                    targetRect.left
                    - sectionRect.left;

                const targetPlayerRows =
                    targetCard.querySelectorAll(
                        '.match-player'
                    );

                let endY =
                    targetRect.top
                    - sectionRect.top
                    + targetRect.height / 2;

                const targetRow =
                    targetPlayerRows[
                        route.targetSlot - 1
                    ];

                if (targetRow) {{
                    const rowRect =
                        targetRow.getBoundingClientRect();

                    endY =
                        rowRect.top
                        - sectionRect.top
                        + rowRect.height / 2;
                }}

                const middleX =
                    startX
                    + (endX - startX) / 2;

                const path =
                    document.createElementNS(
                        'http://www.w3.org/2000/svg',
                        'path'
                    );

                path.setAttribute(
                    'd',
                    [
                        'M', startX, startY,
                        'L', middleX, startY,
                        'L', middleX, endY,
                        'L', endX, endY,
                    ].join(' ')
                );

                const className =
                    route.sourceOutcome === 'loser'
                    ? 'bracket-line bracket-line-loser'
                    : 'bracket-line';

                path.setAttribute(
                    'class',
                    className
                );

                svg.appendChild(path);
            }}

            function alignFinalsPanel() {{
                const finalsPanel =
                    document.querySelector(
                        '.bracket-finals'
                    );

                const winnersFinal =
                    getCard('WF');

                const losersFinal =
                    getCard('LF');

                const grandFinal =
                    getCard('GF');

                if (
                    !finalsPanel
                    || !winnersFinal
                    || !losersFinal
                    || !grandFinal
                ) {{
                    return;
                }}

                finalsPanel.style.marginTop = '0px';

                const winnersRect =
                    winnersFinal.getBoundingClientRect();

                const losersRect =
                    losersFinal.getBoundingClientRect();

                const grandFinalRect =
                    grandFinal.getBoundingClientRect();

                const desiredCenterY =
                    (
                        winnersRect.top
                        + winnersRect.height / 2
                        + losersRect.top
                        + losersRect.height / 2
                    ) / 2;

                const currentCenterY =
                    grandFinalRect.top
                    + grandFinalRect.height / 2;

                const offset = Math.max(
                    0,
                    desiredCenterY - currentCenterY
                );

                finalsPanel.style.marginTop =
                    offset + 'px';
            }}

            function ensureGlobalSvg(canvas) {{
                const svg =
                    canvas.querySelector(
                        ':scope > .global-bracket-lines'
                    );

                if (!svg) {{
                    return null;
                }}

                svg.innerHTML = '';

                const width =
                    canvas.scrollWidth;

                const height =
                    canvas.scrollHeight;

                svg.setAttribute(
                    'viewBox',
                    '0 0 ' + width + ' ' + height
                );

                svg.setAttribute(
                    'width',
                    width
                );

                svg.setAttribute(
                    'height',
                    height
                );

                return svg;
            }}

            function drawCrossSectionRoute(
                svg,
                canvas,
                route,
                sourceCard,
                targetCard
            ) {{
                const canvasRect =
                    canvas.getBoundingClientRect();

                const sourceRect =
                    sourceCard.getBoundingClientRect();

                const targetRect =
                    targetCard.getBoundingClientRect();

                const startX =
                    sourceRect.right
                    - canvasRect.left;

                const startY =
                    sourceRect.top
                    - canvasRect.top
                    + sourceRect.height / 2;

                const endX =
                    targetRect.left
                    - canvasRect.left;

                const targetRows =
                    targetCard.querySelectorAll(
                        '.match-player'
                    );

                let endY =
                    targetRect.top
                    - canvasRect.top
                    + targetRect.height / 2;

                const targetRow =
                    targetRows[
                        route.targetSlot - 1
                    ];

                if (targetRow) {{
                    const rowRect =
                        targetRow.getBoundingClientRect();

                    endY =
                        rowRect.top
                        - canvasRect.top
                        + rowRect.height / 2;
                }}

                const middleX =
                    startX
                    + (endX - startX) / 2;

                const path =
                    document.createElementNS(
                        'http://www.w3.org/2000/svg',
                        'path'
                    );

                path.setAttribute(
                    'd',
                    [
                        'M', startX, startY,
                        'L', middleX, startY,
                        'L', middleX, endY,
                        'L', endX, endY,
                    ].join(' ')
                );

                path.setAttribute(
                    'class',
                    'bracket-line'
                );

                svg.appendChild(path);
            }}

            function drawBracketLines() {{
                alignFinalsPanel();

                const svgBySection = new Map();

                document
                    .querySelectorAll(
                        '.bracket-section'
                    )
                    .forEach((section) => {{
                        const svg = ensureSvg(section);

                        svgBySection.set(
                            section,
                            svg
                        );
                    }});

                routes.forEach((route) => {{
                    if (!route.sameSection) {{
                        return;
                    }}

                    const sourceCard =
                        getCard(route.sourceCode);

                    const targetCard =
                        getCard(route.targetCode);

                    if (
                        !sourceCard
                        || !targetCard
                    ) {{
                        return;
                    }}

                    const sourceSection =
                        sourceCard.closest(
                            '.bracket-section'
                        );

                    const targetSection =
                        targetCard.closest(
                            '.bracket-section'
                        );

                    if (
                        !sourceSection
                        || sourceSection
                        !== targetSection
                    ) {{
                        return;
                    }}

                    const svg =
                        svgBySection.get(
                            sourceSection
                        );

                    if (!svg) {{
                        return;
                    }}

                    drawRoute(
                        svg,
                        sourceSection,
                        route,
                        sourceCard,
                        targetCard
                    );
                }});

                const canvas =
                    document.querySelector(
                        '.bracket-canvas'
                    );

                if (!canvas) {{
                    return;
                }}

                const globalSvg =
                    ensureGlobalSvg(canvas);

                if (!globalSvg) {{
                    return;
                }}

                routes.forEach((route) => {{
                    if (route.sameSection) {{
                        return;
                    }}

                    const targetCard =
                        getCard(route.targetCode);

                    if (
                        !targetCard
                        || !targetCard.closest(
                            '[data-section-key="finals"]'
                        )
                    ) {{
                        return;
                    }}

                    const sourceCard =
                        getCard(route.sourceCode);

                    if (!sourceCard) {{
                        return;
                    }}

                    drawCrossSectionRoute(
                        globalSvg,
                        canvas,
                        route,
                        sourceCard,
                        targetCard
                    );
                }});
            }}

            window.addEventListener(
                'load',
                () => {{
                    requestAnimationFrame(
                        drawBracketLines
                    );
                }}
            );

            window.addEventListener(
                'resize',
                () => {{
                    requestAnimationFrame(
                        drawBracketLines
                    );
                }}
            );
        </script>
    </body>
    </html>
    """

def render_bracket(
    matches: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    *,
    height: int = 950,
) -> None:
    """Render the bracket inside Streamlit."""

    bracket_html = build_bracket_html(
        matches,
        routes,
    )

    components.html(
        bracket_html,
        height=height,
        scrolling=True,
    )