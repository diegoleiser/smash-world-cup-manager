"""Tests for versioned local model artifacts and forecast service."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from monte_carlo.artifacts import ArtifactError, load_artifact  # noqa: E402
from monte_carlo.cli import main as cli_main  # noqa: E402
from monte_carlo.service import forecast_neutral_matchup  # noqa: E402


class ArtifactTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.artifact_path = Path(self.temporary_directory.name) / "model"
        self.artifact_path.mkdir()
        self.write_valid_artifact()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_valid_artifact(self) -> None:
        metadata = {
            "artifact_schema_version": 1,
            "model_version": "test-model",
            "training_cutoff": "synthetic",
            "trained_at": "2026-07-30T00:00:00Z",
            "database_fingerprint": "sha256:test",
            "player_count": 2,
            "set_count": 10,
            "score_known_set_count": 8,
        }
        config = {
            "model_version": "test-model",
            "training_cutoff": "synthetic",
            "parameters": {
                "sigma_initial": 1.0,
                "sigma_skill_drift_per_180_days": 0.05,
                "sigma_h2h": 0.4,
                "sigma_clutch": 1.2,
                "sigma_day": 0.4,
                "prediction_clip_min": 0.005,
                "prediction_clip_max": 0.995,
            },
        }
        (self.artifact_path / "metadata.json").write_text(
            json.dumps(metadata),
            encoding="utf-8",
        )
        (self.artifact_path / "config.json").write_text(
            json.dumps(config),
            encoding="utf-8",
        )
        (self.artifact_path / "dynamic_skill.csv").write_text(
            "player_id,player,skill_log_odds\n"
            "a,Alpha,0.4\n"
            "b,Bravo,-0.2\n",
            encoding="utf-8",
        )
        (self.artifact_path / "clutch_effects.csv").write_text(
            "player_id,clutch_log_odds\n"
            "a,0.3\n"
            "b,-0.1\n",
            encoding="utf-8",
        )
        (self.artifact_path / "h2h_effects.csv").write_text(
            "player_1_id,player_2_id,h2h_log_odds_for_player_1\n"
            "a,b,0.15\n",
            encoding="utf-8",
        )


class ArtifactLoaderTests(ArtifactTestCase):
    def test_valid_artifact_loads(self) -> None:
        artifact = load_artifact(self.artifact_path)
        self.assertEqual(artifact.metadata.model_version, "test-model")
        self.assertEqual(set(artifact.model.players), {"a", "b"})
        self.assertAlmostEqual(artifact.model.h2h_effect("b", "a"), -0.15)

    def test_missing_file_has_clear_error(self) -> None:
        (self.artifact_path / "clutch_effects.csv").unlink()
        with self.assertRaisesRegex(
            ArtifactError,
            "clutch_effects.csv",
        ):
            load_artifact(self.artifact_path)

    def test_wrong_schema_version_is_rejected(self) -> None:
        metadata_path = self.artifact_path / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["artifact_schema_version"] = 999
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(
            ArtifactError,
            "Unsupported artifact schema",
        ):
            load_artifact(self.artifact_path)

    def test_non_antisymmetric_h2h_is_rejected(self) -> None:
        (self.artifact_path / "h2h_effects.csv").write_text(
            "player_1_id,player_2_id,h2h_log_odds_for_player_1\n"
            "a,b,0.15\n"
            "b,a,-0.10\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ArtifactError, "antisymmetric"):
            load_artifact(self.artifact_path)

    def test_unknown_clutch_player_is_rejected(self) -> None:
        (self.artifact_path / "clutch_effects.csv").write_text(
            "player_id,clutch_log_odds\n"
            "a,0.3\n"
            "b,-0.1\n"
            "c,1.0\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ArtifactError, "unknown players"):
            load_artifact(self.artifact_path)


class ForecastServiceTests(ArtifactTestCase):
    def test_forecast_contains_probabilities_and_versions(self) -> None:
        forecast = forecast_neutral_matchup(
            self.artifact_path,
            "a",
            "b",
        )
        self.assertEqual(forecast.player_a_name, "Alpha")
        self.assertGreater(forecast.neutral_game_probability, 0.5)
        self.assertGreater(forecast.neutral_bo3_probability, 0.5)
        self.assertGreater(forecast.neutral_bo5_probability, 0.5)
        self.assertEqual(forecast.model_version, "test-model")
        self.assertEqual(forecast.training_cutoff, "synthetic")

    def test_unknown_player_is_controlled(self) -> None:
        with self.assertRaisesRegex(KeyError, "unknown"):
            forecast_neutral_matchup(self.artifact_path, "a", "unknown")

    def test_cli_forecast_prints_human_readable_summary(self) -> None:
        with (
            patch(
                "sys.argv",
                [
                    "monte_carlo.cli",
                    "forecast",
                    str(self.artifact_path),
                    "a",
                    "b",
                ],
            ),
            patch("builtins.print") as print_mock,
        ):
            cli_main()

        output = "\n".join(
            str(call.args[0])
            for call in print_mock.call_args_list
        )
        self.assertIn("Alpha vs Bravo", output)
        self.assertIn("Neutral-Day Bo3 probability", output)
        self.assertIn("Model: test-model", output)


if __name__ == "__main__":
    unittest.main()
