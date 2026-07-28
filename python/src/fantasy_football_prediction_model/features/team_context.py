"""Team-context features.

A player's projection depends heavily on the offence around them: how many
plays it runs, how often it passes, how efficient it is, and how much
opportunity the players who left have vacated.

Two subtleties:

* **Which team's context?** For season ``t`` features predicting season
  ``t + 1``, the relevant environment is the team the player will play for.
  So the season-``t`` context of the player's *next* team is attached when the
  next team is known, and the season-``t`` context of their current team
  otherwise. Only season-``t`` statistics are ever used, never season-``t+1``
  outcomes.

* **Vacated opportunity.** Computed as the share of a team's season-``t``
  targets and carries that belonged to players who are not on that team at
  week 1 of season ``t + 1``. This is the single most direct measure of the
  opportunity actually available to the players who remain.
"""

from __future__ import annotations

import polars as pl

from fantasy_football_prediction_model.constants import CANONICAL_ID_COLUMN
from fantasy_football_prediction_model.data.aggregation import safe_ratio
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)

#: Team-context columns attached to each player-season.
TEAM_CONTEXT_COLUMNS: tuple[str, ...] = (
    "team_plays",
    "team_pass_attempts",
    "team_dropbacks",
    "team_rush_attempts",
    "team_targets",
    "team_pass_rate",
    "team_rush_rate",
    "team_plays_per_game",
    "team_points_per_game",
    "team_epa_per_play",
    "team_pass_epa_per_play",
    "team_rush_epa_per_play",
    "team_passing_tds",
    "team_rushing_tds",
    "team_offensive_tds",
    "team_neutral_pass_rate",
    "team_seconds_per_play",
    "team_rz_plays",
    "team_rz_pass_plays",
    "team_rz_rush_plays",
)


def build_team_context(team_seasons: pl.DataFrame, pbp_team: pl.DataFrame | None) -> pl.DataFrame:
    """Merge weekly-derived and play-by-play-derived team context."""
    context = team_seasons
    if pbp_team is not None and not pbp_team.is_empty():
        context = context.join(pbp_team, on=["team", "season"], how="left")
    else:
        logger.info(
            "No play-by-play team aggregates; pace, neutral pass rate and red-zone volume "
            "will be marked missing."
        )
        for column in (
            "team_neutral_pass_rate",
            "team_seconds_per_play",
            "team_rz_plays",
            "team_rz_pass_plays",
            "team_rz_rush_plays",
        ):
            if column not in context.columns:
                context = context.with_columns(pl.lit(None, dtype=pl.Float64).alias(column))

    for column in TEAM_CONTEXT_COLUMNS:
        if column not in context.columns:
            context = context.with_columns(pl.lit(None, dtype=pl.Float64).alias(column))

    return context.with_columns(
        [pl.col(column).cast(pl.Float64, strict=False) for column in TEAM_CONTEXT_COLUMNS]
    )


def attach_team_context(frame: pl.DataFrame, team_context: pl.DataFrame) -> pl.DataFrame:
    """Attach the projected team's season-``t`` context to each player-season.

    ``projected_team`` is the week-1 team for season ``t + 1`` when known, and
    the season-``t`` team otherwise.
    """
    frame = frame.with_columns(
        pl.coalesce([pl.col("next_team"), pl.col("team")]).alias("projected_team")
    )

    # Phase 1 already attached the player's own-team context for the share
    # denominators. Drop any overlap so the projected-team values replace them
    # cleanly instead of arriving as suffixed duplicates.
    attachable = [column for column in TEAM_CONTEXT_COLUMNS if column in team_context.columns]
    frame = frame.drop([column for column in attachable if column in frame.columns])

    context = team_context.select(
        pl.col("team").alias("projected_team"),
        pl.col("season"),
        *[pl.col(column) for column in attachable],
    )
    return frame.join(context, on=["projected_team", "season"], how="left")


def add_vacated_opportunity(frame: pl.DataFrame, team_context: pl.DataFrame) -> pl.DataFrame:
    """Compute vacated and returning target/carry share for each team-season.

    For team ``T`` in season ``t``: the share of ``T``'s season-``t`` targets
    and carries produced by players who are *not* on ``T`` at week 1 of season
    ``t + 1``. Everything in the calculation is a season-``t`` statistic; only
    the roster membership comes from the preseason of ``t + 1``.

    Players whose next team is unknown are excluded from both the vacated and
    the returning pool, and the resulting coverage is reported, so an
    incomplete roster refresh cannot masquerade as mass departures.
    """
    required = {"team", "season", "targets", "carries", "next_team", "next_team_known"}
    missing = sorted(required - set(frame.columns))
    if missing:
        logger.warning("Cannot compute vacated opportunity; missing %s.", missing)
        return frame.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("vacated_targets_share"),
            pl.lit(None, dtype=pl.Float64).alias("vacated_carries_share"),
            pl.lit(None, dtype=pl.Float64).alias("returning_target_competition"),
            pl.lit(None, dtype=pl.Float64).alias("returning_carry_competition"),
        )

    known = frame.filter(pl.col("next_team_known") == 1)
    if known.is_empty():
        logger.warning("No known week-1 team assignments; vacated opportunity is unavailable.")
        return frame.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("vacated_targets_share"),
            pl.lit(None, dtype=pl.Float64).alias("vacated_carries_share"),
            pl.lit(None, dtype=pl.Float64).alias("returning_target_competition"),
            pl.lit(None, dtype=pl.Float64).alias("returning_carry_competition"),
        )

    departed = pl.col("next_team") != pl.col("team")
    per_team = known.group_by(["team", "season"]).agg(
        pl.col("targets").fill_null(0).sum().alias("_known_targets"),
        pl.col("carries").fill_null(0).sum().alias("_known_carries"),
        pl.col("targets").fill_null(0).filter(departed).sum().alias("_departed_targets"),
        pl.col("carries").fill_null(0).filter(departed).sum().alias("_departed_carries"),
        pl.len().alias("_known_players"),
    )

    per_team = per_team.with_columns(
        safe_ratio(pl.col("_departed_targets"), pl.col("_known_targets")).alias(
            "vacated_targets_share"
        ),
        safe_ratio(pl.col("_departed_carries"), pl.col("_known_carries")).alias(
            "vacated_carries_share"
        ),
    )

    # Competition is the opportunity that stayed: the complement of vacated.
    per_team = per_team.with_columns(
        (1.0 - pl.col("vacated_targets_share")).alias("returning_target_competition"),
        (1.0 - pl.col("vacated_carries_share")).alias("returning_carry_competition"),
    )

    coverage = known.height / frame.height if frame.height else 0.0
    logger.info(
        "Vacated-opportunity coverage: %.1f%% of player-seasons have a known week-1 "
        "team for the following season.",
        100 * coverage,
    )

    # The shares describe the team a player is *joining*, so they join on
    # projected_team rather than the season-t team.
    vacancy = per_team.select(
        pl.col("team").alias("projected_team"),
        pl.col("season"),
        "vacated_targets_share",
        "vacated_carries_share",
        "returning_target_competition",
        "returning_carry_competition",
    )
    return frame.join(vacancy, on=["projected_team", "season"], how="left")


def add_quarterback_context(frame: pl.DataFrame, team_context: pl.DataFrame) -> pl.DataFrame:
    """Quarterback quality and expected quarterback change for each offence.

    ``qb_quality_prior`` is the season-``t`` EPA per dropback of the team's
    highest-volume quarterback. ``qb_change_expected`` fires when that
    quarterback is not on the team at week 1 of season ``t + 1``: a genuine
    preseason fact, and one of the largest swing factors for pass catchers.
    """
    quarterbacks = frame.filter(
        (pl.col("position") == "QB") & (pl.col("pass_attempts").fill_null(0) > 0)
    )
    if quarterbacks.is_empty():
        return frame.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("qb_quality_prior"),
            pl.lit(None, dtype=pl.Int8).alias("qb_change_expected"),
        )

    epa_column = "epa_per_dropback" if "epa_per_dropback" in quarterbacks.columns else "passing_epa"
    primary = (
        quarterbacks.sort("pass_attempts", descending=True, nulls_last=True)
        .group_by(["team", "season"])
        .agg(
            pl.col(epa_column).first().alias("qb_quality_prior"),
            pl.col("next_team").first().alias("_qb_next_team"),
            pl.col("next_team_known").first().alias("_qb_next_known"),
            pl.col(CANONICAL_ID_COLUMN).first().alias("_primary_qb_id"),
        )
    )
    primary = primary.with_columns(
        pl.when(pl.col("_qb_next_known") == 1)
        .then((pl.col("_qb_next_team") != pl.col("team")).cast(pl.Int8))
        .otherwise(None)
        .alias("qb_change_expected")
    ).select(
        pl.col("team").alias("projected_team"),
        "season",
        "qb_quality_prior",
        "qb_change_expected",
        pl.col("_primary_qb_id").alias("primary_qb_id"),
    )

    return frame.join(primary, on=["projected_team", "season"], how="left")
