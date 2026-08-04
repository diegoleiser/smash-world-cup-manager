"""Tests for concise, consistent dashboard narratives."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import narratives  # noqa: E402


class TournamentPreviewNarrativeTests(unittest.TestCase):
    def test_preview_builds_a_longer_multi_angle_outlook(self) -> None:
        preview = narratives.generate_tournament_preview(
            {
                "ranking": [
                    {"player": "Alpha", "elo": 1250.0, "rank": 1},
                    {"player": "Beta", "elo": 1238.0, "rank": 2},
                    {"player": "Gamma", "elo": 1225.0, "rank": 3},
                ],
                "titles": [
                    {"player": "Alpha", "titles": 3},
                    {"player": "Beta", "titles": 2},
                ],
                "recent_form": [
                    {
                        "player": "Alpha",
                        "matches": 10,
                        "wins": 8,
                        "losses": 2,
                        "winrate": 80.0,
                        "elo_change_last_three": 20.0,
                    },
                    {
                        "player": "Beta",
                        "matches": 10,
                        "wins": 6,
                        "losses": 4,
                        "winrate": 60.0,
                        "elo_change_last_three": 5.0,
                    },
                ],
                "defending_champion": "Beta",
                "latest_tournament": "WC 13",
                "featured_rivalry": {
                    "player_a": "Alpha",
                    "player_b": "Beta",
                    "wins_a": 8,
                    "wins_b": 7,
                },
            }
        )

        self.assertEqual(narratives._sentence_count(preview), 6)
        self.assertIn("defending champion", preview)
        self.assertIn(
            "Alpha also carries the strongest recent set record",
            preview,
        )
        self.assertIn("rivalry to watch", preview)
        self.assertIn("title race", preview)
        self.assertIn("wide open", preview)
        self.assertNotIn("The favourite", preview)

    def test_preview_can_add_streak_and_latest_rivalry_meeting(self) -> None:
        preview = narratives.generate_tournament_preview(
            {
                "ranking": [
                    {"player": "Alpha", "elo": 1250.0, "rank": 1},
                    {"player": "Beta", "elo": 1210.0, "rank": 2},
                    {"player": "Gamma", "elo": 1180.0, "rank": 3},
                ],
                "recent_form": [
                    {
                        "player": "Gamma",
                        "matches": 10,
                        "wins": 7,
                        "losses": 3,
                        "winrate": 70.0,
                        "streak_type": "win",
                        "streak": 4,
                        "elo_change_last_three": 18.0,
                    }
                ],
                "featured_rivalry": {
                    "player_a": "Alpha",
                    "player_b": "Beta",
                    "wins_a": 5,
                    "wins_b": 4,
                    "last_match": {
                        "winner": "Beta",
                        "tournament": "WC 13",
                        "score": "3–2",
                    },
                },
            }
        )

        self.assertIn("active winning streak", preview)
        self.assertIn("Their latest meeting came at WC 13", preview)
        self.assertLessEqual(narratives._sentence_count(preview), 9)

    def test_preview_uses_set_terminology(self) -> None:
        preview = narratives.generate_tournament_preview(
            {
                "ranking": [
                    {"player": "Alpha", "elo": 1200.0, "rank": 1},
                ],
                "recent_form": [
                    {
                        "player": "Alpha",
                        "matches": 5,
                        "wins": 4,
                        "losses": 1,
                        "winrate": 80.0,
                        "elo_change_last_three": 0.0,
                    }
                ],
            }
        )

        self.assertIn("recorded sets", preview)
        self.assertNotIn("recorded matches", preview)


class DashboardNarrativeConsistencyTests(unittest.TestCase):
    def test_single_meeting_is_described_as_a_set(self) -> None:
        summary = narratives.generate_rivalry_summary(
            {
                "player_a": {"player": "Alpha", "wins": 1},
                "player_b": {"player": "Beta", "wins": 0},
                "history": [{"winner": "Alpha"}],
            }
        )

        self.assertIn("set", summary)
        self.assertNotIn("taking the win", summary)

    def test_rivalry_summary_adds_balance_games_and_recent_form(self) -> None:
        history = [
            {"winner": winner}
            for winner in (
                "Alpha",
                "Beta",
                "Alpha",
                "Beta",
                "Beta",
                "Beta",
                "Beta",
            )
        ]
        summary = narratives.generate_rivalry_summary(
            {
                "player_a": {
                    "player": "Alpha",
                    "wins": 3,
                    "games_won": 14,
                },
                "player_b": {
                    "player": "Beta",
                    "wins": 4,
                    "games_won": 15,
                },
                "matches_with_known_score": 7,
                "history": history,
            }
        )

        self.assertEqual(narratives._sentence_count(summary), 5)
        self.assertIn("7 decided sets", summary)
        self.assertIn("That balance is reflected", summary)
        self.assertIn("Recent momentum", summary)
        self.assertIn("historical margin still narrow", summary)

    def test_rivalry_wording_is_stable_but_varies_between_pairs(self) -> None:
        pairs = [
            ("Alpha", "Beta"),
            ("Gamma", "Delta"),
            ("Echo", "Foxtrot"),
            ("Giona", "Tamira"),
            ("Diego", "Gianni"),
        ]
        summaries = {
            narratives._overall_summary(left, right, 6, 4)
            for left, right in pairs
        }

        self.assertGreaterEqual(len(summaries), 2)
        self.assertEqual(
            narratives._overall_summary("Alpha", "Beta", 6, 4),
            narratives._overall_summary("Alpha", "Beta", 6, 4),
        )

    def test_rivalry_summary_prioritizes_deeper_historical_storylines(
        self,
    ) -> None:
        history = [
            {
                "winner": winner,
                "stage": stage,
                "tournament": tournament,
                "score": score,
                "walkover": False,
            }
            for winner, stage, tournament, score in (
                ("Alpha", "group", "WC 01", "2-1"),
                ("Alpha", "group", "WC 02", "2-1"),
                ("Beta", "bracket", "WC 02", "1-2"),
                ("Alpha", "group", "WC 03", "2-1"),
                ("Beta", "bracket", "WC 03", "1-2"),
                ("Beta", "bracket", "WC 04", "0-2"),
                ("Beta", "bracket", "WC 04", "1-2"),
            )
        ]
        summary = narratives.generate_rivalry_summary(
            {
                "player_a": {
                    "player": "Alpha",
                    "wins": 3,
                    "games_won": 9,
                },
                "player_b": {
                    "player": "Beta",
                    "wins": 4,
                    "games_won": 11,
                },
                "matches_with_known_score": 7,
                "history": history,
                "last_match": history[-1],
            }
        )

        self.assertLessEqual(narratives._sentence_count(summary), 8)
        self.assertIn("once trailed by 2 sets", summary)
        self.assertIn("Tournament stage has mattered", summary)
        self.assertIn("went the full distance", summary)
        self.assertIn("avenged an earlier loss", summary)
        self.assertIn("Most recently", summary)

    def test_new_player_summary_handles_zero_appearances_naturally(
        self,
    ) -> None:
        summary = narratives.generate_player_summary(
            {
                "player": "Alpha",
                "titles": 0,
                "appearances": 0,
                "decided_matches": 0,
            },
            {},
            None,
        )

        self.assertIn("no recorded tournament appearances yet", summary)
        self.assertNotIn("made 0", summary)

    def test_player_summary_combines_six_distinct_career_angles(self) -> None:
        summary = narratives.generate_player_summary(
            {
                "player": "Alpha",
                "titles": 2,
                "appearances": 8,
                "current_elo": 1210.0,
                "peak_elo": 1250.0,
                "decided_matches": 40,
                "winrate": 65.0,
                "best_result": 1,
            },
            {
                "longest_win_streak": 6,
                "nemesis": {
                    "opponent": "Beta",
                    "matches": 8,
                    "wins": 2,
                    "losses": 6,
                    "winrate": 25.0,
                },
                "featured_rivalry": {
                    "opponent": "Gamma",
                    "matches": 10,
                    "wins": 6,
                    "losses": 4,
                },
                "best_elo_event": {
                    "tournament": "WC 12",
                    "elo_change": 44.0,
                },
            },
            2,
        )

        self.assertEqual(narratives._sentence_count(summary), 6)
        self.assertIn("40.0 points above", summary)
        self.assertIn("longest winning streak", summary)
        self.assertIn("toughest recorded opponent", summary)
        self.assertIn("biggest Elo gain", summary)

    def test_tournament_recap_uses_natural_set_and_context_phrasing(
        self,
    ) -> None:
        summary = narratives.generate_tournament_summary(
            {"tournament_number": 14, "winner": "Alpha"},
            [
                {"player": "Alpha", "placement": 1},
                {"player": "Beta", "placement": 2},
                {"player": "Gamma", "placement": 3},
            ],
            [
                {
                    "stage": "knockout",
                    "winner": "Alpha",
                    "player_1": "Alpha",
                    "player_2": "Beta",
                    "player_1_score": 3,
                    "player_2_score": 2,
                    "score_known": True,
                }
            ],
            [],
            winner_title_number=1,
        )

        self.assertIn("led the field with 1 set win", summary)
        self.assertIn(", while Gamma finished third", summary)
        self.assertIn("1 recorded set; 1 set was decided", summary)
        self.assertNotIn(", with Gamma finishing third", summary)

    def test_tournament_recap_prioritizes_extended_event_storylines(
        self,
    ) -> None:
        participants = [
            {"player": "Alpha", "placement": 1, "seed": 3},
            {"player": "Beta", "placement": 2, "seed": 1},
            {"player": "Gamma", "placement": 3, "seed": 4},
            {"player": "Delta", "placement": 4, "seed": 2},
        ]
        matches = [
            {
                "stage": "group",
                "player_1": "Alpha",
                "player_2": "Beta",
                "winner": "Alpha",
                "score_known": True,
                "player_1_score": 2,
                "player_2_score": 0,
            },
            {
                "stage": "group",
                "player_1": "Alpha",
                "player_2": "Gamma",
                "winner": "Alpha",
                "score_known": True,
                "player_1_score": 2,
                "player_2_score": 1,
            },
            {
                "stage": "knockout",
                "player_1": "Alpha",
                "player_2": "Beta",
                "winner": "Alpha",
                "score_known": True,
                "player_1_score": 3,
                "player_2_score": 2,
            },
        ]
        summary = narratives.generate_tournament_summary(
            {"tournament_number": 15, "winner": "Alpha"},
            participants,
            matches,
            [],
            winner_title_number=1,
            milestones=["Alpha reached a new career-high Elo."],
        )

        self.assertEqual(narratives._sentence_count(summary), 7)
        self.assertIn("Group Stage unbeaten", summary)
        self.assertIn("initial seed", summary)
        self.assertIn("new career-high Elo", summary)

    def test_tournament_recap_connects_storylines_across_events(self) -> None:
        summary = narratives.generate_tournament_summary(
            {"tournament_number": 15, "winner": "Alpha"},
            [
                {"player": "Alpha", "placement": 1, "seed": 2},
                {"player": "Beta", "placement": 2, "seed": 1},
                {"player": "Gamma", "placement": 3, "seed": 4},
            ],
            [
                {
                    "stage": "knockout",
                    "player_1": "Alpha",
                    "player_2": "Beta",
                    "winner": "Alpha",
                    "score_known": True,
                    "player_1_score": 3,
                    "player_2_score": 2,
                }
            ],
            [],
            winner_title_number=2,
            defending_champion="Beta",
            story_context={
                "winner_title_streak": 1,
                "previous_title": {"tournament_number": 10},
                "winner_previous_placement": {
                    "tournament_number": 14,
                    "placement": 4,
                },
                "winner_podium_streak": 1,
                "repeat_final": {
                    "previous_tournament": 14,
                    "previous_winner": "Beta",
                },
                "defending_champion_result": {"placement": 2},
                "biggest_placement_improvement": {
                    "player": "Gamma",
                    "previous_tournament": 14,
                    "previous_placement": 7,
                    "current_placement": 3,
                    "improvement": 4,
                },
            },
        )

        self.assertLessEqual(narratives._sentence_count(summary), 10)
        self.assertIn("first title since WC 10", summary)
        self.assertIn("rise from 4th place at WC 14", summary)
        self.assertIn("reversed the outcome", summary)
        self.assertIn("title defence ended", summary)
        self.assertIn("largest jump from a previous appearance", summary)


if __name__ == "__main__":
    unittest.main()
