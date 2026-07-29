"""Tournament-level Day Performance sampling."""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from monte_carlo.model import CombinedModel
from monte_carlo.probability import sigmoid
from tournament.group_stage_standings import (
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_PENDING,
)


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


@dataclass(frozen=True)
class DayPosteriorEstimate:
    values: dict[str, float]
    success: bool
    iterations: int
    objective: float
    completed_score_sets: int


def estimate_group_day(
    player_ids: list[str],
    matches: Iterable[object],
    model: CombinedModel,
) -> DayPosteriorEstimate:
    """
    Estimate MAP Day values from a complete Group Stage and freeze them.

    Only genuinely played, score-known Sets inform Day. Forfeits and
    cancellations carry no Game evidence and are intentionally ignored.
    """

    unique_player_ids = list(dict.fromkeys(player_ids))
    if len(unique_player_ids) != len(player_ids):
        raise ValueError("Day estimation requires unique players.")
    if any(player_id not in model.players for player_id in player_ids):
        raise KeyError("Day estimation contains a player absent from the model.")
    match_list = list(matches)
    if any(str(getattr(match, "status")) == GROUP_MATCH_PENDING for match in match_list):
        raise ValueError(
            "Day Performance activates only after the Group Stage is complete."
        )
    completed_matches = [
        match
        for match in match_list
        if (
            str(getattr(match, "status")) == GROUP_MATCH_COMPLETED
            and getattr(match, "player_1_score") is not None
            and getattr(match, "player_2_score") is not None
        )
    ]
    sigma_day = model.config.sigma_day
    if sigma_day <= 0 or not completed_matches:
        return DayPosteriorEstimate(
            values={player_id: 0.0 for player_id in player_ids},
            success=True,
            iterations=0,
            objective=0.0,
            completed_score_sets=len(completed_matches),
        )
    player_index = {
        player_id: index for index, player_id in enumerate(player_ids)
    }

    def objective(day_values: np.ndarray) -> tuple[float, np.ndarray]:
        value = 0.5 * float(np.sum(day_values**2)) / sigma_day**2
        gradient = day_values / sigma_day**2
        for match in completed_matches:
            first = str(getattr(match, "player_1_id"))
            second = str(getattr(match, "player_2_id"))
            first_score = int(getattr(match, "player_1_score"))
            second_score = int(getattr(match, "player_2_score"))
            first_parameters = model.players[first]
            second_parameters = model.players[second]
            eta = (
                first_parameters.skill_log_odds
                - second_parameters.skill_log_odds
                + model.h2h_effect(first, second)
                + day_values[player_index[first]]
                - day_values[player_index[second]]
            )
            wins_needed = 3 if max(first_score, second_score) >= 3 else 2
            reached_decider = (
                first_score + second_score == 2 * wins_needed - 1
            )
            normal_wins = first_score
            normal_games = first_score + second_score
            if reached_decider:
                normal_games -= 1
                if first_score == wins_needed:
                    normal_wins -= 1

            def add_residual(residual: float) -> None:
                gradient[player_index[first]] += residual
                gradient[player_index[second]] -= residual

            if normal_games:
                probability = sigmoid(float(eta))
                value += (
                    normal_games * float(np.logaddexp(0.0, eta))
                    - normal_wins * eta
                )
                add_residual(normal_games * probability - normal_wins)
            if reached_decider:
                decider_eta = (
                    eta
                    + first_parameters.clutch_log_odds
                    - second_parameters.clutch_log_odds
                )
                actual = 1.0 if first_score == wins_needed else 0.0
                probability = sigmoid(float(decider_eta))
                value += float(np.logaddexp(0.0, decider_eta)) - (
                    actual * decider_eta
                )
                add_residual(probability - actual)
        return float(value), gradient

    result = minimize(
        objective,
        np.zeros(len(player_ids)),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 200, "ftol": 1e-11},
    )
    if not result.success:
        raise RuntimeError(f"Day Performance fit failed: {result.message}")
    return DayPosteriorEstimate(
        values={
            player_id: float(result.x[player_index[player_id]])
            for player_id in player_ids
        },
        success=True,
        iterations=int(result.nit),
        objective=float(result.fun),
        completed_score_sets=len(completed_matches),
    )
