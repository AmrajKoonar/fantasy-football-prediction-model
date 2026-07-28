"""Lightweight local model registry under ``artifacts/models``."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.models.persistence import load_model, save_model
from fantasy_football_prediction_model.models.training import TrainedModel

logger = get_logger(__name__)


@dataclass
class ModelRecord:
    model_version: str
    position: str
    target: str
    algorithm: str
    training_seasons: list[int]
    feature_end_season: int
    projection_season: int
    features: list[str]
    metrics: dict[str, Any] = field(default_factory=dict)
    trained_at: str = ""
    dataset_hash: str = ""
    git_commit: str | None = None
    path: str = ""
    architecture: str = "direct"


class LocalModelRegistry:
    """Filesystem registry: one JSON index plus joblib bundles."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "registry.json"

    def _read_index(self) -> list[dict[str, Any]]:
        if not self.index_path.is_file():
            return []
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _write_index(self, records: list[dict[str, Any]]) -> None:
        self.index_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    def register(
        self,
        model: TrainedModel,
        *,
        model_version: str,
        training_seasons: list[int],
        feature_end_season: int,
        projection_season: int,
        dataset_hash: str = "",
        metrics: dict[str, Any] | None = None,
    ) -> ModelRecord:
        commit = _git_commit()
        path = save_model(
            model,
            self.root / model.position / model.target,
            metadata={
                "model_version": model_version,
                "training_seasons": training_seasons,
                "feature_end_season": feature_end_season,
                "projection_season": projection_season,
                "dataset_hash": dataset_hash,
                "git_commit": commit,
                "metrics": metrics or {},
            },
        )
        record = ModelRecord(
            model_version=model_version,
            position=model.position,
            target=model.target,
            algorithm=model.algorithm,
            training_seasons=training_seasons,
            feature_end_season=feature_end_season,
            projection_season=projection_season,
            features=model.feature_columns,
            metrics=metrics or (model.train_metrics.to_dict() if model.train_metrics else {}),
            trained_at=model.trained_at or datetime.now(UTC).isoformat(),
            dataset_hash=dataset_hash,
            git_commit=commit,
            path=str(path),
            architecture=model.architecture,
        )
        index = self._read_index()
        index = [
            item
            for item in index
            if not (
                item.get("position") == record.position
                and item.get("target") == record.target
                and item.get("model_version") == record.model_version
            )
        ]
        index.append(asdict(record))
        self._write_index(index)
        logger.info(
            "Registered %s/%s (%s) as %s",
            record.position,
            record.target,
            record.algorithm,
            record.model_version,
        )
        return record

    def list_models(self) -> list[ModelRecord]:
        return [ModelRecord(**item) for item in self._read_index()]

    def get_latest(self, position: str, target: str) -> ModelRecord | None:
        matches = [
            ModelRecord(**item)
            for item in self._read_index()
            if item.get("position") == position and item.get("target") == target
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: item.trained_at, reverse=True)
        return matches[0]

    def load(self, record: ModelRecord) -> TrainedModel:
        return load_model(Path(record.path))


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None
