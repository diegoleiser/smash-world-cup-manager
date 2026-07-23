"""Database-level tests for Bracket results, resets, and Grand Finals."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import tournament_manager as tournament  # noqa: E402
from tournament import bracket_finalization  # noqa: E402
from tournament import bracket_progression  # noqa: E402
from tournament import bracket_results  # noqa: E402


class BracketDatabaseTestCase(unittest.TestCase):
    """Provide a minimal real Bracket schema and deterministic players."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temporary_directory.name)
            / "bracket-results.db"
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

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def add_match(
        self,
        match_id: str,
        match_code: str,
        *,
        bracket_side: str,
        round_number: int,
        match_number: int,
        match_type: str = "standard",
        player_1_id: str | None = None,
        player_2_id: str | None = None,
        winner_id: str | None = None,
        player_1_score: int | None = None,
        player_2_score: int | None = None,
        status: str = "waiting",
    ) -> None:
        with tournament.connect_db(self.db_path) as connection:
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
                    status
                )
                VALUES (
                    ?,
                    'draft',
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?
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
                    player_1_score,
                    player_2_score,
                    status,
                ),
            )

    def add_route(
        self,
        route_id: str,
        source_match_id: str,
        source_outcome: str,
        target_match_id: str,
        target_slot: int,
    ) -> None:
        with tournament.connect_db(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO tournament_draft_bracket_routes (
                    route_id,
                    draft_id,
                    source_match_id,
                    source_outcome,
                    target_match_id,
                    target_slot
                )
                VALUES (?, 'draft', ?, ?, ?, ?)
                """,
                (
                    route_id,
                    source_match_id,
                    source_outcome,
                    target_match_id,
                    target_slot,
                ),
            )

    def add_finals(
        self,
        *,
        gf_status: str = "waiting",
        gf_winner_id: str | None = None,
        gf_score_1: int | None = None,
        gf_score_2: int | None = None,
    ) -> None:
        self.add_match(
            "gf",
            "GF",
            bracket_side="finals",
            round_number=1,
            match_number=1,
            match_type="grand_final",
            player_1_id=(
                "a"
                if gf_status != "waiting"
                else None
            ),
            player_2_id=(
                "b"
                if gf_status != "waiting"
                else None
            ),
            winner_id=gf_winner_id,
            player_1_score=gf_score_1,
            player_2_score=gf_score_2,
            status=gf_status,
        )
        self.add_match(
            "gfr",
            "GFR",
            bracket_side="finals",
            round_number=2,
            match_number=1,
            match_type="grand_final_reset",
            status="inactive",
        )

    def load_match(self, match_id: str) -> dict[str, Any]:
        with tournament.connect_db(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM tournament_draft_bracket_matches
                WHERE bracket_match_id = ?
                """,
                (match_id,),
            ).fetchone()

        if row is None:
            self.fail(f"Match was not created: {match_id}")

        return dict(row)


class BracketResultModuleBoundaryTests(unittest.TestCase):
    """Keep the existing tournament_manager API after extraction."""

    def test_progression_function_is_reexported_unchanged(self) -> None:
        self.assertIs(
            tournament.propagate_draft_bracket_results,
            bracket_progression.propagate_draft_bracket_results,
        )

    def test_result_functions_are_reexported_unchanged(self) -> None:
        self.assertIs(
            tournament.update_draft_bracket_match,
            bracket_results.update_draft_bracket_match,
        )
        self.assertIs(
            tournament.reset_draft_bracket_match_result,
            bracket_results.reset_draft_bracket_match_result,
        )

    def test_finalization_functions_are_reexported_unchanged(self) -> None:
        self.assertIs(
            tournament.sync_draft_grand_final_reset,
            bracket_finalization.sync_draft_grand_final_reset,
        )
        self.assertIs(
            tournament.get_draft_bracket_champion,
            bracket_finalization.get_draft_bracket_champion,
        )


class BracketResultTests(BracketDatabaseTestCase):
    """Preserve score, Forfeit, routing, and reset behavior."""

    def prepare_routed_match(self) -> None:
        self.add_match(
            "source",
            "W1M1",
            bracket_side="winners",
            round_number=1,
            match_number=1,
            player_1_id="a",
            player_2_id="b",
            status="pending",
        )
        self.add_match(
            "winner-target",
            "WF",
            bracket_side="winners",
            round_number=2,
            match_number=1,
            match_type="winners_final",
        )
        self.add_match(
            "loser-target",
            "L1M1",
            bracket_side="losers",
            round_number=1,
            match_number=1,
        )
        self.add_route(
            "winner-route",
            "source",
            "winner",
            "winner-target",
            1,
        )
        self.add_route(
            "loser-route",
            "source",
            "loser",
            "loser-target",
            1,
        )
        self.add_finals()

    def test_completed_result_routes_winner_and_loser(self) -> None:
        self.prepare_routed_match()

        result = tournament.update_draft_bracket_match(
            self.db_path,
            "source",
            status="completed",
            player_1_score=3,
            player_2_score=1,
        )

        self.assertEqual(result["winner_id"], "a")
        self.assertEqual(
            self.load_match("winner-target")["player_1_id"],
            "a",
        )
        self.assertEqual(
            self.load_match("loser-target")["player_1_id"],
            "b",
        )

    def test_forfeit_routes_selected_winner_without_scores(self) -> None:
        self.prepare_routed_match()

        result = tournament.update_draft_bracket_match(
            self.db_path,
            "source",
            status="forfeit",
            winner_id="b",
        )
        source = self.load_match("source")

        self.assertEqual(result["winner_id"], "b")
        self.assertIsNone(source["player_1_score"])
        self.assertIsNone(source["player_2_score"])
        self.assertEqual(
            self.load_match("winner-target")["player_1_id"],
            "b",
        )
        self.assertEqual(
            self.load_match("loser-target")["player_1_id"],
            "a",
        )

    def test_reset_clears_every_dependent_match(self) -> None:
        self.prepare_routed_match()
        tournament.update_draft_bracket_match(
            self.db_path,
            "source",
            status="completed",
            player_1_score=2,
            player_2_score=0,
        )

        result = tournament.reset_draft_bracket_match_result(
            self.db_path,
            "source",
        )
        source = self.load_match("source")
        winner_target = self.load_match("winner-target")
        loser_target = self.load_match("loser-target")

        self.assertEqual(result["matches_cleared"], 2)
        self.assertEqual(source["status"], "pending")
        self.assertEqual(source["player_1_id"], "a")
        self.assertEqual(source["player_2_id"], "b")

        for target in (winner_target, loser_target):
            self.assertEqual(target["status"], "waiting")
            self.assertIsNone(target["player_1_id"])
            self.assertIsNone(target["player_2_id"])
            self.assertIsNone(target["winner_id"])


class GrandFinalTests(BracketDatabaseTestCase):
    """Preserve Champion and Grand Final Reset decisions."""

    def test_winners_side_grand_final_winner_is_champion(self) -> None:
        self.add_finals(
            gf_status="completed",
            gf_winner_id="a",
            gf_score_1=3,
            gf_score_2=1,
        )

        state = tournament.sync_draft_grand_final_reset(
            self.db_path,
            "draft",
        )

        self.assertFalse(state["reset_required"])
        self.assertEqual(state["champion_id"], "a")
        self.assertEqual(
            tournament.get_draft_bracket_champion(
                self.db_path,
                "draft",
            ),
            "a",
        )
        self.assertEqual(self.load_match("gfr")["status"], "inactive")

    def test_losers_side_win_activates_and_decides_reset(self) -> None:
        self.add_finals(
            gf_status="completed",
            gf_winner_id="b",
            gf_score_1=1,
            gf_score_2=3,
        )

        state = tournament.sync_draft_grand_final_reset(
            self.db_path,
            "draft",
        )
        reset_match = self.load_match("gfr")

        self.assertTrue(state["reset_required"])
        self.assertIsNone(state["champion_id"])
        self.assertEqual(reset_match["status"], "pending")
        self.assertEqual(reset_match["player_1_id"], "a")
        self.assertEqual(reset_match["player_2_id"], "b")

        result = tournament.update_draft_bracket_match(
            self.db_path,
            "gfr",
            status="completed",
            player_1_score=3,
            player_2_score=2,
        )

        self.assertEqual(result["champion_id"], "a")
        self.assertEqual(
            tournament.get_draft_bracket_champion(
                self.db_path,
                "draft",
            ),
            "a",
        )


if __name__ == "__main__":
    unittest.main()
