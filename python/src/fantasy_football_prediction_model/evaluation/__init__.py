"""Evaluation: metrics, rolling-origin backtesting, leakage checks, reports."""

from fantasy_football_prediction_model.evaluation.backtesting import BacktestResult, run_backtest
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
    "BacktestResult",
    "LeakageCheckResult",
    "RankMetrics",
    "RegressionMetrics",
    "rank_metrics",
    "regression_metrics",
    "run_backtest",
    "run_leakage_checks",
]
