"""Tight-end features.

Tight ends share most of the receiver feature set, but they get their own
model. Two reasons, both testable rather than assumed:

1. Their opportunity distribution is different. A top-five tight end's target
   share resembles a team's third receiver, so a model trained mostly on
   receivers systematically under-projects them.
2. Their age curve is different. Tight ends typically break out later, so the
   age term needs to be fitted on tight ends alone.

Whether the separate model actually helps is measured in the backtest and
published on the model-performance page. If a shared model with an explicit
position feature ever wins, the comparison will say so.

The extra features here capture usage that distinguishes a receiving tight end
from a blocking one, which is the single largest source of variance in the
position's fantasy value.
"""

from __future__ import annotations

import polars as pl

from fantasy_football_prediction_model.data.aggregation import safe_ratio
from fantasy_football_prediction_model.features.receiver import add_receiver_features

MIN_SNAPS = 50


def add_tight_end_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Add receiver features plus tight-end-specific usage."""
    frame = add_receiver_features(frame)

    # How much of the team's tight-end target volume this player commands.
    # A team's tight-end targets are far more concentrated than its receiver
    # targets, so this separates a genuine every-down receiving tight end from
    # a rotational one better than raw target share does.
    if {"projected_team", "season", "targets"} <= set(frame.columns):
        tight_ends = frame.filter(pl.col("position") == "TE")
        if not tight_ends.is_empty():
            room = tight_ends.group_by(["team", "season"]).agg(
                pl.col("targets").fill_null(0).sum().alias("_team_te_targets")
            )
            frame = frame.join(room, on=["team", "season"], how="left").with_columns(
                safe_ratio(
                    pl.col("targets").cast(pl.Float64), pl.col("_team_te_targets")
                ).alias("team_tight_end_target_share")
            ).drop("_team_te_targets")
        else:
            frame = frame.with_columns(
                pl.lit(None, dtype=pl.Float64).alias("team_tight_end_target_share")
            )
    else:
        frame = frame.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("team_tight_end_target_share")
        )

    # Routes per team dropback is the cleanest available inline-versus-
    # receiving proxy: a blocking tight end takes snaps without running routes,
    # so his estimated route rate falls well below his snap share.
    if {"routes_estimated", "own_team_dropbacks"} <= set(frame.columns):
        frame = frame.with_columns(
            safe_ratio(
                pl.col("routes_estimated"), pl.col("own_team_dropbacks").cast(pl.Float64)
            ).alias("routes_per_team_dropback")
        )
    else:
        frame = frame.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("routes_per_team_dropback")
        )

    # The gap between snap share and route participation is the inline signal.
    if {"snap_share", "route_participation"} <= set(frame.columns):
        frame = frame.with_columns(
            (
                pl.col("snap_share").cast(pl.Float64) - pl.col("route_participation")
            ).alias("inline_usage_gap")
        )
    else:
        frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("inline_usage_gap"))

    return frame
