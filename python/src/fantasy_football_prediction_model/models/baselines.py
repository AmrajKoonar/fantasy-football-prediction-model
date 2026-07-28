"""Baseline projections that every ML candidate must beat.

A complex model is only preferred when it improves out-of-sample accuracy
relative to these baselines. When a baseline wins for a target, that result
is published rather than hidden.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import polars as pl
from sklearn.linear_model import Ridge

from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class BaselinePrediction:
    """Point predictions from a named baseline."""

    name: str
    values: np.ndarray


class BaselineModel(ABC):
    """Fit on historical pairs, predict for held-out pairs."""

    name: str

    @abstractmethod
    def fit(
        self,
        train: pl.DataFrame,
        *,
        target_column: str,
        feature_columns: Sequence[str] | None = None,
    ) -> BaselineModel:
        """Learn any parameters from training rows only."""

    @abstractmethod
    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        """Return one prediction per row."""


def _col_or_zero(frame: pl.DataFrame, name: str) -> np.ndarray:
    if name not in frame.columns:
        return np.zeros(frame.height, dtype=float)
    return frame.get_column(name).cast(pl.Float64, strict=False).fill_null(0.0).to_numpy()


def _stat_from_outcome(target_column: str) -> str:
    """Map ``outcome_passing_yards`` -> ``passing_yards``."""
    if target_column.startswith("outcome_"):
        return target_column.removeprefix("outcome_")
    return target_column


class PreviousSeasonTotal(BaselineModel):
    """Last observed season total for the same statistic."""

    name = "previous_season_total"

    def __init__(self) -> None:
        self._stat: str = ""

    def fit(
        self,
        train: pl.DataFrame,
        *,
        target_column: str,
        feature_columns: Sequence[str] | None = None,
    ) -> PreviousSeasonTotal:
        del train, feature_columns
        self._stat = _stat_from_outcome(target_column)
        return self

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        return _col_or_zero(frame, self._stat)


class PreviousSeasonPerGame(BaselineModel):
    """Prior per-game rate times expected games (or prior games)."""

    name = "previous_season_per_game"

    def __init__(self) -> None:
        self._stat: str = ""

    def fit(
        self,
        train: pl.DataFrame,
        *,
        target_column: str,
        feature_columns: Sequence[str] | None = None,
    ) -> PreviousSeasonPerGame:
        del train, feature_columns
        self._stat = _stat_from_outcome(target_column)
        return self

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        totals = _col_or_zero(frame, self._stat)
        games = _col_or_zero(frame, "games")
        expected = _col_or_zero(frame, "expected_games")
        if not np.any(expected):
            expected = np.where(games > 0, games, 16.0)
        rate = np.divide(totals, games, out=np.zeros_like(totals), where=games > 0)
        return rate * expected


class WeightedAverageBaseline(BaselineModel):
    """Weighted blend of prior totals when lag columns exist."""

    def __init__(self, name: str, weights: tuple[float, ...]) -> None:
        self.name = name
        self.weights = weights
        self._stat: str = ""

    def fit(
        self,
        train: pl.DataFrame,
        *,
        target_column: str,
        feature_columns: Sequence[str] | None = None,
    ) -> WeightedAverageBaseline:
        del train, feature_columns
        self._stat = _stat_from_outcome(target_column)
        return self

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        series = [_col_or_zero(frame, self._stat)]
        for lag in range(1, len(self.weights)):
            lag_name = f"{self._stat}_lag{lag}"
            if lag_name in frame.columns:
                series.append(_col_or_zero(frame, lag_name))
            else:
                series.append(series[0].copy())
        stacked = np.column_stack(series[: len(self.weights)])
        weights = np.asarray(self.weights[: stacked.shape[1]], dtype=float)
        weights = weights / weights.sum()
        return stacked @ weights


class PositionAgeGroupAverage(BaselineModel):
    """Mean outcome within position × age band on the training fold."""

    name = "position_age_group_average"

    def __init__(self) -> None:
        self._lookup: dict[tuple[str, str], float] = {}
        self._global: float = 0.0
        self._position_means: dict[str, float] = {}

    def fit(
        self,
        train: pl.DataFrame,
        *,
        target_column: str,
        feature_columns: Sequence[str] | None = None,
    ) -> PositionAgeGroupAverage:
        del feature_columns
        y = _col_or_zero(train, target_column)
        self._global = float(np.nanmean(y)) if y.size else 0.0
        positions = (
            train.get_column("position").to_list()
            if "position" in train.columns
            else ["UNK"] * train.height
        )
        ages = (
            train.get_column("age_at_target_season").to_numpy()
            if "age_at_target_season" in train.columns
            else np.full(train.height, np.nan)
        )
        buckets = [_age_bucket(age) for age in ages]
        sums: dict[tuple[str, str], list[float]] = {}
        pos_sums: dict[str, list[float]] = {}
        for position, bucket, value in zip(positions, buckets, y, strict=True):
            key = (str(position), bucket)
            sums.setdefault(key, []).append(float(value))
            pos_sums.setdefault(str(position), []).append(float(value))
        self._lookup = {key: float(np.mean(vals)) for key, vals in sums.items()}
        self._position_means = {pos: float(np.mean(vals)) for pos, vals in pos_sums.items()}
        return self

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        positions = (
            frame.get_column("position").to_list()
            if "position" in frame.columns
            else ["UNK"] * frame.height
        )
        ages = (
            frame.get_column("age_at_target_season").to_numpy()
            if "age_at_target_season" in frame.columns
            else np.full(frame.height, np.nan)
        )
        out = np.empty(frame.height, dtype=float)
        for i, (position, age) in enumerate(zip(positions, ages, strict=True)):
            key = (str(position), _age_bucket(age))
            if key in self._lookup:
                out[i] = self._lookup[key]
            elif str(position) in self._position_means:
                out[i] = self._position_means[str(position)]
            else:
                out[i] = self._global
        return out


class RidgeBaseline(BaselineModel):
    """Regularized linear regression on numeric features."""

    name = "ridge_baseline"

    def __init__(self, alpha: float = 10.0, random_seed: int = 371) -> None:
        self.alpha = alpha
        self.random_seed = random_seed
        self._model: Ridge | None = None
        self._feature_columns: list[str] = []
        self._medians: np.ndarray = np.array([])

    def fit(
        self,
        train: pl.DataFrame,
        *,
        target_column: str,
        feature_columns: Sequence[str] | None = None,
    ) -> RidgeBaseline:
        cols = list(feature_columns or [])
        numeric = [
            c
            for c in cols
            if c in train.columns and train.schema[c].is_numeric()
        ][:40]
        if not numeric:
            numeric = [
                c
                for c in train.columns
                if train.schema[c].is_numeric()
                and not c.startswith("outcome_")
                and c not in {target_column, "target_season", "season"}
            ][:40]
        self._feature_columns = numeric
        matrix = self._matrix(train)
        y = _col_or_zero(train, target_column)
        self._model = Ridge(alpha=self.alpha, random_state=self.random_seed)
        self._model.fit(matrix, y)
        return self

    def _matrix(self, frame: pl.DataFrame) -> np.ndarray:
        cols = []
        for name in self._feature_columns:
            cols.append(_col_or_zero(frame, name))
        if not cols:
            return np.zeros((frame.height, 1), dtype=float)
        matrix = np.column_stack(cols)
        if self._medians.size == 0:
            with np.errstate(all="ignore"):
                self._medians = np.nanmedian(matrix, axis=0)
            self._medians = np.where(np.isfinite(self._medians), self._medians, 0.0)
        missing = ~np.isfinite(matrix)
        matrix = np.where(missing, self._medians, matrix)
        return matrix

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("RidgeBaseline.predict called before fit.")
        return np.asarray(self._model.predict(self._matrix(frame)), dtype=float)


class HistoricalMedianOpportunity(BaselineModel):
    """Median outcome among training rows with similar opportunity volume."""

    name = "historical_median_comparable_opportunity"

    def __init__(self, n_tiers: int = 4) -> None:
        self.n_tiers = n_tiers
        self._edges: np.ndarray = np.array([])
        self._medians: dict[int, float] = {}
        self._global: float = 0.0
        self._opportunity_column: str = "fantasy_points_ppr"

    def fit(
        self,
        train: pl.DataFrame,
        *,
        target_column: str,
        feature_columns: Sequence[str] | None = None,
    ) -> HistoricalMedianOpportunity:
        del feature_columns
        y = _col_or_zero(train, target_column)
        self._global = float(np.nanmedian(y)) if y.size else 0.0
        for candidate in ("fantasy_points_ppr", "targets", "carries", "pass_attempts", "games"):
            if candidate in train.columns:
                self._opportunity_column = candidate
                break
        opportunity = _col_or_zero(train, self._opportunity_column)
        finite = opportunity[np.isfinite(opportunity)]
        if finite.size >= self.n_tiers * 2:
            self._edges = np.unique(
                np.quantile(finite, np.linspace(0, 1, self.n_tiers + 1)[1:-1])
            )
        else:
            self._edges = np.array([])
        tiers = np.digitize(opportunity, self._edges, right=True) if self._edges.size else np.zeros(
            train.height, dtype=int
        )
        for tier in np.unique(tiers):
            mask = tiers == tier
            if mask.any():
                self._medians[int(tier)] = float(np.nanmedian(y[mask]))
        return self

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        opportunity = _col_or_zero(frame, self._opportunity_column)
        tiers = (
            np.digitize(opportunity, self._edges, right=True)
            if self._edges.size
            else np.zeros(frame.height, dtype=int)
        )
        return np.array(
            [self._medians.get(int(tier), self._global) for tier in tiers],
            dtype=float,
        )


def _age_bucket(age: float) -> str:
    if not np.isfinite(age):
        return "unknown"
    if age < 24:
        return "under 24"
    if age < 27:
        return "24-26"
    if age < 30:
        return "27-29"
    if age < 33:
        return "30-32"
    return "33 and over"


def build_baseline_registry(random_seed: int = 371) -> dict[str, BaselineModel]:
    """Fresh baseline instances for one fold."""
    return {
        "previous_season_total": PreviousSeasonTotal(),
        "previous_season_per_game": PreviousSeasonPerGame(),
        "two_year_weighted_average": WeightedAverageBaseline(
            "two_year_weighted_average", (0.65, 0.35)
        ),
        "three_year_weighted_average": WeightedAverageBaseline(
            "three_year_weighted_average", (0.5, 0.3, 0.2)
        ),
        "position_age_group_average": PositionAgeGroupAverage(),
        "ridge_baseline": RidgeBaseline(random_seed=random_seed),
        "historical_median_comparable_opportunity": HistoricalMedianOpportunity(),
    }


#: Default registry factory used by ``models.__init__``.
BASELINE_REGISTRY = build_baseline_registry


def fit_and_predict_baselines(
    train: pl.DataFrame,
    test: pl.DataFrame,
    *,
    target_column: str,
    feature_columns: Sequence[str] | None = None,
    random_seed: int = 371,
) -> list[BaselinePrediction]:
    """Fit every baseline on ``train`` and predict ``test``."""
    results: list[BaselinePrediction] = []
    for name, model in build_baseline_registry(random_seed).items():
        try:
            model.fit(train, target_column=target_column, feature_columns=feature_columns)
            values = model.predict(test)
            results.append(BaselinePrediction(name=name, values=values))
        except Exception as exc:  # noqa: BLE001 - baselines must not abort a fold
            logger.warning("Baseline %s failed: %s", name, exc)
    return results
