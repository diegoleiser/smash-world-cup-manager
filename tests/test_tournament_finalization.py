"""Database-level tests for previewing and archiving tournament drafts."""

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
from tournament import finalization  # noqa: E402


class TournamentFinalizationTests(unittest.TestCase):
    """Exercise finalization against the real project schema."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temporary_directory.name)
            / "tournament-finalization.db"
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
                PROJECT_ROOT
                / "src"
                / "migrations"
                / "005_add_match_archive_metadata.sql",
            ):
                connection.executescript(sql_path.read_text())

            for player_id, display_name in (
                ("a", "Alpha"),
                ("b", "Bravo"),
                ("c", "Charlie"),
                ("d", "Delta"),
            ):
                connection.execute(
                    """
                    INSERT INTO players (player_id, display_name)
                    VALUES (?, ?)
                    """,
                    (player_id, display_name),
                )

            connection.execute(
                """
                INSERT INTO tournament_drafts (
                    draft_id,
                    tournament_number,
                    tournament_date,
                    format_type,
                    bracket_entry_mode
                )
                VALUES (
                    'draft',
                    999,
                    '2026-07-24',
                    'double_elimination',
                    'all_winners'
                )
                """
            )

            for seed, player_id in enumerate(
                ("a", "b", "c", "d"),
                start=1,
            ):
                connection.execute(
                    """
                    INSERT INTO tournament_draft_participants (
                        draft_id,
                        player_id,
                        manual_seed,
                        bracket_seed
                    )
                    VALUES ('draft', ?, ?, ?)
                    """,
                    (player_id, seed, seed),
                )

            self._insert_match(
                connection,
                match_id="l1",
                match_code="L1M1",
                bracket_side="losers",
                round_number=1,
                match_number=1,
                match_type="standard",
                player_1_id="c",
                player_2_id="d",
                winner_id="c",
                score_1=2,
                score_2=0,
                status="completed",
            )
            self._insert_match(
                connection,
                match_id="lf",
                match_code="LF",
                bracket_side="losers",
                round_number=2,
                match_number=1,
                match_type="losers_final",
                player_1_id="b",
                player_2_id="c",
                winner_id="b",
                score_1=3,
                score_2=1,
                status="completed",
            )
            self._insert_match(
                connection,
                match_id="gf",
                match_code="GF",
                bracket_side="finals",
                round_number=1,
                match_number=1,
                match_type="grand_final",
                player_1_id="a",
                player_2_id="b",
                winner_id="a",
                score_1=3,
                score_2=1,
                status="completed",
            )
            self._insert_match(
                connection,
                match_id="gfr",
                match_code="GFR",
                bracket_side="finals",
                round_number=2,
                match_number=1,
                match_type="grand_final_reset",
                status="inactive",
            )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def _insert_match(
        connection: sqlite3.Connection,
        *,
        match_id: str,
        match_code: str,
        bracket_side: str,
        round_number: int,
        match_number: int,
        match_type: str,
        player_1_id: str | None = None,
        player_2_id: str | None = None,
        winner_id: str | None = None,
        score_1: int | None = None,
        score_2: int | None = None,
        status: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO tournament_draft_bracket_matches (
                bracket_match_id,
                draft_id,
                match_code,
                bracket_side,
                round_number,
                match_number,
                round_label,
                match_type,
                player_1_id,
                player_2_id,
                winner_id,
                player_1_score,
                player_2_score,
                status,
                completed_at
            )
            VALUES (
                ?, 'draft', ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
            )
            """,
            (
                match_id,
                match_code,
                bracket_side,
                round_number,
                match_number,
                match_code,
                match_type,
                player_1_id,
                player_2_id,
                winner_id,
                score_1,
                score_2,
                status,
            ),
        )

    def test_preview_calculates_all_placements(self) -> None:
        preview = tournament.get_draft_finalization_preview(
            self.db_path,
            "draft",
        )

        self.assertEqual(preview["champion_id"], "a")
        self.assertEqual(preview["champion_name"], "Alpha")
        self.assertEqual(
            [
                (row["player_id"], row["placement"], row["seed"])
                for row in preview["placements"]
            ],
            [
                ("a", 1, 1),
                ("b", 2, 2),
                ("c", 3, 3),
                ("d", 4, 4),
            ],
        )
        self.assertEqual(preview["bracket_matches_to_archive"], 3)
        self.assertEqual(preview["automatic_bracket_matches_omitted"], 1)
        self.assertTrue(preview["ready"])

    def test_cancelled_losers_match_places_worse_seed_first(
        self,
    ) -> None:
        with tournament.connect_db(self.db_path) as connection:
            connection.execute(
                """
                UPDATE tournament_draft_bracket_matches
                SET status = 'cancelled',
                    winner_id = NULL,
                    player_1_score = NULL,
                    player_2_score = NULL
                WHERE match_code = 'L1M1'
                """
            )

        preview = tournament.get_draft_finalization_preview(
            self.db_path,
            "draft",
        )

        self.assertEqual(
            [
                (row["player_id"], row["placement"])
                for row in preview["placements"]
            ],
            [
                ("a", 1),
                ("b", 2),
                ("c", 3),
                ("d", 4),
            ],
        )
        self.assertEqual(preview["bracket_matches_to_archive"], 2)

    def test_finalize_archives_matches_and_completes_draft(self) -> None:
        with tournament.connect_db(self.db_path) as connection:
            connection.execute(
                """
                UPDATE players
                SET active = 0
                WHERE player_id = 'd'
                """
            )

        result = tournament.finalize_draft_tournament(
            self.db_path,
            "draft",
        )

        with tournament.connect_db(self.db_path) as connection:
            archived_tournament = connection.execute(
                """
                SELECT tournament_number, winner_id, bracket_source
                FROM tournaments
                WHERE tournament_id = ?
                """,
                (result["tournament_id"],),
            ).fetchone()
            placements = connection.execute(
                """
                SELECT player_id, placement, seed
                FROM tournament_participants
                WHERE tournament_id = ?
                ORDER BY placement
                """,
                (result["tournament_id"],),
            ).fetchall()
            matches = connection.execute(
                """
                SELECT
                    stage,
                    bracket_side,
                    score_known,
                    walkover,
                    suggested_play_order
                FROM matches
                WHERE tournament_id = ?
                ORDER BY suggested_play_order
                """,
                (result["tournament_id"],),
            ).fetchall()
            draft_status = connection.execute(
                """
                SELECT status
                FROM tournament_drafts
                WHERE draft_id = 'draft'
                """
            ).fetchone()["status"]
            reactivated_player = connection.execute(
                """
                SELECT active
                FROM players
                WHERE player_id = 'd'
                """
            ).fetchone()["active"]

        self.assertEqual(
            tuple(archived_tournament),
            (999, "a", "tournament_manager"),
        )
        self.assertEqual(
            [tuple(row) for row in placements],
            [
                ("a", 1, 1),
                ("b", 2, 2),
                ("c", 3, 3),
                ("d", 4, 4),
            ],
        )
        self.assertEqual(len(matches), 3)
        self.assertTrue(all(row["stage"] == "bracket" for row in matches))
        self.assertEqual(
            [row["suggested_play_order"] for row in matches],
            [1, 2, 3],
        )
        self.assertEqual(draft_status, "completed")
        self.assertEqual(reactivated_player, 1)
        self.assertEqual(result["matches_archived"], 3)

    def test_unfinished_match_blocks_preview(self) -> None:
        with tournament.connect_db(self.db_path) as connection:
            connection.execute(
                """
                UPDATE tournament_draft_bracket_matches
                SET status = 'pending',
                    winner_id = NULL,
                    player_1_score = NULL,
                    player_2_score = NULL
                WHERE match_code = 'LF'
                """
            )

        with self.assertRaisesRegex(
            ValueError,
            "Unfinished matches: LF",
        ):
            tournament.get_draft_finalization_preview(
                self.db_path,
                "draft",
            )

    def test_archive_failure_rolls_back_every_write(self) -> None:
        with tournament.connect_db(self.db_path) as connection:
            connection.execute(
                """
                UPDATE players
                SET active = 0
                WHERE player_id = 'd'
                """
            )
            connection.execute(
                """
                CREATE TRIGGER reject_archived_match
                BEFORE INSERT ON matches
                BEGIN
                    SELECT RAISE(ABORT, 'archive blocked');
                END
                """
            )

        with self.assertRaisesRegex(
            sqlite3.IntegrityError,
            "archive blocked",
        ):
            tournament.finalize_draft_tournament(
                self.db_path,
                "draft",
            )

        with tournament.connect_db(self.db_path) as connection:
            tournament_count = connection.execute(
                "SELECT COUNT(*) FROM tournaments"
            ).fetchone()[0]
            participant_count = connection.execute(
                "SELECT COUNT(*) FROM tournament_participants"
            ).fetchone()[0]
            draft_status = connection.execute(
                """
                SELECT status
                FROM tournament_drafts
                WHERE draft_id = 'draft'
                """
            ).fetchone()["status"]
            inactive_player = connection.execute(
                """
                SELECT active
                FROM players
                WHERE player_id = 'd'
                """
            ).fetchone()["active"]

        self.assertEqual(tournament_count, 0)
        self.assertEqual(participant_count, 0)
        self.assertEqual(draft_status, "draft")
        self.assertEqual(inactive_player, 0)


class TournamentFinalizationModuleBoundaryTests(unittest.TestCase):
    """Keep the existing tournament_manager API after extraction."""

    def test_public_functions_are_reexported_unchanged(self) -> None:
        self.assertIs(
            tournament.get_draft_finalization_preview,
            finalization.get_draft_finalization_preview,
        )
        self.assertIs(
            tournament.finalize_draft_tournament,
            finalization.finalize_draft_tournament,
        )


if __name__ == "__main__":
    unittest.main()
