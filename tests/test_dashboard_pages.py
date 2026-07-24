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

class MatchupsPageBoundaryTests(unittest.TestCase):
    """Keep the page's dashboard dependencies explicit."""

    def test_render_function_declares_every_data_dependency(self) -> None:
        module_path = (
            SRC_DIR / "dashboard_pages" / "matchups.py"
        )
        module_tree = ast.parse(module_path.read_text())
        render_function = next(
            node
            for node in module_tree.body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "render_matchups"
            )
        )
        parameters = {
            argument.arg
            for argument in (
                *render_function.args.args,
                *render_function.args.kwonlyargs,
            )
        }

        self.assertEqual(
            parameters,
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


if __name__ == "__main__":
    unittest.main()
