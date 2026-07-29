"""Tests for deterministic Combined-model training."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from monte_carlo.config import load_model_config  # noqa: E402
from monte_carlo.training import CombinedTrainer  # noqa: E402


class CombinedTrainerTests(unittest.TestCase):
    def test_same_input_produces_same_fit(self) -> None:
        players = pd.DataFrame(
            [
                {
                    "player_id": "a",
                    "display_name": "Alpha",
                    "core_player": 1,
                    "active": 1,
                },
                {
                    "player_id": "b",
                    "display_name": "Bravo",
                    "core_player": 1,
                    "active": 1,
                },
            ]
        )
        matches = pd.DataFrame(
            [
                {
                    "player_1_id": "a",
                    "player_2_id": "b",
                    "winner_id": "a",
                    "player_1_score": 2,
                    "player_2_score": 1,
                    "score_known": 1,
                    "best_of": 3,
                    "tournament_number": 1,
                    "tournament_date": "2025-01-01",
                },
                {
                    "player_1_id": "a",
                    "player_2_id": "b",
                    "winner_id": "b",
                    "player_1_score": 0,
                    "player_2_score": 2,
                    "score_known": 1,
                    "best_of": 3,
                    "tournament_number": 2,
                    "tournament_date": "2025-07-01",
                },
            ]
        )
        config = load_model_config(
            PROJECT_ROOT / "config" / "model_freeze_candidate_v0.2.json"
        )

        first_values, first_diagnostics = CombinedTrainer(
            players, matches, config
        ).fit()
        second_values, second_diagnostics = CombinedTrainer(
            players, matches, config
        ).fit()

        self.assertTrue(first_diagnostics["success"])
        self.assertTrue(second_diagnostics["success"])
        np.testing.assert_allclose(first_values, second_values, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
