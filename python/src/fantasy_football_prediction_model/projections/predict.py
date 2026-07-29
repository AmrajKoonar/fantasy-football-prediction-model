"""Apply registered models (+ hybrid fallbacks) to projection feature rows."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from fantasy_football_prediction_model.config import Settings
from fantasy_football_prediction_model.constants import FANTASY_POSITIONS, PROJECTION_TARGETS
from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.models.registry import LocalModelRegistry

logger = get_logger(__name__)

#: Stats that represent opportunity volume (predict these before efficiency).
OPPORTUNITY_STATS: frozenset[str] = frozenset(
    {
        "games",
        "pass_attempts",
        "carries",
        "targets",
    }
)


def age_multiplier(position: str, age: float | None) -> float:
    """Soft age curve applied on top of model/prior blends."""
    if age is None or not np.isfinite(age):
        return 1.0
    age = float(age)
    if position == "RB":
        if age <= 24:
            return 1.03
        if age <= 26:
            return 1.0
        if age <= 28:
            return 0.94
        if age <= 30:
            return 0.86
        return 0.75
    if position == "WR":
        if age <= 26:
            return 1.02
        if age <= 29:
            return 1.0
        if age <= 32:
            return 0.93
        return 0.85
    if position == "TE":
        if age <= 28:
            return 1.01
        if age <= 31:
            return 0.97
        return 0.90
    # QB
    if age <= 32:
        return 1.0
    if age <= 36:
        return 0.96
    return 0.90


def team_change_multiplier(position: str, changed: bool | int | None) -> float:
    if not changed:
        return 1.0
    return {"QB": 0.95, "RB": 0.88, "WR": 0.86, "TE": 0.90}.get(position, 0.9)


def depth_chart_multiplier(row: dict[str, Any]) -> float:
    starter = row.get("depth_chart_is_starter")
    rank = row.get("depth_chart_rank")
    if starter in (1, True):
        return 1.04
    if rank is not None:
        try:
            r = float(rank)
        except (TypeError, ValueError):
            return 1.0
        if r <= 1.5:
            return 1.03
        if r >= 3:
            return 0.88
    return 1.0


def shrink_to_mean(value: float, mean: float, weight: float = 0.32) -> float:
    """Pull extreme priors toward the positional mean (mean reversion)."""
    return (1.0 - weight) * value + weight * mean


def _position_prior_means(frame: pl.DataFrame) -> dict[str, dict[str, float]]:
    means: dict[str, dict[str, float]] = {}
    for position in FANTASY_POSITIONS:
        subset = frame.filter(pl.col("position") == position)
        if subset.is_empty():
            continue
        pos_means: dict[str, float] = {}
        for stat in PROJECTION_TARGETS.get(position, ()):
            if stat not in subset.columns:
                continue
            series = subset.get_column(stat).drop_nulls()
            if series.len() == 0:
                continue
            pos_means[stat] = float(series.mean())
        means[position] = pos_means
    return means


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def compose_efficiency(
    position: str,
    stats: dict[str, float],
    prior: dict[str, Any],
) -> dict[str, float]:
    """Fill efficiency totals from opportunity × prior rates when missing."""
    out = dict(stats)

    if position == "QB":
        attempts = out.get("pass_attempts")
        if attempts is not None:
            prior_att = _safe_float(prior.get("pass_attempts")) or 0.0
            if "completions" not in out or out["completions"] is None:
                rate = (
                    (_safe_float(prior.get("completions")) or 0.0) / prior_att
                    if prior_att > 0
                    else 0.64
                )
                out["completions"] = attempts * max(0.5, min(0.75, rate))
            if "passing_yards" not in out or out["passing_yards"] is None:
                ypa = (
                    (_safe_float(prior.get("passing_yards")) or 0.0) / prior_att
                    if prior_att > 0
                    else 7.1
                )
                out["passing_yards"] = attempts * max(5.5, min(9.0, ypa))
            if "passing_tds" not in out or out["passing_tds"] is None:
                tdr = (
                    (_safe_float(prior.get("passing_tds")) or 0.0) / prior_att
                    if prior_att > 0
                    else 0.045
                )
                out["passing_tds"] = attempts * max(0.02, min(0.07, tdr))
            if "interceptions" not in out or out["interceptions"] is None:
                ir = (
                    (_safe_float(prior.get("interceptions")) or 0.0) / prior_att
                    if prior_att > 0
                    else 0.022
                )
                out["interceptions"] = attempts * max(0.01, min(0.04, ir))

    targets = out.get("targets")
    if targets is not None and position in {"RB", "WR", "TE"}:
        prior_tgt = _safe_float(prior.get("targets")) or 0.0
        if "receptions" not in out or out["receptions"] is None:
            rate = (
                (_safe_float(prior.get("receptions")) or 0.0) / prior_tgt if prior_tgt > 0 else 0.65
            )
            out["receptions"] = targets * max(0.45, min(0.8, rate))
        if "receiving_yards" not in out or out["receiving_yards"] is None:
            ypt = (
                (_safe_float(prior.get("receiving_yards")) or 0.0) / prior_tgt
                if prior_tgt > 0
                else (8.0 if position == "RB" else 12.0)
            )
            out["receiving_yards"] = targets * max(5.0, min(16.0, ypt))
        if "receiving_tds" not in out or out["receiving_tds"] is None:
            tdr = (
                (_safe_float(prior.get("receiving_tds")) or 0.0) / prior_tgt
                if prior_tgt > 0
                else 0.05
            )
            out["receiving_tds"] = targets * max(0.01, min(0.12, tdr))

    carries = out.get("carries")
    if carries is not None and position in {"RB", "QB", "WR"}:
        prior_car = _safe_float(prior.get("carries")) or 0.0
        if "rushing_yards" not in out or out["rushing_yards"] is None:
            ypc = (
                (_safe_float(prior.get("rushing_yards")) or 0.0) / prior_car
                if prior_car > 0
                else 4.2
            )
            out["rushing_yards"] = carries * max(2.5, min(6.5, ypc))
        if "rushing_tds" not in out or out["rushing_tds"] is None:
            tdr = (
                (_safe_float(prior.get("rushing_tds")) or 0.0) / prior_car
                if prior_car > 0
                else 0.03
            )
            out["rushing_tds"] = carries * max(0.005, min(0.08, tdr))

    if "fumbles_lost" not in out or out["fumbles_lost"] is None:
        prior_fum = _safe_float(prior.get("fumbles_lost"))
        if prior_fum is None:
            prior_fum = (
                (_safe_float(prior.get("rushing_fumbles_lost")) or 0.0)
                + (_safe_float(prior.get("receiving_fumbles_lost")) or 0.0)
                + (_safe_float(prior.get("sack_fumbles_lost")) or 0.0)
            )
        out["fumbles_lost"] = max(0.0, prior_fum * 0.9)

    return out


def apply_context_multipliers(
    position: str,
    stats: dict[str, float],
    row: dict[str, Any],
    *,
    max_multiplier: float = 1.15,
) -> dict[str, float]:
    """Age / team-change / depth-chart adjustments with historical caps."""
    age = _safe_float(row.get("age_at_target_season"))
    changed = row.get("team_changed")
    if changed is None:
        changed = row.get("team_change")
    factor = (
        age_multiplier(position, age)
        * team_change_multiplier(position, bool(changed) if changed is not None else False)
        * depth_chart_multiplier(row)
    )
    # Keep games mostly stable; scale volume/production stats.
    out: dict[str, float] = {}
    for key, value in stats.items():
        if key == "games":
            out[key] = float(value)
            continue
        prior = _safe_float(row.get(key))
        scaled = float(value) * factor
        if prior is not None and prior > 0:
            scaled = min(scaled, prior * max_multiplier)
            # Also don't invent huge breakouts from tiny priors without starter signal.
            if prior < 20 and key in OPPORTUNITY_STATS and depth_chart_multiplier(row) < 1.02:
                scaled = min(scaled, max(prior * 1.35, scaled * 0.85))
        out[key] = scaled
    return out


def apply_registered_models(
    frame: pl.DataFrame,
    settings: Settings,
    registry: LocalModelRegistry | None = None,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Attach ``pred_{stat}`` columns using the model registry + hybrid fallback.

    Returns the enriched frame and a small report of which targets used ML vs fallback.
    """
    registry = registry or LocalModelRegistry(settings.path("model_dir"))
    max_mult = float(getattr(settings.model.constraints, "historical_max_multiplier", 1.15))
    prior_means = _position_prior_means(frame)
    report: dict[str, Any] = {"model_hits": 0, "fallback_hits": 0, "by_target": {}}

    working = frame
    all_stats = sorted({stat for pos in FANTASY_POSITIONS for stat in PROJECTION_TARGETS[pos]})
    pred_columns = {f"pred_{stat}": [None] * frame.height for stat in all_stats}

    rows = working.to_dicts()
    index_by_position: dict[str, list[int]] = {pos: [] for pos in FANTASY_POSITIONS}
    for i, row in enumerate(rows):
        pos = str(row.get("position") or "")
        if pos in index_by_position:
            index_by_position[pos].append(i)

    for position in FANTASY_POSITIONS:
        idxs = index_by_position[position]
        if not idxs:
            continue
        pos_frame = working.filter(pl.col("position") == position)
        model_preds: dict[str, np.ndarray] = {}
        for stat in PROJECTION_TARGETS[position]:
            record = registry.get_latest(position, f"outcome_{stat}")
            key = f"{position}:{stat}"
            if record is None:
                report["by_target"][key] = "fallback"
                report["fallback_hits"] += 1
                continue
            try:
                model = registry.load(record)
                preds = np.asarray(model.predict(pos_frame), dtype=float)
                if preds.shape[0] != pos_frame.height:
                    logger.warning(
                        "Prediction length mismatch for %s: %s vs %s",
                        key,
                        preds.shape[0],
                        pos_frame.height,
                    )
                    report["by_target"][key] = "fallback:shape"
                    report["fallback_hits"] += 1
                    continue
                model_preds[stat] = preds
                report["by_target"][key] = record.algorithm
                report["model_hits"] += 1
            except Exception as exc:
                logger.warning("Model predict failed for %s: %s", key, exc)
                report["by_target"][key] = f"fallback:{type(exc).__name__}"
                report["fallback_hits"] += 1

        for local_i, global_i in enumerate(idxs):
            row = rows[global_i]
            raw: dict[str, float] = {}
            for stat in PROJECTION_TARGETS[position]:
                if stat in model_preds:
                    raw[stat] = float(model_preds[stat][local_i])
                else:
                    prior = _safe_float(row.get(stat))
                    mean = prior_means.get(position, {}).get(stat)
                    if prior is None and mean is None:
                        continue
                    if prior is None:
                        value = float(mean or 0.0)
                    elif mean is None:
                        value = prior
                    else:
                        # Stronger reversion for outlier seasons.
                        weight = 0.38 if prior > 1.35 * mean else 0.28
                        value = shrink_to_mean(prior, mean, weight=weight)
                    raw[stat] = value
            composed = compose_efficiency(position, raw, row)
            adjusted = apply_context_multipliers(position, composed, row, max_multiplier=max_mult)
            for stat, value in adjusted.items():
                pred_columns[f"pred_{stat}"][global_i] = float(value)

    for name, values in pred_columns.items():
        working = working.with_columns(pl.Series(name, values))

    logger.info(
        "Projection model apply: %d model targets, %d fallbacks.",
        report["model_hits"],
        report["fallback_hits"],
    )
    return working, report


def stats_from_row(row: dict[str, Any], position: str) -> dict[str, float | None]:
    """Read projected stats preferring ``pred_*`` columns."""
    stats: dict[str, float | None] = {}
    for stat in PROJECTION_TARGETS.get(position, ()):
        pred = _safe_float(row.get(f"pred_{stat}"))
        if pred is not None:
            stats[stat] = pred
            continue
        prior = _safe_float(row.get(stat))
        if prior is not None:
            stats[stat] = prior
        elif stat == "fumbles_lost":
            stats[stat] = (
                (_safe_float(row.get("rushing_fumbles_lost")) or 0.0)
                + (_safe_float(row.get("receiving_fumbles_lost")) or 0.0)
                + (_safe_float(row.get("sack_fumbles_lost")) or 0.0)
            )
        else:
            stats[stat] = 0.0
    if not stats.get("games"):
        stats["games"] = 15.0
    return stats
