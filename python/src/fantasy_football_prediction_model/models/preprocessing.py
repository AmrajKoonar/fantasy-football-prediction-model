"""Fold-safe preprocessing.

Everything that learns a statistic from the data - imputation values,
winsorisation bounds, scaling parameters - is fitted on the training rows of a
single fold and then applied unchanged to that fold's test rows. Fitting on
the full dataset first is the classic way to make a backtest look better than
the model really is, so the transformer physically cannot see test rows: it is
constructed inside the fold loop and discarded afterwards.

Missing values are treated as information rather than noise. Alongside the
imputed value the preprocessor emits a missing indicator, so a model can learn
that "no Next Gen Stats coverage" is itself predictive of a low-usage player.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import polars as pl

from fantasy_football_prediction_model.config import PreprocessingSettings
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class FeatureMatrix:
    """A dense numeric matrix plus the names of its columns."""

    values: np.ndarray
    columns: list[str]

    def __post_init__(self) -> None:
        if self.values.ndim != 2:
            raise ValueError(f"Feature matrix must be 2-D, got shape {self.values.shape}.")
        if self.values.shape[1] != len(self.columns):
            raise ValueError(
                f"Feature matrix has {self.values.shape[1]} columns but {len(self.columns)} names."
            )

    @property
    def n_rows(self) -> int:
        return int(self.values.shape[0])


@dataclass(slots=True)
class FoldPreprocessor:
    """Imputer, winsoriser and scaler fitted on one fold's training rows."""

    settings: PreprocessingSettings
    feature_columns: list[str]
    scale: bool = False

    fitted: bool = field(default=False, init=False)
    _impute_values: np.ndarray = field(default_factory=lambda: np.array([]), init=False)
    _lower_bounds: np.ndarray | None = field(default=None, init=False)
    _upper_bounds: np.ndarray | None = field(default=None, init=False)
    _means: np.ndarray | None = field(default=None, init=False)
    _scales: np.ndarray | None = field(default=None, init=False)
    _indicator_columns: list[str] = field(default_factory=list, init=False)
    _constant_columns: list[str] = field(default_factory=list, init=False)

    # -- extraction ----------------------------------------------------------

    def _extract(self, frame: pl.DataFrame) -> np.ndarray:
        """Pull the feature columns out as a float matrix.

        A configured feature that the frame does not have becomes an all-null
        column rather than an error, so a fold missing an advanced source
        still runs with that feature marked missing.
        """
        series: list[np.ndarray] = []
        for name in self.feature_columns:
            if name in frame.columns:
                column = frame.get_column(name).cast(pl.Float64, strict=False).to_numpy()
            else:
                column = np.full(frame.height, np.nan, dtype=float)
            series.append(np.asarray(column, dtype=float))
        if not series:
            return np.empty((frame.height, 0), dtype=float)
        matrix = np.column_stack(series)
        # Infinities come from a rate whose denominator slipped through as
        # zero. Treat them as missing rather than letting them dominate.
        infinite = ~np.isfinite(matrix) & ~np.isnan(matrix)
        if infinite.any():
            logger.warning(
                "Replaced %d non-finite feature value(s) with missing before fitting.",
                int(infinite.sum()),
            )
            matrix[infinite] = np.nan
        return matrix

    # -- fitting -------------------------------------------------------------

    def fit(self, train: pl.DataFrame) -> FoldPreprocessor:
        """Learn imputation, clipping and scaling from training rows only."""
        matrix = self._extract(train)
        if matrix.shape[0] == 0:
            raise ValueError("Cannot fit the preprocessor on zero training rows.")

        with np.errstate(all="ignore"):
            if self.settings.numeric_imputer == "median":
                statistic = np.nanmedian(matrix, axis=0)
            elif self.settings.numeric_imputer == "mean":
                statistic = np.nanmean(matrix, axis=0)
            else:
                statistic = np.zeros(matrix.shape[1], dtype=float)
        # A column that is missing for every training row has no statistic;
        # zero is the only defensible fallback and the indicator marks it.
        statistic = np.where(np.isfinite(statistic), statistic, 0.0)
        self._impute_values = statistic

        if self.settings.winsorize.enabled and matrix.shape[0] >= 20:
            with np.errstate(all="ignore"):
                self._lower_bounds = np.nanquantile(
                    matrix, self.settings.winsorize.lower_quantile, axis=0
                )
                self._upper_bounds = np.nanquantile(
                    matrix, self.settings.winsorize.upper_quantile, axis=0
                )
            self._lower_bounds = np.where(
                np.isfinite(self._lower_bounds), self._lower_bounds, -np.inf
            )
            self._upper_bounds = np.where(
                np.isfinite(self._upper_bounds), self._upper_bounds, np.inf
            )

        prepared = self._apply(matrix)

        if self.scale and self.settings.scale_linear_models:
            self._means = prepared.mean(axis=0)
            deviation = prepared.std(axis=0)
            # A zero-variance column would divide by zero; leave it unscaled.
            self._scales = np.where(deviation > 1e-12, deviation, 1.0)

        variances = prepared.var(axis=0)
        self._constant_columns = [
            name
            for name, variance in zip(self._output_columns(), variances, strict=True)
            if variance <= 1e-15
        ]
        if self._constant_columns:
            logger.debug(
                "%d feature column(s) are constant within this fold and carry no signal: %s",
                len(self._constant_columns),
                self._constant_columns[:8],
            )

        self.fitted = True
        return self

    # -- transformation ------------------------------------------------------

    def _apply(self, matrix: np.ndarray) -> np.ndarray:
        """Clip, impute and optionally append indicators. No fitting here."""
        missing_mask = np.isnan(matrix)

        if self._lower_bounds is not None and self._upper_bounds is not None:
            matrix = np.clip(matrix, self._lower_bounds, self._upper_bounds)

        filled = np.where(missing_mask, self._impute_values, matrix)

        if self.settings.add_missing_indicators and matrix.shape[1]:
            return np.hstack([filled, missing_mask.astype(float)])
        return filled

    def _output_columns(self) -> list[str]:
        columns = list(self.feature_columns)
        if self.settings.add_missing_indicators:
            columns += [f"{name}__is_missing" for name in self.feature_columns]
        return columns

    def transform(self, frame: pl.DataFrame) -> FeatureMatrix:
        """Apply the fitted transformation to any frame."""
        if not self.fitted:
            raise RuntimeError("FoldPreprocessor.transform called before fit.")
        prepared = self._apply(self._extract(frame))
        if self._means is not None and self._scales is not None:
            prepared = (prepared - self._means) / self._scales
        if not np.isfinite(prepared).all():
            prepared = np.nan_to_num(prepared, nan=0.0, posinf=0.0, neginf=0.0)
        return FeatureMatrix(values=prepared, columns=self._output_columns())

    def fit_transform(self, train: pl.DataFrame) -> FeatureMatrix:
        return self.fit(train).transform(train)

    # -- introspection, used by the leakage tests ----------------------------

    @property
    def imputation_values(self) -> np.ndarray:
        return self._impute_values

    def raw_training_matrix(self, frame: pl.DataFrame) -> np.ndarray:
        """The unprocessed matrix, so a test can recompute the statistics."""
        return self._extract(frame)


def extract_target(frame: pl.DataFrame, column: str) -> np.ndarray:
    """Pull a target column out as a float vector."""
    if column not in frame.columns:
        raise KeyError(f"Target column '{column}' is not present.")
    return frame.get_column(column).cast(pl.Float64, strict=False).fill_null(0.0).to_numpy()


def apply_minimum_volume(frame: pl.DataFrame, min_volume: dict[str, float]) -> pl.DataFrame:
    """Null out rate features computed from too little volume.

    A completion percentage from four attempts is noise dressed up as a
    measurement. Setting it to null lets the missing indicator carry the real
    information - that there was not enough volume to judge - instead of
    feeding the model a number it will treat as a genuine skill estimate.
    """
    #: rate column -> (denominator column, config key)
    guards: dict[str, tuple[str, str]] = {
        "completion_pct": ("pass_attempts", "pass_attempts"),
        "yards_per_attempt": ("pass_attempts", "pass_attempts"),
        "adjusted_yards_per_attempt": ("pass_attempts", "pass_attempts"),
        "passing_td_rate": ("pass_attempts", "pass_attempts"),
        "interception_rate": ("pass_attempts", "pass_attempts"),
        "sack_rate": ("pass_attempts", "pass_attempts"),
        "yards_per_carry": ("carries", "rush_attempts"),
        "rushing_td_rate": ("carries", "rush_attempts"),
        "rushing_success_rate": ("carries", "rush_attempts"),
        "explosive_run_rate": ("carries", "rush_attempts"),
        "stuffed_run_rate": ("carries", "rush_attempts"),
        "catch_rate": ("targets", "targets"),
        "yards_per_target": ("targets", "targets"),
        "receiving_td_rate": ("targets", "targets"),
        "adot": ("targets", "targets"),
        "racr": ("targets", "targets"),
        "targets_per_route_run": ("routes_estimated", "routes"),
        "yards_per_route_run": ("routes_estimated", "routes"),
        "fantasy_points_ppr_per_game": ("games", "games"),
    }

    expressions: list[pl.Expr] = []
    for rate, (denominator, key) in guards.items():
        if rate not in frame.columns or denominator not in frame.columns:
            continue
        threshold = min_volume.get(key)
        if threshold is None:
            continue
        expressions.append(
            pl.when(pl.col(denominator).fill_null(0) >= threshold)
            .then(pl.col(rate))
            .otherwise(None)
            .alias(rate)
        )
    return frame.with_columns(expressions) if expressions else frame


def select_feature_columns(
    frame: pl.DataFrame,
    candidates: Sequence[str],
    *,
    min_coverage: float,
    always_keep: Sequence[str] = (),
    max_features: int | None = None,
    ranking: dict[str, float] | None = None,
) -> list[str]:
    """Filter candidate features by coverage, then cap the count.

    Args:
        frame: Rows the model will be trained on.
        candidates: Feature names to consider.
        min_coverage: Minimum fraction of rows where the feature is present.
        always_keep: Features retained regardless of coverage.
        max_features: Cap on the returned list.
        ranking: Optional importance scores used to choose which features
            survive the cap. Without it the configured order is used.

    Returns:
        The selected feature names, in a deterministic order.
    """
    if frame.is_empty():
        return list(candidates)

    kept: list[str] = []
    for name in candidates:
        if name not in frame.columns:
            continue
        if not frame.schema[name].is_numeric():
            continue
        coverage = float(frame.get_column(name).is_not_null().mean() or 0.0)
        if name in always_keep or coverage >= min_coverage:
            kept.append(name)

    if max_features is not None and len(kept) > max_features:
        if ranking:
            kept = sorted(kept, key=lambda name: (-ranking.get(name, 0.0), name))
        pinned = [name for name in kept if name in always_keep]
        rest = [name for name in kept if name not in always_keep]
        kept = pinned + rest[: max(max_features - len(pinned), 0)]

    return kept
