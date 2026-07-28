"""Availability and durability features.

Injury reports are deliberately **not** the basis of these features. The
nflverse injury feed has not reliably covered seasons after 2024, and even
when present it describes a status rather than a prognosis. Building the model
on it would create a dependency that breaks every time the upstream feed
lapses, and would invite a medical interpretation the data cannot support.

Instead, availability is inferred from things that are always observable:
games played relative to the schedule, multi-season durability, workload
history and roster status. These are weaker signals than a real injury
report, and the limitation is stated on the methodology page.
"""

from __future__ import annotations

import polars as pl

from fantasy_football_prediction_model.constants import CANONICAL_ID_COLUMN
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)

#: Weights for the durability score, newest season first. Recent availability
#: predicts next-season availability better than older seasons do.
_DURABILITY_WEIGHTS: tuple[float, float, float] = (0.5, 0.3, 0.2)


def add_availability_features(
    frame: pl.DataFrame, games_per_season: dict[int, int]
) -> pl.DataFrame:
    """Add games-played, durability and role-continuity features.

    Args:
        frame: Player-season frame sorted by ``(gsis_id, season)``.
        games_per_season: Scheduled regular-season games, by season.

    Returns:
        The frame with availability features appended.
    """
    default_games = max(games_per_season.values(), default=17)
    scheduled = pl.col("season").replace_strict(
        games_per_season, default=default_games, return_dtype=pl.Int64
    )

    frame = frame.with_columns(scheduled.alias("scheduled_games")).with_columns(
        (pl.col("games").cast(pl.Float64) / pl.col("scheduled_games").cast(pl.Float64))
        .clip(0.0, 1.0)
        .alias("games_played_share"),
        (pl.col("scheduled_games") - pl.col("games")).clip(0, None).alias("games_missed"),
    )

    # Prior-season availability. Shifted within player so season t's feature
    # only ever sees seasons strictly before t... except games_played itself,
    # which describes season t and is legitimately known at its end.
    frame = frame.with_columns(
        pl.col("games_played_share")
        .shift(1)
        .over(CANONICAL_ID_COLUMN)
        .alias("games_played_share_prev1"),
        pl.col("games_played_share")
        .shift(2)
        .over(CANONICAL_ID_COLUMN)
        .alias("games_played_share_prev2"),
        pl.col("games").shift(1).over(CANONICAL_ID_COLUMN).alias("games_played_prev2"),
        pl.col("games").shift(2).over(CANONICAL_ID_COLUMN).alias("games_played_prev3"),
        pl.col("games_missed")
        .rolling_sum(window_size=3, min_samples=1)
        .over(CANONICAL_ID_COLUMN)
        .alias("games_missed_3yr"),
    )

    # Weighted three-season availability. Missing older seasons fall back to
    # the seasons that do exist rather than being treated as zero games.
    weights = _DURABILITY_WEIGHTS
    components = [
        (pl.col("games_played_share"), weights[0]),
        (pl.col("games_played_share_prev1"), weights[1]),
        (pl.col("games_played_share_prev2"), weights[2]),
    ]
    weighted_sum = pl.sum_horizontal(
        [pl.when(expr.is_not_null()).then(expr * weight).otherwise(0.0) for expr, weight in components]
    )
    weight_total = pl.sum_horizontal(
        [pl.when(expr.is_not_null()).then(weight).otherwise(0.0) for expr, weight in components]
    )
    frame = frame.with_columns(
        pl.when(weight_total > 0)
        .then(weighted_sum / weight_total)
        .otherwise(None)
        .alias("durability_score")
    )

    frame = frame.with_columns(
        pl.col("season")
        .rank("dense")
        .over([CANONICAL_ID_COLUMN, "team"])
        .cast(pl.Int64)
        .alias("seasons_with_team_raw")
    )

    # Consecutive seasons with the current team, counted by comparing the
    # running team against the previous season's team.
    frame = frame.with_columns(
        (pl.col("team") != pl.col("team").shift(1).over(CANONICAL_ID_COLUMN))
        .fill_null(True)
        .cast(pl.Int8)
        .alias("team_switch_marker")
    ).with_columns(
        pl.col("team_switch_marker").cum_sum().over(CANONICAL_ID_COLUMN).alias("_team_spell")
    )
    frame = frame.with_columns(
        pl.col("season")
        .cum_count()
        .over([CANONICAL_ID_COLUMN, "_team_spell"])
        .cast(pl.Int64)
        .alias("seasons_with_team")
    ).drop(["_team_spell", "seasons_with_team_raw"])

    return frame


def add_next_season_context(
    frame: pl.DataFrame, week1_teams: pl.DataFrame | None
) -> pl.DataFrame:
    """Attach the projected season's week-1 team and derived change flags.

    This is the single place where information about season ``t + 1`` enters a
    feature, and it is limited to *where the player lines up*, which is public
    before the season starts.

    Adds:
        ``next_team``: week-1 team for season ``t + 1`` (null when unknown).
        ``team_changed``: 1 when it differs from the season-``t`` team.
        ``next_team_known``: 1 when the assignment could be established, so
            the model can distinguish "same team" from "we do not know".
    """
    if week1_teams is None or week1_teams.is_empty():
        logger.warning(
            "No week-1 roster data; team-change features are unavailable and will be "
            "marked missing."
        )
        return frame.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("next_team"),
            pl.lit(None, dtype=pl.Int8).alias("team_changed"),
            pl.lit(0, dtype=pl.Int8).alias("next_team_known"),
        )

    # Join on the outcome season when the caller supplies one. Rows for a
    # player who missed a year have a feature season older than
    # ``target_season - 1``, so keying on ``season + 1`` would silently miss
    # them and report every returning player as having no known team.
    if "target_season" in frame.columns:
        lookup = week1_teams.select(
            pl.col(CANONICAL_ID_COLUMN),
            pl.col("season").alias("target_season"),
            pl.col("week1_team").alias("next_team"),
        )
        join_keys = [CANONICAL_ID_COLUMN, "target_season"]
    else:
        lookup = week1_teams.select(
            pl.col(CANONICAL_ID_COLUMN),
            (pl.col("season") - 1).alias("season"),
            pl.col("week1_team").alias("next_team"),
        )
        join_keys = [CANONICAL_ID_COLUMN, "season"]

    joined = frame.join(lookup, on=join_keys, how="left")
    return joined.with_columns(
        pl.col("next_team").is_not_null().cast(pl.Int8).alias("next_team_known"),
        pl.when(pl.col("next_team").is_null())
        .then(None)
        .otherwise((pl.col("next_team") != pl.col("team")).cast(pl.Int8))
        .alias("team_changed"),
    )


def add_roster_status_features(
    frame: pl.DataFrame, rosters: pl.DataFrame
) -> pl.DataFrame:
    """Attach season-``t`` roster status.

    Only the season-``t`` roster row is used. The season-``t+1`` roster is
    deliberately not joined: its ``status`` and ``week`` columns record how the
    following season ended, which is exactly the survival information the
    leakage rules forbid.
    """
    if "status" not in rosters.columns:
        return frame.with_columns(pl.lit(None, dtype=pl.Int8).alias("roster_status_active"))

    status = rosters.select(
        CANONICAL_ID_COLUMN,
        "season",
        pl.col("status").cast(pl.Utf8).alias("roster_status"),
    ).unique(subset=[CANONICAL_ID_COLUMN, "season"], keep="last")

    joined = frame.join(status, on=[CANONICAL_ID_COLUMN, "season"], how="left")
    return joined.with_columns(
        pl.when(pl.col("roster_status").is_null())
        .then(None)
        .otherwise(pl.col("roster_status").is_in(["ACT", "A01"]).cast(pl.Int8))
        .alias("roster_status_active")
    )


def add_depth_chart_features(
    frame: pl.DataFrame, depth_seasons: pl.DataFrame | None
) -> pl.DataFrame:
    """Attach the season-``t`` published depth-chart rank."""
    if depth_seasons is None or depth_seasons.is_empty():
        return frame.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("depth_chart_rank"),
            pl.lit(None, dtype=pl.Int8).alias("depth_chart_is_starter"),
        )
    columns = [CANONICAL_ID_COLUMN, "season", "depth_chart_rank", "depth_chart_is_starter"]
    available = [column for column in columns if column in depth_seasons.columns]
    return frame.join(depth_seasons.select(available), on=[CANONICAL_ID_COLUMN, "season"], how="left")
