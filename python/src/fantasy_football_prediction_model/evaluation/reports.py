"""Write evaluation artifacts for disk and the web export."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from fantasy_football_prediction_model.constants import DATA_MODE_FIXTURE, DATA_MODE_PRODUCTION
from fantasy_football_prediction_model.evaluation.backtesting import BacktestResult
from fantasy_football_prediction_model.evaluation.metrics import interval_calibration
from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.schemas import (
    CalibrationRecord,
    MetricRecord,
    ModelPerformanceFile,
    RankMetricRecord,
)

logger = get_logger(__name__)


def write_backtest_artifacts(result: BacktestResult, directory: Path) -> dict[str, Path]:
    """Persist CSV / JSON / parquet evaluation outputs."""
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    summary = result.summary_frame()
    summary_path = directory / "backtest-summary.csv"
    if summary.height:
        summary.write_csv(summary_path)
    else:
        summary_path.write_text("season,position,target,model,mae\n", encoding="utf-8")
    written["backtest_summary"] = summary_path

    comparison_rows: list[dict[str, Any]] = []
    if summary.height:
        grouped = summary.group_by(["position", "target", "model", "is_baseline"]).agg(
            pl.col("mae").mean().alias("mae"),
            pl.col("rmse").mean().alias("rmse"),
            pl.col("spearman").mean().alias("spearman"),
            pl.len().alias("folds"),
        )
        comparison_rows = grouped.to_dicts()
    comparison_path = directory / "model-comparison.csv"
    pl.DataFrame(comparison_rows).write_csv(comparison_path) if comparison_rows else comparison_path.write_text(
        "position,target,model,mae\n", encoding="utf-8"
    )
    written["model_comparison"] = comparison_path

    pred_rows: list[dict[str, Any]] = []
    for fold in result.predictions:
        for player_id, pred, actual in zip(
            fold.player_ids, fold.predicted.tolist(), fold.actual.tolist(), strict=False
        ):
            pred_rows.append(
                {
                    "season": fold.season,
                    "position": fold.position,
                    "target": fold.target,
                    "model": fold.model,
                    "is_baseline": fold.is_baseline,
                    "player_id": player_id,
                    "predicted": pred,
                    "actual": actual,
                    "error": pred - actual,
                }
            )
    preds_path = directory / "backtest-predictions.parquet"
    if pred_rows:
        pl.DataFrame(pred_rows).write_parquet(preds_path)
    else:
        pl.DataFrame(
            schema={
                "season": pl.Int64,
                "position": pl.Utf8,
                "target": pl.Utf8,
                "model": pl.Utf8,
                "predicted": pl.Float64,
                "actual": pl.Float64,
            }
        ).write_parquet(preds_path)
    written["predictions"] = preds_path

    selection_path = directory / "selected-models.json"
    selection_path.write_text(json.dumps(result.selected_models, indent=2), encoding="utf-8")
    written["selected_models"] = selection_path

    error_path = directory / "error-analysis.json"
    error_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "n_folds": len(result.predictions),
                "selected_models": result.selected_models,
                "notes": [
                    "Metrics are out-of-sample rolling-origin results.",
                    "Baselines are included so complex models can lose honestly.",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    written["error_analysis"] = error_path

    # Placeholder calibration / rank files when no residual intervals were stored.
    (directory / "rank-performance.csv").write_text(
        "season,position,model,spearman,n\n", encoding="utf-8"
    )
    (directory / "interval-calibration.csv").write_text(
        "position,nominal_coverage,empirical_coverage,n\n", encoding="utf-8"
    )
    written["rank_performance"] = directory / "rank-performance.csv"
    written["interval_calibration"] = directory / "interval-calibration.csv"

    logger.info("Wrote backtest artifacts to %s", directory)
    return written


def build_model_performance_file(
    result: BacktestResult,
    *,
    schema_version: str,
    model_version: str,
    data_mode: str = DATA_MODE_PRODUCTION,
    backtest_seasons: list[int] | None = None,
) -> ModelPerformanceFile:
    """Convert a backtest result into the web export schema."""
    if data_mode not in {DATA_MODE_PRODUCTION, DATA_MODE_FIXTURE}:
        raise ValueError(f"Invalid data_mode {data_mode!r}")

    summary = result.summary_frame()
    stat_metrics: list[MetricRecord] = []
    fantasy_metrics: list[MetricRecord] = []
    rank_records: list[RankMetricRecord] = []

    if summary.height:
        for row in summary.group_by(["position", "target", "model", "is_baseline"]).agg(
            pl.col("mae").mean().alias("mae"),
            pl.col("rmse").mean().alias("rmse"),
            pl.col("r2").mean().alias("r2"),
            pl.col("bias").mean().alias("bias"),
            pl.col("n").sum().alias("n"),
            pl.col("spearman").mean().alias("spearman"),
        ).to_dicts():
            key = f"{row['position']}:{row['target']}"
            record = MetricRecord(
                position=row["position"],
                target=row["target"],
                model=row["model"],
                architecture="direct",
                mae=row.get("mae"),
                rmse=row.get("rmse"),
                r2=row.get("r2"),
                bias=row.get("bias"),
                n=int(row.get("n") or 0),
                is_baseline=bool(row.get("is_baseline")),
                is_selected=result.selected_models.get(key) == row["model"],
            )
            if row["target"] == "fantasy_points_ppr":
                fantasy_metrics.append(record)
            else:
                stat_metrics.append(record)

        for fold in result.predictions:
            if fold.target != "fantasy_points_ppr":
                continue
            ranks = __import__(
                "fantasy_football_prediction_model.evaluation.metrics",
                fromlist=["rank_metrics"],
            ).rank_metrics(fold.predicted, fold.actual)
            overlap = ranks.top_overlap or {}
            rank_records.append(
                RankMetricRecord(
                    season=fold.season,
                    position=fold.position,
                    model=fold.model,
                    spearman=ranks.spearman,
                    kendall=ranks.kendall,
                    mean_rank_error=ranks.mean_rank_error,
                    top_12_overlap=overlap.get(12),
                    top_24_overlap=overlap.get(24),
                    top_50_overlap=overlap.get(50),
                    top_100_overlap=overlap.get(100),
                    starter_precision=ranks.starter_precision,
                    starter_recall=ranks.starter_recall,
                    n=ranks.n,
                )
            )

    seasons = backtest_seasons or sorted({fold.season for fold in result.predictions})
    return ModelPerformanceFile(
        schema_version=schema_version,
        data_mode=data_mode,  # type: ignore[arg-type]
        generated_at=datetime.now(UTC),
        model_version=model_version,
        backtest_seasons=seasons,
        stat_metrics=stat_metrics,
        fantasy_metrics=fantasy_metrics,
        rank_metrics=rank_records,
        calibration=[],
        error_slices=[],
        selected_models=result.selected_models,
        known_weaknesses=[
            "Rookie projections without CollegeFootballData run in reduced mode.",
            "Injury reports after 2024 are not automatically ingested.",
            "Small samples for niche role players widen prediction intervals.",
        ],
    )


def write_calibration_from_arrays(
    directory: Path,
    *,
    position: str,
    low: Any,
    high: Any,
    actual: Any,
    nominal: float,
) -> CalibrationRecord | None:
    calib = interval_calibration(low, high, actual, nominal=nominal)
    if calib is None:
        return None
    path = directory / "interval-calibration.csv"
    row = (
        f"{position},{calib.nominal_coverage},{calib.empirical_coverage},"
        f"{calib.mean_interval_width},{calib.n}\n"
    )
    if path.is_file():
        path.write_text(path.read_text(encoding="utf-8") + row, encoding="utf-8")
    return CalibrationRecord(
        position=position,
        nominal_coverage=calib.nominal_coverage,
        empirical_coverage=calib.empirical_coverage,
        mean_interval_width=calib.mean_interval_width,
        n=calib.n,
    )
