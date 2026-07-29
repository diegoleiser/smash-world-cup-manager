"""Stable application-facing forecast service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from monte_carlo.artifacts import load_artifact


@dataclass(frozen=True)
class MatchupForecast:
    player_a_id: str
    player_b_id: str
    player_a_name: str
    player_b_name: str
    neutral_game_probability: float
    neutral_bo3_probability: float
    neutral_bo5_probability: float
    model_version: str
    training_cutoff: str


def forecast_neutral_matchup(
    artifact_path: Path,
    player_a_id: str,
    player_b_id: str,
) -> MatchupForecast:
    """Return neutral-Day Game, Bo3 and Bo5 probabilities."""

    if player_a_id == player_b_id:
        raise ValueError("A matchup requires two different players.")
    artifact = load_artifact(artifact_path)
    model = artifact.model
    player_a = model.players.get(player_a_id)
    player_b = model.players.get(player_b_id)
    if player_a is None:
        raise KeyError(f"Unknown model player: {player_a_id}")
    if player_b is None:
        raise KeyError(f"Unknown model player: {player_b_id}")
    normal_game, _ = model.game_probabilities(player_a_id, player_b_id)
    return MatchupForecast(
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        player_a_name=player_a.display_name,
        player_b_name=player_b.display_name,
        neutral_game_probability=normal_game,
        neutral_bo3_probability=model.set_probability(
            player_a_id,
            player_b_id,
            best_of=3,
        ),
        neutral_bo5_probability=model.set_probability(
            player_a_id,
            player_b_id,
            best_of=5,
        ),
        model_version=model.config.model_version,
        training_cutoff=model.config.training_cutoff,
    )
