"""Command-line tools for local model validation and matchup forecasts."""

from __future__ import annotations

import argparse
from pathlib import Path

from monte_carlo.artifacts import load_artifact
from monte_carlo.service import forecast_neutral_matchup


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smash World Cup Combined-model tools.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate and summarize a local model artifact.",
    )
    validate_parser.add_argument("artifact", type=Path)

    forecast_parser = subparsers.add_parser(
        "forecast",
        help="Forecast one neutral-Day matchup.",
    )
    forecast_parser.add_argument("artifact", type=Path)
    forecast_parser.add_argument("player_a_id")
    forecast_parser.add_argument("player_b_id")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "validate":
        artifact = load_artifact(args.artifact)
        print("Artifact valid")
        print(f"Model: {artifact.metadata.model_version}")
        print(f"Training cutoff: {artifact.metadata.training_cutoff}")
        print(f"Players: {artifact.metadata.player_count}")
        print(f"Sets: {artifact.metadata.set_count}")
        return

    forecast = forecast_neutral_matchup(
        args.artifact,
        args.player_a_id,
        args.player_b_id,
    )
    print(f"{forecast.player_a_name} vs {forecast.player_b_name}")
    print(
        "Neutral-Day Game probability: "
        f"{_percent(forecast.neutral_game_probability)}"
    )
    print(
        "Neutral-Day Bo3 probability: "
        f"{_percent(forecast.neutral_bo3_probability)}"
    )
    print(
        "Neutral-Day Bo5 probability: "
        f"{_percent(forecast.neutral_bo5_probability)}"
    )
    print(f"Model: {forecast.model_version}")
    print(f"Training cutoff: {forecast.training_cutoff}")


if __name__ == "__main__":
    main()
