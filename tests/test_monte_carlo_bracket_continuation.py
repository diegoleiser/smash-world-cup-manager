"""Tests for persisted partial-bracket continuation forecasts."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from monte_carlo.bracket_continuation import (  # noqa: E402
    BracketContinuationInput,
    forecast_bracket_continuation,
    simulate_bracket_continuation,
)
from monte_carlo.config import load_model_config  # noqa: E402
from monte_carlo.model import CombinedModel, PlayerParameters  # noqa: E402
from tournament.bracket_constants import (  # noqa: E402
    BRACKET_SIDE_LOSERS,
    BRACKET_SIDE_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
)
from tournament.bracket_matches import build_bracket_plan  # noqa: E402
from tournament.bracket_routes import build_bracket_route_plan  # noqa: E402
from tournament.bracket_seeding import get_split_bracket_seed_pairs  # noqa: E402


class BracketContinuationTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_model_config(
            PROJECT_ROOT / "config" / "model_freeze_candidate_v0.2.json"
        )
        self.player_ids = tuple(f"p{seed}" for seed in range(1, 8))
        self.model = CombinedModel(
            config,
            {
                player_id: PlayerParameters(player_id, player_id, 0.0)
                for player_id in self.player_ids
            },
            {},
        )
        self.day_values = {
            player_id: 0.0 for player_id in self.player_ids
        }

    def make_start_state(self) -> BracketContinuationInput:
        matches = [
            {
                **match,
                "player_1_id": None,
                "player_2_id": None,
                "winner_id": None,
                "status": (
                    "inactive"
                    if match["match_code"] == "GFR"
                    else "waiting"
                ),
            }
            for match in build_bracket_plan(
                7,
                ENTRY_SPLIT_BY_GROUP_SEED,
            )
        ]
        by_code = {match["match_code"]: match for match in matches}
        pairs = get_split_bracket_seed_pairs(8)
        seeded = {
            seed: (
                self.player_ids[seed - 1]
                if seed <= len(self.player_ids)
                else None
            )
            for seed in range(1, 9)
        }
        for side, prefix in (
            (BRACKET_SIDE_WINNERS, "W1M"),
            (BRACKET_SIDE_LOSERS, "L1M"),
        ):
            for number, (first_seed, second_seed) in enumerate(
                pairs[side],
                start=1,
            ):
                match = by_code[f"{prefix}{number}"]
                match["player_1_id"] = seeded[first_seed]
                match["player_2_id"] = seeded[second_seed]
                match["status"] = (
                    "pending"
                    if seeded[first_seed] and seeded[second_seed]
                    else "bye"
                )
                if match["status"] == "bye":
                    match["winner_id"] = seeded[first_seed] or seeded[second_seed]
        routes = build_bracket_route_plan(
            7,
            ENTRY_SPLIT_BY_GROUP_SEED,
        )
        # Persisted Tournament Manager state already contains propagated Byes.
        bye = by_code["L1M1"]
        for route in routes:
            if (
                route["source_code"] == "L1M1"
                and route["source_outcome"] == "winner"
            ):
                by_code[route["target_code"]][
                    "player_1_id"
                    if route["target_slot"] == 1
                    else "player_2_id"
                ] = bye["winner_id"]
        return BracketContinuationInput(
            matches=tuple(matches),
            routes=tuple(routes),
            seeded_player_ids=self.player_ids,
        )

    def test_start_state_simulates_complete_remaining_bracket(self) -> None:
        result = simulate_bracket_continuation(
            self.make_start_state(),
            self.model,
            self.day_values,
            random.Random(10),
        )
        self.assertEqual(set(result.placements), set(self.player_ids))
        self.assertEqual(result.placements[result.champion_id], 1)
        self.assertIn(len(result.sets), {9, 10})

    def test_fixed_winners_result_is_not_resimulated(self) -> None:
        state = self.make_start_state()
        matches = [dict(match) for match in state.matches]
        by_code = {match["match_code"]: match for match in matches}
        fixed = by_code["W1M1"]
        fixed["status"] = "completed"
        fixed["winner_id"] = fixed["player_1_id"]
        fixed["player_1_score"] = 2
        fixed["player_2_score"] = 0
        loser = fixed["player_2_id"]
        for route in state.routes:
            if route["source_code"] != "W1M1":
                continue
            player_id = (
                fixed["winner_id"]
                if route["source_outcome"] == "winner"
                else loser
            )
            by_code[route["target_code"]][
                "player_1_id"
                if route["target_slot"] == 1
                else "player_2_id"
            ] = player_id
        result = simulate_bracket_continuation(
            BracketContinuationInput(
                matches=tuple(matches),
                routes=state.routes,
                seeded_player_ids=state.seeded_player_ids,
            ),
            self.model,
            self.day_values,
            random.Random(10),
        )
        self.assertNotIn(
            "W1M1",
            {match.match_code for match in result.sets},
        )
        self.assertEqual(set(result.placements), set(self.player_ids))

    def test_continuation_forecast_aggregates_only_remaining_state(self) -> None:
        forecast = forecast_bracket_continuation(
            self.make_start_state(),
            self.model,
            self.day_values,
            100,
            44,
        )
        self.assertEqual(
            {match.match_code for match in forecast.ready_matches},
            {"W1M1", "W1M2", "L1M2"},
        )
        self.assertAlmostEqual(
            sum(player.title_probability for player in forecast.players),
            1.0,
        )
        self.assertAlmostEqual(
            sum(
                player.grand_final_probability
                for player in forecast.players
            ),
            2.0,
        )
        for player in forecast.players:
            self.assertAlmostEqual(
                sum(player.placement_probabilities.values()),
                1.0,
            )

    def test_completed_grand_final_without_reset_is_terminal(self) -> None:
        state = self.make_start_state()
        simulated = None
        for seed in range(100):
            candidate = simulate_bracket_continuation(
                state,
                self.model,
                self.day_values,
                random.Random(seed),
            )
            if not candidate.grand_final_reset_played:
                simulated = candidate
                break
        self.assertIsNotNone(simulated)
        matches = [dict(match) for match in state.matches]
        by_code = {match["match_code"]: match for match in matches}
        for played in simulated.sets:
            match = by_code[played.match_code]
            match.update(
                {
                    "player_1_id": played.player_1_id,
                    "player_2_id": played.player_2_id,
                    "winner_id": played.winner_id,
                    "player_1_score": played.player_1_score,
                    "player_2_score": played.player_2_score,
                    "status": "completed",
                }
            )
        result = simulate_bracket_continuation(
            BracketContinuationInput(
                matches=tuple(matches),
                routes=state.routes,
                seeded_player_ids=state.seeded_player_ids,
            ),
            self.model,
            self.day_values,
            random.Random(999),
        )
        self.assertEqual(result.sets, ())
        self.assertEqual(result.champion_id, simulated.champion_id)
        self.assertEqual(result.placements, simulated.placements)


if __name__ == "__main__":
    unittest.main()
