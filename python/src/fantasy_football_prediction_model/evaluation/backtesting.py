"""Rolling-origin expanding-window backtesting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

from fantasy_football_prediction_model.config import ModelConfig, Settings
from fantasy_football_prediction_model.evaluation.metrics import (
    rank_metrics,
    regression_metrics,
)
from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.models.baselines import fit_and_predict_baselines
from fantasy_football_prediction_model.models.preprocessing import select_feature_columns
from fantasy_football_prediction_model.models.training import train_position_target
from fantasy_football_prediction_model.models.tuning import tune_estimator

logger = get_logger(__name__)


@dataclass
class FoldPrediction:
    season: int
    position: str
    target: str
    model: str
    is_baseline: bool
    player_ids: list[str]
    predicted: np.ndarray
    actual: np.ndarray


@dataclass
class BacktestResult:
    predictions: list[FoldPrediction] = field(default_factory=list)
    summary_rows: list[dict[str, Any]] = field(default_factory=list)
    selected_models: dict[str, str] = field(default_factory=dict)

    def summary_frame(self) -> pl.DataFrame:
        return pl.DataFrame(self.summary_rows) if self.summary_rows else pl.DataFrame()


def _outcome_column(stat: str) -> str:
    return f"outcome_{stat}"


def run_backtest(
    pairs: pl.DataFrame,
    settings: Settings,
    *,
    positions: Sequence[str] | None = None,
    targets_by_position: dict[str, Sequence[str]] | None = None,
    candidate_limit: int | None = 3,
) -> BacktestResult:
    """Expanding-window backtest over configured seasons.

    ``candidate_limit`` caps how many ML candidates are evaluated per fold so
    CI and laptop runs stay tractable. Pass ``None`` for the full set.
    """
    model_cfg: ModelConfig = settings.model
    positions = list(positions or settings.positions)
    if targets_by_position is None:
        from fantasy_football_prediction_model.constants import PROJECTION_TARGETS

        targets_by_position = {
            pos: [t for t in PROJECTION_TARGETS[pos] if t != "games"] + ["fantasy_points_ppr"]
            for pos in positions
            if pos in PROJECTION_TARGETS
        }

    result = BacktestResult()
    enabled = list(model_cfg.enabled_candidates().items())
    if candidate_limit is not None:
        enabled = [item for item in enabled if item[0] != "ensemble"][:candidate_limit]

    seasons = list(
        range(model_cfg.backtest.first_test_season, model_cfg.backtest.last_test_season + 1)
    )

    for position in positions:
        pos_pairs = pairs.filter(pl.col("position") == position) if "position" in pairs.columns else pairs
        if pos_pairs.height < model_cfg.backtest.min_train_rows:
            logger.warning(
                "Skipping backtest for %s: only %d rows.", position, pos_pairs.height
            )
            continue
        feature_candidates = settings.features.candidate_features(position)
        for target in targets_by_position.get(position, ()):
            target_col = _outcome_column(target)
            if target_col not in pos_pairs.columns:
                continue
            mae_by_model: dict[str, list[float]] = {}
            for test_season in seasons:
                train = pos_pairs.filter(pl.col("target_season") < test_season)
                test = pos_pairs.filter(pl.col("target_season") == test_season)
                if train.height < model_cfg.backtest.min_train_rows or test.is_empty():
                    continue
                features = select_feature_columns(
                    train,
                    feature_candidates,
                    min_coverage=settings.features.selection.min_coverage,
                    always_keep=settings.features.selection.always_keep,
                    max_features=settings.features.selection.max_features_per_model,
                )
                if not features:
                    continue

                player_ids = (
                    test.get_column("gsis_id").to_list()
                    if "gsis_id" in test.columns
                    else [str(i) for i in range(test.height)]
                )
                actual = (
                    test.get_column(target_col)
                    .cast(pl.Float64, strict=False)
                    .fill_null(0.0)
                    .to_numpy()
                )

                for baseline in fit_and_predict_baselines(
                    train,
                    test,
                    target_column=target_col,
                    feature_columns=features,
                    random_seed=settings.seed,
                ):
                    metrics = regression_metrics(baseline.values, actual)
                    ranks = rank_metrics(baseline.values, actual)
                    result.predictions.append(
                        FoldPrediction(
                            season=test_season,
                            position=position,
                            target=target,
                            model=baseline.name,
                            is_baseline=True,
                            player_ids=list(player_ids),
                            predicted=baseline.values,
                            actual=actual,
                        )
                    )
                    row = {
                        "season": test_season,
                        "position": position,
                        "target": target,
                        "model": baseline.name,
                        "is_baseline": True,
                        "mae": metrics.mae,
                        "rmse": metrics.rmse,
                        "r2": metrics.r2,
                        "bias": metrics.bias,
                        "n": metrics.n,
                        "spearman": ranks.spearman,
                    }
                    result.summary_rows.append(row)
                    if metrics.mae is not None:
                        mae_by_model.setdefault(baseline.name, []).append(metrics.mae)

                for key, candidate in enabled:
                    algorithm = candidate.algorithm
                    if algorithm == "WeightedEnsemble":
                        continue
                    if candidate.optional_dependency:
                        try:
                            __import__(candidate.optional_dependency)
                        except ImportError:
                            continue
                    try:
                        tuning = tune_estimator(
                            train,
                            algorithm=algorithm,
                            algorithm_key=key,
                            target_column=target_col,
                            feature_columns=features,
                            tuning=model_cfg.tuning,
                            preprocessing=model_cfg.preprocessing,
                            random_seed=settings.seed,
                        )
                        trained = train_position_target(
                            train,
                            position=position,
                            target_column=target_col,
                            feature_columns=features,
                            algorithm=algorithm,
                            params=tuning.best_params,
                            preprocessing=model_cfg.preprocessing,
                            random_seed=settings.seed,
                        )
                        preds = trained.predict(test)
                        metrics = regression_metrics(preds, actual)
                        ranks = rank_metrics(preds, actual)
                        result.predictions.append(
                            FoldPrediction(
                                season=test_season,
                                position=position,
                                target=target,
                                model=key,
                                is_baseline=False,
                                player_ids=list(player_ids),
                                predicted=preds,
                                actual=actual,
                            )
                        )
                        result.summary_rows.append(
                            {
                                "season": test_season,
                                "position": position,
                                "target": target,
                                "model": key,
                                "is_baseline": False,
                                "mae": metrics.mae,
                                "rmse": metrics.rmse,
                                "r2": metrics.r2,
                                "bias": metrics.bias,
                                "n": metrics.n,
                                "spearman": ranks.spearman,
                            }
                        )
                        if metrics.mae is not None:
                            mae_by_model.setdefault(key, []).append(metrics.mae)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Backtest fold failed %s/%s/%s/%s: %s",
                            position,
                            target,
                            key,
                            test_season,
                            exc,
                        )

            if mae_by_model:
                averages = {
                    name: float(np.mean(values)) for name, values in mae_by_model.items()
                }
                winner = min(averages, key=averages.get)
                result.selected_models[f"{position}:{target}"] = winner
                logger.info(
                    "Selected %s for %s/%s (mean MAE=%.3f)",
                    winner,
                    position,
                    target,
                    averages[winner],
                )

    return result
