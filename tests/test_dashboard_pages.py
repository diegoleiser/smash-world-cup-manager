"""Module-boundary tests for extracted Streamlit pages."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard_pages.forecast_format import (  # noqa: E402
    format_winners_probability,
)
from dashboard_pages.tournament_control_center import (  # noqa: E402
    group_ready_matches,
)


class MatchupsPageBoundaryTests(unittest.TestCase):
    """Keep the page's dashboard dependencies explicit."""

    def assert_render_parameters(
        self,
        module_name: str,
        function_name: str,
        expected_parameters: set[str],
    ) -> None:
        module_path = (
            SRC_DIR / "dashboard_pages" / f"{module_name}.py"
        )
        module_tree = ast.parse(module_path.read_text())
        render_function = next(
            node
            for node in module_tree.body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == function_name
            )
        )
        parameters = {
            argument.arg
            for argument in (
                *render_function.args.args,
                *render_function.args.kwonlyargs,
            )
        }

        self.assertEqual(parameters, expected_parameters)

    def test_matchups_declares_every_data_dependency(self) -> None:
        self.assert_render_parameters(
            "matchups",
            "render_matchups",
            {
                "include_inactive",
                "load_players",
                "load_h2h_matrix",
                "load_player_profile",
                "load_player_timeline",
                "load_head_to_head",
                "load_elo_ranking",
                "load_tournament_detail",
            },
        )

    def test_open_winners_probability_does_not_look_locked(self) -> None:
        self.assertEqual(
            format_winners_probability(1.0, "Side Open"),
            ">99.9%",
        )
        self.assertEqual(
            format_winners_probability(0.0, "Side Open"),
            "<0.1%",
        )
        self.assertEqual(
            format_winners_probability(1.0, "Winners Locked"),
            "100.0%",
        )
        self.assertEqual(
            format_winners_probability(0.0, "Losers Locked"),
            "0.0%",
        )

    def test_monte_carlo_declares_every_data_dependency(self) -> None:
        self.assert_render_parameters(
            "monte_carlo",
            "render_monte_carlo",
            {
                "artifact_path",
                "load_players",
                "load_elo_ranking",
            },
        )

    def test_tournaments_declares_every_dashboard_dependency(self) -> None:
        self.assert_render_parameters(
            "tournaments",
            "render_tournaments",
            {
                "load_tournaments",
                "load_tournament_detail",
                "load_tournament_milestones",
                "tournament_elo_changes",
                "format_ordinal",
                "show_archived_match_dialog",
            },
        )

    def test_home_declares_every_data_dependency(self) -> None:
        self.assert_render_parameters(
            "home",
            "render_home",
            {
                "include_inactive",
                "load_tournament_preview_data",
                "load_elo_ranking",
                "load_player_timeline",
                "load_tournaments",
                "load_database_quality",
            },
        )

    def test_player_declares_every_dashboard_dependency(self) -> None:
        self.assert_render_parameters(
            "player",
            "render_player_page",
            {
                "include_inactive",
                "load_players",
                "load_player_profile",
                "load_player_timeline",
                "load_player_history",
                "load_player_insights",
                "load_elo_ranking",
                "format_ordinal",
            },
        )

    def test_tournament_manager_declares_every_dashboard_dependency(
        self,
    ) -> None:
        self.assert_render_parameters(
            "tournament_manager",
            "render_tournament_manager",
            {
                "db_path",
                "model_artifact_path",
                "load_players",
                "load_tournaments",
                "load_tournament_drafts",
                "load_tournament_draft",
                "load_tournament_draft_groups",
                "load_tournament_draft_group_matches",
                "load_tournament_draft_group_standings",
                "load_tournament_draft_global_group_ranking",
                "load_tournament_draft_bracket_state",
                "load_tournament_draft_finalization_preview",
                "show_bracket_match_dialog",
            },
        )


class TournamentControlCenterTests(unittest.TestCase):
    def test_group_up_next_balances_completed_set_counts(self) -> None:
        matches = [
            {
                "group_match_id": "played",
                "player_1_id": "a",
                "player_2_id": "b",
                "status": "completed",
                "round_number": 1,
                "match_number": 1,
            },
            {
                "group_match_id": "later_for_busy_players",
                "player_1_id": "a",
                "player_2_id": "b",
                "status": "pending",
                "round_number": 1,
                "match_number": 2,
            },
            {
                "group_match_id": "recommended",
                "player_1_id": "c",
                "player_2_id": "d",
                "status": "pending",
                "round_number": 2,
                "match_number": 1,
            },
        ]

        ready = group_ready_matches(matches)

        self.assertEqual(
            [match["group_match_id"] for match in ready],
            ["recommended", "later_for_busy_players"],
        )

    def test_group_up_next_returns_only_pending_sets(self) -> None:
        matches = [
            {
                "group_match_id": status,
                "player_1_id": "a",
                "player_2_id": "b",
                "status": status,
                "round_number": 1,
                "match_number": index,
            }
            for index, status in enumerate(
                ("completed", "forfeit", "cancelled", "pending"),
                start=1,
            )
        ]

        ready = group_ready_matches(matches)

        self.assertEqual(
            [match["group_match_id"] for match in ready],
            ["pending"],
        )


if __name__ == "__main__":
    unittest.main()
