"""Tests for joint live forecasts across multiple groups."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from monte_carlo.config import load_model_config  # noqa: E402
from monte_carlo.group_simulation import SimulationPlayer  # noqa: E402
from monte_carlo.live_group import (  # noqa: E402
    LOSERS_LOCKED,
    WINNERS_LOCKED,
    LiveGroupMatch,
)
from monte_carlo.live_multi_group import (  # noqa: E402
    LiveGroupPool,
    forecast_live_groups,
)
from monte_carlo.model import CombinedModel, PlayerParameters  # noqa: E402
from tournament.group_stage_pairings import (  # noqa: E402
    generate_round_robin_pairings,
)
from tournament.group_stage_standings import (  # noqa: E402
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_PENDING,
)


class LiveMultiGroupForecastTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_model_config(
            PROJECT_ROOT / "config" / "model_freeze_candidate_v0.2.json"
        )
        self.players = [
            SimulationPlayer(
                player_id=player_id,
                display_name=player_id.upper(),
                initial_seed=seed,
                initial_elo=1000.0 - seed,
            )
            for seed, player_id in enumerate(
                ("a", "b", "c", "d", "e", "f"),
                start=1,
            )
        ]
        self.model = CombinedModel(
            config,
            {
                player.player_id: PlayerParameters(
                    player.player_id,
                    player.display_name,
                    0.0,
                )
                for player in self.players
            },
            {},
        )

    def make_groups(self, status: str) -> list[LiveGroupPool]:
        groups = []
        for group_index, members in enumerate(
            (self.players[:3], self.players[3:]),
            start=1,
        ):
            matches = []
            for round_pairings in generate_round_robin_pairings(
                [player.player_id for player in members]
            ):
                for first, second in round_pairings:
                    matches.append(
                        LiveGroupMatch(
                            first,
                            second,
                            status,
                            (
                                first
                                if status == GROUP_MATCH_COMPLETED
                                else None
                            ),
                            (
                                2
                                if status == GROUP_MATCH_COMPLETED
                                else None
                            ),
                            (
                                0
                                if status == GROUP_MATCH_COMPLETED
                                else None
                            ),
                        )
                    )
            groups.append(
                LiveGroupPool(
                    group_id=f"g{group_index}",
                    group_name=f"Group {group_index}",
                    players=tuple(members),
                    matches=tuple(matches),
                )
            )
        return groups

    def test_pending_groups_share_global_winners_probabilities(self) -> None:
        forecast = forecast_live_groups(
            self.make_groups(GROUP_MATCH_PENDING),
            self.model,
            200,
            27,
        )
        self.assertEqual(forecast.pending_sets, 6)
        self.assertEqual(len(forecast.match_leverage), 6)
        self.assertAlmostEqual(
            sum(
                player.winners_probability
                for player in forecast.players
            ),
            4.0,
        )
        for player in forecast.players:
            self.assertAlmostEqual(
                sum(player.group_seed_probabilities.values()),
                1.0,
            )

    def test_complete_groups_lock_global_bracket_sides(self) -> None:
        forecast = forecast_live_groups(
            self.make_groups(GROUP_MATCH_COMPLETED),
            self.model,
            20,
            9,
        )
        status_by_player = {
            player.player_id: player.winners_status
            for player in forecast.players
        }
        self.assertEqual(
            {
                player_id
                for player_id, status in status_by_player.items()
                if status == WINNERS_LOCKED
            },
            {"a", "b", "d", "e"},
        )
        self.assertEqual(status_by_player["c"], LOSERS_LOCKED)
        self.assertEqual(status_by_player["f"], LOSERS_LOCKED)
        self.assertEqual(forecast.pending_sets, 0)
        self.assertEqual(forecast.match_leverage, ())


if __name__ == "__main__":
    unittest.main()
