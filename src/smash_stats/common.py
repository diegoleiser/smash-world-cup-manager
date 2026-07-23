"""Small calculation helpers shared by statistics services."""

from __future__ import annotations


def _percentage(numerator: int, denominator: int) -> float | None:
    """Calculates a percentage or returns None when the denominator is zero."""

    if denominator == 0:
        return None

    return round(numerator / denominator * 100, 1)
def _format_percent(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f} %"

