"""Tests for the pure Elo rules and their compatibility exports."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import smash_statistics as statistics  # noqa: E402
from smash_stats import database  # noqa: E402
from smash_stats import elo_history  # noqa: E402
from smash_stats import elo_rules  # noqa: E402
from smash_stats import player_stats  # noqa: E402


class EloRuleModuleBoundaryTests(unittest.TestCase):
    """Keep existing callers wired to the focused Elo implementation."""

    def test_functions_are_reexported_unchanged(self) -> None:
        self.assertIs(
            statistics.calculate_expected_score,
            elo_rules.calculate_expected_score,
        )
        self.assertIs(
            statistics.calculate_margin_multiplier,
            elo_rules.calculate_margin_multiplier,
        )
        self.assertIs(
            statistics.calculate_elo_change,
            elo_rules.calculate_elo_change,
        )

    def test_constants_are_reexported_unchanged(self) -> None:
        self.assertEqual(statistics.ELO_START_RATING, 1000.0)
        self.assertEqual(statistics.ELO_K_FACTOR, 32.0)
        self.assertEqual(statistics.ELO_MAX_MARGIN_MULTIPLIER, 1.2)

    def test_database_helpers_are_reexported_unchanged(self) -> None:
        self.assertIs(statistics.connect_db, database.connect_db)
        self.assertIs(statistics.resolve_player, database.resolve_player)
        self.assertIs(
            statistics.PlayerNotFoundError,
            database.PlayerNotFoundError,
        )
        self.assertEqual(
            statistics.DEFAULT_DB_PATH,
            database.DEFAULT_DB_PATH,
        )

    def test_history_functions_are_reexported_unchanged(self) -> None:
        self.assertIs(
            statistics.calculate_elo_history,
            elo_history.calculate_elo_history,
        )
        self.assertIs(
            statistics.get_elo_ranking,
            elo_history.get_elo_ranking,
        )
        self.assertIs(
            statistics.get_player_elo_history,
            elo_history.get_player_elo_history,
        )
        self.assertIs(
            statistics.get_player_elo_summary,
            elo_history.get_player_elo_summary,
        )

    def test_player_functions_are_reexported_unchanged(self) -> None:
        self.assertIs(
            statistics.get_player_stats,
            player_stats.get_player_stats,
        )
        self.assertIs(
            statistics.get_all_player_stats,
            player_stats.get_all_player_stats,
        )
        self.assertIs(
            statistics.get_player_history,
            player_stats.get_player_history,
        )


class EloRuleTests(unittest.TestCase):
    """Preserve the established probability and score-margin rules."""

    def test_equal_ratings_have_equal_expected_scores(self) -> None:
        self.assertEqual(
            elo_rules.calculate_expected_score(1000.0, 1000.0),
            0.5,
        )

    def test_margin_multiplier_is_capped(self) -> None:
        cases = (
            (None, None, 1.0),
            (2, 1, 1.0),
            (2, 0, 1.1),
            (3, 0, 1.2),
            (10, 0, 1.2),
        )

        for winner_score, loser_score, expected in cases:
            with self.subTest(
                winner_score=winner_score,
                loser_score=loser_score,
            ):
                self.assertAlmostEqual(
                    elo_rules.calculate_margin_multiplier(
                        winner_score,
                        loser_score,
                    ),
                    expected,
                )

    def test_equal_rating_win_uses_k_factor_and_margin(self) -> None:
        self.assertAlmostEqual(
            elo_rules.calculate_elo_change(
                1000.0,
                1000.0,
                winner_score=2,
                loser_score=0,
            ),
            17.6,
        )


if __name__ == "__main__":
    unittest.main()
