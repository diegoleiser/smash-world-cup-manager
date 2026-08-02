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
from dashboard_pages.tournaments import (  # noqa: E402
    _all_matches_table_rows,
    _archived_group_tables,
    _archived_tournament_header_html,
    _archived_tournament_selector_styles,
    _elo_change_table_rows,
    _elo_ranking_expander_styles,
    _elo_snapshot_table_data,
    _final_standings_table_data,
    _phase_match_table_rows,
)
from dashboard_pages.ui_components import (  # noqa: E402
    archived_match_result_html,
    clickable_card_button_styles,
    compact_score_input_styles,
    dashboard_table_html,
    up_next_matchup_html,
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
                "include_inactive",
                "load_tournaments",
                "load_tournament_detail",
                "load_tournament_milestones",
                "tournament_elo_changes",
                "format_ordinal",
                "show_archived_match_dialog",
            },
        )

    def test_tournament_ranks_follow_inactive_player_filter(self) -> None:
        dashboard_tree = ast.parse(
            (PROJECT_ROOT / "dashboard.py").read_text()
        )
        elo_changes_function = next(
            node
            for node in dashboard_tree.body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "tournament_elo_changes"
            )
        )
        timeline_call = next(
            node
            for node in ast.walk(elo_changes_function)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "load_player_timeline"
            )
        )
        inactive_keyword = next(
            keyword
            for keyword in timeline_call.keywords
            if keyword.arg == "include_inactive"
        )

        self.assertIsInstance(inactive_keyword.value, ast.Name)
        self.assertEqual(inactive_keyword.value.id, "include_inactive")

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
    def test_up_next_matchup_preserves_layout_probability_and_escaping(
        self,
    ) -> None:
        markup = up_next_matchup_html(
            "Group <A> · Round 2",
            "A & B",
            "<Player>",
            player_1_probability=0.625,
        )

        self.assertIn("grid-template-columns:1fr auto 1fr", markup)
        self.assertIn("font-size:2.15rem", markup)
        self.assertIn("62.5% win chance", markup)
        self.assertIn("37.5% win chance", markup)
        self.assertIn("Group &lt;A&gt; · Round 2", markup)
        self.assertIn("A &amp; B", markup)
        self.assertIn("&lt;Player&gt;", markup)

        markup_without_probability = up_next_matchup_html(
            "Winners Final · W4M1",
            "Player 1",
            "Player 2",
        )
        self.assertNotIn("win chance", markup_without_probability)

    def test_compact_score_styles_preserve_shared_and_optional_states(
        self,
    ) -> None:
        styles = compact_score_input_styles("example_score_")

        self.assertIn('[class*="st-key-example_score_"]', styles)
        self.assertIn('div[data-baseweb="input"]:focus-within', styles)
        self.assertIn("font-size: 1.55rem", styles)
        self.assertIn("button:hover", styles)
        self.assertNotIn("button:first-of-type", styles)
        self.assertNotIn("button:last-of-type", styles)

        separated_styles = compact_score_input_styles(
            "example_score_",
            separate_stepper_buttons=True,
        )
        self.assertIn("button:first-of-type", separated_styles)
        self.assertIn("button:last-of-type", separated_styles)

    def test_dashboard_table_preserves_visual_states_and_escapes_text(
        self,
    ) -> None:
        markup = dashboard_table_html(
            ["Player", "Change"],
            [["A & B", "▲ 2"], ["<Player>", "▼ 1"]],
            columns="2fr 1fr",
            row_highlights={0: "winners", 1: "losers"},
            emphasis_column=0,
        )

        self.assertIn("control-table-row-winners", markup)
        self.assertIn("control-table-row-losers", markup)
        self.assertIn("control-table-emphasis", markup)
        self.assertIn("control-table-positive", markup)
        self.assertIn("control-table-negative", markup)
        self.assertIn("A &amp; B", markup)
        self.assertIn("&lt;Player&gt;", markup)
        self.assertNotIn("<Player>", markup)

    def test_clickable_card_styles_use_shared_hover_language(self) -> None:
        styles = clickable_card_button_styles("example_card_")

        self.assertIn('[class*="st-key-example_card_"]', styles)
        self.assertIn("button:hover", styles)
        self.assertIn("button:focus-visible", styles)
        self.assertIn("transform: translateY(-1px)", styles)
        self.assertIn("0 8px 24px rgba(59, 130, 246, 0.18)", styles)

        focus_styles = clickable_card_button_styles(
            "example_card_",
            show_focus_ring=True,
        )
        self.assertIn("0 0 0 2px rgba(96, 165, 250, 0.22)", focus_styles)

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


class TournamentPageTests(unittest.TestCase):
    def test_archived_tournament_selector_matches_expander_language(
        self,
    ) -> None:
        styles = _archived_tournament_selector_styles()

        self.assertIn("st-key-archived_tournament_selector", styles)
        self.assertIn("padding: 0.55rem 0.85rem 0.75rem", styles)
        self.assertIn("border-radius: 0.8rem", styles)
        self.assertIn("[data-baseweb=\"select\"]", styles)
        self.assertIn("background-color: transparent", styles)
        self.assertIn("font-size: 1.75rem", styles)
        self.assertIn("font-weight: 800", styles)
        self.assertIn("[role=\"combobox\"]", styles)
        self.assertIn("[aria-haspopup=\"listbox\"]", styles)
        self.assertIn(":hover", styles)
        self.assertIn("!important", styles)
        self.assertIn(":focus-within", styles)

    def test_archived_tournament_header_groups_metadata_and_podium(
        self,
    ) -> None:
        markup = _archived_tournament_header_html(
            {
                "tournament_number": 8,
                "tournament_date": "2026-07-31",
            },
            [
                {"placement": 1, "player": "A & B"},
                {"placement": 2, "player": "Beta"},
                {"placement": 3, "player": "<Gamma>"},
                {"placement": 4, "player": "Delta"},
            ],
            14,
        )

        self.assertIn("WC 08", markup)
        self.assertIn("2026-07-31", markup)
        self.assertIn("4 Participants", markup)
        self.assertIn("14 Matches", markup)
        self.assertIn("Champion", markup)
        self.assertIn("archive-tournament-desktop-meta", markup)
        self.assertIn("display: none", markup)
        self.assertIn("A &amp; B", markup)
        self.assertIn("&lt;Gamma&gt;", markup)
        self.assertNotIn("<Gamma>", markup)
        self.assertIn("@media (max-width: 700px)", markup)

    def test_phase_match_rows_omit_redundant_stage(self) -> None:
        rows = _phase_match_table_rows(
            [
                {
                    "stage": "group",
                    "round_label": "Round 1",
                    "score_known": True,
                    "player_1": "Alpha",
                    "player_2": "Beta",
                    "player_1_score": 2,
                    "player_2_score": 1,
                    "winner": "Alpha",
                }
            ],
            [],
        )

        self.assertEqual(
            rows,
            [["Round 1", "Alpha vs Beta", "2:1", "Alpha"]],
        )

    def test_archived_group_tables_reconstruct_and_separate_groups(
        self,
    ) -> None:
        participants = [
            {"player_id": "a", "player": "Alpha", "seed": 1},
            {"player_id": "b", "player": "Beta", "seed": 2},
            {"player_id": "c", "player": "Gamma", "seed": 3},
            {"player_id": "d", "player": "Delta", "seed": 4},
        ]
        matches = [
            {
                "stage": "group",
                "challonge_group_id": "one",
                "player_1_id": "a",
                "player_2_id": "b",
                "winner_id": "a",
                "player_1_score": 2,
                "player_2_score": 0,
                "walkover": False,
            },
            {
                "stage": "group",
                "challonge_group_id": "two",
                "player_1_id": "c",
                "player_2_id": "d",
                "winner_id": "d",
                "player_1_score": 1,
                "player_2_score": 2,
                "walkover": False,
            },
            {
                "stage": "knockout",
                "challonge_group_id": None,
                "bracket_side": "winners",
                "player_1_id": "a",
                "player_2_id": "c",
                "winner_id": "a",
                "player_1_score": 2,
                "player_2_score": 1,
                "walkover": False,
            },
            {
                "stage": "knockout",
                "challonge_group_id": None,
                "bracket_side": "losers",
                "player_1_id": "b",
                "player_2_id": "d",
                "winner_id": "b",
                "player_1_score": 2,
                "player_2_score": 1,
                "walkover": False,
            },
        ]
        changes = [
            {"player_id": player_id, "Elo Before": 1000.0}
            for player_id in ("a", "b", "c", "d")
        ]

        tables = _archived_group_tables(matches, participants, changes)

        self.assertEqual(
            [table["name"] for table in tables],
            ["Group A", "Group B"],
        )
        self.assertEqual(
            tables[0]["rows"],
            [
                ["#1", "Alpha", "1–0", "2–0", "▲ +2"],
                ["#2", "Beta", "0–1", "0–2", "▼ -2"],
            ],
        )
        self.assertEqual(tables[0]["highlights"], {0: "winners"})
        self.assertEqual(tables[1]["rows"][0][1], "Delta")
        self.assertEqual(tables[1]["highlights"], {1: "winners"})

    def test_archived_group_tables_support_internal_archives(self) -> None:
        tables = _archived_group_tables(
            [
                {
                    "stage": "group_stage",
                    "round_label": "Group A · Round 1",
                    "challonge_group_id": None,
                    "player_1_id": "a",
                    "player_2_id": "b",
                    "winner_id": "b",
                    "player_1_score": 0,
                    "player_2_score": 2,
                    "walkover": False,
                }
            ],
            [
                {"player_id": "a", "player": "Alpha", "seed": 1},
                {"player_id": "b", "player": "Beta", "seed": 2},
            ],
            [
                {"player_id": "a", "Elo Before": 1000.0},
                {"player_id": "b", "Elo Before": 1000.0},
            ],
        )

        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["name"], "Group Stage")
        self.assertEqual(tables[0]["rows"][0][1], "Beta")

    def test_elo_snapshot_rows_format_rank_rating_and_participation(
        self,
    ) -> None:
        rows, highlights = _elo_snapshot_table_data(
            [
                {
                    "rank": 1,
                    "player": "Alpha",
                    "elo": 1123.456,
                    "played_in_tournament": True,
                },
                {
                    "rank": 2,
                    "player": "Beta",
                    "elo": 1080,
                    "played_in_tournament": False,
                },
            ]
        )

        self.assertEqual(
            rows,
            [
                ["#1", "Alpha", "1123.5", "Played"],
                ["#2", "Beta", "1080.0", "Did not play"],
            ],
        )
        self.assertEqual(highlights, {0: "participated"})

    def test_elo_ranking_expander_matches_dashboard_card_language(
        self,
    ) -> None:
        styles = _elo_ranking_expander_styles()

        self.assertIn("st-key-archived_elo_ranking", styles)
        self.assertIn("margin-top: 1rem", styles)
        self.assertIn("border-radius: 0.8rem", styles)
        self.assertIn("details:hover", styles)

    def test_elo_change_rows_group_values_and_preserve_unranked_states(
        self,
    ) -> None:
        rows = _elo_change_table_rows(
            [
                {
                    "Players": "Alpha",
                    "Elo Before": 1000.0,
                    "Elo After": 1015.625,
                    "Elo Change": 15.625,
                    "Rank Before": None,
                    "Rank After": 2,
                },
                {
                    "Players": "Beta",
                    "Elo Before": 1042.5,
                    "Elo After": 1030.0,
                    "Elo Change": -12.5,
                    "Rank Before": 2,
                    "Rank After": 3,
                },
                {
                    "Players": "Gamma",
                    "Elo Before": 1000.0,
                    "Elo After": 1000.0,
                    "Elo Change": 0.0,
                    "Rank Before": None,
                    "Rank After": None,
                },
            ]
        )

        self.assertEqual(
            rows,
            [
                ["Alpha", "1000.0 → 1015.6", "▲ +15.6", "Unranked → #2"],
                ["Beta", "1042.5 → 1030.0", "▼ -12.5", "#2 → #3"],
                ["Gamma", "1000.0 → 1000.0", "= 0.0", "Unranked → Unranked"],
            ],
        )

    def test_archived_dialog_uses_its_state_clearing_close_button(
        self,
    ) -> None:
        dashboard_tree = ast.parse((PROJECT_ROOT / "dashboard.py").read_text())
        dialog_function = next(
            node
            for node in dashboard_tree.body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "show_archived_match_dialog"
            )
        )
        dialog_decorator = next(
            decorator
            for decorator in dialog_function.decorator_list
            if isinstance(decorator, ast.Call)
        )
        dismissible = next(
            keyword.value
            for keyword in dialog_decorator.keywords
            if keyword.arg == "dismissible"
        )

        self.assertIsInstance(dismissible, ast.Constant)
        self.assertIs(dismissible.value, False)

    def test_archived_result_card_preserves_context_status_and_escaping(
        self,
    ) -> None:
        markup = archived_match_result_html(
            "WC 18 · Winners Final · W4M1",
            "A & B",
            "<Player>",
            "2–1",
            winner_name="A & B",
            status_label="Played",
        )

        self.assertIn("WC 18 · Winners Final · W4M1", markup)
        self.assertIn("A &amp; B", markup)
        self.assertIn("&lt;Player&gt;", markup)
        self.assertNotIn("<Player>", markup)
        self.assertIn("2–1", markup)
        self.assertIn("Winner · <strong>A &amp; B</strong>", markup)
        self.assertIn("Status · <strong>Played</strong>", markup)
        self.assertIn("rgb(74, 222, 128)", markup)

    def test_all_matches_rows_preserve_scores_rounds_and_pending_winners(
        self,
    ) -> None:
        rows = _all_matches_table_rows(
            [
                {
                    "stage": "Bracket",
                    "player_1": "Alpha",
                    "player_2": "Beta",
                    "player_1_score": 2,
                    "player_2_score": 1,
                    "score_known": True,
                    "winner": "Alpha",
                },
                {
                    "stage": None,
                    "player_1": "Gamma",
                    "player_2": "Delta",
                    "player_1_score": None,
                    "player_2_score": None,
                    "score_known": False,
                    "winner": None,
                },
            ],
            [],
            format_round=lambda match, archived: (
                "Grand Final" if match["stage"] else "Unknown Round"
            ),
        )

        self.assertEqual(
            rows,
            [
                ["Bracket", "Grand Final", "Alpha vs Beta", "2:1", "Alpha"],
                ["–", "Unknown Round", "Gamma vs Delta", "–", "Pending"],
            ],
        )

    def test_final_standings_preserve_ties_seeds_and_missing_values(
        self,
    ) -> None:
        ordinal_labels = {1: "1st", 2: "2nd", 5: "5th"}
        rows, highlights = _final_standings_table_data(
            [
                {"placement": 1, "player": "Champion", "seed": 3},
                {"placement": 2, "player": "Runner-up", "seed": 1},
                {"placement": 5, "player": "Fifth A", "seed": 5},
                {"placement": 5, "player": "Fifth B", "seed": None},
                {"placement": None, "player": "Unknown", "seed": 5},
            ],
            ordinal_labels.__getitem__,
        )

        self.assertEqual(rows[0], ["🥇 1st", "Champion", "Seed #3", "▲ 2"])
        self.assertEqual(rows[1], ["🥈 2nd", "Runner-up", "Seed #1", "▼ 1"])
        self.assertEqual(rows[2][0], "T-5th")
        self.assertEqual(rows[2][3], "= Seed")
        self.assertEqual(rows[3], ["T-5th", "Fifth B", "Not seeded", "–"])
        self.assertEqual(rows[4], ["–", "Unknown", "Seed #5", "–"])
        self.assertEqual(highlights, {0: "winners"})


if __name__ == "__main__":
    unittest.main()
