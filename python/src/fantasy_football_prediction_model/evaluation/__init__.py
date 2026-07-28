"""Evaluation: metrics, rolling-origin backtesting, leakage checks, reports.

``backtesting`` is not imported here on purpose: it depends on ``models.training``,
which imports ``evaluation.metrics``. Eagerly re-exporting backtesting from this
package init creates a circular import when ``ffpm model train`` loads models.
"""

from fantasy_football_prediction_model.evaluation.leakage import (
    LeakageCheckResult,
    run_leakage_checks,
)
from fantasy_football_prediction_model.evaluation.metrics import (
    RankMetrics,
    RegressionMetrics,
    rank_metrics,
    regression_metrics,
)

__all__ = [
    "LeakageCheckResult",
    "RankMetrics",
    "RegressionMetrics",
    "rank_metrics",
    "regression_metrics",
    "run_leakage_checks",
]
