"""Weighted ensemble of trained candidates."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
from sklearn.base import BaseEstimator, RegressorMixin

from fantasy_football_prediction_model.models.training import TrainedModel


@dataclass
class EnsembleMember:
    name: str
    model: TrainedModel
    weight: float
    mae: float


class WeightedEnsemble(BaseEstimator, RegressorMixin):
    """Blend the best candidates with inverse-MAE weights."""

    def __init__(self, members: list[EnsembleMember] | None = None) -> None:
        self.members = members or []

    @classmethod
    def from_models(
        cls,
        models: dict[str, TrainedModel],
        maes: dict[str, float],
        *,
        top_k: int = 3,
    ) -> WeightedEnsemble:
        ranked = sorted(
            ((name, models[name], maes[name]) for name in models if name in maes),
            key=lambda item: item[2],
        )[:top_k]
        if not ranked:
            raise ValueError("Cannot build a WeightedEnsemble with no members.")
        inv = [1.0 / max(mae, 1e-6) for _, _, mae in ranked]
        total = sum(inv)
        members = [
            EnsembleMember(name=name, model=model, weight=weight / total, mae=mae)
            for (name, model, mae), weight in zip(ranked, inv, strict=True)
        ]
        return cls(members=members)

    def fit(self, X: object = None, y: object = None) -> WeightedEnsemble:
        del X, y
        return self

    def predict_frame(self, frame: pl.DataFrame) -> np.ndarray:
        if not self.members:
            raise RuntimeError("WeightedEnsemble has no members.")
        blended = np.zeros(frame.height, dtype=float)
        for member in self.members:
            blended += member.weight * member.model.predict(frame)
        return blended

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict from an already-transformed matrix using the first member's estimator.

        Prefer :meth:`predict_frame` when raw feature frames are available.
        """
        if not self.members:
            raise RuntimeError("WeightedEnsemble has no members.")
        blended = np.zeros(X.shape[0], dtype=float)
        for member in self.members:
            blended += member.weight * np.asarray(member.model.estimator.predict(X), dtype=float)
        return blended
