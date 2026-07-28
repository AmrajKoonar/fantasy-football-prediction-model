"""Wide-receiver features.

Opportunity dominates: target share, air-yard share and their combination
(WOPR) are the most stable year-to-year receiving signals in public data.
Efficiency metrics are included but are treated as secondary, and the
feature-research pipeline measures how much each actually adds.

Routes are not published for free, so route participation is *estimated* from
snap counts and team dropbacks. The estimate is clearly named
``routes_estimated`` and its derivation is documented, so nothing downstream
mistakes it for a charted route count.
"""

from __future__ import annotations

import polars as pl

from fantasy_football_prediction_model.data.aggregation import safe_ratio

MIN_TARGETS = 15
MIN_RECEPTIONS = 10
MIN_SNAPS = 50


def add_receiver_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Add receiving opportunity, efficiency and context features."""
    games = pl.col("games").cast(pl.Float64)
    targets = pl.col("targets").cast(pl.Float64)
    receptions = pl.col("receptions").cast(pl.Float64)
    air_yards = pl.col("receiving_air_yards").cast(pl.Float64)
    receiving_yards = pl.col("receiving_yards").cast(pl.Float64)

    frame = frame.with_columns(
        safe_ratio(targets, games).alias("targets_per_game"),
        safe_ratio(receptions, games).alias("receptions_per_game"),
        safe_ratio(receiving_yards, games).alias("receiving_yards_per_game"),
        safe_ratio(air_yards, games).alias("air_yards_per_game"),
        # Efficiency, volume-gated.
        safe_ratio(receptions, targets, min_denominator=MIN_TARGETS).alias("catch_rate"),
        safe_ratio(receiving_yards, targets, min_denominator=MIN_TARGETS).alias(
            "yards_per_target"
        ),
        safe_ratio(receiving_yards, receptions, min_denominator=MIN_RECEPTIONS).alias(
            "yards_per_reception"
        ),
        safe_ratio(
            pl.col("receiving_yards_after_catch").cast(pl.Float64),
            receptions,
            min_denominator=MIN_RECEPTIONS,
        ).alias("yac_per_reception"),
        safe_ratio(
            pl.col("receiving_tds").cast(pl.Float64), targets, min_denominator=MIN_TARGETS
        ).alias("receiving_td_rate"),
        safe_ratio(
            pl.col("receiving_first_downs").cast(pl.Float64),
            targets,
            min_denominator=MIN_TARGETS,
        ).alias("receiving_first_down_rate"),
        safe_ratio(air_yards, targets, min_denominator=MIN_TARGETS).alias("adot_derived"),
        # Explosive receptions: nflverse publishes counts of receptions gaining
        # at least 20 and 40 yards.
        safe_ratio(
            pl.col("receiving_20").cast(pl.Float64), receptions, min_denominator=MIN_RECEPTIONS
        ).alias("explosive_reception_rate"),
    )

    # RACR: receiving yards per air yard. Above 1.0 means the receiver
    # converts intended yardage into more than its face value.
    frame = frame.with_columns(
        safe_ratio(receiving_yards, air_yards, min_denominator=100).alias("racr_derived")
    )

    # Prefer the nflverse-published share metrics; fall back to derived ones.
    for published, derived in (("racr", "racr_derived"), ("adot", "adot_derived")):
        if published in frame.columns:
            frame = frame.with_columns(
                pl.coalesce([pl.col(published), pl.col(derived)]).alias(published)
            )
        else:
            frame = frame.with_columns(pl.col(derived).alias(published))

    return _add_snap_and_route_features(frame)


def _add_snap_and_route_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Snap share plus an explicitly estimated route count.

    Public data has no charted routes. Offensive snaps for a pass catcher are
    dominated by pass plays, so routes are estimated as::

        routes_estimated = offense_snaps x team_pass_rate

    This is an approximation, not a measurement. Targets per route run and
    yards per route run derived from it inherit that approximation, which is
    why they are named consistently and reported in the feature research with
    their real coverage.
    """
    if "offense_snaps" not in frame.columns:
        for column in (
            "offense_snaps",
            "snap_share",
            "routes_estimated",
            "route_participation",
            "targets_per_route_run",
            "yards_per_route_run",
        ):
            if column not in frame.columns:
                frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(column))
        return frame

    snaps = pl.col("offense_snaps").cast(pl.Float64)
    pass_rate = (
        pl.col("team_pass_rate").cast(pl.Float64)
        if "team_pass_rate" in frame.columns
        else pl.lit(None, dtype=pl.Float64)
    )
    team_dropbacks = (
        pl.col("own_team_dropbacks").cast(pl.Float64)
        if "own_team_dropbacks" in frame.columns
        else pl.lit(None, dtype=pl.Float64)
    )

    frame = frame.with_columns(
        (snaps * pass_rate).alias("routes_estimated"),
    ).with_columns(
        safe_ratio(pl.col("routes_estimated"), team_dropbacks).alias("route_participation"),
        safe_ratio(
            pl.col("targets").cast(pl.Float64),
            pl.col("routes_estimated"),
            min_denominator=MIN_SNAPS,
        ).alias("targets_per_route_run"),
        safe_ratio(
            pl.col("receiving_yards").cast(pl.Float64),
            pl.col("routes_estimated"),
            min_denominator=MIN_SNAPS,
        ).alias("yards_per_route_run"),
        safe_ratio(snaps, pl.col("games").cast(pl.Float64)).alias("snaps_per_game"),
    )
    return frame


def add_target_competition(frame: pl.DataFrame) -> pl.DataFrame:
    """Share of the projected team's targets held by other returning receivers.

    Called during the modelling-pair build, once the projected team for the
    outcome season is known.
    """
    required = {"projected_team", "season", "targets", "next_team_known", "next_team"}
    if not required <= set(frame.columns):
        return frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("target_competition"))

    catchers = frame.filter(
        pl.col("position").is_in(["WR", "TE", "RB"]) & (pl.col("next_team_known") == 1)
    )
    if catchers.is_empty():
        return frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("target_competition"))

    room = catchers.group_by(["next_team", "season"]).agg(
        pl.col("targets").fill_null(0).sum().alias("_room_targets")
    )
    joined = frame.join(
        room.select(pl.col("next_team").alias("projected_team"), "season", "_room_targets"),
        on=["projected_team", "season"],
        how="left",
    )
    return joined.with_columns(
        safe_ratio(
            pl.col("_room_targets") - pl.col("targets").fill_null(0),
            pl.col("_room_targets"),
        ).alias("target_competition")
    ).drop("_room_targets")
