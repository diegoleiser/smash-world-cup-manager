"""Tests for the public synthetic demo-data generator."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = PROJECT_ROOT / "examples"
SRC_DIR = PROJECT_ROOT / "src"
for path in (EXAMPLES_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from create_demo_database import create_demo_database  # noqa: E402
from monte_carlo.artifacts import load_artifact  # noqa: E402


class DemoDatabaseTests(unittest.TestCase):
    def test_generator_creates_archive_live_draft_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            db_path = temporary_path / "demo.db"
            artifact_path = temporary_path / "model"

            create_demo_database(db_path, artifact_path)

            with sqlite3.connect(db_path) as connection:
                player_count = connection.execute(
                    "SELECT COUNT(*) FROM players"
                ).fetchone()[0]
                tournament_count = connection.execute(
                    "SELECT COUNT(*) FROM tournaments"
                ).fetchone()[0]
                match_count = connection.execute(
                    "SELECT COUNT(*) FROM matches"
                ).fetchone()[0]
                archive_match = connection.execute(
                    """
                    SELECT
                        challonge_match_id,
                        challonge_identifier,
                        challonge_group_id,
                        challonge_round
                    FROM matches
                    LIMIT 1
                    """
                ).fetchone()
                live_draft = connection.execute(
                    """
                    SELECT draft_id, status
                    FROM tournament_drafts
                    WHERE tournament_number = 5
                    """
                ).fetchone()
                live_match_counts = connection.execute(
                    """
                    SELECT
                        COUNT(*),
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)
                    FROM tournament_draft_bracket_matches
                    WHERE draft_id = ?
                    """,
                    (live_draft[0],),
                ).fetchone()

            artifact = load_artifact(artifact_path)
            self.assertEqual(player_count, 8)
            self.assertEqual(tournament_count, 4)
            self.assertGreater(match_count, 40)
            self.assertEqual(archive_match, (None, None, None, None))
            self.assertEqual(live_draft[1], "draft")
            self.assertEqual(live_match_counts, (15, 3))
            self.assertEqual(len(artifact.model.players), 8)

    def test_generator_refuses_to_replace_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            db_path = temporary_path / "demo.db"
            artifact_path = temporary_path / "model"

            create_demo_database(db_path, artifact_path)

            with self.assertRaises(FileExistsError):
                create_demo_database(db_path, artifact_path)


if __name__ == "__main__":
    unittest.main()
