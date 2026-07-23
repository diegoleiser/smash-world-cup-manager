"""Tests for shared SQLite transaction and connection lifecycle behavior."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import smash_statistics as statistics  # noqa: E402
import tournament_manager  # noqa: E402


class DatabaseConnectionTests(unittest.TestCase):
    """Verify both legacy entry points use the same safe lifecycle."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temporary_directory.name)
            / "connection-tests.db"
        )

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "CREATE TABLE values_table (value TEXT NOT NULL)"
            )
            connection.commit()
        finally:
            connection.close()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_connections_close_after_successful_context(self) -> None:
        for connect_db in (
            statistics.connect_db,
            tournament_manager.connect_db,
        ):
            with self.subTest(connect_db=connect_db.__module__):
                with connect_db(self.db_path) as connection:
                    connection.execute(
                        "INSERT INTO values_table VALUES ('saved')"
                    )

                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")

    def test_successful_context_commits_changes(self) -> None:
        with tournament_manager.connect_db(
            self.db_path
        ) as connection:
            connection.execute(
                "INSERT INTO values_table VALUES ('committed')"
            )

        verification = sqlite3.connect(self.db_path)
        try:
            count = verification.execute(
                "SELECT COUNT(*) FROM values_table"
            ).fetchone()[0]
        finally:
            verification.close()

        self.assertEqual(count, 1)

    def test_exception_rolls_back_and_still_closes(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with statistics.connect_db(
                self.db_path
            ) as connection:
                connection.execute(
                    "INSERT INTO values_table VALUES ('discarded')"
                )
                raise RuntimeError("rollback")

        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

        verification = sqlite3.connect(self.db_path)
        try:
            count = verification.execute(
                "SELECT COUNT(*) FROM values_table"
            ).fetchone()[0]
        finally:
            verification.close()

        self.assertEqual(count, 0)

    def test_missing_database_is_rejected(self) -> None:
        missing_path = (
            Path(self.temporary_directory.name)
            / "missing.db"
        )

        for connect_db in (
            statistics.connect_db,
            tournament_manager.connect_db,
        ):
            with self.subTest(connect_db=connect_db.__module__):
                with self.assertRaises(FileNotFoundError):
                    connect_db(missing_path)


if __name__ == "__main__":
    unittest.main()
