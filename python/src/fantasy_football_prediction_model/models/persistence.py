"""Joblib persistence for trained models and sidecars."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib

from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.models.training import TrainedModel

logger = get_logger(__name__)


def save_model(
    model: TrainedModel,
    directory: Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Persist a model bundle under ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{model.position}_{model.target}_{model.algorithm}".replace("/", "_")
    model_path = directory / f"{stem}.joblib"
    meta_path = directory / f"{stem}.meta.json"
    payload = {
        "algorithm": model.algorithm,
        "position": model.position,
        "target": model.target,
        "feature_columns": model.feature_columns,
        "params": model.params,
        "architecture": model.architecture,
        "trained_at": model.trained_at,
        "train_metrics": model.train_metrics.to_dict() if model.train_metrics else None,
        "preprocessor": model.preprocessor,
        "estimator": model.estimator,
    }
    joblib.dump(payload, model_path)
    sidecar = {
        "algorithm": model.algorithm,
        "position": model.position,
        "target": model.target,
        "feature_columns": model.feature_columns,
        "params": model.params,
        "architecture": model.architecture,
        "trained_at": model.trained_at,
        "train_metrics": model.train_metrics.to_dict() if model.train_metrics else None,
        **(metadata or {}),
    }
    meta_path.write_text(json.dumps(sidecar, indent=2, default=str), encoding="utf-8")
    logger.info("Saved model bundle to %s", model_path)
    return model_path


def load_model(path: Path) -> TrainedModel:
    """Load a model bundle written by :func:`save_model`."""
    payload = joblib.load(path)
    return TrainedModel(
        algorithm=payload["algorithm"],
        position=payload["position"],
        target=payload["target"],
        feature_columns=list(payload["feature_columns"]),
        estimator=payload["estimator"],
        preprocessor=payload["preprocessor"],
        params=dict(payload.get("params") or {}),
        architecture=payload.get("architecture", "direct"),
        trained_at=payload.get("trained_at", ""),
    )
