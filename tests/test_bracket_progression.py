"""Database-level tests for bracket result propagation."""

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


class CancelledBracketPropagationTests(unittest.TestCase):
    """Distinguish technical empty cancellations from real cancelled Sets."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temporary_directory.name)
            / "bracket-progression.db"
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

            for player_id in ("a", "b", "c", "d"):
                connection.execute(
                    """
                    INSERT INTO players (
                        player_id,
                        display_name
                    )
                    VALUES (?, ?)
                    """,
                    (player_id, player_id.upper()),
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
                    'double_elimination',
                    'all_winners'
                )
                """
            )

            for player_id, seed in (
                ("c", 1),
                ("a", 2),
                ("b", 3),
                ("d", 4),
            ):
                connection.execute(
                    """
                    INSERT INTO tournament_draft_participants (
                        draft_id,
                        player_id,
                        bracket_seed
                    )
                    VALUES ('draft', ?, ?)
                    """,
                    (player_id, seed),
                )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def create_source_and_target_matches(
        self,
        *,
        cancelled_player_1_id: str | None,
        cancelled_player_2_id: str | None,
    ) -> None:
        with tournament.connect_db(self.db_path) as connection:
            matches = [
                (
                    "cancelled-source",
                    "L1M1",
                    1,
                    1,
                    cancelled_player_1_id,
                    cancelled_player_2_id,
                    None,
                    "cancelled",
                ),
                (
                    "bye-source",
                    "L1M2",
                    1,
                    2,
                    "c",
                    None,
                    "c",
                    "bye",
                ),
                (
                    "target",
                    "L2M1",
                    2,
                    1,
                    None,
                    "c",
                    None,
                    "waiting",
                ),
                (
                    "other-finalist",
                    "WF",
                    1,
                    3,
                    "d",
                    None,
                    "d",
                    "bye",
                ),
                (
                    "final-target",
                    "LF",
                    3,
                    1,
                    None,
                    None,
                    None,
                    "waiting",
                ),
            ]

            connection.executemany(
                """
                INSERT INTO tournament_draft_bracket_matches (
                    bracket_match_id,
                    draft_id,
                    match_code,
                    bracket_side,
                    round_number,
                    match_number,
                    round_label,
                    player_1_id,
                    player_2_id,
                    winner_id,
                    status
                )
                VALUES (
                    ?,
                    'draft',
                    ?,
                    'losers',
                    ?,
                    ?,
                    'Losers Round',
                    ?,
                    ?,
                    ?,
                    ?
                )
                """,
                matches,
            )

            connection.executemany(
                """
                INSERT INTO tournament_draft_bracket_routes (
                    route_id,
                    draft_id,
                    source_match_id,
                    source_outcome,
                    target_match_id,
                    target_slot
                )
                VALUES (?, 'draft', ?, 'winner', ?, ?)
                """,
                [
                    (
                        "route-1",
                        "cancelled-source",
                        "target",
                        1,
                    ),
                    (
                        "route-2",
                        "bye-source",
                        "target",
                        2,
                    ),
                    (
                        "route-3",
                        "target",
                        "final-target",
                        1,
                    ),
                    (
                        "route-4",
                        "other-finalist",
                        "final-target",
                        2,
                    ),
                ],
            )

    def load_target(self) -> sqlite3.Row:
        with tournament.connect_db(self.db_path) as connection:
            target = connection.execute(
                """
                SELECT
                    player_1_id,
                    player_2_id,
                    winner_id,
                    status
                FROM tournament_draft_bracket_matches
                WHERE bracket_match_id = 'target'
                """
            ).fetchone()

        if target is None:
            self.fail("Target match was not created.")

        return target

    def test_real_cancelled_match_uses_seeds_for_placements(
        self,
    ) -> None:
        self.create_source_and_target_matches(
            cancelled_player_1_id="a",
            cancelled_player_2_id="b",
        )

        tournament.propagate_draft_bracket_results(
            self.db_path,
            "draft",
        )

        target = self.load_target()

        # A is better seeded than B and occupies the next placement
        # position. C qualified normally, so C advances automatically.
        self.assertEqual(target["status"], "forfeit")
        self.assertEqual(target["player_1_id"], "a")
        self.assertEqual(target["player_2_id"], "c")
        self.assertEqual(target["winner_id"], "c")

        with tournament.connect_db(self.db_path) as connection:
            final_target = connection.execute(
                """
                SELECT
                    player_1_id,
                    player_2_id,
                    winner_id,
                    status
                FROM tournament_draft_bracket_matches
                WHERE bracket_match_id = 'final-target'
                """
            ).fetchone()

        if final_target is None:
            self.fail("Final target match was not created.")

        self.assertEqual(final_target["player_1_id"], "c")
        self.assertEqual(final_target["player_2_id"], "d")
        self.assertEqual(final_target["status"], "pending")
        self.assertIsNone(final_target["winner_id"])

    def test_empty_cancelled_placeholder_still_creates_bye(
        self,
    ) -> None:
        self.create_source_and_target_matches(
            cancelled_player_1_id=None,
            cancelled_player_2_id=None,
        )

        tournament.propagate_draft_bracket_results(
            self.db_path,
            "draft",
        )

        target = self.load_target()

        self.assertEqual(target["status"], "bye")
        self.assertEqual(target["winner_id"], "c")


if __name__ == "__main__":
    unittest.main()
