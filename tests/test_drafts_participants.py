"""Database-level tests for drafts, participants, and seeding."""

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
from tournament import drafts  # noqa: E402
from tournament import participants  # noqa: E402
from tournament import seeding  # noqa: E402


class DraftParticipantModuleBoundaryTests(unittest.TestCase):
    """Keep existing tournament_manager imports after extraction."""

    def test_draft_functions_are_reexported_unchanged(self) -> None:
        for function_name in (
            "validate_draft_configuration",
            "create_draft",
            "update_draft_date",
            "list_drafts",
            "get_draft",
            "delete_draft",
        ):
            self.assertIs(
                getattr(tournament, function_name),
                getattr(drafts, function_name),
            )

    def test_participant_functions_are_reexported_unchanged(
        self,
    ) -> None:
        for function_name in (
            "create_player",
            "create_player_and_add_to_draft",
            "add_participant",
            "update_participant",
            "remove_participant",
        ):
            self.assertIs(
                getattr(tournament, function_name),
                getattr(participants, function_name),
            )

    def test_seeding_functions_are_reexported_unchanged(self) -> None:
        for function_name in (
            "assign_manual_seeds",
            "get_automatic_seed_order",
            "apply_automatic_seeding",
            "save_participant_order",
        ):
            self.assertIs(
                getattr(tournament, function_name),
                getattr(seeding, function_name),
            )


class DraftParticipantTests(unittest.TestCase):
    """Exercise the editable draft lifecycle against the real schema."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temporary_directory.name)
            / "draft-participants.db"
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

        self.draft_id = tournament.create_draft(
            self.db_path,
            999,
            None,
            tournament.FORMAT_DOUBLE_ELIMINATION,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def add_players(self, *names: str) -> list[str]:
        return [
            tournament.create_player_and_add_to_draft(
                self.db_path,
                self.draft_id,
                name,
            )
            for name in names
        ]

    def participant_order(self) -> list[tuple[str, int, int]]:
        draft = tournament.get_draft(
            self.db_path,
            self.draft_id,
        )
        return [
            (
                str(row["player"]),
                int(row["manual_seed"]),
                int(row["bracket_seed"]),
            )
            for row in draft["participants"]
        ]

    def test_create_and_update_draft(self) -> None:
        tournament.update_draft_date(
            self.db_path,
            self.draft_id,
            " 2026-08-01 ",
        )

        draft = tournament.get_draft(
            self.db_path,
            self.draft_id,
        )
        drafts = tournament.list_drafts(
            self.db_path,
        )

        self.assertEqual(draft["tournament_number"], 999)
        self.assertEqual(draft["tournament_date"], "2026-08-01")
        self.assertEqual(drafts[0]["draft_id"], self.draft_id)
        self.assertEqual(drafts[0]["participant_count"], 0)

        with self.assertRaisesRegex(
            ValueError,
            "already exists",
        ):
            tournament.create_draft(
                self.db_path,
                999,
                None,
                tournament.FORMAT_DOUBLE_ELIMINATION,
            )

    def test_new_players_receive_consecutive_seeds(self) -> None:
        self.add_players("Alpha", "Bravo", "Charlie")

        self.assertEqual(
            self.participant_order(),
            [
                ("Alpha", 1, 1),
                ("Bravo", 2, 2),
                ("Charlie", 3, 3),
            ],
        )

    def test_remove_participant_closes_seed_gap(self) -> None:
        _, bravo_id, _ = self.add_players(
            "Alpha",
            "Bravo",
            "Charlie",
        )

        tournament.remove_participant(
            self.db_path,
            self.draft_id,
            bravo_id,
        )

        self.assertEqual(
            self.participant_order(),
            [
                ("Alpha", 1, 1),
                ("Charlie", 2, 2),
            ],
        )

    def test_save_order_and_create_seed_snapshot(self) -> None:
        alpha_id, bravo_id, charlie_id = self.add_players(
            "Alpha",
            "Bravo",
            "Charlie",
        )

        tournament.save_participant_order(
            self.db_path,
            self.draft_id,
            [charlie_id, alpha_id, bravo_id],
        )
        snapshot = tournament.create_draft_bracket_seed_snapshot(
            self.db_path,
            self.draft_id,
        )

        self.assertEqual(
            self.participant_order(),
            [
                ("Charlie", 1, 1),
                ("Alpha", 2, 2),
                ("Bravo", 3, 3),
            ],
        )
        self.assertEqual(
            [
                (row["player_id"], row["bracket_seed"])
                for row in snapshot
            ],
            [
                (charlie_id, 1),
                (alpha_id, 2),
                (bravo_id, 3),
            ],
        )

    def test_delete_draft_cascades_participants(self) -> None:
        self.add_players("Alpha", "Bravo", "Charlie")

        tournament.delete_draft(
            self.db_path,
            self.draft_id,
        )

        with tournament.connect_db(self.db_path) as connection:
            draft_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM tournament_drafts
                WHERE draft_id = ?
                """,
                (self.draft_id,),
            ).fetchone()[0]
            participant_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM tournament_draft_participants
                WHERE draft_id = ?
                """,
                (self.draft_id,),
            ).fetchone()[0]
            player_count = connection.execute(
                "SELECT COUNT(*) FROM players"
            ).fetchone()[0]

        self.assertEqual(draft_count, 0)
        self.assertEqual(participant_count, 0)
        self.assertEqual(player_count, 3)


if __name__ == "__main__":
    unittest.main()
