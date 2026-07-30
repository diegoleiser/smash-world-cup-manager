"""Immutable Combined-model artifact used for matchup forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from monte_carlo.config import ModelConfig
from monte_carlo.probability import (
    bo3_probability,
    bo5_probability,
    clip_probability,
    sigmoid,
)


@dataclass(frozen=True)
class PlayerParameters:
    player_id: str
    display_name: str
    skill_log_odds: float
    clutch_log_odds: float = 0.0


class CombinedModel:
    """Dynamic Skill + static H2H + decider-only Clutch."""

    def __init__(
        self,
        config: ModelConfig,
        players: Mapping[str, PlayerParameters],
        h2h_effects: Mapping[tuple[str, str], float],
    ) -> None:
        self.config = config
        self.players = MappingProxyType(dict(players))
        self.h2h_effects = MappingProxyType(dict(h2h_effects))

    def with_neutral_players(
        self,
        player_names: Mapping[str, str],
    ) -> "CombinedModel":
        """Return a runtime copy with zero-effect priors for new players."""

        players = dict(self.players)
        for player_id, display_name in player_names.items():
            if player_id in players:
                continue
            players[player_id] = PlayerParameters(
                player_id=player_id,
                display_name=display_name,
                skill_log_odds=0.0,
                clutch_log_odds=0.0,
            )
        return CombinedModel(
            self.config,
            players,
            self.h2h_effects,
        )

    def _player(self, player_id: str) -> PlayerParameters:
        try:
            return self.players[player_id]
        except KeyError as exc:
            raise KeyError(f"Unknown model player: {player_id}") from exc

    def h2h_effect(self, player_a_id: str, player_b_id: str) -> float:
        direct = self.h2h_effects.get((player_a_id, player_b_id))
        reverse = self.h2h_effects.get((player_b_id, player_a_id))
        if direct is not None and reverse is not None:
            if abs(direct + reverse) > 1e-9:
                raise ValueError("H2H effects must be antisymmetric.")
        if direct is not None:
            return direct
        if reverse is not None:
            return -reverse
        return 0.0

    def game_probabilities(
        self,
        player_a_id: str,
        player_b_id: str,
        *,
        day_a: float = 0.0,
        day_b: float = 0.0,
    ) -> tuple[float, float]:
        player_a = self._player(player_a_id)
        player_b = self._player(player_b_id)
        normal_logit = (
            player_a.skill_log_odds
            - player_b.skill_log_odds
            + self.h2h_effect(player_a_id, player_b_id)
            + day_a
            - day_b
        )
        decider_logit = (
            normal_logit
            + player_a.clutch_log_odds
            - player_b.clutch_log_odds
        )
        return sigmoid(normal_logit), sigmoid(decider_logit)

    def set_probability(
        self,
        player_a_id: str,
        player_b_id: str,
        *,
        best_of: int = 3,
        day_a: float = 0.0,
        day_b: float = 0.0,
    ) -> float:
        normal, decider = self.game_probabilities(
            player_a_id,
            player_b_id,
            day_a=day_a,
            day_b=day_b,
        )
        if best_of == 3:
            raw_probability = bo3_probability(normal, decider)
        elif best_of == 5:
            raw_probability = bo5_probability(normal, decider)
        else:
            raise ValueError("Only Best-of-3 and Best-of-5 are supported.")
        return clip_probability(
            raw_probability,
            self.config.prediction_clip_min,
            self.config.prediction_clip_max,
        )
