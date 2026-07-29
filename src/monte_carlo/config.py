"""Versioned configuration for the Combined forecast model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    """Validated parameters needed by the production probability model."""

    model_version: str
    training_cutoff: str
    sigma_initial: float
    sigma_skill_drift_per_180_days: float
    sigma_h2h: float
    sigma_clutch: float
    sigma_day: float
    prediction_clip_min: float
    prediction_clip_max: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelConfig":
        parameters = data.get("parameters", data)
        config = cls(
            model_version=str(data["model_version"]),
            training_cutoff=str(data["training_cutoff"]),
            sigma_initial=float(parameters["sigma_initial"]),
            sigma_skill_drift_per_180_days=float(
                parameters["sigma_skill_drift_per_180_days"]
            ),
            sigma_h2h=float(parameters["sigma_h2h"]),
            sigma_clutch=float(parameters["sigma_clutch"]),
            sigma_day=float(parameters["sigma_day"]),
            prediction_clip_min=float(parameters["prediction_clip_min"]),
            prediction_clip_max=float(parameters["prediction_clip_max"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.model_version.strip():
            raise ValueError("model_version must not be empty.")
        if not self.training_cutoff.strip():
            raise ValueError("training_cutoff must not be empty.")
        for field_name in (
            "sigma_initial",
            "sigma_skill_drift_per_180_days",
            "sigma_h2h",
            "sigma_clutch",
            "sigma_day",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative.")
        if not (
            0.0
            < self.prediction_clip_min
            < self.prediction_clip_max
            < 1.0
        ):
            raise ValueError(
                "Prediction clipping limits must satisfy 0 < min < max < 1."
            )


def load_model_config(path: Path) -> ModelConfig:
    """Load and validate a model configuration JSON file."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Model config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid model config JSON: {path}") from exc
    return ModelConfig.from_dict(data)
