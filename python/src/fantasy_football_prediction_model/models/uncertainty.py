"""Projection intervals and confidence scores."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fantasy_football_prediction_model.config import UncertaintySettings
from fantasy_football_prediction_model.constants import CONFIDENCE_LABELS
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class PredictionInterval:
    low: np.ndarray
    median: np.ndarray
    high: np.ndarray
    low_quantile: float
    high_quantile: float


@dataclass(slots=True)
class ConfidenceResult:
    score: float
    label: str
    reasons: list[str]


class ResidualIntervalCalibrator:
    """Calibrate intervals from out-of-fold residuals by opportunity tier."""

    def __init__(self, settings: UncertaintySettings) -> None:
        self.settings = settings
        self._bucket_residuals: dict[int, np.ndarray] = {}
        self._global_residuals: np.ndarray = np.array([])
        self._edges: np.ndarray = np.array([])
        self.fitted = False

    def fit(
        self,
        residuals: np.ndarray,
        opportunity: np.ndarray,
    ) -> ResidualIntervalCalibrator:
        residuals = np.asarray(residuals, dtype=float).ravel()
        opportunity = np.asarray(opportunity, dtype=float).ravel()
        mask = np.isfinite(residuals) & np.isfinite(opportunity)
        residuals = residuals[mask]
        opportunity = opportunity[mask]
        self._global_residuals = residuals
        if opportunity.size >= self.settings.opportunity_tiers * 2:
            self._edges = np.unique(
                np.quantile(
                    opportunity,
                    np.linspace(0, 1, self.settings.opportunity_tiers + 1)[1:-1],
                )
            )
        tiers = (
            np.digitize(opportunity, self._edges, right=True)
            if self._edges.size
            else np.zeros(opportunity.size, dtype=int)
        )
        for tier in np.unique(tiers):
            bucket = residuals[tiers == tier]
            if bucket.size >= self.settings.min_bucket_size:
                self._bucket_residuals[int(tier)] = bucket
        self.fitted = True
        return self

    def _residual_pool(self, tier: int) -> np.ndarray:
        pool = self._bucket_residuals.get(tier)
        if pool is not None and pool.size:
            return pool
        return self._global_residuals

    def predict(
        self,
        point: np.ndarray,
        opportunity: np.ndarray | None = None,
    ) -> PredictionInterval:
        if not self.fitted or self._global_residuals.size == 0:
            point = np.asarray(point, dtype=float)
            width = np.maximum(np.abs(point) * 0.25, 5.0)
            return PredictionInterval(
                low=point - width,
                median=point,
                high=point + width,
                low_quantile=self.settings.low_quantile,
                high_quantile=self.settings.high_quantile,
            )

        point = np.asarray(point, dtype=float).ravel()
        if opportunity is None:
            opportunity = np.zeros_like(point)
        opportunity = np.asarray(opportunity, dtype=float).ravel()
        tiers = (
            np.digitize(opportunity, self._edges, right=True)
            if self._edges.size
            else np.zeros(point.size, dtype=int)
        )
        low = np.empty_like(point)
        high = np.empty_like(point)
        for i, (pred, tier) in enumerate(zip(point, tiers, strict=True)):
            pool = self._residual_pool(int(tier))
            low_q = float(np.quantile(pool, self.settings.low_quantile))
            high_q = float(np.quantile(pool, self.settings.high_quantile))
            low[i] = pred + low_q
            high[i] = pred + high_q
        # Enforce ordering around the point prediction.
        median = point.copy()
        low = np.minimum(low, median)
        high = np.maximum(high, median)
        return PredictionInterval(
            low=low,
            median=median,
            high=high,
            low_quantile=self.settings.low_quantile,
            high_quantile=self.settings.high_quantile,
        )


def compute_confidence(
    *,
    weights: dict[str, float],
    labels: dict[str, float],
    sample_size_score: float,
    feature_coverage_score: float,
    interval_width_score: float,
    role_stability_score: float,
    model_agreement_score: float,
    reasons: list[str] | None = None,
) -> ConfidenceResult:
    """Weighted confidence in ``[0, 1]`` with a categorical label.

    Confidence measures trust in the projection, not projected quality.
    """
    score = (
        weights.get("sample_size", 0.22) * _clip01(sample_size_score)
        + weights.get("feature_coverage", 0.18) * _clip01(feature_coverage_score)
        + weights.get("interval_width", 0.25) * _clip01(interval_width_score)
        + weights.get("role_stability", 0.20) * _clip01(role_stability_score)
        + weights.get("model_agreement", 0.15) * _clip01(model_agreement_score)
    )
    score = float(_clip01(score))
    high_cut = labels.get("high", 0.70)
    medium_cut = labels.get("medium", 0.45)
    if score >= high_cut:
        label = "high"
    elif score >= medium_cut:
        label = "medium"
    else:
        label = "low"
    if label not in CONFIDENCE_LABELS:
        label = "medium"
    return ConfidenceResult(score=score, label=label, reasons=list(reasons or []))


def _clip01(value: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return float(min(1.0, max(0.0, value)))


def interval_width_score(low: float, median: float, high: float) -> float:
    """Map a narrow relative interval to a high score."""
    width = max(high - low, 0.0)
    scale = max(abs(median), 20.0)
    relative = width / scale
    return float(_clip01(1.0 - relative / 1.5))
