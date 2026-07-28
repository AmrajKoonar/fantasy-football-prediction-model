import numpy as np
import polars as pl
import pytest

from fantasy_football_prediction_model.evaluation.leakage import run_leakage_checks
from fantasy_football_prediction_model.evaluation.metrics import regression_metrics
from fantasy_football_prediction_model.logging import LeakageError


def test_regression_metrics_basic():
    metrics = regression_metrics(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.5, 2.5]))
    assert metrics.n == 3
    assert metrics.mae is not None


def test_leakage_detects_bad_season_ordering():
    frame = pl.DataFrame(
        {
            "gsis_id": ["a", "b"],
            "season": [2025, 2026],
            "target_season": [2025, 2026],
            "outcome_receiving_yards": [100.0, 110.0],
            "targets": [80.0, 90.0],
        }
    )
    with pytest.raises(LeakageError):
        run_leakage_checks(
            frame,
            feature_columns=["targets"],
            target_columns=["outcome_receiving_yards"],
            raise_on_failure=True,
        )
