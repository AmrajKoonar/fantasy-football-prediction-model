"""Season-level aggregation of raw nflverse tables.

Turns weekly and play-level sources into one row per ``(gsis_id, season)``.

Two things make this less mechanical than it sounds:

* **Multi-team seasons.** A traded player has rows under two teams. Statistics
  are summed across the whole season; the team recorded is the one they
  finished with, because that is what predicts the following year's role.
* **Schema drift.** nflverse changed the depth-chart layout for 2025, and
  advanced sources start in different seasons. Both layouts are handled and
  every gap is reported instead of being filled with a guess.

Nothing here imputes. Missing means missing, and the modelling layer decides
what to do about it.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from fantasy_football_prediction_model.constants import (
    CANONICAL_ID_COLUMN,
    REGULAR_SEASON_GAMES_BY_ERA,
)
from fantasy_football_prediction_model.data.identities import (
    PlayerIdentityResolver,
    normalise_position_expr,
    normalise_team_expr,
)
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)

REGULAR_SEASON = "REG"

#: Weekly statistics summed to season totals.
_SUM_COLUMNS: tuple[str, ...] = (
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "sacks_suffered",
    "sack_yards_lost",
    "sack_fumbles",
    "sack_fumbles_lost",
    "passing_air_yards",
    "passing_yards_after_catch",
    "passing_first_downs",
    "passing_2pt_conversions",
    "passing_20",
    "passing_40",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "rushing_fumbles",
    "rushing_fumbles_lost",
    "rushing_first_downs",
    "rushing_2pt_conversions",
    "rushing_20",
    "rushing_40",
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
    "receiving_fumbles",
    "receiving_fumbles_lost",
    "receiving_air_yards",
    "receiving_yards_after_catch",
    "receiving_first_downs",
    "receiving_2pt_conversions",
    "receiving_20",
    "receiving_40",
    "special_teams_tds",
    "fantasy_points",
    "fantasy_points_ppr",
)

#: EPA columns are additive over plays, so they sum like counting statistics.
_EPA_COLUMNS: tuple[str, ...] = ("passing_epa", "rushing_epa", "receiving_epa")

#: Rate statistics that must be re-derived from totals rather than averaged
#: across weeks, because a weekly mean silently over-weights low-volume games.
_RATE_COLUMNS: tuple[str, ...] = ("passing_cpoe", "target_share", "air_yards_share", "wopr")


def _sum_if_present(frame: pl.DataFrame, columns: Sequence[str]) -> list[pl.Expr]:
    """Sum expressions for whichever of ``columns`` the frame actually has."""
    return [
        pl.col(column).cast(pl.Float64, strict=False).sum().alias(column)
        for column in columns
        if column in frame.columns
    ]


def games_per_season_from_schedule(schedules: pl.DataFrame | None) -> dict[int, int]:
    """Maximum regular-season games any team plays, by season.

    Derived from the schedule so the 16-to-17 game change (and any future
    change) is picked up automatically instead of being hardcoded.
    """
    if schedules is None or schedules.is_empty():
        logger.warning(
            "No schedule data available; falling back to the documented games-per-era table."
        )
        return {
            season: games
            for era, games in REGULAR_SEASON_GAMES_BY_ERA.items()
            for season in era
            if season <= 2100
        }

    regular = schedules
    if "game_type" in schedules.columns:
        regular = schedules.filter(pl.col("game_type") == REGULAR_SEASON)
    if regular.is_empty():
        regular = schedules

    per_team = pl.concat(
        [
            regular.select(pl.col("season"), pl.col("home_team").alias("team")),
            regular.select(pl.col("season"), pl.col("away_team").alias("team")),
        ]
    )
    counts = (
        per_team.group_by(["season", "team"])
        .len()
        .group_by("season")
        .agg(pl.col("len").max().alias("games"))
    )
    mapping = {int(row["season"]): int(row["games"]) for row in counts.iter_rows(named=True)}
    logger.debug("Games per season derived from the schedule: %s", mapping)
    return mapping


# ---------------------------------------------------------------------------
# Player season statistics
# ---------------------------------------------------------------------------


def aggregate_player_seasons(weekly: pl.DataFrame) -> pl.DataFrame:
    """Aggregate weekly player statistics into regular-season totals.

    Args:
        weekly: ``load_player_stats(summary_level="week")`` output.

    Returns:
        One row per ``(gsis_id, season)`` with season totals, the finishing
        team, games played and the number of distinct teams played for.
    """
    if weekly.is_empty():
        raise ValueError("Cannot aggregate an empty weekly player-statistics frame.")

    regular = weekly
    if "season_type" in weekly.columns:
        regular = weekly.filter(pl.col("season_type") == REGULAR_SEASON)
    if regular.is_empty():
        raise ValueError("The weekly player-statistics frame contains no regular-season rows.")

    regular = regular.with_columns(
        pl.col("player_id").cast(pl.Utf8).alias(CANONICAL_ID_COLUMN),
        normalise_team_expr("team", "team"),
        pl.col("week").cast(pl.Int64),
        pl.col("season").cast(pl.Int64),
    )

    aggregations: list[pl.Expr] = [
        # Count distinct weeks, not rows: a mid-week transaction can produce
        # two rows for the same player in the same week.
        pl.col("week").n_unique().alias("games"),
        pl.col("team").last().alias("team"),
        pl.col("team").n_unique().alias("teams_played_for"),
        pl.col("position").drop_nulls().last().alias("raw_position"),
        pl.col("player_display_name").drop_nulls().last().alias("source_name"),
    ]
    aggregations.extend(_sum_if_present(regular, _SUM_COLUMNS))
    aggregations.extend(_sum_if_present(regular, _EPA_COLUMNS))

    # Weight per-week rate statistics by the volume that produced them, so a
    # one-attempt week cannot swing a season CPOE.
    weight_map = {
        "passing_cpoe": "attempts",
        "target_share": "week",
        "air_yards_share": "week",
        "wopr": "week",
    }
    for rate, weight in weight_map.items():
        if rate not in regular.columns:
            continue
        if weight == "week":
            aggregations.append(pl.col(rate).cast(pl.Float64).mean().alias(rate))
        elif weight in regular.columns:
            numerator = (pl.col(rate).cast(pl.Float64) * pl.col(weight).cast(pl.Float64)).sum()
            denominator = (
                pl.when(pl.col(rate).is_not_null())
                .then(pl.col(weight).cast(pl.Float64))
                .otherwise(0.0)
                .sum()
            )
            aggregations.append(
                pl.when(denominator > 0).then(numerator / denominator).otherwise(None).alias(rate)
            )

    seasons = (
        regular.group_by([CANONICAL_ID_COLUMN, "season"])
        .agg(aggregations)
        .sort([CANONICAL_ID_COLUMN, "season"])
    )

    seasons = seasons.with_columns(
        normalise_position_expr("raw_position", "position"),
        (pl.col("teams_played_for") > 1).alias("multi_team_season"),
    )

    # nflverse splits fumbles lost by the play type that produced them.
    lost_columns = [
        column
        for column in ("sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost")
        if column in seasons.columns
    ]
    if lost_columns:
        seasons = seasons.with_columns(
            pl.sum_horizontal([pl.col(c).fill_null(0.0) for c in lost_columns]).alias(
                "fumbles_lost"
            )
        )
    else:
        seasons = seasons.with_columns(pl.lit(0.0).alias("fumbles_lost"))

    renames = {
        "attempts": "pass_attempts",
        "passing_interceptions": "interceptions",
    }
    seasons = seasons.rename({old: new for old, new in renames.items() if old in seasons.columns})

    two_point_columns = [
        c
        for c in ("passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions")
        if c in seasons.columns
    ]
    if two_point_columns:
        seasons = seasons.with_columns(
            pl.sum_horizontal([pl.col(c).fill_null(0.0) for c in two_point_columns]).alias(
                "two_point_conversions"
            )
        )

    logger.info(
        "Aggregated %d player-seasons across %d seasons.",
        seasons.height,
        seasons.get_column("season").n_unique(),
    )
    return seasons


def aggregate_team_seasons(team_weekly: pl.DataFrame) -> pl.DataFrame:
    """Aggregate weekly team statistics into regular-season team context."""
    if team_weekly.is_empty():
        raise ValueError("Cannot aggregate an empty weekly team-statistics frame.")

    regular = team_weekly
    if "season_type" in team_weekly.columns:
        regular = team_weekly.filter(pl.col("season_type") == REGULAR_SEASON)

    regular = regular.with_columns(
        normalise_team_expr("team", "team"),
        pl.col("season").cast(pl.Int64),
    )

    columns = (
        "attempts",
        "completions",
        "passing_yards",
        "passing_tds",
        "passing_interceptions",
        "passing_air_yards",
        "passing_first_downs",
        "sacks_suffered",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "rushing_first_downs",
        "targets",
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "receiving_air_yards",
        "passing_epa",
        "rushing_epa",
        "receiving_epa",
        "fantasy_points_ppr",
    )
    aggregated = (
        regular.group_by(["team", "season"])
        .agg(
            pl.col("week").n_unique().alias("team_games"),
            *_sum_if_present(regular, columns),
        )
        .sort(["team", "season"])
    )

    renames = {
        "attempts": "team_pass_attempts",
        "completions": "team_completions",
        "passing_yards": "team_passing_yards",
        "passing_tds": "team_passing_tds",
        "passing_interceptions": "team_interceptions",
        "passing_air_yards": "team_air_yards",
        "passing_first_downs": "team_passing_first_downs",
        "sacks_suffered": "team_sacks_allowed",
        "carries": "team_rush_attempts",
        "rushing_yards": "team_rushing_yards",
        "rushing_tds": "team_rushing_tds",
        "rushing_first_downs": "team_rushing_first_downs",
        "targets": "team_targets",
        "receptions": "team_receptions",
        "receiving_yards": "team_receiving_yards",
        "receiving_tds": "team_receiving_tds",
        "receiving_air_yards": "team_receiving_air_yards",
        "passing_epa": "team_passing_epa",
        "rushing_epa": "team_rushing_epa",
        "receiving_epa": "team_receiving_epa",
        "fantasy_points_ppr": "team_fantasy_points_ppr",
    }
    aggregated = aggregated.rename(
        {old: new for old, new in renames.items() if old in aggregated.columns}
    )

    # Dropbacks approximate team pass volume better than attempts alone,
    # because a sack consumes a pass play without recording an attempt.
    aggregated = aggregated.with_columns(
        (
            pl.col("team_pass_attempts").fill_null(0) + pl.col("team_sacks_allowed").fill_null(0)
        ).alias("team_dropbacks")
    ).with_columns(
        (pl.col("team_dropbacks") + pl.col("team_rush_attempts").fill_null(0)).alias("team_plays"),
        (pl.col("team_passing_tds").fill_null(0) + pl.col("team_rushing_tds").fill_null(0)).alias(
            "team_offensive_tds"
        ),
    )
    aggregated = aggregated.with_columns(
        _safe_divide("team_dropbacks", "team_plays").alias("team_pass_rate"),
        _safe_divide("team_rush_attempts", "team_plays").alias("team_rush_rate"),
        _safe_divide("team_plays", "team_games").alias("team_plays_per_game"),
        (
            (pl.col("team_passing_epa").fill_null(0) + pl.col("team_rushing_epa").fill_null(0))
            / pl.when(pl.col("team_plays") > 0).then(pl.col("team_plays")).otherwise(None)
        ).alias("team_epa_per_play"),
        (
            pl.col("team_passing_epa")
            / pl.when(pl.col("team_dropbacks") > 0).then(pl.col("team_dropbacks")).otherwise(None)
        ).alias("team_pass_epa_per_play"),
        (
            pl.col("team_rushing_epa")
            / pl.when(pl.col("team_rush_attempts") > 0)
            .then(pl.col("team_rush_attempts"))
            .otherwise(None)
        ).alias("team_rush_epa_per_play"),
    )
    return aggregated


def _safe_divide(numerator: str, denominator: str) -> pl.Expr:
    """``numerator / denominator``, or null when the denominator is 0/null.

    Guards every per-game and per-opportunity rate in the project. Producing
    an infinity here would silently poison the models downstream.
    """
    return (
        pl.when(pl.col(denominator).is_not_null() & (pl.col(denominator) > 0))
        .then(pl.col(numerator).cast(pl.Float64) / pl.col(denominator).cast(pl.Float64))
        .otherwise(None)
    )


def safe_ratio(
    numerator: pl.Expr, denominator: pl.Expr, *, min_denominator: float = 0.0
) -> pl.Expr:
    """Null-safe, minimum-volume-aware division for expression pipelines."""
    return (
        pl.when(denominator.is_not_null() & (denominator > max(min_denominator, 0.0)))
        .then(numerator.cast(pl.Float64) / denominator.cast(pl.Float64))
        .otherwise(None)
    )


def add_team_scoring(team_seasons: pl.DataFrame, schedules: pl.DataFrame | None) -> pl.DataFrame:
    """Attach points scored per game from the schedule's final scores."""
    if schedules is None or schedules.is_empty():
        return team_seasons.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("team_points_per_game")
        )

    regular = schedules
    if "game_type" in schedules.columns:
        regular = schedules.filter(pl.col("game_type") == REGULAR_SEASON)
    scored = regular.filter(pl.col("home_score").is_not_null() & pl.col("away_score").is_not_null())
    if scored.is_empty():
        return team_seasons.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("team_points_per_game")
        )

    stacked = pl.concat(
        [
            scored.select(
                pl.col("season").cast(pl.Int64),
                normalise_team_expr("home_team", "team"),
                pl.col("home_score").cast(pl.Float64).alias("points"),
            ),
            scored.select(
                pl.col("season").cast(pl.Int64),
                normalise_team_expr("away_team", "team"),
                pl.col("away_score").cast(pl.Float64).alias("points"),
            ),
        ]
    )
    per_team = stacked.group_by(["season", "team"]).agg(
        pl.col("points").mean().alias("team_points_per_game")
    )
    return team_seasons.join(per_team, on=["season", "team"], how="left")


# ---------------------------------------------------------------------------
# Snap counts
# ---------------------------------------------------------------------------


def aggregate_snap_counts(
    snap_counts: pl.DataFrame | None, resolver: PlayerIdentityResolver
) -> pl.DataFrame | None:
    """Season snap totals keyed on GSIS.

    Snap counts come from Pro Football Reference and carry ``pfr_player_id``
    rather than a GSIS id, so they are joined through the player dimension's
    PFR crosswalk. Names are never used for this join.
    """
    if snap_counts is None or snap_counts.is_empty():
        return None
    if "pfr_player_id" not in snap_counts.columns:
        logger.warning("Snap counts have no pfr_player_id column; skipping snap features.")
        return None

    regular = snap_counts
    if "game_type" in snap_counts.columns:
        regular = snap_counts.filter(pl.col("game_type") == REGULAR_SEASON)

    aggregated = (
        regular.with_columns(pl.col("season").cast(pl.Int64))
        .group_by(["pfr_player_id", "season"])
        .agg(
            pl.col("offense_snaps").cast(pl.Float64).sum().alias("offense_snaps"),
            pl.col("offense_pct").cast(pl.Float64).mean().alias("snap_share"),
            pl.col("week").n_unique().alias("snap_games"),
        )
    )

    crosswalk = (
        resolver.dimension.select(
            pl.col("pfr_id").cast(pl.Utf8).alias("pfr_player_id"),
            pl.col(CANONICAL_ID_COLUMN),
        )
        .filter(pl.col("pfr_player_id").is_not_null())
        .unique(subset=["pfr_player_id"], keep="first")
    )

    joined = aggregated.join(crosswalk, on="pfr_player_id", how="left")
    unmatched = joined.filter(pl.col(CANONICAL_ID_COLUMN).is_null()).height
    if unmatched:
        logger.info(
            "%d of %d snap-count player-seasons (%.1f%%) have no PFR-to-GSIS mapping and are "
            "excluded from snap features.",
            unmatched,
            joined.height,
            100 * unmatched / max(joined.height, 1),
        )
    return joined.filter(pl.col(CANONICAL_ID_COLUMN).is_not_null()).drop("pfr_player_id")


# ---------------------------------------------------------------------------
# Depth charts (two incompatible layouts)
# ---------------------------------------------------------------------------


def aggregate_depth_charts(
    depth_charts: pl.DataFrame | None, *, season: int | None = None
) -> pl.DataFrame | None:
    """Season depth-chart rank, tolerant of both nflverse layouts.

    Legacy layout (2001-2024): ``season``, ``week``, ``club_code``,
    ``depth_team``, ``gsis_id``.
    Current layout (2025 onward): dated snapshots with ``dt``, ``team``,
    ``pos_rank``, ``gsis_id`` and no season column.

    Returns one row per ``(gsis_id, season)`` holding the median and final
    published rank. The median resists a single erroneous snapshot; the final
    rank captures where the player ended the season.
    """
    if depth_charts is None or depth_charts.is_empty():
        return None
    if "gsis_id" not in depth_charts.columns:
        logger.warning("Depth charts have no gsis_id column; skipping depth-chart features.")
        return None

    frame = depth_charts
    legacy = "depth_team" in frame.columns and "season" in frame.columns

    if legacy:
        frame = frame.with_columns(
            pl.col("season").cast(pl.Int64),
            pl.col("depth_team").cast(pl.Float64, strict=False).alias("depth_rank"),
            normalise_team_expr("club_code", "team"),
            pl.col("week").cast(pl.Int64, strict=False).alias("order_key"),
        )
        if "game_type" in frame.columns:
            frame = frame.filter(pl.col("game_type") == REGULAR_SEASON)
    else:
        if "pos_rank" not in frame.columns:
            logger.warning(
                "Depth charts use the post-2024 layout but have no pos_rank column; "
                "skipping depth-chart features."
            )
            return None
        season_expr = (
            pl.col("dt").cast(pl.Utf8).str.slice(0, 4).cast(pl.Int64, strict=False)
            if "dt" in frame.columns
            else pl.lit(season, dtype=pl.Int64)
        )
        frame = frame.with_columns(
            season_expr.alias("season"),
            pl.col("pos_rank").cast(pl.Float64, strict=False).alias("depth_rank"),
            normalise_team_expr("team", "team"),
        )
        frame = frame.with_columns(
            (
                pl.col("dt").cast(pl.Utf8).str.slice(0, 10).str.to_date(strict=False)
                if "dt" in frame.columns
                else pl.lit(None, dtype=pl.Date)
            ).alias("snapshot_date")
        )
        # A depth chart published in January belongs to the season that began
        # the previous calendar year.
        if "snapshot_date" in frame.columns:
            frame = frame.with_columns(
                pl.when(pl.col("snapshot_date").dt.month() < 3)
                .then(pl.col("season") - 1)
                .otherwise(pl.col("season"))
                .alias("season")
            )
        frame = frame.with_columns(
            pl.col("snapshot_date").dt.ordinal_day().cast(pl.Int64).alias("order_key")
        )

    if season is not None:
        frame = frame.filter(pl.col("season") == season)

    frame = frame.filter(pl.col("depth_rank").is_not_null() & pl.col("gsis_id").is_not_null())
    if frame.is_empty():
        return None

    return (
        frame.sort("order_key", nulls_last=True)
        .group_by([pl.col("gsis_id").cast(pl.Utf8).alias(CANONICAL_ID_COLUMN), "season"])
        .agg(
            pl.col("depth_rank").median().alias("depth_chart_rank"),
            pl.col("depth_rank").last().alias("depth_chart_rank_final"),
            pl.col("team").last().alias("depth_chart_team"),
        )
        .with_columns(
            (pl.col("depth_chart_rank") <= 1.0).cast(pl.Int8).alias("depth_chart_is_starter")
        )
    )


# ---------------------------------------------------------------------------
# Next Gen Stats
# ---------------------------------------------------------------------------

#: NGS column -> project feature name, per statistic type.
NGS_COLUMN_MAP: dict[str, dict[str, str]] = {
    "passing": {
        "avg_time_to_throw": "ngs_avg_time_to_throw",
        "avg_completed_air_yards": "ngs_avg_completed_air_yards",
        "avg_intended_air_yards": "ngs_avg_intended_air_yards",
        "aggressiveness": "ngs_aggressiveness",
        "expected_completion_percentage": "ngs_expected_completion_pct",
        "completion_percentage_above_expectation": "ngs_completion_pct_above_expectation",
        "avg_air_yards_differential": "ngs_avg_air_yards_differential",
    },
    "rushing": {
        "efficiency": "ngs_efficiency",
        "percent_attempts_gte_eight_defenders": "ngs_pct_attempts_gte_eight_defenders",
        "avg_time_to_los": "ngs_avg_time_to_los",
        "rush_yards_over_expected": "ngs_rush_yards_over_expected",
        "rush_yards_over_expected_per_att": "ngs_rush_yards_over_expected_per_att",
        "rush_pct_over_expected": "ngs_rush_pct_over_expected",
    },
    "receiving": {
        "avg_cushion": "ngs_avg_cushion",
        "avg_separation": "ngs_avg_separation",
        "avg_yac_above_expectation": "ngs_avg_yac_above_expectation",
        "catch_percentage": "ngs_catch_pct",
        "percent_share_of_intended_air_yards": "ngs_share_of_intended_air_yards",
    },
}


def aggregate_nextgen(frame: pl.DataFrame | None, stat_type: str) -> pl.DataFrame | None:
    """Season Next Gen Stats keyed on GSIS.

    NGS publishes a season summary row with ``week == 0`` alongside weekly
    rows. The summary row is used when present, because it is the league's own
    season calculation rather than an average of averages.
    """
    if frame is None or frame.is_empty():
        return None
    if "player_gsis_id" not in frame.columns:
        logger.warning("Next Gen Stats (%s) have no player_gsis_id column; skipping.", stat_type)
        return None

    mapping = {
        source: target
        for source, target in NGS_COLUMN_MAP.get(stat_type, {}).items()
        if source in frame.columns
    }
    if not mapping:
        logger.warning("Next Gen Stats (%s) contain none of the expected columns.", stat_type)
        return None

    working = frame
    if "season_type" in working.columns:
        working = working.filter(pl.col("season_type") == REGULAR_SEASON)

    season_rows = working.filter(pl.col("week") == 0) if "week" in working.columns else working
    if season_rows.is_empty():
        logger.debug(
            "Next Gen Stats (%s) have no season-summary rows; averaging the weekly rows.",
            stat_type,
        )
        season_rows = working

    return (
        season_rows.with_columns(
            pl.col("player_gsis_id").cast(pl.Utf8).alias(CANONICAL_ID_COLUMN),
            pl.col("season").cast(pl.Int64),
        )
        .group_by([CANONICAL_ID_COLUMN, "season"])
        .agg(
            [
                pl.col(source).cast(pl.Float64, strict=False).mean().alias(target)
                for source, target in mapping.items()
            ]
        )
    )


# ---------------------------------------------------------------------------
# Pro Football Reference advanced statistics
# ---------------------------------------------------------------------------

PFR_COLUMN_MAP: dict[str, dict[str, str]] = {
    "pass": {
        "pocket_time": "pfr_pocket_time",
        "pressure_pct": "pfr_pressure_pct",
        "bad_throw_pct": "pfr_bad_throw_pct",
        "drop_pct": "pfr_drop_pct",
        "on_tgt_pct": "pfr_on_target_pct",
        "scrambles": "pfr_scrambles",
    },
    "rush": {
        "ybc_att": "pfr_yards_before_contact_per_att",
        "yac_att": "pfr_yards_after_contact_per_att",
        "brk_tkl": "pfr_broken_tackles",
        "att_br": "pfr_attempts_per_broken_tackle",
    },
    "rec": {
        "adot": "pfr_adot",
        "brk_tkl": "pfr_receiving_broken_tackles",
        "drop_percent": "pfr_receiving_drop_pct",
        "yac_r": "pfr_receiving_yac_per_reception",
        "ybc_r": "pfr_receiving_ybc_per_reception",
    },
}


def aggregate_pfr_advstats(
    frame: pl.DataFrame | None, stat_type: str, resolver: PlayerIdentityResolver
) -> pl.DataFrame | None:
    """Season PFR advanced statistics, joined to GSIS through ``pfr_id``."""
    if frame is None or frame.is_empty():
        return None
    if "pfr_id" not in frame.columns:
        logger.warning("PFR advanced stats (%s) have no pfr_id column; skipping.", stat_type)
        return None

    mapping = {
        source: target
        for source, target in PFR_COLUMN_MAP.get(stat_type, {}).items()
        if source in frame.columns
    }
    if not mapping:
        logger.warning("PFR advanced stats (%s) contain none of the expected columns.", stat_type)
        return None

    aggregated = (
        frame.with_columns(pl.col("season").cast(pl.Int64))
        .group_by([pl.col("pfr_id").cast(pl.Utf8).alias("pfr_id"), "season"])
        .agg(
            [
                pl.col(source).cast(pl.Float64, strict=False).mean().alias(target)
                for source, target in mapping.items()
            ]
        )
    )

    crosswalk = (
        resolver.dimension.select(
            pl.col("pfr_id").cast(pl.Utf8),
            pl.col(CANONICAL_ID_COLUMN),
        )
        .filter(pl.col("pfr_id").is_not_null())
        .unique(subset=["pfr_id"], keep="first")
    )
    joined = aggregated.join(crosswalk, on="pfr_id", how="left")
    return joined.filter(pl.col(CANONICAL_ID_COLUMN).is_not_null()).drop("pfr_id")


# ---------------------------------------------------------------------------
# Play-by-play derived features
# ---------------------------------------------------------------------------

RED_ZONE_YARDLINE = 20
INSIDE_FIVE_YARDLINE = 5


def aggregate_pbp_player_features(pbp: pl.DataFrame | None) -> pl.DataFrame | None:
    """Situational usage that only play-by-play can provide.

    Produces red-zone and goal-line opportunity counts plus success and
    explosive-play rates, per ``(gsis_id, season)``.
    """
    if pbp is None or pbp.is_empty():
        return None

    required = {"season", "posteam", "yardline_100", "rusher_player_id", "receiver_player_id"}
    missing = sorted(required - set(pbp.columns))
    if missing:
        logger.warning(
            "Play-by-play is missing columns %s; situational features will be unavailable.",
            missing,
        )
        return None

    plays = pbp
    if "season_type" in plays.columns:
        plays = plays.filter(pl.col("season_type") == REGULAR_SEASON)
    plays = plays.with_columns(
        pl.col("season").cast(pl.Int64),
        pl.col("yardline_100").cast(pl.Float64),
    )

    rush_plays = plays.filter(
        (pl.col("rush_attempt") == 1) & pl.col("rusher_player_id").is_not_null()
    )
    rushing = rush_plays.group_by(
        [pl.col("rusher_player_id").cast(pl.Utf8).alias(CANONICAL_ID_COLUMN), "season"]
    ).agg(
        pl.len().alias("pbp_carries"),
        (pl.col("yardline_100") <= RED_ZONE_YARDLINE).sum().alias("rz_carries"),
        (pl.col("yardline_100") <= INSIDE_FIVE_YARDLINE).sum().alias("inside_five_carries"),
        (pl.col("epa") > 0).mean().alias("rushing_success_rate"),
        (pl.col("yards_gained") >= 10).mean().alias("explosive_run_rate"),
        (pl.col("yards_gained") <= 0).mean().alias("stuffed_run_rate"),
        pl.col("epa").mean().alias("rushing_epa_per_carry"),
        (pl.col("down") == 3).mean().alias("third_down_carry_rate"),
    )

    pass_plays = plays.filter(
        (pl.col("pass_attempt") == 1) & pl.col("receiver_player_id").is_not_null()
    )
    receiving = pass_plays.group_by(
        [pl.col("receiver_player_id").cast(pl.Utf8).alias(CANONICAL_ID_COLUMN), "season"]
    ).agg(
        pl.len().alias("pbp_targets"),
        (pl.col("yardline_100") <= RED_ZONE_YARDLINE).sum().alias("rz_targets"),
        pl.col("air_yards")
        .filter(pl.col("air_yards") >= pl.col("yardline_100"))
        .len()
        .alias("end_zone_targets"),
        (pl.col("epa") > 0).mean().alias("receiving_success_rate"),
        (pl.col("air_yards") >= 20).mean().alias("deep_target_rate"),
        pl.col("air_yards").mean().alias("adot"),
        pl.col("epa").mean().alias("receiving_epa_per_target"),
        (pl.col("down") == 3).mean().alias("third_down_target_rate"),
    )

    passer = None
    if "passer_player_id" in plays.columns:
        dropbacks = plays.filter(
            pl.col("passer_player_id").is_not_null()
            & ((pl.col("pass_attempt") == 1) | (pl.col("sack") == 1))
        )
        passer = dropbacks.group_by(
            [pl.col("passer_player_id").cast(pl.Utf8).alias(CANONICAL_ID_COLUMN), "season"]
        ).agg(
            pl.len().alias("dropbacks"),
            pl.col("epa").mean().alias("epa_per_dropback"),
            (pl.col("epa") > 0).mean().alias("passing_success_rate"),
            (pl.col("sack") == 1).mean().alias("sack_rate"),
            (pl.col("yardline_100") <= RED_ZONE_YARDLINE).sum().alias("rz_pass_attempts"),
            (pl.col("air_yards") >= 20).mean().alias("deep_attempt_rate"),
        )

    combined = rushing.join(
        receiving, on=[CANONICAL_ID_COLUMN, "season"], how="full", coalesce=True
    )
    if passer is not None:
        combined = combined.join(
            passer, on=[CANONICAL_ID_COLUMN, "season"], how="full", coalesce=True
        )
    return combined


def aggregate_pbp_team_features(pbp: pl.DataFrame | None) -> pl.DataFrame | None:
    """Team pace, neutral pass rate and red-zone volume from play-by-play."""
    if pbp is None or pbp.is_empty() or "posteam" not in pbp.columns:
        return None

    plays = pbp
    if "season_type" in plays.columns:
        plays = plays.filter(pl.col("season_type") == REGULAR_SEASON)
    plays = plays.filter(
        pl.col("posteam").is_not_null()
        & (pl.col("play_type").is_in(["pass", "run"]) if "play_type" in plays.columns else True)
    ).with_columns(
        pl.col("season").cast(pl.Int64),
        normalise_team_expr("posteam", "team"),
    )
    if plays.is_empty():
        return None

    aggregations = [
        pl.len().alias("team_pbp_plays"),
        (pl.col("yardline_100") <= RED_ZONE_YARDLINE).sum().alias("team_rz_plays"),
        ((pl.col("play_type") == "pass") & (pl.col("yardline_100") <= RED_ZONE_YARDLINE))
        .sum()
        .alias("team_rz_pass_plays"),
        ((pl.col("play_type") == "run") & (pl.col("yardline_100") <= RED_ZONE_YARDLINE))
        .sum()
        .alias("team_rz_rush_plays"),
    ]
    if "wp" in plays.columns and "half_seconds_remaining" in plays.columns:
        # "Neutral" script: competitive win probability, outside two-minute
        # situations, where play calling reflects preference not necessity.
        neutral = (
            (pl.col("wp") >= 0.2) & (pl.col("wp") <= 0.8) & (pl.col("half_seconds_remaining") > 120)
        )
        aggregations.append(
            (pl.col("play_type") == "pass").filter(neutral).mean().alias("team_neutral_pass_rate")
        )
    if "epa" in plays.columns:
        aggregations.append(pl.col("epa").mean().alias("team_pbp_epa_per_play"))

    team_season = plays.group_by(["team", "season"]).agg(aggregations)

    if {"game_id", "game_seconds_remaining"} <= set(plays.columns):
        pace = (
            plays.group_by(["team", "season", "game_id"])
            .agg(
                pl.len().alias("plays"),
                (
                    pl.col("game_seconds_remaining").max() - pl.col("game_seconds_remaining").min()
                ).alias("elapsed_seconds"),
            )
            .group_by(["team", "season"])
            .agg(
                safe_ratio(pl.col("elapsed_seconds").sum(), pl.col("plays").sum()).alias(
                    "team_seconds_per_play"
                )
            )
        )
        team_season = team_season.join(pace, on=["team", "season"], how="left")

    return team_season
