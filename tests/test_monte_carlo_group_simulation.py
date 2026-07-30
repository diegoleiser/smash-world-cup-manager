"""Tests for Day sampling, scorelines, and Round Robin simulation."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from monte_carlo.config import load_model_config  # noqa: E402
from monte_carlo.bracket_simulation import simulate_split_bracket  # noqa: E402
from monte_carlo.day_performance import sample_day_values  # noqa: E402
from monte_carlo.group_simulation import (  # noqa: E402
    SimulationPlayer,
    simulate_group,
)
from monte_carlo.model import CombinedModel, PlayerParameters  # noqa: E402
from monte_carlo.scorelines import simulate_scoreline  # noqa: E402
from monte_carlo.simulation import simulate_pre_tournament  # noqa: E402
from tournament.bracket_seeding import get_bracket_size  # noqa: E402


class DayPerformanceTests(unittest.TestCase):
    def test_same_seed_reproduces_one_value_per_player(self) -> None:
        first = sample_day_values(["a", "b", "c"], 0.4, random.Random(7))
        second = sample_day_values(["a", "b", "c"], 0.4, random.Random(7))
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"a", "b", "c"})


class ScorelineTests(unittest.TestCase):
    def test_scoreline_never_changes_drawn_winner(self) -> None:
        rng = random.Random(123)
        for best_of, winning_score in ((3, 2), (5, 3)):
            for player_a_won in (True, False):
                for _ in range(100):
                    score = simulate_scoreline(
                        player_a_won=player_a_won,
                        normal_game_probability=0.61,
                        decider_game_probability=0.55,
                        best_of=best_of,
                        rng=rng,
                    )
                    if player_a_won:
                        self.assertEqual(score.player_a_score, winning_score)
                        self.assertLess(score.player_b_score, winning_score)
                    else:
                        self.assertEqual(score.player_b_score, winning_score)
                        self.assertLess(score.player_a_score, winning_score)

    def test_impossible_sweep_path_falls_back_to_close_score(self) -> None:
        score = simulate_scoreline(
            player_a_won=True,
            normal_game_probability=0.0,
            decider_game_probability=1.0,
            best_of=3,
            rng=random.Random(1),
        )
        self.assertEqual((score.player_a_score, score.player_b_score), (2, 1))


class GroupSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_model_config(
            PROJECT_ROOT / "config" / "model_freeze_candidate_v0.2.json"
        )
        self.players = [
            SimulationPlayer(
                player_id=f"p{seed}",
                display_name=f"Player {seed}",
                initial_seed=seed,
                initial_elo=1100.0 - seed * 10,
            )
            for seed in range(1, 8)
        ]
        self.model = CombinedModel(
            config,
            {
                player.player_id: PlayerParameters(
                    player.player_id,
                    player.display_name,
                    (8 - player.initial_seed) * 0.1,
                )
                for player in self.players
            },
            {},
        )

    def test_seven_player_group_has_complete_unique_results(self) -> None:
        result = simulate_group(
            self.players,
            self.model,
            random.Random(42),
        )
        self.assertEqual(len(result.sets), 21)
        self.assertEqual(len(result.standings), 7)
        self.assertEqual(
            {int(row["placement"]) for row in result.standings},
            set(range(1, 8)),
        )
        self.assertEqual(set(result.day_values), {
            player.player_id for player in self.players
        })
        pairs = {
            frozenset((match.player_1_id, match.player_2_id))
            for match in result.sets
        }
        self.assertEqual(len(pairs), 21)

    def test_group_simulation_is_reproducible(self) -> None:
        first = simulate_group(
            self.players,
            self.model,
            random.Random(1234),
        )
        second = simulate_group(
            self.players,
            self.model,
            random.Random(1234),
        )
        self.assertEqual(first, second)


class BracketSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_model_config(
            PROJECT_ROOT / "config" / "model_freeze_candidate_v0.2.json"
        )
        self.player_ids = [f"p{seed}" for seed in range(1, 8)]
        self.model = CombinedModel(
            config,
            {
                player_id: PlayerParameters(
                    player_id,
                    player_id.upper(),
                    0.0,
                )
                for player_id in self.player_ids
            },
            {},
        )
        self.day_values = {
            player_id: 0.0 for player_id in self.player_ids
        }

    def test_seven_player_split_bracket_uses_project_routes(self) -> None:
        result = simulate_split_bracket(
            self.player_ids,
            self.model,
            self.day_values,
            random.Random(1),
        )
        self.assertEqual(set(result.placements), set(self.player_ids))
        self.assertEqual(
            list(result.placements.values()).count(1),
            1,
        )
        self.assertEqual(
            list(result.placements.values()).count(2),
            1,
        )
        self.assertEqual(
            list(result.placements.values()).count(3),
            1,
        )
        self.assertEqual(
            {match.match_code for match in result.sets},
            {
                "W1M1",
                "W1M2",
                "WF",
                "L1M2",
                "L2M1",
                "L2M2",
                "L3M1",
                "LF",
                "GF",
            },
        )
        self.assertNotIn("L1M1", {
            match.match_code for match in result.sets
        })
        self.assertFalse(result.grand_final_reset_played)

    def test_losers_side_grand_final_win_plays_reset(self) -> None:
        result = simulate_split_bracket(
            self.player_ids,
            self.model,
            self.day_values,
            random.Random(0),
        )
        self.assertTrue(result.grand_final_reset_played)
        self.assertEqual(result.sets[-1].match_code, "GFR")
        self.assertEqual(result.placements[result.champion_id], 1)

    def test_bracket_simulation_is_reproducible(self) -> None:
        first = simulate_split_bracket(
            self.player_ids,
            self.model,
            self.day_values,
            random.Random(99),
        )
        second = simulate_split_bracket(
            self.player_ids,
            self.model,
            self.day_values,
            random.Random(99),
        )
        self.assertEqual(first, second)

    def test_split_bracket_handles_byes_across_supported_sizes(self) -> None:
        player_ids = [f"p{seed}" for seed in range(1, 21)]
        model = CombinedModel(
            self.model.config,
            {
                player_id: PlayerParameters(
                    player_id,
                    player_id.upper(),
                    0.0,
                )
                for player_id in player_ids
            },
            {},
        )
        for participant_count in range(3, 21):
            with self.subTest(participant_count=participant_count):
                selected_ids = player_ids[:participant_count]
                result = simulate_split_bracket(
                    selected_ids,
                    model,
                    {
                        player_id: 0.0
                        for player_id in selected_ids
                    },
                    random.Random(1000 + participant_count),
                )
                self.assertEqual(
                    set(result.placements),
                    set(selected_ids),
                )
                self.assertEqual(
                    result.placements[result.champion_id],
                    1,
                )


class PreTournamentSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_model_config(
            PROJECT_ROOT / "config" / "model_freeze_candidate_v0.2.json"
        )
        self.players = [
            SimulationPlayer(
                player_id=f"p{seed}",
                display_name=f"Player {seed}",
                initial_seed=seed,
                initial_elo=1000.0,
            )
            for seed in range(1, 8)
        ]
        self.model = CombinedModel(
            config,
            {
                player.player_id: PlayerParameters(
                    player.player_id,
                    player.display_name,
                    (8 - player.initial_seed) * 0.1,
                )
                for player in self.players
            },
            {},
        )

    def test_simulation_is_reproducible_and_distributions_close(self) -> None:
        first = simulate_pre_tournament(
            self.players,
            self.model,
            n_simulations=100,
            random_seed=2026,
        )
        second = simulate_pre_tournament(
            self.players,
            self.model,
            n_simulations=100,
            random_seed=2026,
        )
        self.assertEqual(first.players, second.players)
        self.assertEqual(first.reset_probability, second.reset_probability)

        for player in first.players:
            self.assertAlmostEqual(
                sum(player.group_seed_probabilities.values()),
                1.0,
            )
            self.assertAlmostEqual(
                sum(player.placement_probabilities.values()),
                1.0,
            )
        self.assertAlmostEqual(
            sum(player.title_probability for player in first.players),
            1.0,
        )
        self.assertAlmostEqual(
            sum(player.winners_probability for player in first.players),
            4.0,
        )
        self.assertAlmostEqual(
            sum(
                player.grand_final_probability
                for player in first.players
            ),
            2.0,
        )
        for seed in range(1, 8):
            self.assertAlmostEqual(
                sum(
                    player.group_seed_probabilities[seed]
                    for player in first.players
                ),
                1.0,
            )

    def test_neutral_new_player_can_enter_tournament(self) -> None:
        model = self.model.with_neutral_players({"new": "New Player"})
        players = [
            *self.players[:-1],
            SimulationPlayer(
                player_id="new",
                display_name="New Player",
                initial_seed=7,
                initial_elo=1000.0,
            ),
        ]
        result = simulate_pre_tournament(
            players,
            model,
            n_simulations=20,
            random_seed=88,
        )
        by_player_id = {
            player.player_id: player for player in result.players
        }
        self.assertIn("new", by_player_id)
        self.assertAlmostEqual(
            sum(
                player.title_probability
                for player in result.players
            ),
            1.0,
        )

    def test_current_placement_convention_preserves_ties(self) -> None:
        result = simulate_pre_tournament(
            self.players,
            self.model,
            n_simulations=20,
            random_seed=7,
        )
        expected_players_per_placement = {
            1: 1.0,
            2: 1.0,
            3: 1.0,
            4: 1.0,
            5: 2.0,
            6: 0.0,
            7: 1.0,
        }
        for placement, expected in expected_players_per_placement.items():
            self.assertAlmostEqual(
                sum(
                    player.placement_probabilities[placement]
                    for player in result.players
                ),
                expected,
            )

    def test_variable_participant_counts_preserve_distributions(self) -> None:
        player_ids = [f"v{seed}" for seed in range(1, 17)]
        model = CombinedModel(
            self.model.config,
            {
                player_id: PlayerParameters(
                    player_id,
                    player_id.upper(),
                    0.0,
                )
                for player_id in player_ids
            },
            {},
        )
        for participant_count in (3, 4, 5, 6, 8, 9, 12, 16):
            with self.subTest(participant_count=participant_count):
                players = [
                    SimulationPlayer(
                        player_id=player_id,
                        display_name=player_id.upper(),
                        initial_seed=seed,
                        initial_elo=1000.0,
                    )
                    for seed, player_id in enumerate(
                        player_ids[:participant_count],
                        start=1,
                    )
                ]
                result = simulate_pre_tournament(
                    players,
                    model,
                    n_simulations=5,
                    random_seed=participant_count,
                )
                self.assertEqual(len(result.players), participant_count)
                self.assertAlmostEqual(
                    sum(
                        player.title_probability
                        for player in result.players
                    ),
                    1.0,
                )
                self.assertAlmostEqual(
                    sum(
                        player.grand_final_probability
                        for player in result.players
                    ),
                    2.0,
                )
                self.assertAlmostEqual(
                    sum(
                        player.winners_probability
                        for player in result.players
                    ),
                    get_bracket_size(participant_count) // 2,
                )


if __name__ == "__main__":
    unittest.main()
