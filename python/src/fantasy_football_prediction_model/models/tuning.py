"""Time-aware hyperparameter search."""

from __future__ import annotations

import itertools
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from fantasy_football_prediction_model.config import PreprocessingSettings, TuningSettings
from fantasy_football_prediction_model.evaluation.metrics import regression_metrics
from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.models.preprocessing import FoldPreprocessor, extract_target
from fantasy_football_prediction_model.models.training import LINEAR_ALGORITHMS, build_estimator

logger = get_logger(__name__)


@dataclass(slots=True)
class TuningResult:
    """Best parameters found on an inner seasonal holdout."""

    algorithm: str
    best_params: dict[str, Any]
    best_mae: float | None
    n_trials: int
    search_space: dict[str, list[Any]]


def _expand_grid(space: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not space:
        return [{}]
    keys = list(space)
    values = [space[key] for key in keys]
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*values)]


def _sample_space(
    space: dict[str, list[Any]], n_iter: int, rng: random.Random
) -> list[dict[str, Any]]:
    if not space:
        return [{}]
    keys = list(space)
    trials: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    attempts = 0
    max_attempts = max(n_iter * 20, 50)
    while len(trials) < n_iter and attempts < max_attempts:
        attempts += 1
        combo = tuple(rng.choice(space[key]) for key in keys)
        if combo in seen:
            continue
        seen.add(combo)
        trials.append(dict(zip(keys, combo, strict=True)))
    return trials


def inner_holdout_split(
    train: pl.DataFrame,
    *,
    season_column: str = "target_season",
    holdout_seasons: int = 2,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Split the last ``holdout_seasons`` outcome seasons for tuning.

    The fold's eventual test season is never present in ``train``, so this
    holdout is still strictly prior information.
    """
    if season_column not in train.columns or train.is_empty():
        split = max(int(train.height * 0.8), 1) if train.height else 0
        return train.head(split), train.tail(train.height - split)

    seasons = sorted(train.get_column(season_column).unique().to_list())
    if len(seasons) <= holdout_seasons:
        holdout_cut = seasons[-1:]
    else:
        holdout_cut = seasons[-holdout_seasons:]
    holdout = train.filter(pl.col(season_column).is_in(holdout_cut))
    fit = train.filter(~pl.col(season_column).is_in(holdout_cut))
    if fit.is_empty():
        return train, train.head(0)
    return fit, holdout


def tune_estimator(
    train: pl.DataFrame,
    *,
    algorithm: str,
    algorithm_key: str,
    target_column: str,
    feature_columns: Sequence[str],
    tuning: TuningSettings,
    preprocessing: PreprocessingSettings,
    random_seed: int = 371,
) -> TuningResult:
    """Search hyperparameters with a seasonal inner holdout."""
    space = dict(tuning.search_space.get(algorithm_key, {}))
    if not tuning.enabled or tuning.strategy == "none" or not space:
        return TuningResult(
            algorithm=algorithm,
            best_params={},
            best_mae=None,
            n_trials=0,
            search_space=space,
        )

    fit_frame, holdout = inner_holdout_split(
        train, holdout_seasons=tuning.inner_holdout_seasons
    )
    if holdout.is_empty():
        logger.warning("Inner holdout empty for %s; skipping tuning.", algorithm)
        return TuningResult(
            algorithm=algorithm,
            best_params={},
            best_mae=None,
            n_trials=0,
            search_space=space,
        )

    rng = random.Random(random_seed)
    if tuning.strategy == "grid":
        trials = _expand_grid(space)
    else:
        trials = _sample_space(space, tuning.n_iter, rng)

    best_params: dict[str, Any] = {}
    best_mae: float | None = None

    scale = algorithm in LINEAR_ALGORITHMS
    for params in trials:
        # sklearn rejects JSON-null max_depth; YAML null becomes None already.
        cleaned = {k: v for k, v in params.items()}
        try:
            preprocessor = FoldPreprocessor(
                settings=preprocessing,
                feature_columns=list(feature_columns),
                scale=scale,
            )
            x_fit = preprocessor.fit_transform(fit_frame)
            y_fit = extract_target(fit_frame, target_column)
            estimator = build_estimator(algorithm, cleaned, random_seed=random_seed)
            estimator.fit(x_fit.values, y_fit)
            preds = np.asarray(
                estimator.predict(preprocessor.transform(holdout).values),
                dtype=float,
            )
            metrics = regression_metrics(preds, extract_target(holdout, target_column))
            mae = metrics.mae
            if mae is None:
                continue
            if best_mae is None or mae < best_mae:
                best_mae = mae
                best_params = cleaned
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tuning trial failed for %s params=%s: %s", algorithm, cleaned, exc)

    logger.info(
        "Tuning %s: best MAE=%s over %d trials params=%s",
        algorithm,
        f"{best_mae:.3f}" if best_mae is not None else "n/a",
        len(trials),
        best_params,
    )
    return TuningResult(
        algorithm=algorithm,
        best_params=best_params,
        best_mae=best_mae,
        n_trials=len(trials),
        search_space=space,
    )
