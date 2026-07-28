"""The export contract.

These Pydantic models are the single source of truth for every JSON file the
Python pipeline writes into ``web/public/data/``. The TypeScript side mirrors
them with Zod schemas in ``web/src/lib/schemas.ts``, and a regression test
asserts the two stay in step by validating the same fixture with both.

Field names are camelCase to match the frontend, mapped from snake_case
Python attributes by ``alias_generator``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from fantasy_football_prediction_model.constants import (
    CONFIDENCE_LABELS,
    DATA_MODE_FIXTURE,
    DATA_MODE_PRODUCTION,
    FANTASY_POSITIONS,
)

DataMode = Literal["production", "fixture"]
ConfidenceLabel = Literal["low", "medium", "high"]
Position = Literal["QB", "RB", "WR", "TE"]

NonNegative = Annotated[float, Field(ge=0)]


class ExportModel(BaseModel):
    """Base for every exported object: camelCase aliases, strict extras."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        ser_json_timedelta="iso8601",
    )


# ---------------------------------------------------------------------------
# Player projection
# ---------------------------------------------------------------------------


class ProjectedStats(ExportModel):
    """Projected season totals. Positional statistics are ``None`` when the
    position does not produce them (a receiver has no ``passAttempts``)."""

    games: NonNegative
    pass_attempts: NonNegative | None = None
    completions: NonNegative | None = None
    passing_yards: float | None = None
    passing_touchdowns: NonNegative | None = None
    interceptions: NonNegative | None = None
    carries: NonNegative | None = None
    rushing_yards: float | None = None
    rushing_touchdowns: NonNegative | None = None
    targets: NonNegative | None = None
    receptions: NonNegative | None = None
    receiving_yards: float | None = None
    receiving_touchdowns: NonNegative | None = None
    fumbles_lost: NonNegative | None = None

    @model_validator(mode="after")
    def _check_ratio_consistency(self) -> ProjectedStats:
        # A tiny tolerance absorbs float noise from the constraint solver.
        tolerance = 1e-6
        if (
            self.completions is not None
            and self.pass_attempts is not None
            and self.completions > self.pass_attempts + tolerance
        ):
            raise ValueError(
                f"completions ({self.completions}) exceeds passAttempts ({self.pass_attempts})."
            )
        if (
            self.receptions is not None
            and self.targets is not None
            and self.receptions > self.targets + tolerance
        ):
            raise ValueError(f"receptions ({self.receptions}) exceeds targets ({self.targets}).")
        return self


class FantasySummary(ExportModel):
    """Fantasy value under the project's default full-PPR settings.

    The frontend recomputes all of this client-side whenever the user changes
    scoring or league settings; these are the published defaults.
    """

    default_ppr_points: float
    points_per_game: float
    replacement_value: float
    overall_rank: int = Field(ge=1)
    position_rank: int = Field(ge=1)
    tier: int = Field(ge=1)
    points_rank: int = Field(ge=1)
    points_per_game_rank: int = Field(ge=1)
    vorp_rank: int = Field(ge=1)
    risk_adjusted_rank: int = Field(ge=1)
    risk_adjusted_value: float


class ProjectionRange(ExportModel):
    """Calibrated prediction interval in fantasy points."""

    low_ppr_points: float
    median_ppr_points: float
    high_ppr_points: float
    low_quantile: float = Field(gt=0, lt=1)
    high_quantile: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def _check_ordering(self) -> ProjectionRange:
        if not (self.low_ppr_points <= self.median_ppr_points <= self.high_ppr_points):
            raise ValueError(
                f"Projection range is not monotonic: low={self.low_ppr_points}, "
                f"median={self.median_ppr_points}, high={self.high_ppr_points}."
            )
        if self.low_quantile >= self.high_quantile:
            raise ValueError("lowQuantile must be below highQuantile.")
        return self


class ConfidenceBlock(ExportModel):
    """How much the model trusts its own projection.

    Confidence is independent of projected quality: a top-five player can
    carry medium confidence when their role or supporting cast changed.
    """

    score: float = Field(ge=0, le=1)
    label: ConfidenceLabel
    reasons: list[str] = Field(default_factory=list)


class ExplanationFactor(ExportModel):
    """One deterministic, template-generated driver of a projection."""

    feature: str
    label: str
    value: float | None = None
    display_value: str | None = None
    percentile: float | None = Field(default=None, ge=0, le=1)
    contribution: float
    direction: Literal["positive", "negative"]
    description: str


class ExplanationBlock(ExportModel):
    positive_factors: list[ExplanationFactor] = Field(default_factory=list)
    negative_factors: list[ExplanationFactor] = Field(default_factory=list)
    summary: str = ""
    optimistic_note: str = ""
    cautious_note: str = ""
    method: Literal["shap", "permutation", "unavailable"] = "unavailable"
    comparable_seasons: list[ComparableSeason] = Field(default_factory=list)


class ComparableSeason(ExportModel):
    """A historical player-season with a similar feature profile.

    Similarity is nearest-neighbour distance in the standardised feature
    space, not a subjective analyst comparison.
    """

    player_name: str
    season: int
    position: Position
    similarity: float = Field(ge=0, le=1)
    next_season_ppr_points: float | None = None


class HistoricalSeason(ExportModel):
    """One observed prior season, shown on the player page trend charts."""

    season: int
    team: str
    games: NonNegative
    ppr_points: float
    ppr_points_per_game: float
    pass_attempts: float | None = None
    passing_yards: float | None = None
    passing_touchdowns: float | None = None
    interceptions: float | None = None
    carries: float | None = None
    rushing_yards: float | None = None
    rushing_touchdowns: float | None = None
    targets: float | None = None
    receptions: float | None = None
    receiving_yards: float | None = None
    receiving_touchdowns: float | None = None
    snap_share: float | None = None
    target_share: float | None = None


class DraftInfo(ExportModel):
    year: int | None = None
    round: int | None = None
    pick: int | None = None
    team: str | None = None
    undrafted: bool = False


class PlayerWarning(ExportModel):
    """A machine-readable caveat surfaced next to the projection."""

    code: str
    severity: Literal["info", "warning"]
    message: str


class AdjustmentRecord(ExportModel):
    """Audit trail for an applied manual projection override."""

    field: str
    model_value: float
    adjusted_value: float
    reason: str
    source_note: str | None = None
    date_entered: str | None = None


class PlayerProjection(ExportModel):
    """One published player projection."""

    player_id: str
    slug: str
    name: str
    short_name: str
    team: str
    position: Position
    age: float | None = None
    experience: int | None = Field(default=None, ge=0)
    rookie: bool = False
    headshot_url: str | None = None
    draft: DraftInfo = Field(default_factory=DraftInfo)

    projection_season: int
    source_season: int
    model_version: str
    model_architecture: Literal["direct", "component", "rookie"] = "direct"
    rookie_mode: Literal["full", "reduced", "not_applicable"] = "not_applicable"

    projected_stats: ProjectedStats
    fantasy: FantasySummary
    range: ProjectionRange
    confidence: ConfidenceBlock
    explanation: ExplanationBlock = Field(default_factory=ExplanationBlock)
    history: list[HistoricalSeason] = Field(default_factory=list)
    warnings: list[PlayerWarning] = Field(default_factory=list)

    is_adjusted: bool = False
    adjustments: list[AdjustmentRecord] = Field(default_factory=list)
    model_projected_stats: ProjectedStats | None = None

    #: Small set of raw feature values surfaced in the UI ("key opportunity
    #: statistic" column, player-page context). Kept flat and optional so the
    #: frontend never crashes on an absent field.
    context: dict[str, float | None] = Field(default_factory=dict)

    @field_validator("player_id")
    @classmethod
    def _non_empty_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("playerId must not be empty.")
        return value

    @field_validator("position")
    @classmethod
    def _known_position(cls, value: str) -> str:
        if value not in FANTASY_POSITIONS:
            raise ValueError(f"Unsupported position {value!r}.")
        return value

    @model_validator(mode="after")
    def _check_seasons(self) -> PlayerProjection:
        if self.projection_season != self.source_season + 1:
            raise ValueError(
                f"projectionSeason ({self.projection_season}) must be one season after "
                f"sourceSeason ({self.source_season})."
            )
        if self.is_adjusted and not self.adjustments:
            raise ValueError("isAdjusted is true but no adjustment records were recorded.")
        return self


# ---------------------------------------------------------------------------
# Metadata and supporting exports
# ---------------------------------------------------------------------------


class SourceAttribution(ExportModel):
    name: str
    dataset: str
    url: str
    licence: str
    attribution: str
    seasons_covered: str
    last_fetched: datetime | None = None
    rows: int | None = None
    required: bool = True
    notes: str | None = None


class ScoringRuleExport(ExportModel):
    """The default scoring rules, published so the UI and the CSV download
    describe exactly the same arithmetic the Python engine used."""

    passing_yards_per_point: float
    passing_touchdown: float
    interception: float
    passing_two_point: float
    rushing_yards_per_point: float
    rushing_touchdown: float
    rushing_two_point: float
    reception: float
    receiving_yards_per_point: float
    receiving_touchdown: float
    receiving_two_point: float
    fumble_lost: float


class LeagueDefaultsExport(ExportModel):
    teams: int
    qb: int
    rb: int
    wr: int
    te: int
    flex: int
    superflex: int
    bench_size: int
    replacement_method: str
    replacement_ranks: dict[str, int]
    risk_penalty_weight: float


class PipelineStageRecord(ExportModel):
    stage: str
    status: Literal["ok", "skipped", "degraded", "failed"]
    detail: str = ""
    duration_seconds: float | None = None


class ExportMetadata(ExportModel):
    """``metadata.json`` - the file every page checks before rendering."""

    schema_version: str
    model_version: str
    projection_release: str
    data_mode: DataMode
    projection_season: int
    source_season: int
    data_start_season: int
    generated_at: datetime
    git_commit: str | None = None
    dataset_hash: str | None = None
    player_count: int = Field(ge=0)
    candidate_pool_size: int = Field(ge=0)
    positions: list[Position]
    rookie_mode: Literal["full", "reduced", "fixture"]
    scoring: ScoringRuleExport
    league_defaults: LeagueDefaultsExport
    sources: list[SourceAttribution] = Field(default_factory=list)
    pipeline: list[PipelineStageRecord] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    package_versions: dict[str, str] = Field(default_factory=dict)

    @field_validator("data_mode")
    @classmethod
    def _known_mode(cls, value: str) -> str:
        if value not in (DATA_MODE_PRODUCTION, DATA_MODE_FIXTURE):
            raise ValueError(f"Unknown dataMode {value!r}.")
        return value


class ProjectionsFile(ExportModel):
    """``projections.json`` - the primary payload."""

    schema_version: str
    data_mode: DataMode
    projection_season: int
    generated_at: datetime
    players: list[PlayerProjection]

    @model_validator(mode="after")
    def _check_unique(self) -> ProjectionsFile:
        ids = [player.player_id for player in self.players]
        if len(ids) != len(set(ids)):
            duplicates = sorted({pid for pid in ids if ids.count(pid) > 1})
            raise ValueError(f"Duplicate playerId values in projections: {duplicates}.")
        slugs = [player.slug for player in self.players]
        if len(slugs) != len(set(slugs)):
            duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
            raise ValueError(f"Duplicate slug values in projections: {duplicates}.")
        return self


class RankingEntry(ExportModel):
    """Compact ranking row. Keeps ``rankings.json`` small enough to load on a
    slow mobile connection without shipping every projection detail twice."""

    player_id: str
    slug: str
    name: str
    team: str
    position: Position
    overall_rank: int
    position_rank: int
    tier: int
    ppr_points: float
    points_per_game: float
    vorp: float
    risk_adjusted_value: float
    confidence_score: float
    confidence_label: ConfidenceLabel
    rookie: bool
    games: float
    previous_season_ppr_points: float | None = None
    key_opportunity_label: str | None = None
    key_opportunity_value: float | None = None


class RankingsFile(ExportModel):
    schema_version: str
    data_mode: DataMode
    projection_season: int
    generated_at: datetime
    scoring_preset: str
    entries: list[RankingEntry]

    @model_validator(mode="after")
    def _check_ranks(self) -> RankingsFile:
        ranks = [entry.overall_rank for entry in self.entries]
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ValueError(
                "overallRank must be a dense 1..N sequence with no gaps or duplicates."
            )
        for position in FANTASY_POSITIONS:
            pos_ranks = sorted(e.position_rank for e in self.entries if e.position == position)
            if pos_ranks and pos_ranks != list(range(1, len(pos_ranks) + 1)):
                raise ValueError(f"positionRank for {position} is not a dense 1..N sequence.")
        return self


class PlayerIndexEntry(ExportModel):
    """``players.json`` - the lightweight search and routing index."""

    player_id: str
    slug: str
    name: str
    short_name: str
    team: str
    position: Position
    rookie: bool
    overall_rank: int | None = None


class PlayersFile(ExportModel):
    schema_version: str
    data_mode: DataMode
    generated_at: datetime
    players: list[PlayerIndexEntry]


class MetricRecord(ExportModel):
    position: str
    target: str
    model: str
    architecture: str
    mae: float | None = None
    rmse: float | None = None
    median_absolute_error: float | None = None
    r2: float | None = None
    bias: float | None = None
    n: int = 0
    is_baseline: bool = False
    is_selected: bool = False


class RankMetricRecord(ExportModel):
    season: int
    position: str
    model: str
    spearman: float | None = None
    kendall: float | None = None
    mean_rank_error: float | None = None
    top_12_overlap: float | None = None
    top_24_overlap: float | None = None
    top_50_overlap: float | None = None
    top_100_overlap: float | None = None
    starter_precision: float | None = None
    starter_recall: float | None = None
    n: int = 0


class CalibrationRecord(ExportModel):
    position: str
    nominal_coverage: float
    empirical_coverage: float
    mean_interval_width: float
    n: int


class ErrorSliceRecord(ExportModel):
    slice_type: Literal["position", "volume", "age", "experience", "season"]
    slice_value: str
    mae: float
    rmse: float
    bias: float
    n: int


class ModelPerformanceFile(ExportModel):
    """``model-performance.json`` - everything the performance page renders."""

    schema_version: str
    data_mode: DataMode
    generated_at: datetime
    model_version: str
    backtest_seasons: list[int]
    stat_metrics: list[MetricRecord] = Field(default_factory=list)
    fantasy_metrics: list[MetricRecord] = Field(default_factory=list)
    rank_metrics: list[RankMetricRecord] = Field(default_factory=list)
    calibration: list[CalibrationRecord] = Field(default_factory=list)
    error_slices: list[ErrorSliceRecord] = Field(default_factory=list)
    selected_models: dict[str, str] = Field(default_factory=dict)
    known_weaknesses: list[str] = Field(default_factory=list)


class FeatureImportanceRecord(ExportModel):
    position: str
    target: str
    feature: str
    label: str
    group: str
    importance: float
    rank: int
    method: Literal["shap", "permutation", "coefficient"]


class FeatureResearchRecord(ExportModel):
    feature: str
    label: str
    group: str
    position: str
    coverage: float
    year_over_year_pearson: float | None = None
    year_over_year_spearman: float | None = None
    next_season_pearson: float | None = None
    next_season_spearman: float | None = None
    univariate_r2: float | None = None
    incremental_mae_gain: float | None = None
    decision: Literal["included", "excluded", "experimental"]
    decision_reason: str


class FeatureImportanceFile(ExportModel):
    schema_version: str
    data_mode: DataMode
    generated_at: datetime
    importances: list[FeatureImportanceRecord] = Field(default_factory=list)
    research: list[FeatureResearchRecord] = Field(default_factory=list)
    group_summary: list[dict[str, Any]] = Field(default_factory=list)


class DataCoverageRecord(ExportModel):
    dataset: str
    description: str
    earliest_season: int | None = None
    latest_season: int | None = None
    positions_covered: str
    row_count: int
    important_columns: list[str] = Field(default_factory=list)
    missing_seasons: list[int] = Field(default_factory=list)
    last_updated: datetime | None = None
    licence: str
    required: bool
    status: Literal["ok", "partial", "unavailable"]
    notes: str = ""


class DataCoverageFile(ExportModel):
    schema_version: str
    data_mode: DataMode
    generated_at: datetime
    datasets: list[DataCoverageRecord] = Field(default_factory=list)


# Resolve the forward reference used inside ExplanationBlock.
ExplanationBlock.model_rebuild()

__all__ = [
    "CONFIDENCE_LABELS",
    "AdjustmentRecord",
    "CalibrationRecord",
    "ComparableSeason",
    "ConfidenceBlock",
    "DataCoverageFile",
    "DataCoverageRecord",
    "DraftInfo",
    "ErrorSliceRecord",
    "ExplanationBlock",
    "ExplanationFactor",
    "ExportMetadata",
    "FantasySummary",
    "FeatureImportanceFile",
    "FeatureImportanceRecord",
    "FeatureResearchRecord",
    "HistoricalSeason",
    "LeagueDefaultsExport",
    "MetricRecord",
    "ModelPerformanceFile",
    "PipelineStageRecord",
    "PlayerIndexEntry",
    "PlayerProjection",
    "PlayerWarning",
    "PlayersFile",
    "ProjectedStats",
    "ProjectionRange",
    "ProjectionsFile",
    "RankMetricRecord",
    "RankingEntry",
    "RankingsFile",
    "ScoringRuleExport",
    "SourceAttribution",
]
