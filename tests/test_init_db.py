"""Tests for creating a complete database from the checked-in schema."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from init_db import (
    DEFAULT_MIGRATIONS_DIR,
    DEFAULT_SCHEMA_PATH,
    initialize_database,
)


class InitializeDatabaseTests(unittest.TestCase):
    def test_new_database_applies_all_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            db_path = temporary_path / "new.db"
            seed_path = temporary_path / "seed.json"
            seed_path.write_text(
                json.dumps(
                    {
                        "players": [
                            {
                                "player_id": "winner",
                                "display_name": "Winner",
                            }
                        ],
                        "tournaments": [
                            {
                                "tournament_id": "wm-1",
                                "tournament_number": 1,
                                "tournament_date": "2026-01-01",
                                "winner_id": "winner",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            initialize_database(
                db_path,
                DEFAULT_SCHEMA_PATH,
                seed_path,
                migrations_dir=DEFAULT_MIGRATIONS_DIR,
            )

            with sqlite3.connect(db_path) as connection:
                match_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(matches)"
                    )
                }
                draft_table = connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'tournament_drafts'
                    """
                ).fetchone()

            self.assertTrue(
                {
                    "stage",
                    "suggested_play_order",
                    "completed_at",
                }.issubset(match_columns)
            )
            self.assertIsNotNone(draft_table)


if __name__ == "__main__":
    unittest.main()
