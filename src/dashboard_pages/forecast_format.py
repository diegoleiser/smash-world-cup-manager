"""Presentation helpers for live tournament forecasts."""

from monte_carlo.live_group import (
    LOSERS_LOCKED,
    SIDE_OPEN,
    WINNERS_LOCKED,
)


def format_winners_probability(
    probability: float,
    status: str,
) -> str:
    """Keep sampled extremes distinct from mathematically locked sides."""

    if status == WINNERS_LOCKED:
        return "100.0%"
    if status == LOSERS_LOCKED:
        return "0.0%"
    if status == SIDE_OPEN and probability >= 0.9995:
        return ">99.9%"
    if status == SIDE_OPEN and probability <= 0.0005:
        return "<0.1%"
    return f"{probability:.1%}"
