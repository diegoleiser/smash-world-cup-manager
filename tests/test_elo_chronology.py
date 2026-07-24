"""Regression tests for chronological Elo tournament ordering."""

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

from smash_stats import elo_history  # noqa: E402
from dashboard_pages.timeline_order import (  # noqa: E402
    chronological_tournament_labels,
)


class EloChronologyTests(unittest.TestCase):
    """Order imported tournament numbers by their actual date."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temporary_directory.name) / "elo-order.db"
        )

        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE players (
                    player_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    core_player INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE tournaments (
                    tournament_id TEXT PRIMARY KEY,
                    tournament_number INTEGER NOT NULL,
                    tournament_date TEXT
                );

                CREATE TABLE matches (
                    match_id TEXT PRIMARY KEY,
                    tournament_id TEXT NOT NULL,
                    round_label TEXT,
                    stage TEXT,
                    player_1_id TEXT,
                    player_2_id TEXT,
                    winner_id TEXT,
                    player_1_score INTEGER,
                    player_2_score INTEGER,
                    score_known INTEGER NOT NULL DEFAULT 1,
                    walkover INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT,
                    suggested_play_order INTEGER
                );

                INSERT INTO players (player_id, display_name)
                VALUES ('a', 'Alpha'), ('b', 'Bravo');

                INSERT INTO tournaments
                    (tournament_id, tournament_number, tournament_date)
                VALUES
                    ('later', 11, '2026-08-01'),
                    ('earlier', 102, '2026-07-31');

                INSERT INTO matches (
                    match_id,
                    tournament_id,
                    player_1_id,
                    player_2_id,
                    winner_id,
                    player_1_score,
                    player_2_score,
                    completed_at
                )
                VALUES
                    (
                        'later-match',
                        'later',
                        'a',
                        'b',
                        'a',
                        2,
                        0,
                        '2026-08-01 20:00:00'
                    ),
                    (
                        'earlier-match',
                        'earlier',
                        'a',
                        'b',
                        'b',
                        2,
                        3,
                        '2026-07-31 20:00:00'
                    );
                """
            )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_history_uses_date_before_tournament_number(self) -> None:
        history = elo_history.calculate_elo_history(self.db_path)

        self.assertEqual(
            [event["tournament_number"] for event in history],
            [102, 11],
        )

    def test_ranking_timeline_preserves_chronological_order(self) -> None:
        timeline = elo_history.get_elo_ranking_timeline(
            self.db_path,
            active_only=False,
        )
        tournament_order = list(
            dict.fromkeys(
                entry["tournament_number"]
                for entry in timeline
            )
        )

        self.assertEqual(tournament_order, [102, 11])

    def test_dashboard_order_uses_date_available_on_source_rows(
        self,
    ) -> None:
        labels = chronological_tournament_labels(
            [
                {
                    "tournament": "WM 11",
                    "tournament_number": 11,
                    "tournament_date": "2026-08-01",
                },
                {
                    "tournament": "WM 102",
                    "tournament_number": 102,
                    "tournament_date": "2026-07-31",
                },
                {
                    "tournament": "WM 102",
                    "tournament_number": 102,
                    "tournament_date": "2026-07-31",
                },
            ]
        )

        self.assertEqual(labels, ["WM 102", "WM 11"])


if __name__ == "__main__":
    unittest.main()
