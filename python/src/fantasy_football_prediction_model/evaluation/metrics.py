"""Evaluation metrics.

Two families:

* **Regression metrics** for individual projected statistics - how far off is
  the number.
* **Rank metrics** for fantasy usefulness - did the ranking put the right
  players near the top. A model can have a good MAE and a useless ranking, so
  both are reported and neither is allowed to stand alone.

Every function tolerates nulls and degenerate inputs by returning ``None``
rather than raising or silently producing a misleading zero.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy import stats


def _clean(predicted: np.ndarray, actual: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Drop pairs where either side is missing or non-finite."""
    predicted = np.asarray(predicted, dtype=float).ravel()
    actual = np.asarray(actual, dtype=float).ravel()
    if predicted.shape != actual.shape:
        raise ValueError(
            f"Predicted and actual arrays differ in shape: {predicted.shape} vs {actual.shape}."
        )
    mask = np.isfinite(predicted) & np.isfinite(actual)
    return predicted[mask], actual[mask]


@dataclass(slots=True)
class RegressionMetrics:
    """Accuracy of a single projected statistic."""

    n: int
    mae: float | None = None
    rmse: float | None = None
    median_absolute_error: float | None = None
    r2: float | None = None
    bias: float | None = None
    mean_actual: float | None = None
    mean_predicted: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def regression_metrics(predicted: np.ndarray, actual: np.ndarray) -> RegressionMetrics:
    """Mean and median error, RMSE, R-squared and bias.

    ``bias`` is mean(predicted) - mean(actual): positive means the model
    systematically over-projects. It is reported separately from MAE because a
    model can be accurate on average and still be biased in a way that
    distorts rankings.

    R-squared is returned as ``None`` when the actual values have no variance,
    where the statistic is undefined rather than zero.
    """
    predicted, actual = _clean(predicted, actual)
    n = int(predicted.size)
    if n == 0:
        return RegressionMetrics(n=0)

    errors = predicted - actual
    absolute = np.abs(errors)
    total_variance = float(np.sum((actual - actual.mean()) ** 2))
    r2 = None
    if total_variance > 1e-12:
        r2 = float(1.0 - np.sum(errors**2) / total_variance)

    return RegressionMetrics(
        n=n,
        mae=float(absolute.mean()),
        rmse=float(np.sqrt(np.mean(errors**2))),
        median_absolute_error=float(np.median(absolute)),
        r2=r2,
        bias=float(errors.mean()),
        mean_actual=float(actual.mean()),
        mean_predicted=float(predicted.mean()),
    )


@dataclass(slots=True)
class RankMetrics:
    """How useful the ordering is, which is what a draft actually consumes."""

    n: int
    spearman: float | None = None
    kendall: float | None = None
    mean_rank_error: float | None = None
    median_rank_error: float | None = None
    top_overlap: dict[int, float] | None = None
    starter_precision: float | None = None
    starter_recall: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["top_overlap"] = dict(self.top_overlap or {})
        return payload


def rank_metrics(
    predicted: np.ndarray,
    actual: np.ndarray,
    *,
    top_k: tuple[int, ...] = (12, 24, 50, 100),
    starter_count: int | None = None,
) -> RankMetrics:
    """Rank correlation, positional-rank error and top-K overlap.

    ``top_overlap[k]`` is the fraction of the actual top ``k`` that the
    projection also placed in its top ``k``. It answers the question a drafter
    cares about: of the players who mattered, how many did the model find?

    ``starter_precision`` and ``starter_recall`` treat the top
    ``starter_count`` as the positive class.
    """
    predicted, actual = _clean(predicted, actual)
    n = int(predicted.size)
    if n < 3:
        return RankMetrics(n=n, top_overlap={})

    spearman = kendall = None
    if np.std(predicted) > 1e-12 and np.std(actual) > 1e-12:
        spearman = float(stats.spearmanr(predicted, actual).statistic)
        kendall = float(stats.kendalltau(predicted, actual).statistic)

    # Rank 1 is the best, so ranks descend with value.
    predicted_rank = stats.rankdata(-predicted, method="average")
    actual_rank = stats.rankdata(-actual, method="average")
    rank_error = np.abs(predicted_rank - actual_rank)

    overlap: dict[int, float] = {}
    for k in top_k:
        if k > n:
            continue
        actual_top = set(np.argsort(-actual, kind="stable")[:k].tolist())
        predicted_top = set(np.argsort(-predicted, kind="stable")[:k].tolist())
        overlap[k] = len(actual_top & predicted_top) / k

    precision = recall = None
    if starter_count and 0 < starter_count <= n:
        actual_top = set(np.argsort(-actual, kind="stable")[:starter_count].tolist())
        predicted_top = set(np.argsort(-predicted, kind="stable")[:starter_count].tolist())
        hits = len(actual_top & predicted_top)
        precision = hits / len(predicted_top)
        recall = hits / len(actual_top)

    return RankMetrics(
        n=n,
        spearman=spearman,
        kendall=kendall,
        mean_rank_error=float(rank_error.mean()),
        median_rank_error=float(np.median(rank_error)),
        top_overlap=overlap,
        starter_precision=precision,
        starter_recall=recall,
    )


@dataclass(slots=True)
class IntervalCalibration:
    """Whether a prediction interval means what it claims."""

    n: int
    nominal_coverage: float
    empirical_coverage: float
    mean_interval_width: float
    median_interval_width: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def interval_calibration(
    low: np.ndarray, high: np.ndarray, actual: np.ndarray, *, nominal: float
) -> IntervalCalibration | None:
    """Fraction of outcomes that fell inside the interval.

    A 20th-to-80th-percentile interval should contain roughly 60 percent of
    outcomes. Materially more means the intervals are too wide to be useful;
    materially less means they understate the risk.
    """
    low = np.asarray(low, dtype=float).ravel()
    high = np.asarray(high, dtype=float).ravel()
    actual = np.asarray(actual, dtype=float).ravel()
    mask = np.isfinite(low) & np.isfinite(high) & np.isfinite(actual)
    if mask.sum() == 0:
        return None
    low, high, actual = low[mask], high[mask], actual[mask]
    inside = (actual >= low) & (actual <= high)
    width = high - low
    return IntervalCalibration(
        n=int(mask.sum()),
        nominal_coverage=float(nominal),
        empirical_coverage=float(inside.mean()),
        mean_interval_width=float(width.mean()),
        median_interval_width=float(np.median(width)),
    )


def error_by_group(
    predicted: np.ndarray, actual: np.ndarray, groups: np.ndarray
) -> dict[str, RegressionMetrics]:
    """Regression metrics split by an arbitrary grouping.

    Used for the by-position, by-volume, by-age and by-experience breakdowns
    on the model-performance page, so a model that is good overall but poor
    for one cohort cannot hide behind the average.
    """
    predicted = np.asarray(predicted, dtype=float).ravel()
    actual = np.asarray(actual, dtype=float).ravel()
    groups = np.asarray(groups).ravel()
    results: dict[str, RegressionMetrics] = {}
    for label in sorted({str(value) for value in groups.tolist()}):
        mask = groups.astype(str) == label
        if mask.sum() == 0:
            continue
        results[label] = regression_metrics(predicted[mask], actual[mask])
    return results


def volume_bucket(values: np.ndarray, *, quantiles: int = 4) -> np.ndarray:
    """Label each row with a volume quartile, for error slicing.

    Falls back to a single bucket when the distribution is too degenerate to
    split, rather than producing empty groups.
    """
    values = np.asarray(values, dtype=float).ravel()
    finite = values[np.isfinite(values)]
    if finite.size < quantiles * 2:
        return np.array(["all"] * values.size, dtype=object)
    edges = np.quantile(finite, np.linspace(0, 1, quantiles + 1)[1:-1])
    edges = np.unique(edges)
    if edges.size == 0:
        return np.array(["all"] * values.size, dtype=object)
    indices = np.digitize(values, edges, right=True)
    labels = [f"Q{index + 1}" for index in range(edges.size + 1)]
    return np.array(
        [
            labels[min(int(index), len(labels) - 1)] if np.isfinite(value) else "unknown"
            for index, value in zip(indices, values, strict=True)
        ],
        dtype=object,
    )


def age_bucket(ages: np.ndarray) -> np.ndarray:
    """Group ages into the bands used for the error breakdown."""
    ages = np.asarray(ages, dtype=float).ravel()
    labels = []
    for age in ages:
        if not np.isfinite(age):
            labels.append("unknown")
        elif age < 24:
            labels.append("under 24")
        elif age < 27:
            labels.append("24-26")
        elif age < 30:
            labels.append("27-29")
        elif age < 33:
            labels.append("30-32")
        else:
            labels.append("33 and over")
    return np.array(labels, dtype=object)


def experience_bucket(experience: np.ndarray) -> np.ndarray:
    """Group NFL experience into bands used for the error breakdown."""
    experience = np.asarray(experience, dtype=float).ravel()
    labels = []
    for years in experience:
        if not np.isfinite(years):
            labels.append("unknown")
        elif years <= 0:
            labels.append("rookie")
        elif years == 1:
            labels.append("2nd season")
        elif years <= 3:
            labels.append("3rd-4th season")
        elif years <= 7:
            labels.append("5th-8th season")
        else:
            labels.append("9th season and beyond")
    return np.array(labels, dtype=object)
