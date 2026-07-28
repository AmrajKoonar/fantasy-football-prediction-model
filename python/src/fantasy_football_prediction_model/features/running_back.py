"""Running-back features.

Running-back production is dominated by workload rather than efficiency:
carry share, target share and goal-line usage carry far more year-to-year
signal than yards per carry, which is famously noisy. The feature set is
weighted accordingly, and the feature-research pipeline tests that assumption
rather than assuming it.

Receiving usage is modelled explicitly because it is the most durable source
of PPR value for the position and the least sensitive to touchdown variance.
"""

from __future__ import annotations

import polars as pl

from fantasy_football_prediction_model.data.aggregation import safe_ratio

MIN_CARRIES = 20
MIN_TARGETS = 15

#: A weighted opportunity counts a target as worth more than a carry, because
#: a target is worth roughly 2x a carry in expected PPR points. The weight is
#: a documented modelling choice, exposed here rather than buried in a formula.
TARGET_WEIGHT = 2.0
CARRY_WEIGHT = 1.0


def add_running_back_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Add workload, rushing-efficiency and receiving features."""
    games = pl.col("games").cast(pl.Float64)
    carries = pl.col("carries").cast(pl.Float64)
    targets = pl.col("targets").cast(pl.Float64)
    receptions = pl.col("receptions").cast(pl.Float64)

    frame = frame.with_columns(
        safe_ratio(carries, games).alias("carries_per_game"),
        safe_ratio(targets, games).alias("rb_targets_per_game"),
        safe_ratio(receptions, games).alias("receptions_per_game"),
        (
            CARRY_WEIGHT * carries.fill_null(0) + TARGET_WEIGHT * targets.fill_null(0)
        ).alias("weighted_opportunity"),
        # Rushing efficiency, gated on volume.
        safe_ratio(
            pl.col("rushing_yards").cast(pl.Float64), carries, min_denominator=MIN_CARRIES
        ).alias("yards_per_carry"),
        safe_ratio(
            pl.col("rushing_tds").cast(pl.Float64), carries, min_denominator=MIN_CARRIES
        ).alias("rushing_td_rate"),
        safe_ratio(
            pl.col("rushing_first_downs").cast(pl.Float64), carries, min_denominator=MIN_CARRIES
        ).alias("rushing_first_down_rate"),
        # Receiving efficiency.
        safe_ratio(receptions, targets, min_denominator=MIN_TARGETS).alias("catch_rate"),
        safe_ratio(
            pl.col("receiving_yards").cast(pl.Float64), targets, min_denominator=MIN_TARGETS
        ).alias("yards_per_target"),
        safe_ratio(
            pl.col("receiving_yards").cast(pl.Float64), receptions, min_denominator=10
        ).alias("yards_per_reception"),
        safe_ratio(
            pl.col("receiving_yards_after_catch").cast(pl.Float64), receptions, min_denominator=10
        ).alias("yac_per_reception"),
        safe_ratio(
            pl.col("receiving_tds").cast(pl.Float64), targets, min_denominator=MIN_TARGETS
        ).alias("receiving_td_rate"),
    )

    frame = frame.with_columns(
        safe_ratio(
            pl.col("weighted_opportunity"), games
        ).alias("weighted_opportunity_per_game")
    )

    # Share of team opportunity. The denominators come from the player's own
    # season-t team, because that is the offence they actually played in.
    if "own_team_rush_attempts" in frame.columns:
        frame = frame.with_columns(
            safe_ratio(carries, pl.col("own_team_rush_attempts").cast(pl.Float64)).alias(
                "rush_share"
            )
        )
    else:
        frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("rush_share"))

    # Goal-line and red-zone carry share within the player's own backfield.
    if "rz_carries" in frame.columns:
        frame = frame.with_columns(
            pl.col("rz_carries").cast(pl.Float64).alias("rz_carries"),
            pl.col("inside_five_carries").cast(pl.Float64).alias("inside_five_carries")
            if "inside_five_carries" in frame.columns
            else pl.lit(None, dtype=pl.Float64).alias("inside_five_carries"),
        )
        team_rz_rush = (
            pl.col("team_rz_rush_plays").cast(pl.Float64)
            if "team_rz_rush_plays" in frame.columns
            else pl.lit(None, dtype=pl.Float64)
        )
        frame = frame.with_columns(
            safe_ratio(pl.col("rz_carries"), team_rz_rush).alias("rz_carry_share"),
            safe_ratio(pl.col("inside_five_carries"), team_rz_rush).alias(
                "inside_five_carry_share"
            ),
            safe_ratio(pl.col("inside_five_carries"), pl.col("rz_carries")).alias(
                "goal_line_carry_share"
            ),
        )
    else:
        for column in (
            "rz_carries",
            "inside_five_carries",
            "rz_carry_share",
            "inside_five_carry_share",
            "goal_line_carry_share",
        ):
            if column not in frame.columns:
                frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(column))

    return frame


def add_backfield_competition(frame: pl.DataFrame) -> pl.DataFrame:
    """Share of team carries held by *other* returning running backs.

    Called during the modelling-pair build, once the projected team for the
    outcome season is known.
    """
    required = {"projected_team", "season", "carries", "next_team_known", "next_team"}
    if not required <= set(frame.columns):
        return frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("backfield_competition"))

    backs = frame.filter((pl.col("position") == "RB") & (pl.col("next_team_known") == 1))
    if backs.is_empty():
        return frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("backfield_competition"))

    # Group by the team each back is joining, so competition reflects the
    # projected room rather than last season's room.
    room = backs.group_by(["next_team", "season"]).agg(
        pl.col("carries").fill_null(0).sum().alias("_room_carries")
    )
    joined = frame.join(
        room.select(
            pl.col("next_team").alias("projected_team"), "season", "_room_carries"
        ),
        on=["projected_team", "season"],
        how="left",
    )
    return joined.with_columns(
        safe_ratio(
            pl.col("_room_carries") - pl.col("carries").fill_null(0),
            pl.col("_room_carries"),
        ).alias("backfield_competition")
    ).drop("_room_carries")
