"""Characterization tests for the existing bracket-planning behavior."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import tournament_manager as tournament  # noqa: E402
from tournament import bracket_matches  # noqa: E402
from tournament import bracket_planning  # noqa: E402
from tournament import bracket_routes  # noqa: E402
from tournament import bracket_seeding  # noqa: E402


def _plan_digest(participant_count: int, entry_mode: str) -> str:
    """Return a stable snapshot hash for a complete bracket plan."""
    payload = {
        "matches": tournament.build_bracket_plan(
            participant_count,
            entry_mode,
        ),
        "routes": tournament.build_bracket_route_plan(
            participant_count,
            entry_mode,
        ),
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


class BracketSizingTests(unittest.TestCase):
    """Lock down the supported power-of-two sizing rules."""

    def test_bracket_size_boundaries(self) -> None:
        expected_sizes = {
            3: 4,
            4: 4,
            5: 8,
            8: 8,
            9: 16,
            16: 16,
            17: 32,
            32: 32,
        }

        for participant_count, expected_size in expected_sizes.items():
            with self.subTest(participant_count=participant_count):
                self.assertEqual(
                    tournament.get_bracket_size(participant_count),
                    expected_size,
                )

    def test_unsupported_participant_counts_are_rejected(self) -> None:
        for participant_count in (0, 1, 2, 33):
            with self.subTest(participant_count=participant_count):
                with self.assertRaises(ValueError):
                    tournament.get_bracket_size(participant_count)


class SeedPairingTests(unittest.TestCase):
    """Preserve the project's current seed-slot assignments."""

    def test_standard_seed_order_for_eight_player_bracket(self) -> None:
        self.assertEqual(
            tournament.get_standard_seed_order(8),
            [1, 8, 4, 5, 2, 7, 3, 6],
        )

    def test_split_seed_pairs_for_eight_player_bracket(self) -> None:
        self.assertEqual(
            tournament.get_split_bracket_seed_pairs(8),
            {
                tournament.BRACKET_SIDE_WINNERS: [(1, 4), (2, 3)],
                tournament.BRACKET_SIDE_LOSERS: [(5, 8), (6, 7)],
            },
        )


class BracketPlanSnapshotTests(unittest.TestCase):
    """Detect any structural or routing change during modularization."""

    EXPECTED_DIGESTS = {
        tournament.ENTRY_ALL_WINNERS: {
            3: "ca24b8a01083a159d7c2403de4d2b58a788ac4bbb9f87a13188589fc304d323c",
            5: "20f3d0ef4354c34545a7f6d6e5daea4deccd05d93f3e9c2986c6ae29427cfe6a",
            8: "20f3d0ef4354c34545a7f6d6e5daea4deccd05d93f3e9c2986c6ae29427cfe6a",
            9: "ddcd14b9b4df7beedcbd1e355da16dca67bdc1870a8d191a92aec2501f15c02c",
            12: "ddcd14b9b4df7beedcbd1e355da16dca67bdc1870a8d191a92aec2501f15c02c",
            17: "efa377b8d51d2b7d8fa6588632b1d8f8b2c0ec94c94a6004fd35b4963f218f10",
            32: "efa377b8d51d2b7d8fa6588632b1d8f8b2c0ec94c94a6004fd35b4963f218f10",
        },
        tournament.ENTRY_SPLIT_BY_GROUP_SEED: {
            3: "7c19d1d2ce75490d7c72d0c1970f4538deb3324416dcf4ddc92b1efbb9ec585a",
            5: "a6e8524dd9416b16f7915a024adccb734f9fffed2130f07965f4079930dacc31",
            8: "a6e8524dd9416b16f7915a024adccb734f9fffed2130f07965f4079930dacc31",
            9: "7c2c92a372e8fc4310f0b0d36bc1e3be106d9f93335532639cacf40e50ffba4c",
            12: "7c2c92a372e8fc4310f0b0d36bc1e3be106d9f93335532639cacf40e50ffba4c",
            17: "e74666fa9fa5f642fe3574803bf7ec2baca37cdb8b8f5dcaac9d9bcb507bde0c",
            32: "e74666fa9fa5f642fe3574803bf7ec2baca37cdb8b8f5dcaac9d9bcb507bde0c",
        },
    }

    def test_complete_match_and_route_plans(self) -> None:
        for entry_mode, snapshots in self.EXPECTED_DIGESTS.items():
            for participant_count, expected_digest in snapshots.items():
                with self.subTest(
                    entry_mode=entry_mode,
                    participant_count=participant_count,
                ):
                    self.assertEqual(
                        _plan_digest(participant_count, entry_mode),
                        expected_digest,
                    )

    def test_every_plan_contains_both_final_stages(self) -> None:
        for entry_mode in (
            tournament.ENTRY_ALL_WINNERS,
            tournament.ENTRY_SPLIT_BY_GROUP_SEED,
        ):
            matches = tournament.build_bracket_plan(8, entry_mode)
            match_codes = {match["match_code"] for match in matches}

            self.assertIn("GF", match_codes)
            self.assertIn("GFR", match_codes)

    def test_grand_final_reset_has_no_normal_incoming_route(self) -> None:
        for entry_mode in (
            tournament.ENTRY_ALL_WINNERS,
            tournament.ENTRY_SPLIT_BY_GROUP_SEED,
        ):
            routes = tournament.build_bracket_route_plan(8, entry_mode)
            self.assertNotIn(
                "GFR",
                {route["target_code"] for route in routes},
            )


class BracketModuleBoundaryTests(unittest.TestCase):
    """Keep the compatibility facade wired to the focused modules."""

    def test_tournament_manager_keeps_existing_public_imports(self) -> None:
        self.assertIs(
            tournament.get_bracket_size,
            bracket_seeding.get_bracket_size,
        )
        self.assertIs(
            tournament.build_bracket_plan,
            bracket_matches.build_bracket_plan,
        )
        self.assertIs(
            tournament.build_bracket_route_plan,
            bracket_routes.build_bracket_route_plan,
        )

    def test_compatibility_facade_reexports_focused_implementations(
        self,
    ) -> None:
        self.assertIs(
            bracket_planning.get_standard_seed_order,
            bracket_seeding.get_standard_seed_order,
        )
        self.assertIs(
            bracket_planning.build_split_bracket_plan,
            bracket_matches.build_split_bracket_plan,
        )
        self.assertIs(
            bracket_planning.build_split_bracket_route_plan,
            bracket_routes.build_split_bracket_route_plan,
        )


if __name__ == "__main__":
    unittest.main()
