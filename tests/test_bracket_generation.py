"""Database-level tests for creating and resetting draft brackets."""

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
from tournament import bracket_generation  # noqa: E402
from tournament import legacy_split_bracket  # noqa: E402


class BracketGenerationModuleBoundaryTests(unittest.TestCase):
    """Keep existing helper imports available after extraction."""

    def test_active_helpers_are_reexported_unchanged(self) -> None:
        for function_name in (
            "create_draft_bracket_matches",
            "create_draft_bracket_routes",
            "seed_draft_bracket_matches",
            "reset_draft_bracket",
            "get_draft_bracket_matches",
            "get_draft_bracket_routes",
            "get_draft_bracket_state",
        ):
            self.assertIs(
                getattr(tournament, function_name),
                getattr(bracket_generation, function_name),
            )

    def test_legacy_split_helpers_remain_importable(self) -> None:
        for function_name in (
            "create_draft_split_bracket_matches",
            "create_draft_split_bracket_routes",
            "seed_draft_split_bracket_matches",
        ):
            self.assertIs(
                getattr(tournament, function_name),
                getattr(legacy_split_bracket, function_name),
            )


class BracketGenerationTests(unittest.TestCase):
    """Generate a real five-player all-Winners bracket."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temporary_directory.name)
            / "bracket-generation.db"
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
                / "004_add_double_elimination_bracket.sql",
            ):
                connection.executescript(sql_path.read_text())

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
                    'double_elimination',
                    'all_winners'
                )
                """
            )

            for seed, player_id in enumerate(
                ("a", "b", "c", "d", "e"),
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

    def table_count(self, table_name: str) -> int:
        allowed_tables = {
            "tournament_draft_bracket_seeds",
            "tournament_draft_bracket_matches",
            "tournament_draft_bracket_routes",
        }

        if table_name not in allowed_tables:
            self.fail(f"Unsupported test table: {table_name}")

        with tournament.connect_db(self.db_path) as connection:
            return int(
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table_name}
                    WHERE draft_id = 'draft'
                    """
                ).fetchone()[0]
            )

    def test_generate_creates_seeded_and_propagated_bracket(
        self,
    ) -> None:
        result = tournament.generate_draft_bracket(
            self.db_path,
            "draft",
        )
        state = tournament.get_draft_bracket_state(
            self.db_path,
            "draft",
        )
        matches_by_code = {
            match["match_code"]: match
            for match in state["matches"]
        }

        self.assertEqual(result["participant_count"], 5)
        self.assertEqual(result["bracket_size"], 8)
        self.assertEqual(result["matches_created"], state["match_count"])
        self.assertEqual(result["routes_created"], state["route_count"])
        self.assertEqual(
            [
                (row["player_id"], row["bracket_seed"])
                for row in result["seed_rows"]
            ],
            [
                ("a", 1),
                ("b", 2),
                ("c", 3),
                ("d", 4),
                ("e", 5),
            ],
        )
        self.assertEqual(matches_by_code["W1M1"]["status"], "bye")
        self.assertEqual(matches_by_code["W1M1"]["winner_id"], "a")
        self.assertEqual(state["played_set_count"], 0)
        self.assertEqual(
            state["playable_set_count"],
            state["ready_set_count"]
            + state["waiting_set_count"],
        )
        self.assertEqual(matches_by_code["W1M2"]["status"], "pending")
        self.assertEqual(
            {
                matches_by_code["W1M2"]["player_1_id"],
                matches_by_code["W1M2"]["player_2_id"],
            },
            {"d", "e"},
        )

    def test_create_four_player_split_entry_bracket_routes(
        self,
    ) -> None:
        with tournament.connect_db(self.db_path) as connection:
            connection.execute(
                """
                DELETE FROM tournament_draft_participants
                WHERE draft_id = 'draft'
                  AND player_id = 'e'
                """
            )
            connection.execute(
                """
                UPDATE tournament_drafts
                SET
                    format_type = 'group_stage_double_elimination',
                    bracket_entry_mode = ?
                WHERE draft_id = 'draft'
                """,
                (tournament.ENTRY_SPLIT_BY_GROUP_SEED,),
            )
            connection.executemany(
                """
                INSERT INTO tournament_draft_bracket_seeds (
                    draft_id,
                    player_id,
                    bracket_seed,
                    starts_in
                )
                VALUES ('draft', ?, ?, ?)
                """,
                [
                    (
                        player_id,
                        seed,
                        (
                            "winners"
                            if seed <= 2
                            else "losers"
                        ),
                    )
                    for seed, player_id in enumerate(
                        ("a", "b", "c", "d"),
                        start=1,
                    )
                ],
            )

        matches = tournament.create_draft_bracket_matches(
            self.db_path,
            "draft",
        )
        routes = tournament.create_draft_bracket_routes(
            self.db_path,
            "draft",
        )
        seeded_matches = tournament.seed_draft_bracket_matches(
            self.db_path,
            "draft",
        )
        state = tournament.get_draft_bracket_state(
            self.db_path,
            "draft",
        )
        matches_by_code = {
            match["match_code"]: match
            for match in state["matches"]
        }
        match_codes = {
            match["match_code"]
            for match in state["matches"]
        }

        self.assertEqual(
            match_codes,
            {"WF", "L1M1", "LF", "GF", "GFR"},
        )
        self.assertEqual(
            len(matches),
            5,
        )
        self.assertEqual(
            len(routes),
            4,
        )
        self.assertEqual(
            {
                row["match_code"]
                for row in seeded_matches
            },
            {"WF", "L1M1"},
        )
        self.assertEqual(
            {
                matches_by_code["WF"]["player_1_id"],
                matches_by_code["WF"]["player_2_id"],
            },
            {"a", "b"},
        )
        self.assertEqual(
            {
                matches_by_code["L1M1"]["player_1_id"],
                matches_by_code["L1M1"]["player_2_id"],
            },
            {"c", "d"},
        )

    def test_reset_removes_every_generated_bracket_row(
        self,
    ) -> None:
        tournament.generate_draft_bracket(
            self.db_path,
            "draft",
        )

        result = tournament.reset_draft_bracket(
            self.db_path,
            "draft",
        )

        self.assertGreater(result["matches_deleted"], 0)
        self.assertGreater(result["routes_deleted"], 0)
        self.assertEqual(result["seeds_deleted"], 5)
        self.assertEqual(
            self.table_count(
                "tournament_draft_bracket_matches"
            ),
            0,
        )
        self.assertEqual(
            self.table_count(
                "tournament_draft_bracket_routes"
            ),
            0,
        )
        self.assertEqual(
            self.table_count(
                "tournament_draft_bracket_seeds"
            ),
            0,
        )

        with tournament.connect_db(self.db_path) as connection:
            assigned_seed_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM tournament_draft_participants
                WHERE draft_id = 'draft'
                  AND bracket_seed IS NOT NULL
                """
            ).fetchone()[0]

        self.assertEqual(assigned_seed_count, 0)

    def test_second_generation_does_not_modify_existing_bracket(
        self,
    ) -> None:
        tournament.generate_draft_bracket(
            self.db_path,
            "draft",
        )
        original_counts = (
            self.table_count(
                "tournament_draft_bracket_seeds"
            ),
            self.table_count(
                "tournament_draft_bracket_matches"
            ),
            self.table_count(
                "tournament_draft_bracket_routes"
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "already been generated",
        ):
            tournament.generate_draft_bracket(
                self.db_path,
                "draft",
            )

        self.assertEqual(
            (
                self.table_count(
                    "tournament_draft_bracket_seeds"
                ),
                self.table_count(
                    "tournament_draft_bracket_matches"
                ),
                self.table_count(
                    "tournament_draft_bracket_routes"
                ),
            ),
            original_counts,
        )

    def test_partial_generation_is_cleaned_up_after_failure(
        self,
    ) -> None:
        with tournament.connect_db(self.db_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_bracket_route
                BEFORE INSERT
                ON tournament_draft_bracket_routes
                BEGIN
                    SELECT RAISE(ABORT, 'route blocked');
                END
                """
            )

        with self.assertRaisesRegex(
            sqlite3.IntegrityError,
            "route blocked",
        ):
            tournament.generate_draft_bracket(
                self.db_path,
                "draft",
            )

        self.assertEqual(
            self.table_count(
                "tournament_draft_bracket_seeds"
            ),
            0,
        )
        self.assertEqual(
            self.table_count(
                "tournament_draft_bracket_matches"
            ),
            0,
        )
        self.assertEqual(
            self.table_count(
                "tournament_draft_bracket_routes"
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
