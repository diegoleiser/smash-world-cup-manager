"""Characterization tests for the current group-stage tournament rules."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import tournament_manager as tournament  # noqa: E402
from tournament import group_stage_pairings  # noqa: E402
from tournament import group_stage_ranking  # noqa: E402
from tournament import group_stage_standings  # noqa: E402


class RoundRobinPairingTests(unittest.TestCase):
    """Preserve the circle-method schedule and its validation rules."""

    def test_every_pair_plays_exactly_once(self) -> None:
        for player_count in range(2, 8):
            players = [
                f"player-{index}"
                for index in range(1, player_count + 1)
            ]

            with self.subTest(player_count=player_count):
                rounds = tournament.generate_round_robin_pairings(players)
                pairs = [
                    frozenset(pair)
                    for round_pairings in rounds
                    for pair in round_pairings
                ]

                self.assertEqual(
                    len(pairs),
                    player_count * (player_count - 1) // 2,
                )
                self.assertEqual(len(pairs), len(set(pairs)))

                for round_pairings in rounds:
                    players_in_round = [
                        player
                        for pair in round_pairings
                        for player in pair
                    ]
                    self.assertEqual(
                        len(players_in_round),
                        len(set(players_in_round)),
                    )

    def test_odd_groups_contain_no_persisted_bye_pair(self) -> None:
        rounds = tournament.generate_round_robin_pairings(
            ["a", "b", "c"],
        )

        self.assertEqual(len(rounds), 3)
        self.assertTrue(
            all(len(round_pairings) == 1 for round_pairings in rounds)
        )
        self.assertTrue(
            all(
                player is not None
                for round_pairings in rounds
                for pair in round_pairings
                for player in pair
            )
        )

    def test_invalid_player_lists_are_rejected(self) -> None:
        for players in ([], ["a"], ["a", "a"]):
            with self.subTest(players=players):
                with self.assertRaises(ValueError):
                    tournament.generate_round_robin_pairings(players)


class GroupStageModuleBoundaryTests(unittest.TestCase):
    """Keep legacy Tournament Manager imports wired to pure modules."""

    def test_pairing_function_is_reexported_unchanged(self) -> None:
        self.assertIs(
            tournament.generate_round_robin_pairings,
            group_stage_pairings.generate_round_robin_pairings,
        )

    def test_status_constants_are_reexported_unchanged(self) -> None:
        self.assertEqual(
            tournament.VALID_GROUP_MATCH_STATUSES,
            group_stage_standings.VALID_GROUP_MATCH_STATUSES,
        )

    def test_two_player_ranking_keeps_original_bracket_size(self) -> None:
        group = {
            "group_id": "group-1",
            "group_name": "Group 1",
            "pending_matches": 0,
            "cancelled_matches": 0,
            "total_matches": 1,
            "decided_matches": 1,
            "standings": [
                {
                    "player_id": player_id,
                    "player": player_name,
                    "placement": placement,
                    "set_win_percentage": percentage,
                    "game_win_percentage": percentage,
                    "games_won": games_won,
                    "initial_elo": 1000.0,
                    "initial_seed": placement,
                }
                for (
                    player_id,
                    player_name,
                    placement,
                    percentage,
                    games_won,
                ) in (
                    ("a", "Alpha", 1, 100.0, 2),
                    ("b", "Bravo", 2, 0.0, 0),
                )
            ],
        }

        ranking = group_stage_ranking.build_global_group_ranking(
            [group],
            tournament.ENTRY_ALL_WINNERS,
        )

        self.assertEqual(ranking["bracket_size"], 2)


class GroupStageDatabaseTestCase(unittest.TestCase):
    """Create the smallest real schema needed by standings calculations."""

    PLAYER_NAMES = {
        "a": "Alpha",
        "b": "Bravo",
        "c": "Charlie",
        "d": "Delta",
    }

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temporary_directory.name)
            / "group-stage-tests.db"
        )

        with closing(sqlite3.connect(self.db_path)) as connection, connection:
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

            for seed, (player_id, name) in enumerate(
                self.PLAYER_NAMES.items(),
                start=1,
            ):
                connection.execute(
                    """
                    INSERT INTO players (
                        player_id,
                        display_name
                    )
                    VALUES (?, ?)
                    """,
                    (player_id, name),
                )

            connection.execute(
                """
                INSERT INTO tournament_drafts (
                    draft_id,
                    tournament_number,
                    format_type,
                    bracket_entry_mode
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "draft",
                    999,
                    tournament.FORMAT_GROUP_STAGE,
                    tournament.ENTRY_SPLIT_BY_GROUP_SEED,
                ),
            )

            for seed, player_id in enumerate(
                self.PLAYER_NAMES,
                start=1,
            ):
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

        self.elo_patch = patch.object(
            tournament.stats,
            "get_elo_ranking",
            return_value=[
                {
                    "player_id": player_id,
                    "elo": 1000.0,
                }
                for player_id in self.PLAYER_NAMES
            ],
        )
        self.elo_patch.start()

    def tearDown(self) -> None:
        self.elo_patch.stop()
        self.temporary_directory.cleanup()

    def add_group(
        self,
        group_id: str,
        group_number: int,
        player_ids: list[str],
    ) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                """
                INSERT INTO tournament_draft_groups (
                    group_id,
                    draft_id,
                    group_number,
                    group_name
                )
                VALUES (?, 'draft', ?, ?)
                """,
                (
                    group_id,
                    group_number,
                    f"Group {group_number}",
                ),
            )

            for position, player_id in enumerate(
                player_ids,
                start=1,
            ):
                connection.execute(
                    """
                    INSERT INTO tournament_draft_group_members (
                        group_id,
                        player_id,
                        group_position
                    )
                    VALUES (?, ?, ?)
                    """,
                    (group_id, player_id, position),
                )

    def add_match(
        self,
        group_id: str,
        match_number: int,
        player_1_id: str,
        player_2_id: str,
        *,
        status: str,
        winner_id: str | None = None,
        player_1_score: int | None = None,
        player_2_score: int | None = None,
    ) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                """
                INSERT INTO tournament_draft_group_matches (
                    group_match_id,
                    group_id,
                    round_number,
                    match_number,
                    player_1_id,
                    player_2_id,
                    winner_id,
                    player_1_score,
                    player_2_score,
                    status
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{group_id}-match-{match_number}",
                    group_id,
                    match_number,
                    player_1_id,
                    player_2_id,
                    winner_id,
                    player_1_score,
                    player_2_score,
                    status,
                ),
            )


class GroupStandingsTests(GroupStageDatabaseTestCase):
    """Lock down set, game, completion, and tie-break behavior."""

    def test_direct_results_resolve_equal_set_wins(self) -> None:
        self.add_group("group-1", 1, ["a", "b", "c", "d"])

        results = [
            ("a", "b", "a"),
            ("c", "a", "c"),
            ("a", "d", "a"),
            ("b", "c", "b"),
            ("b", "d", "b"),
            ("d", "c", "d"),
        ]

        for match_number, (
            player_1,
            player_2,
            winner,
        ) in enumerate(results, start=1):
            self.add_match(
                "group-1",
                match_number,
                player_1,
                player_2,
                status=tournament.GROUP_MATCH_COMPLETED,
                winner_id=winner,
                player_1_score=2 if winner == player_1 else 1,
                player_2_score=2 if winner == player_2 else 1,
            )

        standings = tournament.get_draft_group_standings(
            self.db_path,
            "draft",
        )

        self.assertEqual(
            [
                player["player_id"]
                for player in standings[0]["standings"]
            ],
            ["a", "b", "d", "c"],
        )
        self.assertTrue(standings[0]["complete"])

    def test_unresolved_three_way_mini_table_uses_game_percentage(
        self,
    ) -> None:
        self.add_group("group-1", 1, ["a", "b", "c", "d"])

        results = [
            ("a", "b", "a", 3, 0),
            ("c", "a", "c", 3, 2),
            ("a", "d", "a", 3, 0),
            ("b", "c", "b", 3, 2),
            ("b", "d", "b", 3, 0),
            ("c", "d", "c", 3, 2),
        ]

        for match_number, result in enumerate(results, start=1):
            player_1, player_2, winner, score_1, score_2 = result
            self.add_match(
                "group-1",
                match_number,
                player_1,
                player_2,
                status=tournament.GROUP_MATCH_COMPLETED,
                winner_id=winner,
                player_1_score=score_1,
                player_2_score=score_2,
            )

        standings = tournament.get_draft_group_standings(
            self.db_path,
            "draft",
        )

        self.assertEqual(
            [
                player["player_id"]
                for player in standings[0]["standings"]
            ],
            ["a", "b", "c", "d"],
        )

    def test_forfeit_counts_as_set_but_not_games(self) -> None:
        self.add_group("group-1", 1, ["a", "b", "c"])
        self.add_match(
            "group-1",
            1,
            "a",
            "b",
            status=tournament.GROUP_MATCH_FORFEIT,
            winner_id="a",
        )
        self.add_match(
            "group-1",
            2,
            "a",
            "c",
            status=tournament.GROUP_MATCH_CANCELLED,
        )
        self.add_match(
            "group-1",
            3,
            "b",
            "c",
            status=tournament.GROUP_MATCH_PENDING,
        )

        group = tournament.get_draft_group_standings(
            self.db_path,
            "draft",
        )[0]
        alpha = next(
            player
            for player in group["standings"]
            if player["player_id"] == "a"
        )

        self.assertEqual(alpha["sets_played"], 1)
        self.assertEqual(alpha["sets_won"], 1)
        self.assertEqual(alpha["games_won"], 0)
        self.assertEqual(alpha["games_lost"], 0)
        self.assertIsNone(alpha["game_win_percentage"])
        self.assertFalse(group["complete"])
        self.assertEqual(group["cancelled_matches"], 1)
        self.assertEqual(group["pending_matches"], 1)


class GlobalGroupRankingTests(GroupStageDatabaseTestCase):
    """Preserve cross-group ordering and bracket-entry assignment."""

    def test_group_placement_precedes_cross_group_percentages(self) -> None:
        self.add_group("group-1", 1, ["a", "b"])
        self.add_group("group-2", 2, ["c", "d"])

        self.add_match(
            "group-1",
            1,
            "a",
            "b",
            status=tournament.GROUP_MATCH_COMPLETED,
            winner_id="a",
            player_1_score=2,
            player_2_score=0,
        )
        self.add_match(
            "group-2",
            1,
            "c",
            "d",
            status=tournament.GROUP_MATCH_COMPLETED,
            winner_id="c",
            player_1_score=2,
            player_2_score=1,
        )

        ranking = tournament.get_draft_global_group_ranking(
            self.db_path,
            "draft",
        )

        self.assertEqual(
            [
                player["player_id"]
                for player in ranking["ranking"]
            ],
            ["a", "c", "d", "b"],
        )
        self.assertEqual(ranking["bracket_size"], 4)
        self.assertEqual(ranking["winners_count"], 2)
        self.assertEqual(ranking["losers_count"], 2)
        self.assertEqual(
            [
                player["starts_in"]
                for player in ranking["ranking"]
            ],
            ["winners", "winners", "losers", "losers"],
        )
        self.assertTrue(ranking["complete"])


if __name__ == "__main__":
    unittest.main()
