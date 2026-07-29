"""Read and validate versioned local Combined-model artifacts."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from monte_carlo.config import ModelConfig, load_model_config
from monte_carlo.model import CombinedModel, PlayerParameters


ARTIFACT_SCHEMA_VERSION = 1
REQUIRED_FILES = (
    "metadata.json",
    "config.json",
    "dynamic_skill.csv",
    "h2h_effects.csv",
    "clutch_effects.csv",
)


class ArtifactError(ValueError):
    """Raised when a local model artifact is missing or incompatible."""


@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_schema_version: int
    model_version: str
    training_cutoff: str
    trained_at: str
    database_fingerprint: str
    player_count: int
    set_count: int
    score_known_set_count: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactMetadata":
        try:
            metadata = cls(
                artifact_schema_version=int(data["artifact_schema_version"]),
                model_version=str(data["model_version"]),
                training_cutoff=str(data["training_cutoff"]),
                trained_at=str(data["trained_at"]),
                database_fingerprint=str(data["database_fingerprint"]),
                player_count=int(data["player_count"]),
                set_count=int(data["set_count"]),
                score_known_set_count=int(data["score_known_set_count"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactError("Artifact metadata is incomplete or invalid.") from exc
        if metadata.artifact_schema_version != ARTIFACT_SCHEMA_VERSION:
            raise ArtifactError(
                "Unsupported artifact schema version: "
                f"{metadata.artifact_schema_version}; "
                f"expected {ARTIFACT_SCHEMA_VERSION}."
            )
        if metadata.player_count < 1:
            raise ArtifactError("Artifact player_count must be positive.")
        if metadata.set_count < 0 or metadata.score_known_set_count < 0:
            raise ArtifactError("Artifact Set counts must be non-negative.")
        if metadata.score_known_set_count > metadata.set_count:
            raise ArtifactError(
                "score_known_set_count cannot exceed set_count."
            )
        return metadata


@dataclass(frozen=True)
class LoadedArtifact:
    path: Path
    metadata: ArtifactMetadata
    model: CombinedModel


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArtifactError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"Invalid JSON in {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ArtifactError(f"{label} must contain a JSON object: {path}")
    return value


def _read_csv(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or ())
            missing_columns = required_columns - columns
            if missing_columns:
                raise ArtifactError(
                    f"{path.name} is missing columns: "
                    + ", ".join(sorted(missing_columns))
                )
            return list(reader)
    except FileNotFoundError as exc:
        raise ArtifactError(f"Missing artifact file: {path}") from exc


def _validate_artifact_files(artifact_path: Path) -> None:
    if not artifact_path.is_dir():
        raise ArtifactError(f"Artifact directory not found: {artifact_path}")
    missing = [
        filename
        for filename in REQUIRED_FILES
        if not (artifact_path / filename).is_file()
    ]
    if missing:
        raise ArtifactError(
            "Artifact is incomplete; missing: " + ", ".join(missing)
        )


def load_artifact(artifact_path: Path) -> LoadedArtifact:
    """Load a complete artifact directory into an immutable model."""

    artifact_path = artifact_path.resolve()
    _validate_artifact_files(artifact_path)
    metadata = ArtifactMetadata.from_dict(
        _read_json(artifact_path / "metadata.json", "artifact metadata")
    )
    try:
        config = load_model_config(artifact_path / "config.json")
    except (FileNotFoundError, ValueError) as exc:
        raise ArtifactError(str(exc)) from exc
    if metadata.model_version != config.model_version:
        raise ArtifactError(
            "Artifact metadata and config use different model versions."
        )
    if metadata.training_cutoff != config.training_cutoff:
        raise ArtifactError(
            "Artifact metadata and config use different training cutoffs."
        )

    skill_rows = _read_csv(
        artifact_path / "dynamic_skill.csv",
        {"player_id", "player", "skill_log_odds"},
    )
    clutch_rows = _read_csv(
        artifact_path / "clutch_effects.csv",
        {"player_id", "clutch_log_odds"},
    )
    h2h_rows = _read_csv(
        artifact_path / "h2h_effects.csv",
        {"player_1_id", "player_2_id", "h2h_log_odds_for_player_1"},
    )

    clutch_by_player_id: dict[str, float] = {}
    for row in clutch_rows:
        player_id = row["player_id"].strip()
        if player_id in clutch_by_player_id:
            raise ArtifactError(f"Duplicate Clutch player: {player_id}")
        clutch_by_player_id[player_id] = float(row["clutch_log_odds"])

    players: dict[str, PlayerParameters] = {}
    for row in skill_rows:
        player_id = row["player_id"].strip()
        if not player_id:
            raise ArtifactError("dynamic_skill.csv contains an empty player_id.")
        if player_id in players:
            raise ArtifactError(f"Duplicate Dynamic Skill player: {player_id}")
        players[player_id] = PlayerParameters(
            player_id=player_id,
            display_name=row["player"].strip(),
            skill_log_odds=float(row["skill_log_odds"]),
            clutch_log_odds=clutch_by_player_id.pop(player_id, 0.0),
        )
    if clutch_by_player_id:
        raise ArtifactError(
            "Clutch effects reference unknown players: "
            + ", ".join(sorted(clutch_by_player_id))
        )
    if len(players) != metadata.player_count:
        raise ArtifactError(
            "metadata player_count does not match dynamic_skill.csv."
        )

    h2h_effects: dict[tuple[str, str], float] = {}
    for row in h2h_rows:
        player_1_id = row["player_1_id"].strip()
        player_2_id = row["player_2_id"].strip()
        if player_1_id not in players or player_2_id not in players:
            raise ArtifactError("H2H effect references an unknown player.")
        if player_1_id == player_2_id:
            raise ArtifactError("H2H effect cannot reference one player twice.")
        key = (player_1_id, player_2_id)
        if key in h2h_effects:
            raise ArtifactError(
                f"Duplicate H2H effect: {player_1_id} vs {player_2_id}"
            )
        h2h_effects[key] = float(row["h2h_log_odds_for_player_1"])

    model = CombinedModel(config, players, h2h_effects)
    try:
        for player_1_id, player_2_id in h2h_effects:
            model.h2h_effect(player_1_id, player_2_id)
    except ValueError as exc:
        raise ArtifactError(str(exc)) from exc
    return LoadedArtifact(artifact_path, metadata, model)
