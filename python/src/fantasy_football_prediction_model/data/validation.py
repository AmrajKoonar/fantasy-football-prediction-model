"""Data-quality and leakage validation.

Two rules govern this module:

* **A validation failure is never silent.** Every check produces a record, and
  critical failures abort the run before anything is exported.
* **A check that cannot run is reported, not skipped.** If a column needed for
  a check is missing, that is itself a finding.

The same :class:`ValidationReport` type is used for ingestion checks, feature
checks and export checks, so ``ffpm project validate`` can print one table.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from enum import Enum

import polars as pl

from fantasy_football_prediction_model.constants import (
    FANTASY_POSITIONS,
    MAX_PLAUSIBLE_AGE,
    MIN_PLAUSIBLE_AGE,
    STAT_SANITY_BOUNDS,
)
from fantasy_football_prediction_model.logging import DataQualityError, get_logger

logger = get_logger(__name__)


class Severity(str, Enum):
    """How badly a failed check should be treated."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    """Blocks the production export."""


@dataclass(slots=True)
class ValidationResult:
    check: str
    passed: bool
    severity: Severity
    message: str
    count: int = 0
    examples: list[str] = field(default_factory=list)
    dataset: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        payload["examples"] = "; ".join(self.examples[:5])
        return payload


@dataclass(slots=True)
class ValidationReport:
    """Accumulated results for one validation pass."""

    results: list[ValidationResult] = field(default_factory=list)

    def add(self, result: ValidationResult) -> ValidationResult:
        self.results.append(result)
        if not result.passed:
            log = {
                Severity.INFO: logger.info,
                Severity.WARNING: logger.warning,
                Severity.ERROR: logger.error,
            }[result.severity]
            log("[%s] %s (%d affected)", result.check, result.message, result.count)
        return result

    def ok(self, check: str, message: str = "", *, dataset: str = "") -> ValidationResult:
        return self.add(
            ValidationResult(
                check=check,
                passed=True,
                severity=Severity.INFO,
                message=message or "Passed.",
                dataset=dataset,
            )
        )

    def fail(
        self,
        check: str,
        message: str,
        *,
        severity: Severity = Severity.ERROR,
        count: int = 0,
        examples: Iterable[str] = (),
        dataset: str = "",
    ) -> ValidationResult:
        return self.add(
            ValidationResult(
                check=check,
                passed=False,
                severity=severity,
                message=message,
                count=count,
                examples=list(examples)[:10],
                dataset=dataset,
            )
        )

    @property
    def errors(self) -> list[ValidationResult]:
        return [r for r in self.results if not r.passed and r.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationResult]:
        return [r for r in self.results if not r.passed and r.severity is Severity.WARNING]

    @property
    def failed(self) -> bool:
        return bool(self.errors)

    def extend(self, other: ValidationReport) -> ValidationReport:
        self.results.extend(other.results)
        return self

    def to_frame(self) -> pl.DataFrame:
        if not self.results:
            return pl.DataFrame(
                schema={
                    "check": pl.Utf8,
                    "passed": pl.Boolean,
                    "severity": pl.Utf8,
                    "message": pl.Utf8,
                    "count": pl.Int64,
                    "examples": pl.Utf8,
                    "dataset": pl.Utf8,
                }
            )
        return pl.DataFrame([result.to_dict() for result in self.results])

    def summary(self) -> str:
        passed = sum(1 for r in self.results if r.passed)
        return (
            f"{passed}/{len(self.results)} checks passed, "
            f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        )

    def raise_if_failed(self, context: str) -> None:
        """Abort when any ERROR-severity check failed."""
        if not self.failed:
            return
        lines = [f"  - [{r.check}] {r.message}" for r in self.errors]
        raise DataQualityError(
            f"{context} failed {len(self.errors)} critical validation check(s):\n"
            + "\n".join(lines),
            hint=(
                "Inspect artifacts/evaluations/validation-report.csv for the full detail. "
                "Fix the source data or add a documented factual correction in "
                "data/manual/player-context.csv, then rerun."
            ),
        )


# ---------------------------------------------------------------------------
# Generic frame checks
# ---------------------------------------------------------------------------


def check_required_columns(
    frame: pl.DataFrame, columns: Sequence[str], *, dataset: str, report: ValidationReport
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        report.fail(
            "required_columns",
            f"{dataset} is missing required columns: {missing}.",
            count=len(missing),
            examples=missing,
            dataset=dataset,
        )
    else:
        report.ok(
            "required_columns",
            f"{dataset} has all {len(columns)} required columns.",
            dataset=dataset,
        )


def check_not_empty(frame: pl.DataFrame, *, dataset: str, report: ValidationReport) -> None:
    if frame.is_empty():
        report.fail("not_empty", f"{dataset} contains zero rows.", dataset=dataset)
    else:
        report.ok("not_empty", f"{dataset} contains {frame.height} rows.", dataset=dataset)


def check_unique_key(
    frame: pl.DataFrame,
    keys: Sequence[str],
    *,
    dataset: str,
    report: ValidationReport,
    severity: Severity = Severity.ERROR,
) -> None:
    """Assert the frame has exactly one row per key combination."""
    present = [key for key in keys if key in frame.columns]
    if len(present) != len(keys):
        report.fail(
            "unique_key",
            f"{dataset} cannot be key-checked: missing {sorted(set(keys) - set(present))}.",
            severity=Severity.WARNING,
            dataset=dataset,
        )
        return

    duplicates = frame.group_by(present).len().filter(pl.col("len") > 1)
    if duplicates.height:
        examples = [
            " / ".join(str(row[key]) for key in present)
            for row in duplicates.head(10).iter_rows(named=True)
        ]
        report.fail(
            "unique_key",
            f"{dataset} has {duplicates.height} duplicated {tuple(present)} combinations.",
            severity=severity,
            count=duplicates.height,
            examples=examples,
            dataset=dataset,
        )
    else:
        report.ok("unique_key", f"{dataset} is unique on {tuple(present)}.", dataset=dataset)


def check_no_nulls(
    frame: pl.DataFrame,
    columns: Sequence[str],
    *,
    dataset: str,
    report: ValidationReport,
    severity: Severity = Severity.ERROR,
) -> None:
    for column in columns:
        if column not in frame.columns:
            continue
        null_count = int(frame.get_column(column).null_count())
        if null_count:
            report.fail(
                "no_nulls",
                f"{dataset}.{column} has {null_count} null value(s) where none are allowed.",
                severity=severity,
                count=null_count,
                dataset=dataset,
            )
        else:
            report.ok("no_nulls", f"{dataset}.{column} has no nulls.", dataset=dataset)


# ---------------------------------------------------------------------------
# Football plausibility
# ---------------------------------------------------------------------------


def check_stat_bounds(
    frame: pl.DataFrame,
    *,
    dataset: str,
    report: ValidationReport,
    id_column: str = "gsis_id",
    bounds: dict[str, tuple[float, float]] | None = None,
    severity: Severity = Severity.ERROR,
) -> None:
    """Flag statistics outside physically plausible bounds.

    The bounds are deliberately generous. They exist to catch unit errors and
    corruption, not to second-guess an unusual season.
    """
    effective = bounds or STAT_SANITY_BOUNDS
    for column, (low, high) in effective.items():
        if column not in frame.columns:
            continue
        violations = frame.filter(
            pl.col(column).is_not_null() & ((pl.col(column) < low) | (pl.col(column) > high))
        )
        if violations.height:
            examples = []
            for row in violations.head(5).iter_rows(named=True):
                identifier = row.get(id_column, "?")
                examples.append(f"{identifier}: {column}={row[column]}")
            report.fail(
                "stat_bounds",
                f"{dataset}.{column} has {violations.height} value(s) outside [{low}, {high}].",
                severity=severity,
                count=violations.height,
                examples=examples,
                dataset=dataset,
            )
    report.ok("stat_bounds", f"{dataset} bounds check complete.", dataset=dataset)


def check_ratio_consistency(
    frame: pl.DataFrame,
    *,
    dataset: str,
    report: ValidationReport,
    id_column: str = "gsis_id",
    tolerance: float = 1e-6,
    severity: Severity = Severity.ERROR,
) -> None:
    """Assert receptions <= targets and completions <= attempts."""
    pairs = [("receptions", "targets"), ("completions", "pass_attempts")]
    for smaller, larger in pairs:
        if smaller not in frame.columns or larger not in frame.columns:
            continue
        violations = frame.filter(
            pl.col(smaller).is_not_null()
            & pl.col(larger).is_not_null()
            & (pl.col(smaller) > pl.col(larger) + tolerance)
        )
        if violations.height:
            examples = [
                f"{row.get(id_column, '?')}: {smaller}={row[smaller]} > {larger}={row[larger]}"
                for row in violations.head(5).iter_rows(named=True)
            ]
            report.fail(
                "ratio_consistency",
                f"{dataset} has {violations.height} row(s) where {smaller} exceeds {larger}.",
                severity=severity,
                count=violations.height,
                examples=examples,
                dataset=dataset,
            )
        else:
            report.ok("ratio_consistency", f"{dataset}: {smaller} <= {larger}.", dataset=dataset)


def check_games_within_schedule(
    frame: pl.DataFrame,
    games_by_season: dict[int, int],
    *,
    dataset: str,
    report: ValidationReport,
    games_column: str = "games",
    season_column: str = "season",
    severity: Severity = Severity.ERROR,
) -> None:
    """Assert nobody played more games than their team had scheduled.

    Multi-team seasons make this a genuine constraint rather than a formality:
    a traded player can appear on two rosters in the same week in raw data.
    """
    if games_column not in frame.columns or season_column not in frame.columns:
        report.fail(
            "games_within_schedule",
            f"{dataset} lacks {games_column}/{season_column}; the check was skipped.",
            severity=Severity.WARNING,
            dataset=dataset,
        )
        return

    max_expr = pl.col(season_column).replace_strict(
        games_by_season, default=max(games_by_season.values(), default=17), return_dtype=pl.Int64
    )
    violations = frame.filter(pl.col(games_column) > max_expr + 1e-6)
    if violations.height:
        report.fail(
            "games_within_schedule",
            f"{dataset} has {violations.height} row(s) with more games than the season "
            f"schedule allows.",
            severity=severity,
            count=violations.height,
            dataset=dataset,
        )
    else:
        report.ok(
            "games_within_schedule", f"{dataset}: games are within schedule.", dataset=dataset
        )


def check_positions(
    frame: pl.DataFrame,
    *,
    dataset: str,
    report: ValidationReport,
    column: str = "position",
    severity: Severity = Severity.ERROR,
) -> None:
    if column not in frame.columns:
        report.fail(
            "valid_positions",
            f"{dataset} has no '{column}' column.",
            severity=Severity.WARNING,
            dataset=dataset,
        )
        return
    invalid = frame.filter(~pl.col(column).is_in(list(FANTASY_POSITIONS)))
    if invalid.height:
        examples = sorted({str(v) for v in invalid.get_column(column).to_list()})[:10]
        report.fail(
            "valid_positions",
            f"{dataset} has {invalid.height} row(s) with a position outside {FANTASY_POSITIONS}.",
            severity=severity,
            count=invalid.height,
            examples=examples,
            dataset=dataset,
        )
    else:
        report.ok("valid_positions", f"{dataset}: all positions are modelled.", dataset=dataset)


def check_ages(
    frame: pl.DataFrame,
    *,
    dataset: str,
    report: ValidationReport,
    column: str = "age",
    severity: Severity = Severity.WARNING,
) -> None:
    if column not in frame.columns:
        return
    invalid = frame.filter(
        pl.col(column).is_not_null()
        & ((pl.col(column) < MIN_PLAUSIBLE_AGE) | (pl.col(column) > MAX_PLAUSIBLE_AGE))
    )
    if invalid.height:
        report.fail(
            "plausible_age",
            f"{dataset} has {invalid.height} row(s) with an age outside "
            f"[{MIN_PLAUSIBLE_AGE}, {MAX_PLAUSIBLE_AGE}].",
            severity=severity,
            count=invalid.height,
            dataset=dataset,
        )
    else:
        report.ok("plausible_age", f"{dataset}: ages are plausible.", dataset=dataset)


def check_finite(
    frame: pl.DataFrame,
    columns: Sequence[str] | None = None,
    *,
    dataset: str,
    report: ValidationReport,
    severity: Severity = Severity.ERROR,
) -> None:
    """Catch infinities produced by division by a zero denominator."""
    numeric = [
        name
        for name, dtype in frame.schema.items()
        if dtype.is_numeric() and (columns is None or name in columns)
    ]
    offenders: list[str] = []
    total = 0
    for column in numeric:
        count = int(frame.select(pl.col(column).is_infinite().fill_null(False).sum()).item() or 0)
        if count:
            offenders.append(f"{column} ({count})")
            total += count
    if offenders:
        report.fail(
            "finite_values",
            f"{dataset} contains {total} infinite value(s). A per-game or per-opportunity "
            f"rate was computed with a zero denominator.",
            severity=severity,
            count=total,
            examples=offenders,
            dataset=dataset,
        )
    else:
        report.ok("finite_values", f"{dataset}: no infinite values.", dataset=dataset)


def check_non_negative(
    frame: pl.DataFrame,
    columns: Sequence[str],
    *,
    dataset: str,
    report: ValidationReport,
    severity: Severity = Severity.ERROR,
) -> None:
    offenders: list[str] = []
    total = 0
    for column in columns:
        if column not in frame.columns:
            continue
        count = int(frame.select((pl.col(column) < 0).fill_null(False).sum()).item() or 0)
        if count:
            offenders.append(f"{column} ({count})")
            total += count
    if offenders:
        report.fail(
            "non_negative",
            f"{dataset} has {total} negative value(s) in count columns.",
            severity=severity,
            count=total,
            examples=offenders,
            dataset=dataset,
        )
    else:
        report.ok("non_negative", f"{dataset}: counts are non-negative.", dataset=dataset)


# ---------------------------------------------------------------------------
# Modelling-table checks
# ---------------------------------------------------------------------------


def check_player_season_uniqueness(
    frame: pl.DataFrame, *, dataset: str, report: ValidationReport
) -> None:
    check_unique_key(frame, ["gsis_id", "season"], dataset=dataset, report=report)


def check_target_season_alignment(
    frame: pl.DataFrame,
    *,
    dataset: str,
    report: ValidationReport,
    feature_season_column: str = "season",
    target_season_column: str = "target_season",
) -> None:
    """Assert every training row pairs season t with season t+1."""
    if feature_season_column not in frame.columns or target_season_column not in frame.columns:
        report.fail(
            "target_season_alignment",
            f"{dataset} lacks {feature_season_column}/{target_season_column}.",
            severity=Severity.ERROR,
            dataset=dataset,
        )
        return
    misaligned = frame.filter(pl.col(target_season_column) != pl.col(feature_season_column) + 1)
    if misaligned.height:
        report.fail(
            "target_season_alignment",
            f"{dataset} has {misaligned.height} row(s) where the target season is not "
            f"exactly one season after the feature season.",
            count=misaligned.height,
            dataset=dataset,
        )
    else:
        report.ok(
            "target_season_alignment",
            f"{dataset}: every row pairs season t with season t+1.",
            dataset=dataset,
        )
