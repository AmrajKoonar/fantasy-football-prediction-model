"""Rookie feature construction (full / reduced / fixture modes)."""

from __future__ import annotations

from typing import Literal

import polars as pl

from fantasy_football_prediction_model.config import Settings
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)

RookieMode = Literal["full", "reduced", "fixture"]


def detect_rookie_mode(settings: Settings) -> RookieMode:
    import os

    if os.environ.get("FFPM_FIXTURE", "").lower() in {"1", "true", "yes"}:
        return "fixture"
    if os.environ.get("CFBD_API_KEY"):
        return "full"
    return "reduced"


def build_rookie_features(
    draft_picks: pl.DataFrame,
    combine: pl.DataFrame | None,
    *,
    target_season: int,
    college_stats: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Build one feature row per drafted offensive rookie for ``target_season``."""
    if draft_picks.is_empty():
        return pl.DataFrame()

    frame = draft_picks.filter(pl.col("season") == target_season)
    if "position" in frame.columns:
        frame = frame.filter(pl.col("position").is_in(["QB", "RB", "WR", "TE"]))

    if combine is not None and not combine.is_empty():
        # Best-effort join on name when IDs are absent.
        join_keys = [
            c
            for c in ("pfr_id", "cfb_id", "player_name")
            if c in frame.columns and c in combine.columns
        ]
        if join_keys:
            frame = frame.join(combine, on=join_keys[0], how="left", suffix="_combine")

    if college_stats is not None and not college_stats.is_empty():
        keys = [
            c
            for c in ("cfbd_id", "player_name")
            if c in frame.columns and c in college_stats.columns
        ]
        if keys:
            frame = frame.join(college_stats, on=keys[0], how="left", suffix="_college")
            logger.info("Joined college stats for rookie features (full mode).")
    else:
        logger.info("Building reduced rookie features (draft/combine only).")

    # Derived draft capital transforms.
    if "pick" in frame.columns:
        frame = frame.with_columns(
            (1.0 / pl.col("pick").cast(pl.Float64).clip(1, None)).alias("draft_capital_inverse"),
            pl.col("pick").cast(pl.Float64).log1p().alias("draft_pick_log"),
        )
    if "forty" in frame.columns:
        frame = frame.with_columns(pl.col("forty").alias("combine_forty"))
    return frame
