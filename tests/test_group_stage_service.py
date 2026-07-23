"""Database-level tests for Group Stage draft services."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import tournament_manager as tournament  # noqa: E402
from tournament import group_stage_service  # noqa: E402


class GroupStageServiceModuleBoundaryTests(unittest.TestCase):
    """Keep all existing tournament_manager imports after extraction."""

    def test_group_stage_functions_are_reexported_unchanged(
        self,
    ) -> None:
        for function_name in (
            "get_draft_groups",
            "reset_draft_groups",
            "create_draft_groups",
            "move_draft_group_member",
            "get_draft_group_matches",
            "create_draft_group_matches",
            "reset_draft_group_matches",
            "update_draft_group_match",
            "get_draft_group_standings",
            "get_draft_global_group_ranking",
        ):
            self.assertIs(
                getattr(tournament, function_name),
                getattr(group_stage_service, function_name),
            )


class GroupStageServiceTests(unittest.TestCase):
    """Exercise one complete six-player Group Stage setup."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temporary_directory.name)
            / "group-stage-service.db"
        )

        with closing(
            sqlite3.connect(self.db_path)
        ) as connection, connection:
            for sql_path in (
                PROJECT_ROOT / "src" / "schema.sql",
                PROJECT_ROOT
                / "src"
                / "migrations"
                / "001_add_tournament_drafts.sql",
                PROJECT_ROOT
                / "src"
                / "migrations"
                / "002_add_group_stage_structure.sql",
                PROJECT_ROOT
                / "src"
                / "migrations"
                / "003_add_group_stage_matches.sql",
            ):
                connection.executescript(sql_path.read_text())

            connection.executescript(
                """
                ALTER TABLE matches ADD COLUMN stage TEXT;
                ALTER TABLE matches
                    ADD COLUMN suggested_play_order INTEGER;
                ALTER TABLE matches ADD COLUMN completed_at TEXT;
                """
            )

            connection.execute(
                """
                INSERT INTO tournament_drafts (
                    draft_id,
                    tournament_number,
                    format_type,
                    bracket_entry_mode
                )
                VALUES (
                    'draft',
                    999,
                    'group_stage_double_elimination',
                    'split_by_group_seed'
                )
                """
            )

            for seed, player_id in enumerate(
                ("a", "b", "c", "d", "e", "f"),
                start=1,
            ):
                connection.execute(
                    """
                    INSERT INTO players (player_id, display_name)
                    VALUES (?, ?)
                    """,
                    (player_id, player_id.upper()),
                )
                connection.execute(
                    """
                    INSERT INTO tournament_draft_participants (
                        draft_id,
                        player_id,
                        manual_seed
                    )
                    VALUES ('draft', ?, ?)
                    """,
                    (player_id, seed),
                )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_groups_use_snake_seeding(self) -> None:
        groups = tournament.create_draft_groups(
            self.db_path,
            "draft",
            2,
        )

        self.assertEqual(
            [
                [
                    member["player_id"]
                    for member in group["members"]
                ]
                for group in groups
            ],
            [
                ["a", "d", "e"],
                ["b", "c", "f"],
            ],
        )

    def test_move_member_and_generate_round_robin_matches(
        self,
    ) -> None:
        groups = tournament.create_draft_groups(
            self.db_path,
            "draft",
            2,
        )
        moved_groups = tournament.move_draft_group_member(
            self.db_path,
            "draft",
            "e",
            groups[1]["group_id"],
        )
        matches = tournament.create_draft_group_matches(
            self.db_path,
            "draft",
        )

        self.assertEqual(
            [len(group["members"]) for group in moved_groups],
            [2, 4],
        )
        self.assertEqual(len(matches), 7)
        self.assertEqual(
            len(
                {
                    (
                        match["group_id"],
                        frozenset(
                            (
                                match["player_1_id"],
                                match["player_2_id"],
                            )
                        ),
                    )
                    for match in matches
                }
            ),
            7,
        )

    def test_match_results_feed_standings_and_global_ranking(
        self,
    ) -> None:
        tournament.create_draft_groups(
            self.db_path,
            "draft",
            2,
        )
        matches = tournament.create_draft_group_matches(
            self.db_path,
            "draft",
        )

        for match in matches:
            tournament.update_draft_group_match(
                self.db_path,
                match["group_match_id"],
                status="completed",
                player_1_score=2,
                player_2_score=0,
            )

        standings = tournament.get_draft_group_standings(
            self.db_path,
            "draft",
        )
        ranking = tournament.get_draft_global_group_ranking(
            self.db_path,
            "draft",
        )

        self.assertEqual(len(standings), 2)
        self.assertTrue(all(group["complete"] for group in standings))
        self.assertTrue(ranking["complete"])
        self.assertEqual(len(ranking["ranking"]), 6)

    def test_draw_is_rejected_without_changing_match(self) -> None:
        tournament.create_draft_groups(
            self.db_path,
            "draft",
            2,
        )
        match = tournament.create_draft_group_matches(
            self.db_path,
            "draft",
        )[0]

        with self.assertRaisesRegex(
            ValueError,
            "cannot end in a draw",
        ):
            tournament.update_draft_group_match(
                self.db_path,
                match["group_match_id"],
                status="completed",
                player_1_score=1,
                player_2_score=1,
            )

        stored_match = next(
            row
            for row in tournament.get_draft_group_matches(
                self.db_path,
                "draft",
            )
            if row["group_match_id"]
            == match["group_match_id"]
        )
        self.assertEqual(stored_match["status"], "pending")

    def test_matches_and_groups_reset_in_required_order(self) -> None:
        tournament.create_draft_groups(
            self.db_path,
            "draft",
            2,
        )
        tournament.create_draft_group_matches(
            self.db_path,
            "draft",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Reset the group matches first",
        ):
            tournament.reset_draft_groups(
                self.db_path,
                "draft",
            )

        tournament.reset_draft_group_matches(
            self.db_path,
            "draft",
        )
        tournament.reset_draft_groups(
            self.db_path,
            "draft",
        )

        self.assertEqual(
            tournament.get_draft_group_matches(
                self.db_path,
                "draft",
            ),
            [],
        )
        self.assertEqual(
            tournament.get_draft_groups(
                self.db_path,
                "draft",
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
