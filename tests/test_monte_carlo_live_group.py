"""Tests for frozen-strength Live Group forecasts."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from monte_carlo.config import load_model_config  # noqa: E402
from monte_carlo.group_simulation import SimulationPlayer  # noqa: E402
from monte_carlo.live_group import (  # noqa: E402
    LiveGroupMatch,
    forecast_live_group,
)
from monte_carlo.model import CombinedModel, PlayerParameters  # noqa: E402
from monte_carlo.live_service import (  # noqa: E402
    LiveDraftGroupState,
    forecast_live_draft_group,
)
from tournament.group_stage_standings import (  # noqa: E402
    GROUP_MATCH_CANCELLED,
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
    GROUP_MATCH_PENDING,
)


class LiveGroupForecastTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_model_config(
            PROJECT_ROOT / "config" / "model_freeze_candidate_v0.2.json"
        )
        self.players = [
            SimulationPlayer(
                player_id=player_id,
                display_name=player_id.upper(),
                initial_seed=seed,
                initial_elo=1100.0 - seed * 10,
            )
            for seed, player_id in enumerate(["a", "b", "c", "d"], start=1)
        ]
        parameters = {
            player.player_id: PlayerParameters(
                player.player_id,
                player.display_name,
                0.5 - player.initial_seed * 0.2,
            )
            for player in self.players
        }
        self.model = CombinedModel(self.config, parameters, {})
        self.matches = [
            LiveGroupMatch(
                "a",
                "b",
                GROUP_MATCH_COMPLETED,
                "a",
                2,
                1,
            ),
            LiveGroupMatch(
                "a",
                "c",
                GROUP_MATCH_FORFEIT,
                "c",
            ),
            LiveGroupMatch("a", "d", GROUP_MATCH_CANCELLED),
            LiveGroupMatch("b", "c", GROUP_MATCH_PENDING),
            LiveGroupMatch("b", "d", GROUP_MATCH_PENDING),
            LiveGroupMatch("c", "d", GROUP_MATCH_PENDING),
        ]

    def test_completed_results_are_fixed_and_pending_sets_are_forecast(
        self,
    ) -> None:
        forecast = forecast_live_group(
            self.players,
            self.matches,
            self.model,
            n_simulations=200,
            random_seed=17,
            winners_count=2,
        )
        by_player = {
            player.player_id: player for player in forecast.players
        }
        self.assertEqual(
            (
                by_player["a"].current_sets_won,
                by_player["a"].current_sets_lost,
            ),
            (1, 1),
        )
        self.assertEqual(
            (
                by_player["c"].current_sets_won,
                by_player["c"].current_sets_lost,
            ),
            (1, 0),
        )
        self.assertEqual(forecast.completed_sets, 2)
        self.assertEqual(forecast.pending_sets, 3)
        for player in forecast.players:
            self.assertAlmostEqual(
                sum(player.group_seed_probabilities.values()),
                1.0,
            )
        self.assertAlmostEqual(
            sum(player.winners_probability for player in forecast.players),
            2.0,
        )

    def test_day_sigma_does_not_affect_remaining_group_forecast(self) -> None:
        no_day_model = CombinedModel(
            replace(self.config, sigma_day=0.0),
            self.model.players,
            self.model.h2h_effects,
        )
        large_day_model = CombinedModel(
            replace(self.config, sigma_day=5.0),
            self.model.players,
            self.model.h2h_effects,
        )
        first = forecast_live_group(
            self.players,
            self.matches,
            no_day_model,
            100,
            99,
            winners_count=2,
        )
        second = forecast_live_group(
            self.players,
            self.matches,
            large_day_model,
            100,
            99,
            winners_count=2,
        )
        self.assertEqual(first.players, second.players)

    def test_complete_group_has_deterministic_final_probabilities(self) -> None:
        complete_matches = [
            LiveGroupMatch(
                match.player_1_id,
                match.player_2_id,
                (
                    GROUP_MATCH_COMPLETED
                    if match.status == GROUP_MATCH_PENDING
                    else match.status
                ),
                (
                    match.player_1_id
                    if match.status == GROUP_MATCH_PENDING
                    else match.winner_id
                ),
                2 if match.status == GROUP_MATCH_PENDING else match.player_1_score,
                0 if match.status == GROUP_MATCH_PENDING else match.player_2_score,
            )
            for match in self.matches
        ]
        forecast = forecast_live_group(
            self.players,
            complete_matches,
            self.model,
            20,
            5,
            winners_count=2,
        )
        self.assertEqual(forecast.pending_sets, 0)
        for player in forecast.players:
            probabilities = set(player.group_seed_probabilities.values())
            self.assertLessEqual(probabilities, {0.0, 1.0})

    def test_draft_service_rejects_non_production_group_size(self) -> None:
        state = LiveDraftGroupState(
            draft_id="draft",
            tournament_number=99,
            group_id="group",
            group_name="Group 1",
            players=tuple(self.players),
            matches=tuple(self.matches),
        )
        with (
            patch(
                "monte_carlo.live_service.load_live_draft_group_state",
                return_value=state,
            ),
            self.assertRaisesRegex(ValueError, "exactly seven"),
        ):
            forecast_live_draft_group(
                "unused.db",
                "draft",
                self.model,
                10,
                1,
            )


if __name__ == "__main__":
    unittest.main()
