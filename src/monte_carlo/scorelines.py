"""Conditional Set score simulation that preserves the drawn winner."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class SimulatedScore:
    player_a_score: int
    player_b_score: int


def _weighted_choice(
    weighted_values: list[tuple[int, float]],
    rng: random.Random,
) -> int:
    total = sum(weight for _, weight in weighted_values)
    if total <= 0:
        return weighted_values[-1][0]
    draw = rng.random() * total
    cumulative = 0.0
    for value, weight in weighted_values:
        cumulative += weight
        if draw <= cumulative:
            return value
    return weighted_values[-1][0]


def simulate_scoreline(
    *,
    player_a_won: bool,
    normal_game_probability: float,
    decider_game_probability: float,
    best_of: int,
    rng: random.Random,
) -> SimulatedScore:
    """Draw a score conditional on a Set winner already having been drawn."""

    p = normal_game_probability
    q = decider_game_probability
    if not 0.0 <= p <= 1.0 or not 0.0 <= q <= 1.0:
        raise ValueError("Game probabilities must be between zero and one.")

    if best_of == 3:
        if player_a_won:
            loser_score = _weighted_choice(
                [(0, p * p), (1, 2.0 * p * (1.0 - p) * q)],
                rng,
            )
            return SimulatedScore(2, loser_score)
        loser_score = _weighted_choice(
            [
                (0, (1.0 - p) ** 2),
                (1, 2.0 * p * (1.0 - p) * (1.0 - q)),
            ],
            rng,
        )
        return SimulatedScore(loser_score, 2)

    if best_of == 5:
        shared_decider_path = 6.0 * p**2 * (1.0 - p) ** 2
        if player_a_won:
            loser_score = _weighted_choice(
                [
                    (0, p**3),
                    (1, 3.0 * p**3 * (1.0 - p)),
                    (2, shared_decider_path * q),
                ],
                rng,
            )
            return SimulatedScore(3, loser_score)
        loser_score = _weighted_choice(
            [
                (0, (1.0 - p) ** 3),
                (1, 3.0 * (1.0 - p) ** 3 * p),
                (2, shared_decider_path * (1.0 - q)),
            ],
            rng,
        )
        return SimulatedScore(loser_score, 3)

    raise ValueError("Only Best-of-3 and Best-of-5 are supported.")
