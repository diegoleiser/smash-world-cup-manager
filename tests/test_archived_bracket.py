"""Tests for reconstructing archived Tournament Manager brackets."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from tournament.archived_bracket import (  # noqa: E402
    build_archived_bracket_matches,
    build_archived_bracket_routes,
)


def archived_match(
    match_code: str,
    round_label: str,
    bracket_side: str,
    player_1: str,
    player_2: str,
    winner: str,
    play_order: int,
    *,
    walkover: bool = False,
) -> dict[str, Any]:
    """Build the archive shape returned by load_tournament_detail."""

    return {
        "match_id": match_code.lower(),
        "stage": "bracket",
        "round_label": f"{round_label} ({match_code})",
        "bracket_side": bracket_side,
        "challonge_identifier": None,
        "challonge_round": None,
        "suggested_play_order": play_order,
        "player_1_id": player_1.lower(),
        "player_1": player_1,
        "player_2_id": player_2.lower(),
        "player_2": player_2,
        "winner_id": winner.lower(),
        "winner": winner,
        "player_1_score": None if walkover else 2,
        "player_2_score": None if walkover else 0,
        "score_known": int(not walkover),
        "walkover": int(walkover),
    }


class ArchivedTournamentManagerBracketTests(unittest.TestCase):
    """Rebuild cards and routes without Challonge metadata."""

    def setUp(self) -> None:
        self.matches = [
            archived_match(
                "W1M2",
                "Winners Round 1",
                "winners",
                "Diego",
                "Frutos",
                "Diego",
                1,
            ),
            archived_match(
                "W2M1",
                "Winners Round 2",
                "winners",
                "Adem",
                "Diego",
                "Diego",
                2,
                walkover=True,
            ),
            archived_match(
                "W2M2",
                "Winners Round 2",
                "winners",
                "Ammar",
                "Beniam",
                "Ammar",
                3,
            ),
            archived_match(
                "WF",
                "Winners Final",
                "winners",
                "Diego",
                "Ammar",
                "Diego",
                4,
            ),
            archived_match(
                "L3M1",
                "Losers Round 3",
                "losers",
                "Beniam",
                "Adem",
                "Adem",
                5,
                walkover=True,
            ),
            archived_match(
                "LF",
                "Losers Final",
                "losers",
                "Adem",
                "Ammar",
                "Ammar",
                6,
            ),
            archived_match(
                "GF",
                "Grand Final",
                "finals",
                "Diego",
                "Ammar",
                "Diego",
                7,
            ),
        ]

    def test_match_codes_restore_visual_rounds(self) -> None:
        bracket_matches = build_archived_bracket_matches(
            self.matches
        )
        matches_by_code = {
            match["match_code"]: match
            for match in bracket_matches
        }

        self.assertEqual(len(bracket_matches), 7)
        self.assertEqual(
            matches_by_code["W2M1"]["round_number"],
            2,
        )
        self.assertEqual(
            matches_by_code["WF"]["round_number"],
            3,
        )
        self.assertEqual(
            matches_by_code["LF"]["round_number"],
            4,
        )
        self.assertEqual(
            matches_by_code["L3M1"]["status"],
            "forfeit",
        )

    def test_routes_are_reconstructed_from_player_paths(self) -> None:
        bracket_matches = build_archived_bracket_matches(
            self.matches
        )
        routes = build_archived_bracket_routes(
            self.matches,
            bracket_matches,
        )
        route_keys = {
            (
                route["source_code"],
                route["source_outcome"],
                route["target_code"],
                route["target_slot"],
            )
            for route in routes
        }

        self.assertIn(
            ("W1M2", "winner", "W2M1", 2),
            route_keys,
        )
        self.assertIn(
            ("W2M2", "loser", "L3M1", 1),
            route_keys,
        )
        self.assertIn(
            ("LF", "winner", "GF", 2),
            route_keys,
        )


if __name__ == "__main__":
    unittest.main()
