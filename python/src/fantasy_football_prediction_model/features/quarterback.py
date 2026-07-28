"""Quarterback features.

Quarterback fantasy value has two largely independent components: passing
volume x passing efficiency, and rushing value. The second is what separates
the top tier from the rest, so designed rushing and goal-line carries are
modelled explicitly rather than being folded into a generic rushing rate.

Every rate here is null-safe and volume-aware: a quarterback with four pass
attempts gets a null completion percentage plus a missing indicator, not a
completion percentage of 0.25 that the model would read as terrible accuracy.
"""

from __future__ import annotations

import polars as pl

from fantasy_football_prediction_model.data.aggregation import safe_ratio

#: Minimum attempts before a passing rate is considered meaningful.
MIN_PASS_ATTEMPTS = 50
MIN_RUSH_ATTEMPTS = 20
MIN_GAMES = 4


def add_quarterback_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Add passing volume, passing efficiency and rushing-value features."""
    attempts = pl.col("pass_attempts").cast(pl.Float64)
    games = pl.col("games").cast(pl.Float64)
    carries = pl.col("carries").cast(pl.Float64)

    dropbacks = (
        pl.col("dropbacks").cast(pl.Float64)
        if "dropbacks" in frame.columns
        else attempts.fill_null(0) + pl.col("sacks_suffered").cast(pl.Float64).fill_null(0)
    )

    features = [
        dropbacks.alias("dropbacks"),
        safe_ratio(dropbacks, games, min_denominator=0).alias("dropbacks_per_game"),
        safe_ratio(attempts, games, min_denominator=0).alias("pass_attempts_per_game"),
        # Volume-gated efficiency rates.
        safe_ratio(
            pl.col("completions").cast(pl.Float64), attempts, min_denominator=MIN_PASS_ATTEMPTS
        ).alias("completion_pct"),
        safe_ratio(
            pl.col("passing_yards").cast(pl.Float64), attempts, min_denominator=MIN_PASS_ATTEMPTS
        ).alias("yards_per_attempt"),
        safe_ratio(
            pl.col("passing_tds").cast(pl.Float64), attempts, min_denominator=MIN_PASS_ATTEMPTS
        ).alias("passing_td_rate"),
        safe_ratio(
            pl.col("interceptions").cast(pl.Float64), attempts, min_denominator=MIN_PASS_ATTEMPTS
        ).alias("interception_rate"),
        safe_ratio(
            pl.col("passing_air_yards").cast(pl.Float64),
            attempts,
            min_denominator=MIN_PASS_ATTEMPTS,
        ).alias("air_yards_per_attempt"),
        safe_ratio(
            pl.col("passing_first_downs").cast(pl.Float64),
            attempts,
            min_denominator=MIN_PASS_ATTEMPTS,
        ).alias("passing_first_down_rate"),
        safe_ratio(
            pl.col("sacks_suffered").cast(pl.Float64), dropbacks, min_denominator=MIN_PASS_ATTEMPTS
        ).alias("sack_rate"),
        # Rushing value.
        safe_ratio(carries, games, min_denominator=0).alias("qb_carries_per_game"),
        safe_ratio(
            pl.col("rushing_yards").cast(pl.Float64), carries, min_denominator=MIN_RUSH_ATTEMPTS
        ).alias("qb_yards_per_carry"),
        safe_ratio(
            pl.col("rushing_tds").cast(pl.Float64), carries, min_denominator=MIN_RUSH_ATTEMPTS
        ).alias("qb_rushing_td_rate"),
        safe_ratio(pl.col("rushing_yards").cast(pl.Float64), games, min_denominator=0).alias(
            "qb_rushing_yards_per_game"
        ),
    ]

    frame = frame.with_columns(features)

    # Adjusted yards per attempt is the standard efficiency summary that
    # prices touchdowns and interceptions into a yardage scale.
    frame = frame.with_columns(
        safe_ratio(
            pl.col("passing_yards").cast(pl.Float64)
            + 20 * pl.col("passing_tds").cast(pl.Float64).fill_null(0)
            - 45 * pl.col("interceptions").cast(pl.Float64).fill_null(0),
            attempts,
            min_denominator=MIN_PASS_ATTEMPTS,
        ).alias("adjusted_yards_per_attempt"),
        # Air-conversion rate: how much of the intended air yardage the
        # offence actually realises.
        safe_ratio(
            pl.col("passing_yards").cast(pl.Float64),
            pl.col("passing_air_yards").cast(pl.Float64),
            min_denominator=100,
        ).alias("passing_air_conversion_rate"),
    )

    # Share of the offence's dropbacks the quarterback took: the cleanest
    # available proxy for "is this the starter".
    if "own_team_dropbacks" in frame.columns:
        frame = frame.with_columns(
            safe_ratio(dropbacks, pl.col("own_team_dropbacks").cast(pl.Float64)).alias(
                "qb_dropback_share"
            )
        )
    else:
        frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("qb_dropback_share"))

    # Red-zone and goal-line rushing, available only when play-by-play was
    # ingested. Marked missing rather than zero when it was not.
    for source, target in (
        ("rz_carries", "rz_rush_attempts_qb"),
        ("rz_pass_attempts", "rz_pass_attempts"),
    ):
        if source in frame.columns:
            frame = frame.with_columns(pl.col(source).cast(pl.Float64).alias(target))
        elif target not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(target))

    return frame
