"""Tests for presentation-only bracket filtering."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# bracket_visualization registers a Streamlit component at import time. These
# tests exercise only its pure grouping helper, so a minimal component stub
# keeps the test independent from the optional dashboard dependencies.
streamlit_module = types.ModuleType("streamlit")
components_module = types.ModuleType("streamlit.components")
components_v2_module = types.ModuleType("streamlit.components.v2")
components_v2_module.component = lambda **_kwargs: lambda **_data: None
streamlit_module.components = components_module
components_module.v2 = components_v2_module

sys.modules.setdefault("streamlit", streamlit_module)
sys.modules.setdefault("streamlit.components", components_module)
sys.modules.setdefault("streamlit.components.v2", components_v2_module)

import bracket_visualization as bracket_view  # noqa: E402


class BracketVisibilityTests(unittest.TestCase):
    """Ensure technical placeholder matches do not reach the UI."""

    def test_technical_placeholder_matches_are_hidden(self) -> None:
        matches = [
            {
                "match_code": "W1M1",
                "round_number": 1,
                "round_label": "Winners Round 1",
                "match_number": 1,
                "status": "bye",
            },
            {
                "match_code": "W1M2",
                "round_number": 1,
                "round_label": "Winners Round 1",
                "match_number": 2,
                "status": "pending",
            },
            {
                "match_code": "GFR",
                "round_number": 2,
                "round_label": "Grand Final Reset",
                "match_number": 1,
                "status": "inactive",
            },
            {
                "match_code": "L1M1",
                "round_number": 1,
                "round_label": "Losers Round 1",
                "match_number": 1,
                "status": "cancelled",
                "player_1_id": None,
                "player_2_id": None,
                "player_1_name": "TBD",
                "player_2_name": "TBD",
            },
        ]

        grouped_rounds = bracket_view._group_matches_by_round(matches)
        visible_codes = [
            match["match_code"]
            for _number, _label, round_matches in grouped_rounds
            for match in round_matches
        ]

        self.assertEqual(visible_codes, ["W1M2"])

    def test_playable_and_completed_matches_remain_visible(self) -> None:
        matches = [
            {
                "match_code": "W1M1",
                "round_number": 1,
                "round_label": "Winners Round 1",
                "match_number": 1,
                "status": status,
            }
            for status in ("waiting", "pending", "completed", "forfeit")
        ]

        grouped_rounds = bracket_view._group_matches_by_round(matches)

        self.assertEqual(len(grouped_rounds), 1)
        self.assertEqual(len(grouped_rounds[0][2]), 4)

    def test_cancelled_match_with_players_remains_visible(self) -> None:
        matches = [
            {
                "match_code": "L1M1",
                "round_number": 1,
                "round_label": "Losers Round 1",
                "match_number": 1,
                "status": "cancelled",
                "player_1_id": "player-1",
                "player_2_id": "player-2",
            },
        ]

        grouped_rounds = bracket_view._group_matches_by_round(matches)

        self.assertEqual(len(grouped_rounds), 1)
        self.assertEqual(
            grouped_rounds[0][2][0]["match_code"],
            "L1M1",
        )

    def test_future_bye_is_hidden_before_its_player_is_known(self) -> None:
        matches = [
            {
                "match_code": "W1M1",
                "status": "pending",
                "player_1_id": "player-1",
                "player_2_id": "player-2",
            },
            {
                "match_code": "L1M1",
                "status": "cancelled",
                "player_1_id": None,
                "player_2_id": None,
            },
            {
                "match_code": "L2M1",
                "status": "waiting",
                "player_1_id": None,
                "player_2_id": None,
            },
        ]
        routes = [
            {
                "source_code": "W1M1",
                "source_outcome": "loser",
                "target_code": "L2M1",
                "target_slot": 1,
            },
            {
                "source_code": "L1M1",
                "source_outcome": "winner",
                "target_code": "L2M1",
                "target_slot": 2,
            },
        ]

        hidden_codes = (
            bracket_view._get_hidden_technical_match_codes(
                matches,
                routes,
            )
        )

        self.assertIn("L2M1", hidden_codes)

    def test_normal_future_match_with_two_live_routes_stays_visible(
        self,
    ) -> None:
        matches = [
            {
                "match_code": source_code,
                "status": "pending",
                "player_1_id": f"{source_code}-1",
                "player_2_id": f"{source_code}-2",
            }
            for source_code in ("W1M1", "W1M2")
        ]
        matches.append(
            {
                "match_code": "WF",
                "status": "waiting",
                "player_1_id": None,
                "player_2_id": None,
            }
        )
        routes = [
            {
                "source_code": source_code,
                "source_outcome": "winner",
                "target_code": "WF",
                "target_slot": slot,
            }
            for slot, source_code in enumerate(
                ("W1M1", "W1M2"),
                start=1,
            )
        ]

        hidden_codes = (
            bracket_view._get_hidden_technical_match_codes(
                matches,
                routes,
            )
        )

        self.assertNotIn("WF", hidden_codes)


if __name__ == "__main__":
    unittest.main()
