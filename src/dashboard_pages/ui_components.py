"""Shared visual helpers for dashboard components."""

from __future__ import annotations


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
