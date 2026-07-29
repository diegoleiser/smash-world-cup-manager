"""Tournament-level Day Performance sampling."""

from __future__ import annotations

import random
from collections.abc import Iterable


def sample_day_values(
    player_ids: Iterable[str],
    sigma_day: float,
    rng: random.Random,
) -> dict[str, float]:
    """Draw exactly one persistent Day value for every player."""

    if sigma_day < 0:
        raise ValueError("sigma_day must be non-negative.")
    unique_player_ids = list(dict.fromkeys(player_ids))
    return {
        player_id: rng.gauss(0.0, sigma_day)
        for player_id in unique_player_ids
    }
