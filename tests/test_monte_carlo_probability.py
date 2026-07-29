"""Tests for the production Combined-model probability core."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from monte_carlo.config import load_model_config  # noqa: E402
from monte_carlo.model import CombinedModel, PlayerParameters  # noqa: E402
from monte_carlo.probability import (  # noqa: E402
    bo3_probability,
    bo5_probability,
    logit,
    sigmoid,
)


class ProbabilityCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_model_config(
            PROJECT_ROOT / "config" / "model_freeze_candidate_v0.2.json"
        )

    def test_sigmoid_and_logit_are_inverses(self) -> None:
        for probability in (0.01, 0.2, 0.5, 0.8, 0.99):
            with self.subTest(probability=probability):
                self.assertAlmostEqual(
                    sigmoid(logit(probability)),
                    probability,
                )

    def test_standard_bo3_and_bo5_formulas_without_clutch(self) -> None:
        for probability in (0.2, 0.5, 0.8):
            self.assertAlmostEqual(
                bo3_probability(probability, probability),
                3 * probability**2 - 2 * probability**3,
            )
            self.assertAlmostEqual(
                bo5_probability(probability, probability),
                10 * probability**3
                - 15 * probability**4
                + 6 * probability**5,
            )

    def test_identical_players_are_fifty_fifty(self) -> None:
        model = CombinedModel(
            self.config,
            {
                "a": PlayerParameters("a", "Alpha", 0.0),
                "b": PlayerParameters("b", "Bravo", 0.0),
            },
            {},
        )
        self.assertAlmostEqual(model.set_probability("a", "b"), 0.5)

    def test_reversing_players_returns_complement(self) -> None:
        model = CombinedModel(
            self.config,
            {
                "a": PlayerParameters("a", "Alpha", 0.7, 0.2),
                "b": PlayerParameters("b", "Bravo", -0.1, -0.3),
            },
            {("a", "b"): 0.25},
        )
        for best_of in (3, 5):
            probability = model.set_probability("a", "b", best_of=best_of)
            reverse = model.set_probability("b", "a", best_of=best_of)
            self.assertAlmostEqual(probability + reverse, 1.0)

    def test_clutch_changes_only_decider_probability(self) -> None:
        model = CombinedModel(
            self.config,
            {
                "a": PlayerParameters("a", "Alpha", 0.0, 1.0),
                "b": PlayerParameters("b", "Bravo", 0.0, 0.0),
            },
            {},
        )
        normal, decider = model.game_probabilities("a", "b")
        self.assertEqual(normal, 0.5)
        self.assertGreater(decider, normal)

    def test_production_probability_is_clipped_centrally(self) -> None:
        model = CombinedModel(
            self.config,
            {
                "a": PlayerParameters("a", "Alpha", 100.0),
                "b": PlayerParameters("b", "Bravo", -100.0),
            },
            {},
        )
        self.assertTrue(
            math.isclose(model.set_probability("a", "b"), 0.995)
        )


if __name__ == "__main__":
    unittest.main()
