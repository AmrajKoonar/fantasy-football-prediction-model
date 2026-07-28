"""Builds the player-season modelling table.

Two phases, deliberately separated so the leakage boundary is a property of
the code structure rather than a convention:

**Phase 1 - season-t features.** Everything that describes what a player did
through the end of season ``t``: box-score totals, per-game and
per-opportunity rates, own-team context, snaps, advanced statistics, lags and
trends. Phase 1 cannot see any season after ``t``, because it is never given
one.

**Phase 2 - modelling pairs.** For each outcome season ``S``, take each
player's most recent observed season ``t < S`` and attach the only
season-``S`` information permitted: their week-1 team. That drives the
team-change flag, decides whose team context applies, and produces vacated
opportunity and competition. The outcome is then joined from season ``S``.

Building pairs this way, rather than requiring ``t = S - 1``, has an important
consequence: a player who missed an entire season still gets a row, carrying
``seasons_since_last_played >= 1``. The projection is constructed identically,
so training and serving cannot drift apart.

Survivorship bias is addressed by the candidate rule in
:func:`candidate_players_for_season`: a player is a candidate for season ``S``
if they played at any point in the previous ``lookback`` seasons, regardless
of whether they played in ``S``. Players who left the league contribute a
genuine zero outcome instead of vanishing from the training set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import polars as pl

from fantasy_football_prediction_model.config import Settings
from fantasy_football_prediction_model.constants import (
    ANOMALOUS_SEASONS,
    CANONICAL_ID_COLUMN,
    FANTASY_POSITIONS,
)
from fantasy_football_prediction_model.data.aggregation import safe_ratio
from fantasy_football_prediction_model.data.ingestion import IngestedData
from fantasy_football_prediction_model.features.availability import (
    add_availability_features,
    add_depth_chart_features,
    add_next_season_context,
    add_roster_status_features,
)
from fantasy_football_prediction_model.features.quarterback import add_quarterback_features
from fantasy_football_prediction_model.features.receiver import (
    add_target_competition,
)
from fantasy_football_prediction_model.features.running_back import (
    add_backfield_competition,
    add_running_back_features,
)
from fantasy_football_prediction_model.features.team_context import (
    add_quarterback_context,
    add_vacated_opportunity,
    attach_team_context,
    build_team_context,
)
from fantasy_football_prediction_model.features.tight_end import add_tight_end_features
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)

#: A player is a candidate for outcome season S if they recorded a season
#: within this many seasons before S. Three seasons is long enough to capture
#: a player returning from a lost year, short enough to exclude the retired.
DEFAULT_LOOKBACK_SEASONS = 3

#: Outcome columns, i.e. what the models predict. Prefixed in the pair table.
OUTCOME_STATS: tuple[str, ...] = (
    "games",
    "pass_attempts",
    "completions",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "fumbles_lost",
    "fantasy_points_ppr",
)

#: The 1 September of a season is used as the age reference date. Using a
#: fixed in-season date rather than 1 January keeps ages comparable across
#: players born either side of the new year.
AGE_REFERENCE_MONTH = 9
AGE_REFERENCE_DAY = 1

#: Exponential weights for multi-season averages, most recent first.
_TWO_YEAR_WEIGHTS = (0.65, 0.35)
_THREE_YEAR_WEIGHTS = (0.55, 0.30, 0.15)


@dataclass(slots=True)
class FeatureBuildResult:
    """Output of the feature build."""

    #: One row per (player, season) describing season ``t`` only.
    season_features: pl.DataFrame
    #: One row per (player, outcome season) with features and outcomes.
    pairs: pl.DataFrame
    #: Rows for the projected season; outcomes are unknown and left null.
    projection_rows: pl.DataFrame
    #: Feature columns actually present after the build.
    feature_columns: list[str] = field(default_factory=list)
    #: Coverage of each feature column, for the research report.
    coverage: dict[str, float] = field(default_factory=dict)

    def training_pairs(self, max_outcome_season: int) -> pl.DataFrame:
        """Pairs whose outcome season is at or before a cutoff."""
        return self.pairs.filter(pl.col("target_season") <= max_outcome_season)


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------


def build_season_features(data: IngestedData) -> pl.DataFrame:
    """Build the season-``t`` feature table.

    Contains only information observable by the end of each season.
    """
    frame = data.player_seasons.filter(pl.col("position").is_in(list(FANTASY_POSITIONS)))
    logger.info(
        "Building season features for %d player-seasons at modelled positions.", frame.height
    )

    frame = _attach_player_dimension(frame, data)
    frame = _attach_optional_sources(frame, data)

    team_context = build_team_context(data.team_seasons, data.pbp_team)
    frame = _attach_own_team_context(frame, team_context)

    frame = add_availability_features(frame, data.games_per_season)
    frame = add_roster_status_features(frame, data.rosters)
    frame = add_depth_chart_features(frame, data.depth_seasons)

    frame = _add_shared_rates(frame)
    frame = add_quarterback_features(frame)
    frame = add_running_back_features(frame)
    frame = add_tight_end_features(frame)  # includes the receiver feature set

    frame = _add_lag_and_trend_features(frame)
    frame = _add_era_flags(frame)

    return frame.sort([CANONICAL_ID_COLUMN, "season"])


def _attach_player_dimension(frame: pl.DataFrame, data: IngestedData) -> pl.DataFrame:
    """Join biography and draft capital from the canonical player dimension."""
    dimension = data.resolver.dimension.select(
        CANONICAL_ID_COLUMN,
        pl.col("display_name"),
        pl.col("short_name"),
        pl.col("slug"),
        pl.col("birth_date"),
        pl.col("height").cast(pl.Float64),
        pl.col("weight").cast(pl.Float64),
        pl.col("draft_year").cast(pl.Float64),
        pl.col("draft_round").cast(pl.Float64),
        pl.col("draft_pick").cast(pl.Float64),
        pl.col("draft_team"),
        pl.col("rookie_year").cast(pl.Float64),
        pl.col("headshot_url"),
        pl.col("college"),
        pl.col("pfr_id"),
    )
    joined = frame.join(dimension, on=CANONICAL_ID_COLUMN, how="left")

    # Rosters carry experience and, for some players, a birth date the player
    # dimension lacks.
    roster_bio = data.rosters.select(
        CANONICAL_ID_COLUMN,
        "season",
        pl.col("years_exp").alias("roster_years_exp"),
        pl.col("birth_date").alias("roster_birth_date"),
        pl.col("height").alias("roster_height"),
        pl.col("weight").alias("roster_weight"),
        pl.col("entry_year").alias("roster_entry_year"),
    ).unique(subset=[CANONICAL_ID_COLUMN, "season"], keep="last")
    joined = joined.join(roster_bio, on=[CANONICAL_ID_COLUMN, "season"], how="left")

    joined = joined.with_columns(
        pl.coalesce([pl.col("birth_date"), pl.col("roster_birth_date")]).alias("birth_date"),
        pl.coalesce([pl.col("height"), pl.col("roster_height")]).alias("height"),
        pl.coalesce([pl.col("weight"), pl.col("roster_weight")]).alias("weight"),
        pl.coalesce(
            [pl.col("rookie_year"), pl.col("roster_entry_year"), pl.col("draft_year")]
        ).alias("entry_season"),
    ).drop(["roster_birth_date", "roster_height", "roster_weight", "roster_entry_year"])

    return joined.with_columns(
        # Experience in season t. Prefer the derived value over the roster's,
        # which is inconsistent about whether it counts the current season.
        (pl.col("season") - pl.col("entry_season")).clip(0, None).alias("experience"),
        safe_ratio(
            pl.col("weight") * 703.0, pl.col("height") * pl.col("height"), min_denominator=1
        ).alias("bmi"),
        pl.col("draft_pick").is_null().cast(pl.Int8).alias("is_undrafted"),
        # Draft capital falls off sharply with pick number, so the log of the
        # pick is a far better linear predictor than the pick itself.
        pl.when(pl.col("draft_pick").is_not_null() & (pl.col("draft_pick") > 0))
        .then((263.0 - pl.col("draft_pick")).log1p())
        .otherwise(0.0)
        .alias("draft_capital_log"),
    )


def _attach_optional_sources(frame: pl.DataFrame, data: IngestedData) -> pl.DataFrame:
    """Join snaps, Next Gen Stats, PFR advanced and play-by-play aggregates."""
    for label, source in (
        ("snap counts", data.snap_seasons),
        ("Next Gen passing", data.ngs_passing),
        ("Next Gen rushing", data.ngs_rushing),
        ("Next Gen receiving", data.ngs_receiving),
        ("PFR passing", data.pfr_pass),
        ("PFR rushing", data.pfr_rush),
        ("PFR receiving", data.pfr_rec),
        ("play-by-play", data.pbp_player),
    ):
        if source is None or source.is_empty():
            logger.info("%s is unavailable; its features will be marked missing.", label)
            continue
        overlap = (set(source.columns) & set(frame.columns)) - {CANONICAL_ID_COLUMN, "season"}
        payload = source.drop(overlap) if overlap else source
        frame = frame.join(payload, on=[CANONICAL_ID_COLUMN, "season"], how="left")
    return frame


def _attach_own_team_context(frame: pl.DataFrame, team_context: pl.DataFrame) -> pl.DataFrame:
    """Attach the season-``t`` context of the team the player actually played for."""
    own = team_context.select(
        pl.col("team"),
        pl.col("season"),
        *[
            pl.col(column).alias(f"own_{column}")
            for column in (
                "team_pass_attempts",
                "team_rush_attempts",
                "team_targets",
                "team_plays",
                "team_dropbacks",
            )
            if column in team_context.columns
        ],
        *[
            pl.col(column)
            for column in ("team_pass_rate", "team_rz_rush_plays", "team_rz_pass_plays")
            if column in team_context.columns
        ],
    )
    return frame.join(own, on=["team", "season"], how="left")


def _add_shared_rates(frame: pl.DataFrame) -> pl.DataFrame:
    """Rates every position shares."""
    games = pl.col("games").cast(pl.Float64)
    return frame.with_columns(
        safe_ratio(pl.col("fantasy_points_ppr").cast(pl.Float64), games).alias(
            "fantasy_points_ppr_per_game"
        ),
        safe_ratio(pl.col("fumbles_lost").cast(pl.Float64), games).alias("fumbles_lost_per_game"),
        safe_ratio(pl.col("rushing_yards").cast(pl.Float64), games).alias("rushing_yards_per_game"),
    )


def _weighted_lag(column: str, weights: tuple[float, ...]) -> pl.Expr:
    """Weighted average of the current and preceding seasons for one player.

    Seasons the player did not record are skipped and the weights renormalise,
    so a two-season veteran is not penalised for having no third season.
    """
    shifted = [
        pl.col(column).shift(index).over(CANONICAL_ID_COLUMN) for index in range(len(weights))
    ]
    numerator = pl.sum_horizontal(
        [
            pl.when(expr.is_not_null()).then(expr * weight).otherwise(0.0)
            for expr, weight in zip(shifted, weights, strict=True)
        ]
    )
    denominator = pl.sum_horizontal(
        [
            pl.when(expr.is_not_null()).then(weight).otherwise(0.0)
            for expr, weight in zip(shifted, weights, strict=True)
        ]
    )
    return pl.when(denominator > 0).then(numerator / denominator).otherwise(None)


def _add_lag_and_trend_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Multi-season averages, trends and career aggregates.

    Every expression here is a backward-looking window over a player's own
    history, ordered by season, so no value can come from the future.
    """
    frame = frame.sort([CANONICAL_ID_COLUMN, "season"])

    trend_columns = {
        "fantasy_points_ppr_per_game": "fantasy_points_ppr_trend",
        "targets_per_game": "target_trend",
        "carries_per_game": "carry_trend",
        "snap_share": "snap_share_trend",
    }

    expressions: list[pl.Expr] = [
        _weighted_lag("fantasy_points_ppr", _TWO_YEAR_WEIGHTS).alias("fantasy_points_ppr_w2"),
        _weighted_lag("fantasy_points_ppr", _THREE_YEAR_WEIGHTS).alias("fantasy_points_ppr_w3"),
        _weighted_lag("fantasy_points_ppr_per_game", _TWO_YEAR_WEIGHTS).alias(
            "fantasy_points_ppr_per_game_w2"
        ),
        _weighted_lag("fantasy_points_ppr_per_game", _THREE_YEAR_WEIGHTS).alias(
            "fantasy_points_ppr_per_game_w3"
        ),
        # Career aggregates use cumulative windows over prior seasons plus the
        # current one, which is known at the end of season t.
        pl.col("fantasy_points_ppr")
        .cum_sum()
        .over(CANONICAL_ID_COLUMN)
        .alias("career_fantasy_points"),
        pl.col("games").cum_sum().over(CANONICAL_ID_COLUMN).alias("career_games"),
        pl.col("fantasy_points_ppr")
        .cum_max()
        .over(CANONICAL_ID_COLUMN)
        .alias("best_season_fantasy_points"),
        pl.col("season")
        .cum_count()
        .over(CANONICAL_ID_COLUMN)
        .cast(pl.Int64)
        .alias("seasons_observed"),
    ]

    for source, target in trend_columns.items():
        if source in frame.columns:
            expressions.append(
                (pl.col(source) - pl.col(source).shift(1).over(CANONICAL_ID_COLUMN)).alias(target)
            )

    for column in ("targets", "carries", "pass_attempts", "receptions"):
        if column in frame.columns:
            expressions.append(
                pl.col(column).cum_sum().over(CANONICAL_ID_COLUMN).alias(f"career_{column}")
            )

    # Prior-season values, used by the baseline models and by the explanation
    # templates that compare a projection with last year.
    for column in ("fantasy_points_ppr", "targets", "carries", "receptions", "games"):
        if column in frame.columns:
            expressions.append(
                pl.col(column).shift(1).over(CANONICAL_ID_COLUMN).alias(f"prev_{column}")
            )

    frame = frame.with_columns(expressions)

    frame = frame.with_columns(
        safe_ratio(pl.col("career_fantasy_points"), pl.col("career_games")).alias(
            "career_fantasy_points_per_game"
        ),
    )

    # Opportunity trend blends the position-relevant usage trends into one
    # column so every position model has a comparable signal.
    trend_parts = [
        pl.col(name)
        for name in ("target_trend", "carry_trend", "snap_share_trend")
        if name in frame.columns
    ]
    if trend_parts:
        frame = frame.with_columns(pl.mean_horizontal(trend_parts).alias("opportunity_trend"))
    else:
        frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("opportunity_trend"))

    return frame


def _add_era_flags(frame: pl.DataFrame) -> pl.DataFrame:
    """Flag structurally unusual seasons rather than dropping them."""
    return frame.with_columns(
        pl.col("season").is_in(list(ANOMALOUS_SEASONS)).cast(pl.Int8).alias("anomalous_season"),
        (pl.col("season") >= 2021).cast(pl.Int8).alias("seventeen_game_era"),
    )


# ---------------------------------------------------------------------------
# Phase 2
# ---------------------------------------------------------------------------


def candidate_players_for_season(
    season_features: pl.DataFrame, outcome_season: int, *, lookback: int = DEFAULT_LOOKBACK_SEASONS
) -> pl.DataFrame:
    """Rows eligible to predict ``outcome_season``, one per player.

    A player qualifies if they recorded a season in
    ``[outcome_season - lookback, outcome_season - 1]``. Their most recent such
    season supplies the features.

    The rule uses no information from ``outcome_season``, which is what makes
    it safe, and it deliberately keeps players who went on to record nothing,
    which is what makes it free of survivorship bias.
    """
    window = season_features.filter(
        (pl.col("season") < outcome_season) & (pl.col("season") >= outcome_season - lookback)
    )
    if window.is_empty():
        return window
    latest = (
        window.sort("season")
        .group_by(CANONICAL_ID_COLUMN)
        .last()
        .with_columns(
            pl.lit(outcome_season, dtype=pl.Int64).alias("target_season"),
        )
    )
    return latest.with_columns(
        (pl.col("target_season") - pl.col("season") - 1)
        .cast(pl.Int64)
        .alias("seasons_since_last_played")
    )


def build_modelling_pairs(
    data: IngestedData,
    season_features: pl.DataFrame,
    outcome_seasons: list[int],
    *,
    lookback: int = DEFAULT_LOOKBACK_SEASONS,
    attach_outcomes: bool = True,
) -> pl.DataFrame:
    """Assemble feature/outcome pairs for a list of outcome seasons."""
    team_context = build_team_context(data.team_seasons, data.pbp_team)
    outcomes = _build_outcome_table(data.player_seasons) if attach_outcomes else None

    built: list[pl.DataFrame] = []
    for outcome_season in outcome_seasons:
        candidates = candidate_players_for_season(
            season_features, outcome_season, lookback=lookback
        )
        if candidates.is_empty():
            logger.warning("No candidate players for outcome season %d.", outcome_season)
            continue

        enriched = add_next_season_context(
            candidates, _week1_for_season(data.week1_teams, outcome_season)
        )
        enriched = attach_team_context(enriched, team_context)
        enriched = add_vacated_opportunity(enriched, team_context)
        enriched = add_quarterback_context(enriched, team_context)
        enriched = add_backfield_competition(enriched)
        enriched = add_target_competition(enriched)
        enriched = _add_age_features(enriched)

        if outcomes is not None:
            enriched = _attach_outcomes(enriched, outcomes, outcome_season)

        built.append(enriched)

    if not built:
        raise ValueError(
            f"No modelling pairs could be built for outcome seasons {outcome_seasons}."
        )

    pairs = pl.concat(built, how="diagonal_relaxed")
    logger.info(
        "Built %d modelling pairs across outcome seasons %d-%d.",
        pairs.height,
        min(outcome_seasons),
        max(outcome_seasons),
    )
    return pairs


def _week1_for_season(week1_teams: pl.DataFrame | None, outcome_season: int) -> pl.DataFrame | None:
    """Week-1 assignments for one outcome season, shaped for the join.

    :func:`add_next_season_context` expects rows keyed by the *feature*
    season, so the outcome season is shifted back by one before the join. For
    gap rows the feature season is older, so the shift is applied per row
    afterwards instead; here the frame is simply filtered.
    """
    if week1_teams is None or week1_teams.is_empty():
        return None
    return week1_teams.filter(pl.col("season") == outcome_season)


def _add_age_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Age at the start of the outcome season, plus a non-linear term.

    The relationship between age and production is not linear for any
    position, so a squared term is provided and the tree models are free to
    find the shape themselves.
    """
    reference = pl.date(pl.col("target_season"), AGE_REFERENCE_MONTH, AGE_REFERENCE_DAY)
    frame = frame.with_columns(
        pl.when(pl.col("birth_date").is_not_null())
        .then((reference - pl.col("birth_date")).dt.total_days() / 365.25)
        .otherwise(None)
        .alias("age_at_target_season")
    )
    frame = frame.with_columns(
        (pl.col("age_at_target_season") ** 2).alias("age_squared"),
        (pl.col("target_season") - pl.col("entry_season"))
        .clip(0, None)
        .alias("experience_at_target_season"),
    )
    return frame.with_columns(
        (pl.col("experience_at_target_season") == 0).cast(pl.Int8).alias("is_rookie_season")
    )


def _build_outcome_table(player_seasons: pl.DataFrame) -> pl.DataFrame:
    """Observed outcomes, one row per ``(player, season)``."""
    available = [column for column in OUTCOME_STATS if column in player_seasons.columns]
    return player_seasons.select(
        CANONICAL_ID_COLUMN,
        pl.col("season").alias("target_season"),
        pl.col("team").alias("outcome_team"),
        pl.col("position").alias("outcome_position"),
        *[pl.col(column).cast(pl.Float64).alias(f"outcome_{column}") for column in available],
    )


def _attach_outcomes(
    frame: pl.DataFrame, outcomes: pl.DataFrame, outcome_season: int
) -> pl.DataFrame:
    """Join observed outcomes, treating an absent season as a genuine zero.

    A candidate with no outcome row did not record a statistic that season.
    That is a real result, not missing data: they were injured, buried on a
    depth chart, or out of the league. Recording it as zero is what stops the
    model from learning only from players who stayed productive.
    """
    season_outcomes = outcomes.filter(pl.col("target_season") == outcome_season)
    joined = frame.join(season_outcomes, on=[CANONICAL_ID_COLUMN, "target_season"], how="left")

    outcome_columns = [column for column in joined.columns if column.startswith("outcome_")]
    numeric = [column for column in outcome_columns if joined.schema[column].is_numeric()]

    joined = joined.with_columns(
        pl.col("outcome_games").is_not_null().cast(pl.Int8).alias("target_played")
    )
    joined = joined.with_columns([pl.col(column).fill_null(0.0) for column in numeric])

    played = int(joined.get_column("target_played").sum())
    logger.debug(
        "Outcome season %d: %d of %d candidates recorded a statistic (%.1f%%); the rest "
        "carry a true zero outcome.",
        outcome_season,
        played,
        joined.height,
        100 * played / max(joined.height, 1),
    )
    return joined


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_feature_table(
    data: IngestedData,
    settings: Settings,
    *,
    lookback: int = DEFAULT_LOOKBACK_SEASONS,
) -> FeatureBuildResult:
    """Build season features, training pairs and projection rows.

    Args:
        data: Ingested and validated season tables.
        settings: Validated configuration.
        lookback: How many seasons back a candidate may have last played.

    Returns:
        The season feature table, the training pairs and the rows to project.
    """
    season_features = build_season_features(data)

    # Outcome seasons that can be supervised: everything after the first
    # season with data, up to and including the last observed season.
    training_seasons = list(range(settings.data_start_season + 1, settings.feature_end_season + 1))
    pairs = build_modelling_pairs(
        data, season_features, training_seasons, lookback=lookback, attach_outcomes=True
    )

    projection_rows = build_modelling_pairs(
        data,
        season_features,
        [settings.target_season],
        lookback=lookback,
        attach_outcomes=False,
    )

    feature_columns = _resolve_feature_columns(pairs, settings)
    coverage = _feature_coverage(pairs, feature_columns)

    logger.info(
        "Feature table complete: %d training pairs, %d projection rows, %d candidate "
        "feature columns.",
        pairs.height,
        projection_rows.height,
        len(feature_columns),
    )
    return FeatureBuildResult(
        season_features=season_features,
        pairs=pairs,
        projection_rows=projection_rows,
        feature_columns=feature_columns,
        coverage=coverage,
    )


def _resolve_feature_columns(pairs: pl.DataFrame, settings: Settings) -> list[str]:
    """Configured candidate features that the build actually produced.

    Configured-but-absent features are logged once so a typo in
    ``configs/features.yml`` is visible rather than silently ignored.
    """
    configured: list[str] = []
    for position in settings.positions:
        configured.extend(settings.features.candidate_features(position))
        configured.extend(settings.features.candidate_features(position, rookie=True))

    present: list[str] = []
    absent: list[str] = []
    seen: set[str] = set()
    for name in configured:
        if name in seen:
            continue
        seen.add(name)
        if name in pairs.columns and pairs.schema[name].is_numeric():
            present.append(name)
        else:
            absent.append(name)

    if absent:
        logger.info(
            "%d configured candidate feature(s) are not produced by the current data and "
            "will be skipped: %s%s",
            len(absent),
            ", ".join(absent[:15]),
            " ..." if len(absent) > 15 else "",
        )
    return present


def _feature_coverage(pairs: pl.DataFrame, feature_columns: list[str]) -> dict[str, float]:
    """Fraction of rows where each feature is present."""
    if pairs.is_empty() or not feature_columns:
        return {}
    counts = pairs.select(
        [pl.col(column).is_not_null().mean().alias(column) for column in feature_columns]
    ).row(0, named=True)
    return {name: float(value or 0.0) for name, value in counts.items()}


def reference_date_for_season(season: int) -> date:
    """The 1 September reference date used for age calculations."""
    return date(season, AGE_REFERENCE_MONTH, AGE_REFERENCE_DAY)
