"""Pure probability functions shared by forecasts and simulations."""

from __future__ import annotations

import math


def clip_probability(value: float, minimum: float, maximum: float) -> float:
    """Apply the model's single central probability clipping policy."""

    return min(max(float(value), minimum), maximum)


def sigmoid(value: float) -> float:
    """Numerically stable logistic function."""

    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def logit(probability: float) -> float:
    """Convert a strict probability to log odds."""

    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be strictly between zero and one.")
    return math.log(probability / (1.0 - probability))


def bo3_probability(normal_game: float, decider_game: float) -> float:
    """Probability of winning a Bo3 with Clutch only in Game 3."""

    p = normal_game
    q = decider_game
    return p * p + 2.0 * p * (1.0 - p) * q


def bo5_probability(normal_game: float, decider_game: float) -> float:
    """Probability of winning a Bo5 with Clutch only in Game 5."""

    p = normal_game
    q = decider_game
    return p**3 * (4.0 - 3.0 * p) + 6.0 * p**2 * (1.0 - p) ** 2 * q
