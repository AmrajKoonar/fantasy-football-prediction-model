"""Feature research: coverage, stability, next-season relationships."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from scipy import stats

from fantasy_football_prediction_model.config import Settings
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)


def _corr(x: np.ndarray, y: np.ndarray) -> tuple[float | None, float | None]:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 30:
        return None, None
    if np.std(x[mask]) < 1e-12 or np.std(y[mask]) < 1e-12:
        return None, None
    pearson = float(stats.pearsonr(x[mask], y[mask]).statistic)
    spearman = float(stats.spearmanr(x[mask], y[mask]).statistic)
    return pearson, spearman


def run_feature_research(settings: Settings) -> dict[str, Path]:
    """Write research CSVs under ``artifacts/feature-research``."""
    out = settings.path("feature_research_dir")
    out.mkdir(parents=True, exist_ok=True)
    pairs_path = settings.path("processed_dir") / "modelling_pairs.parquet"
    written: dict[str, Path] = {}

    if not pairs_path.is_file():
        logger.warning("No modelling pairs for research; writing empty placeholders.")
        empty = pl.DataFrame({"feature": [], "coverage": []})
        for name in (
            "feature-coverage.csv",
            "year-over-year-stability.csv",
            "incremental-value.csv",
            "feature-importance.csv",
        ):
            path = out / name
            empty.write_csv(path)
            written[name] = path
        summary = {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "skipped",
            "reason": "modelling_pairs.parquet missing",
        }
        summary_path = out / "research-summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        written["research-summary.json"] = summary_path
        return written

    pairs = pl.read_parquet(pairs_path)
    numeric = [
        name
        for name, dtype in pairs.schema.items()
        if dtype.is_numeric()
        and not name.startswith("outcome_")
        and name not in {"target_season", "season", "target_played"}
    ]

    coverage_rows: list[dict[str, Any]] = []
    stability_rows: list[dict[str, Any]] = []
    predict_rows: list[dict[str, Any]] = []

    target_col = (
        "outcome_fantasy_points_ppr"
        if "outcome_fantasy_points_ppr" in pairs.columns
        else None
    )
    y = (
        pairs.get_column(target_col).cast(pl.Float64, strict=False).fill_null(0.0).to_numpy()
        if target_col
        else None
    )

    for feature in numeric:
        series = pairs.get_column(feature).cast(pl.Float64, strict=False)
        coverage = float(series.is_not_null().mean() or 0.0)
        values = series.to_numpy()
        coverage_rows.append(
            {
                "feature": feature,
                "coverage": coverage,
                "missing_rate": 1.0 - coverage,
                "mean": float(np.nanmean(values)) if np.isfinite(values).any() else None,
                "std": float(np.nanstd(values)) if np.isfinite(values).any() else None,
                "decision": (
                    "included"
                    if coverage >= settings.features.selection.min_coverage
                    else "excluded"
                ),
                "decision_reason": (
                    "Meets minimum coverage"
                    if coverage >= settings.features.selection.min_coverage
                    else "Below minimum coverage"
                ),
            }
        )

        # Year-over-year stability: correlate feature at t with same feature lag if present.
        lag = f"{feature}_lag1"
        if lag in pairs.columns:
            pearson, spearman = _corr(
                pairs.get_column(feature).cast(pl.Float64, strict=False).to_numpy(),
                pairs.get_column(lag).cast(pl.Float64, strict=False).to_numpy(),
            )
            stability_rows.append(
                {
                    "feature": feature,
                    "year_over_year_pearson": pearson,
                    "year_over_year_spearman": spearman,
                }
            )

        if y is not None:
            pearson, spearman = _corr(values.astype(float), y)
            predict_rows.append(
                {
                    "feature": feature,
                    "next_season_pearson": pearson,
                    "next_season_spearman": spearman,
                    "univariate_r2": (pearson**2) if pearson is not None else None,
                }
            )

    cov_path = out / "feature-coverage.csv"
    pl.DataFrame(coverage_rows).write_csv(cov_path)
    written["feature-coverage.csv"] = cov_path

    stab_path = out / "year-over-year-stability.csv"
    pl.DataFrame(stability_rows).write_csv(stab_path) if stability_rows else stab_path.write_text(
        "feature,year_over_year_pearson\n", encoding="utf-8"
    )
    written["year-over-year-stability.csv"] = stab_path

    pred_path = out / "incremental-value.csv"
    pl.DataFrame(predict_rows).write_csv(pred_path) if predict_rows else pred_path.write_text(
        "feature,next_season_pearson\n", encoding="utf-8"
    )
    written["incremental-value.csv"] = pred_path

    # Importance proxy: |next-season pearson|
    importance_rows = [
        {
            "feature": row["feature"],
            "importance": abs(row["next_season_pearson"] or 0.0),
            "method": "univariate_pearson",
        }
        for row in predict_rows
    ]
    importance_rows.sort(key=lambda r: -r["importance"])
    for rank, row in enumerate(importance_rows, start=1):
        row["rank"] = rank
    imp_path = out / "feature-importance.csv"
    pl.DataFrame(importance_rows).write_csv(imp_path) if importance_rows else imp_path.write_text(
        "feature,importance,rank\n", encoding="utf-8"
    )
    written["feature-importance.csv"] = imp_path

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "ok",
        "n_features_evaluated": len(numeric),
        "n_included": sum(1 for row in coverage_rows if row["decision"] == "included"),
        "top_features": [row["feature"] for row in importance_rows[:15]],
        "notes": [
            "Univariate correlations do not imply causality.",
            "Final model features also require incremental out-of-sample value.",
        ],
    }
    summary_path = out / "research-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    written["research-summary.json"] = summary_path
    logger.info("Feature research wrote %d artifacts to %s", len(written), out)
    return written
