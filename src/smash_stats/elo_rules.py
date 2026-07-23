"""Pure Elo calculation rules for Smash World Championship matches."""

from __future__ import annotations


ELO_START_RATING = 1000.0
ELO_K_FACTOR = 32.0
ELO_MAX_MARGIN_MULTIPLIER = 1.2


def calculate_expected_score(
    rating: float,
    opponent_rating: float,
) -> float:
    """Calculate the classic Elo win probability."""

    return 1.0 / (1.0 + 10.0 ** ((opponent_rating - rating) / 400.0))


def calculate_margin_multiplier(
    winner_score: int | None,
    loser_score: int | None,
) -> float:
    """
    Return the small Elo bonus for a decisive match win.

    A one-game margin has no bonus, a two-game margin receives 1.10,
    and larger margins are capped at 1.20. Unknown scores have no bonus.
    """

    if winner_score is None or loser_score is None:
        return 1.0

    game_difference = winner_score - loser_score

    if game_difference <= 1:
        return 1.0

    return min(
        1.0 + 0.1 * (game_difference - 1),
        ELO_MAX_MARGIN_MULTIPLIER,
    )


def calculate_elo_change(
    winner_rating: float,
    loser_rating: float,
    *,
    winner_score: int | None = None,
    loser_score: int | None = None,
    k_factor: float = ELO_K_FACTOR,
) -> float:
    """Calculate the equal rating gain and loss for a decided match."""

    expected_winner = calculate_expected_score(
        winner_rating,
        loser_rating,
    )
    margin_multiplier = calculate_margin_multiplier(
        winner_score,
        loser_score,
    )

    return k_factor * margin_multiplier * (1.0 - expected_winner)
