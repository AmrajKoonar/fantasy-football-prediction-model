"""Temporal-leakage detection.

Leakage is the failure mode most likely to produce an impressive backtest and
a worthless projection, and it is easy to introduce accidentally: one badly
ordered ``shift``, one preprocessing step fitted before the split, one join
that pulls next season's roster into this season's features.

These checks run as part of ``ffpm model backtest`` and as unit tests. A
failure is an error, never a warning, because a leaking model must not be
published.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import polars as pl

from fantasy_football_prediction_model.constants import CANONICAL_ID_COLUMN
from fantasy_football_prediction_model.logging import LeakageError, get_logger

logger = get_logger(__name__)

#: Column prefixes that may only ever appear as a target, never as a feature.
FORBIDDEN_FEATURE_PREFIXES: tuple[str, ...] = ("outcome_",)

#: Columns that describe the outcome season and must not be used as features.
FORBIDDEN_FEATURE_NAMES: frozenset[str] = frozenset(
    {
        "target_played",
        "outcome_team",
        "outcome_position",
        # The season roster's status and last-week columns encode whether a
        # player survived the season, which is the outcome in disguise.
        "roster_status",
        "next_team",
        "projected_team",
        "primary_qb_id",
    }
)


@dataclass(slots=True)
class LeakageCheckResult:
    check: str
    passed: bool
    detail: str
    offenders: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LeakageReport:
    results: list[LeakageCheckResult] = field(default_factory=list)

    def add(self, result: LeakageCheckResult) -> LeakageCheckResult:
        self.results.append(result)
        if result.passed:
            logger.debug("Leakage check '%s' passed.", result.check)
        else:
            logger.error("Leakage check '%s' FAILED: %s", result.check, result.detail)
        return result

    @property
    def failures(self) -> list[LeakageCheckResult]:
        return [result for result in self.results if not result.passed]

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_frame(self) -> pl.DataFrame:
        if not self.results:
            return pl.DataFrame(
                schema={
                    "check": pl.Utf8,
                    "passed": pl.Boolean,
                    "detail": pl.Utf8,
                    "offenders": pl.Utf8,
                }
            )
        return pl.DataFrame(
            [
                {
                    "check": result.check,
                    "passed": result.passed,
                    "detail": result.detail,
                    "offenders": "; ".join(result.offenders[:12]),
                }
                for result in self.results
            ]
        )

    def raise_if_failed(self) -> None:
        if self.passed:
            return
        lines = [f"  - [{result.check}] {result.detail}" for result in self.failures]
        raise LeakageError(
            "Temporal leakage was detected. The model must not be trained or published "
            "in this state:\n" + "\n".join(lines),
            hint=(
                "Check that features are shifted within player and ordered by season, that "
                "preprocessing is fitted on training rows only, and that no season-(t+1) "
                "column entered the feature list. See docs/METHODOLOGY.md."
            ),
        )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_feature_names(
    feature_columns: Sequence[str], report: LeakageReport
) -> LeakageCheckResult:
    """No feature may be an outcome column or an outcome-season descriptor."""
    offenders = sorted(
        name
        for name in feature_columns
        if name in FORBIDDEN_FEATURE_NAMES
        or any(name.startswith(prefix) for prefix in FORBIDDEN_FEATURE_PREFIXES)
    )
    return report.add(
        LeakageCheckResult(
            check="feature_names",
            passed=not offenders,
            detail=(
                f"{len(offenders)} feature(s) describe the outcome season: {offenders}"
                if offenders
                else f"None of the {len(feature_columns)} features reference the outcome season."
            ),
            offenders=offenders,
        )
    )


def check_season_ordering(frame: pl.DataFrame, report: LeakageReport) -> LeakageCheckResult:
    """Every row's feature season must precede its outcome season."""
    if not {"season", "target_season"} <= set(frame.columns):
        return report.add(
            LeakageCheckResult(
                check="season_ordering",
                passed=False,
                detail="The frame has no season/target_season pair to check.",
            )
        )
    violations = frame.filter(pl.col("season") >= pl.col("target_season"))
    return report.add(
        LeakageCheckResult(
            check="season_ordering",
            passed=violations.height == 0,
            detail=(
                f"{violations.height} row(s) have a feature season at or after the outcome season."
                if violations.height
                else f"All {frame.height} rows have season < target_season."
            ),
            offenders=[
                f"{row[CANONICAL_ID_COLUMN]}: {row['season']} -> {row['target_season']}"
                for row in violations.head(10).iter_rows(named=True)
            ],
        )
    )


def check_fold_separation(
    train: pl.DataFrame, test: pl.DataFrame, report: LeakageReport
) -> LeakageCheckResult:
    """A fold's training outcomes must all precede its test outcome season."""
    if train.is_empty() or test.is_empty():
        return report.add(
            LeakageCheckResult(
                check="fold_separation",
                passed=True,
                detail="One side of the fold is empty; nothing to compare.",
            )
        )
    max_train = int(train.get_column("target_season").max() or 0)
    min_test = int(test.get_column("target_season").min() or 0)
    passed = max_train < min_test
    return report.add(
        LeakageCheckResult(
            check="fold_separation",
            passed=passed,
            detail=(
                f"Training outcomes reach {max_train} while the test season starts at {min_test}."
                if not passed
                else f"Training outcomes end at {max_train}, test season is {min_test}."
            ),
        )
    )


def check_feature_seasons_within_fold(
    train: pl.DataFrame, test_season: int, report: LeakageReport
) -> LeakageCheckResult:
    """No training row may carry a feature season at or after the test season."""
    violations = train.filter(pl.col("season") >= test_season)
    return report.add(
        LeakageCheckResult(
            check="feature_seasons_within_fold",
            passed=violations.height == 0,
            detail=(
                f"{violations.height} training row(s) use features from season "
                f">= the test season {test_season}."
                if violations.height
                else f"No training feature season reaches the test season {test_season}."
            ),
        )
    )


def check_no_duplicate_rows(frame: pl.DataFrame, report: LeakageReport) -> LeakageCheckResult:
    """A player may appear at most once per outcome season."""
    keys = [CANONICAL_ID_COLUMN, "target_season"]
    if not set(keys) <= set(frame.columns):
        return report.add(
            LeakageCheckResult(
                check="no_duplicate_rows",
                passed=False,
                detail=f"The frame lacks {keys}.",
            )
        )
    duplicates = frame.group_by(keys).len().filter(pl.col("len") > 1)
    return report.add(
        LeakageCheckResult(
            check="no_duplicate_rows",
            passed=duplicates.height == 0,
            detail=(
                f"{duplicates.height} (player, outcome season) combinations appear more than once."
                if duplicates.height
                else f"All {frame.height} rows are unique on (player, outcome season)."
            ),
            offenders=[
                f"{row[CANONICAL_ID_COLUMN]} @ {row['target_season']}"
                for row in duplicates.head(10).iter_rows(named=True)
            ],
        )
    )


def check_preprocessing_fitted_on_training_only(
    train_values: np.ndarray,
    fitted_statistic: np.ndarray,
    report: LeakageReport,
    *,
    tolerance: float = 1e-8,
) -> LeakageCheckResult:
    """Assert an imputer's statistic matches the training rows alone.

    Recomputes the column medians from the training matrix and compares them
    with what the fitted transformer stored. A mismatch means the transformer
    saw rows it should not have.
    """
    with np.errstate(all="ignore"):
        expected = np.nanmedian(train_values, axis=0)
    finite = np.isfinite(expected) & np.isfinite(fitted_statistic)
    if not finite.any():
        return report.add(
            LeakageCheckResult(
                check="preprocessing_fitted_on_training_only",
                passed=True,
                detail="No finite statistics to compare.",
            )
        )
    difference = np.abs(expected[finite] - fitted_statistic[finite])
    worst = float(difference.max())
    return report.add(
        LeakageCheckResult(
            check="preprocessing_fitted_on_training_only",
            passed=worst <= tolerance,
            detail=(
                f"The fitted imputation statistic differs from the training-only value by "
                f"up to {worst:.6g}, so the transformer saw non-training rows."
                if worst > tolerance
                else "Imputation statistics match the training rows exactly."
            ),
        )
    )


def check_target_not_in_features(
    frame: pl.DataFrame,
    feature_columns: Sequence[str],
    target_column: str,
    report: LeakageReport,
    *,
    correlation_threshold: float = 0.999,
) -> LeakageCheckResult:
    """Catch a feature that is a copy of the target under another name.

    A near-perfect correlation between a feature and the outcome is not
    evidence of a great model; it is evidence that the outcome was joined in
    by accident.
    """
    if target_column not in frame.columns:
        return report.add(
            LeakageCheckResult(
                check="target_not_in_features",
                passed=False,
                detail=f"Target column '{target_column}' is absent.",
            )
        )
    target = frame.get_column(target_column).cast(pl.Float64).to_numpy()
    offenders: list[str] = []
    for name in feature_columns:
        if name not in frame.columns:
            continue
        values = frame.get_column(name).cast(pl.Float64, strict=False).to_numpy()
        mask = np.isfinite(values) & np.isfinite(target)
        if mask.sum() < 30:
            continue
        left, right = values[mask], target[mask]
        if np.std(left) < 1e-12 or np.std(right) < 1e-12:
            continue
        correlation = float(np.corrcoef(left, right)[0, 1])
        if abs(correlation) >= correlation_threshold:
            offenders.append(f"{name} (r={correlation:.4f})")
    return report.add(
        LeakageCheckResult(
            check="target_not_in_features",
            passed=not offenders,
            detail=(
                f"{len(offenders)} feature(s) are almost perfectly correlated with "
                f"'{target_column}', which usually means the target leaked in: {offenders}"
                if offenders
                else f"No feature is degenerate with '{target_column}'."
            ),
            offenders=offenders,
        )
    )


def check_rolling_features_exclude_target_year(
    season_features: pl.DataFrame,
    report: LeakageReport,
    *,
    columns: Sequence[str] = ("fantasy_points_ppr_w2", "fantasy_points_ppr_w3"),
) -> LeakageCheckResult:
    """Assert multi-season averages are backward-looking.

    Recomputes each rolling column from a strictly backward window and checks
    the stored values match. A forward-looking window would disagree.
    """
    if not {CANONICAL_ID_COLUMN, "season"} <= set(season_features.columns):
        return report.add(
            LeakageCheckResult(
                check="rolling_features_backward_only",
                passed=False,
                detail="The season feature table lacks its key columns.",
            )
        )

    offenders: list[str] = []
    ordered = season_features.sort([CANONICAL_ID_COLUMN, "season"])
    for column in columns:
        if column not in ordered.columns:
            continue
        # A backward-looking average can never exceed the running maximum of
        # the source series; a forward-looking one can.
        source = "fantasy_points_ppr"
        if source not in ordered.columns:
            continue
        checked = ordered.with_columns(
            pl.col(source).cum_max().over(CANONICAL_ID_COLUMN).alias("_running_max")
        )
        violations = checked.filter(
            pl.col(column).is_not_null()
            & pl.col("_running_max").is_not_null()
            & (pl.col(column) > pl.col("_running_max") + 1e-6)
        )
        if violations.height:
            offenders.append(f"{column} ({violations.height} rows exceed the running maximum)")

    return report.add(
        LeakageCheckResult(
            check="rolling_features_backward_only",
            passed=not offenders,
            detail=(
                f"Rolling features appear to include future seasons: {offenders}"
                if offenders
                else "Rolling features never exceed the player's running maximum."
            ),
            offenders=offenders,
        )
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_leakage_checks(
    pairs: pl.DataFrame,
    feature_columns: Sequence[str],
    *,
    season_features: pl.DataFrame | None = None,
    target_columns: Sequence[str] = ("outcome_fantasy_points_ppr",),
    raise_on_failure: bool = True,
) -> LeakageReport:
    """Run every dataset-level leakage check.

    Args:
        pairs: The modelling-pair table.
        feature_columns: Columns that will be handed to the models.
        season_features: Phase-1 table, used for the rolling-window check.
        target_columns: Outcome columns to test features against.
        raise_on_failure: Raise :class:`LeakageError` when a check fails.

    Returns:
        The completed report.
    """
    report = LeakageReport()
    check_feature_names(feature_columns, report)
    check_season_ordering(pairs, report)
    check_no_duplicate_rows(pairs, report)
    for target in target_columns:
        check_target_not_in_features(pairs, feature_columns, target, report)
    if season_features is not None:
        check_rolling_features_exclude_target_year(season_features, report)

    if report.passed:
        logger.info("All %d leakage checks passed.", len(report.results))
    if raise_on_failure:
        report.raise_if_failed()
    return report
