"""Estimator construction and single-target training."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.ensemble import (
    ExtraTreesRegressor,
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.linear_model import ElasticNet, Ridge

from fantasy_football_prediction_model.config import PreprocessingSettings
from fantasy_football_prediction_model.evaluation.metrics import RegressionMetrics, regression_metrics
from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.models.preprocessing import (
    FoldPreprocessor,
    extract_target,
)

logger = get_logger(__name__)


def _try_import_lightgbm() -> type[Any] | None:
    try:
        from lightgbm import LGBMRegressor

        return LGBMRegressor
    except ImportError:
        return None


def _try_import_xgboost() -> type[Any] | None:
    try:
        from xgboost import XGBRegressor

        return XGBRegressor
    except ImportError:
        return None


LINEAR_ALGORITHMS = frozenset({"Ridge", "ElasticNet"})


def build_estimator(
    algorithm: str,
    params: dict[str, Any] | None = None,
    *,
    random_seed: int = 371,
) -> BaseEstimator:
    """Construct a scikit-learn-compatible regressor.

    Optional LightGBM / XGBoost backends are used when installed; otherwise
    ``HistGradientBoostingRegressor`` is substituted so the pipeline never
    fails because of a platform-specific binary.
    """
    params = dict(params or {})
    params.setdefault("random_state", random_seed)

    if algorithm == "Ridge":
        params.pop("random_state", None)
        return Ridge(**params)
    if algorithm == "ElasticNet":
        params.setdefault("max_iter", 5000)
        params.pop("random_state", None)
        return ElasticNet(**params)
    if algorithm == "RandomForestRegressor":
        params.setdefault("n_jobs", -1)
        return RandomForestRegressor(**params)
    if algorithm == "ExtraTreesRegressor":
        params.setdefault("n_jobs", -1)
        return ExtraTreesRegressor(**params)
    if algorithm == "HistGradientBoostingRegressor":
        return HistGradientBoostingRegressor(**params)
    if algorithm == "GradientBoostingRegressor":
        return GradientBoostingRegressor(**params)
    if algorithm == "LGBMRegressor":
        cls = _try_import_lightgbm()
        if cls is None:
            logger.warning("lightgbm not installed; falling back to HistGradientBoostingRegressor.")
            return HistGradientBoostingRegressor(random_state=random_seed)
        params.setdefault("verbosity", -1)
        params.setdefault("n_jobs", -1)
        return cls(**params)
    if algorithm == "XGBRegressor":
        cls = _try_import_xgboost()
        if cls is None:
            logger.warning("xgboost not installed; falling back to HistGradientBoostingRegressor.")
            return HistGradientBoostingRegressor(random_state=random_seed)
        params.setdefault("n_jobs", -1)
        params.setdefault("verbosity", 0)
        return cls(**params)
    if algorithm == "WeightedEnsemble":
        raise ValueError("WeightedEnsemble is constructed by models.ensemble, not build_estimator.")
    raise ValueError(f"Unknown algorithm '{algorithm}'.")


@dataclass
class TrainedModel:
    """A fitted estimator plus the fold-safe preprocessor that feeds it."""

    algorithm: str
    position: str
    target: str
    feature_columns: list[str]
    estimator: BaseEstimator
    preprocessor: FoldPreprocessor
    params: dict[str, Any] = field(default_factory=dict)
    train_metrics: RegressionMetrics | None = None
    trained_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    architecture: str = "direct"

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        matrix = self.preprocessor.transform(frame)
        return np.asarray(self.estimator.predict(matrix.values), dtype=float)


def train_position_target(
    train: pl.DataFrame,
    *,
    position: str,
    target_column: str,
    feature_columns: Sequence[str],
    algorithm: str,
    params: dict[str, Any] | None = None,
    preprocessing: PreprocessingSettings,
    random_seed: int = 371,
    holdout: pl.DataFrame | None = None,
) -> TrainedModel:
    """Fit preprocessor + estimator on training rows for one position-target."""
    params = dict(params or {})
    scale = algorithm in LINEAR_ALGORITHMS
    preprocessor = FoldPreprocessor(
        settings=preprocessing,
        feature_columns=list(feature_columns),
        scale=scale,
    )
    x_train = preprocessor.fit_transform(train)
    y_train = extract_target(train, target_column)

    estimator = build_estimator(algorithm, params, random_seed=random_seed)
    estimator.fit(x_train.values, y_train)

    train_metrics = regression_metrics(
        np.asarray(estimator.predict(x_train.values), dtype=float),
        y_train,
    )
    if holdout is not None and holdout.height:
        y_hold = extract_target(holdout, target_column)
        preds = np.asarray(
            estimator.predict(preprocessor.transform(holdout).values),
            dtype=float,
        )
        hold_metrics = regression_metrics(preds, y_hold)
        logger.info(
            "Trained %s/%s (%s): train MAE=%.3f holdout MAE=%s",
            position,
            target_column,
            algorithm,
            train_metrics.mae or float("nan"),
            f"{hold_metrics.mae:.3f}" if hold_metrics.mae is not None else "n/a",
        )

    return TrainedModel(
        algorithm=algorithm,
        position=position,
        target=target_column,
        feature_columns=list(feature_columns),
        estimator=estimator,
        preprocessor=preprocessor,
        params=params,
        train_metrics=train_metrics,
    )


class SklearnRegressorAdapter(BaseEstimator, RegressorMixin):
    """Thin wrapper so ensembles can treat any predict-callable uniformly."""

    def __init__(self, model: TrainedModel) -> None:
        self.model = model

    def fit(self, X: Any, y: Any = None) -> SklearnRegressorAdapter:
        del X, y
        return self

    def predict(self, X: Any) -> np.ndarray:
        # When called with a FeatureMatrix-like ndarray already transformed,
        # use the underlying estimator directly.
        return np.asarray(self.model.estimator.predict(X), dtype=float)

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        del deep
        return {"model": self.model}

    def set_params(self, **params: Any) -> SklearnRegressorAdapter:
        if "model" in params:
            self.model = params["model"]
        return self


def clone_estimator(estimator: BaseEstimator) -> BaseEstimator:
    return clone(estimator)
