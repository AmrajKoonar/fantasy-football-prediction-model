"""Ingestion orchestration.

Pulls every configured nflverse dataset, resolves player identities, builds
season tables and produces the data-coverage matrix.

The result, :class:`IngestedData`, is the only thing the feature layer sees.
It carries the season tables plus an honest record of what was unavailable, so
downstream code can reason about missing sources instead of discovering a
missing column at model-fit time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from fantasy_football_prediction_model.config import Settings
from fantasy_football_prediction_model.constants import CANONICAL_ID_COLUMN
from fantasy_football_prediction_model.data.aggregation import (
    add_team_scoring,
    aggregate_depth_charts,
    aggregate_nextgen,
    aggregate_pbp_player_features,
    aggregate_pbp_team_features,
    aggregate_pfr_advstats,
    aggregate_player_seasons,
    aggregate_snap_counts,
    aggregate_team_seasons,
    games_per_season_from_schedule,
)
from fantasy_football_prediction_model.data.identities import PlayerIdentityResolver
from fantasy_football_prediction_model.data.manifests import DatasetRecord, RunManifest
from fantasy_football_prediction_model.data.validation import (
    Severity,
    ValidationReport,
    check_not_empty,
    check_player_season_uniqueness,
    check_ratio_consistency,
    check_required_columns,
)
from fantasy_football_prediction_model.data_sources.local_cache import DataCache
from fantasy_football_prediction_model.data_sources.nflverse import (
    DATASETS,
    NflverseAdapter,
)
from fantasy_football_prediction_model.logging import DataUnavailableError, get_logger

logger = get_logger(__name__)

#: Datasets fetched by a standard run, in the order they are needed.
CORE_DATASETS: tuple[str, ...] = (
    "players",
    "schedules",
    "player_stats_week",
    "team_stats_week",
    "rosters",
    "ff_playerids",
    "snap_counts",
    "depth_charts",
    "nextgen_passing",
    "nextgen_rushing",
    "nextgen_receiving",
    "pfr_pass",
    "pfr_rush",
    "pfr_rec",
    "draft_picks",
    "combine",
    "injuries",
)


@dataclass(slots=True)
class DatasetStatus:
    """Whether one dataset arrived, and what it looked like."""

    name: str
    status: str
    rows: int = 0
    columns: int = 0
    seasons_present: list[int] = field(default_factory=list)
    missing_seasons: list[int] = field(default_factory=list)
    important_columns: list[str] = field(default_factory=list)
    fetched_at: datetime | None = None
    note: str = ""


@dataclass(slots=True)
class IngestedData:
    """Validated season tables plus provenance and coverage information."""

    settings: Settings
    resolver: PlayerIdentityResolver
    player_seasons: pl.DataFrame
    team_seasons: pl.DataFrame
    rosters: pl.DataFrame
    games_per_season: dict[int, int]
    snap_seasons: pl.DataFrame | None = None
    depth_seasons: pl.DataFrame | None = None
    ngs_passing: pl.DataFrame | None = None
    ngs_rushing: pl.DataFrame | None = None
    ngs_receiving: pl.DataFrame | None = None
    pfr_pass: pl.DataFrame | None = None
    pfr_rush: pl.DataFrame | None = None
    pfr_rec: pl.DataFrame | None = None
    pbp_player: pl.DataFrame | None = None
    pbp_team: pl.DataFrame | None = None
    draft_picks: pl.DataFrame | None = None
    combine: pl.DataFrame | None = None
    target_rosters: pl.DataFrame | None = None
    target_depth: pl.DataFrame | None = None
    coverage: list[DatasetStatus] = field(default_factory=list)
    validation: ValidationReport = field(default_factory=ValidationReport)
    data_mode: str = "production"

    def coverage_frame(self) -> pl.DataFrame:
        """The coverage matrix, ready to write to CSV or JSON."""
        rows = []
        for status in self.coverage:
            spec = DATASETS.get(status.name)
            rows.append(
                {
                    "dataset": status.name,
                    "description": spec.description if spec else "",
                    "earliest_season": min(status.seasons_present) if status.seasons_present else None,
                    "latest_season": max(status.seasons_present) if status.seasons_present else None,
                    "positions_covered": _positions_for(status.name),
                    "row_count": status.rows,
                    "column_count": status.columns,
                    "important_columns": "; ".join(status.important_columns[:12]),
                    "missing_seasons": "; ".join(str(s) for s in status.missing_seasons),
                    "last_updated": status.fetched_at.isoformat() if status.fetched_at else "",
                    "licence": spec.licence if spec else "",
                    "required": bool(spec.required) if spec else False,
                    "status": status.status,
                    "notes": status.note or (spec.notes if spec else ""),
                }
            )
        return pl.DataFrame(rows) if rows else pl.DataFrame()


def _positions_for(dataset: str) -> str:
    """Which fantasy positions a dataset meaningfully covers."""
    return {
        "nextgen_passing": "QB",
        "nextgen_rushing": "RB, QB",
        "nextgen_receiving": "WR, TE, RB",
        "pfr_pass": "QB",
        "pfr_rush": "RB, QB",
        "pfr_rec": "WR, TE, RB",
    }.get(dataset, "QB, RB, WR, TE")


def _status_for(
    name: str, frame: pl.DataFrame | None, cache: DataCache, key: str, requested: list[int]
) -> DatasetStatus:
    """Build the coverage record for one fetched dataset."""
    spec = DATASETS.get(name)
    if frame is None:
        return DatasetStatus(
            name=name,
            status="unavailable",
            missing_seasons=requested,
            note="Not returned by the source and not present in the cache.",
        )

    seasons_present: list[int] = []
    if "season" in frame.columns:
        seasons_present = sorted(
            int(season)
            for season in frame.get_column("season").drop_nulls().unique().to_list()
        )
    missing = sorted(set(requested) - set(seasons_present)) if requested and seasons_present else []

    entry = cache.read_manifest("nflverse", key)
    return DatasetStatus(
        name=name,
        status="partial" if missing else "ok",
        rows=frame.height,
        columns=frame.width,
        seasons_present=seasons_present,
        missing_seasons=missing,
        important_columns=list(spec.expected_columns) if spec else list(frame.columns[:10]),
        fetched_at=entry.fetched_datetime if entry else None,
        note=(
            f"{len(missing)} requested season(s) are not present in this dataset."
            if missing
            else ""
        ),
    )


def ingest(
    settings: Settings,
    *,
    manifest: RunManifest | None = None,
    force_refresh: bool = False,
    include_pbp: bool = True,
    seasons: list[int] | None = None,
) -> IngestedData:
    """Fetch, validate and aggregate every dataset the pipeline needs.

    Args:
        settings: Validated configuration.
        manifest: Run manifest to record provenance into.
        force_refresh: Bypass the cache for every dataset.
        include_pbp: Fetch play-by-play. Disabling it saves roughly 2.5 GB of
            disk and several minutes, at the cost of red-zone, situational and
            pace features, which are then marked missing rather than guessed.
        seasons: Override the season window (used by fixture tests).

    Returns:
        Aggregated season tables plus coverage and validation reports.

    Raises:
        DataUnavailableError: a required dataset could not be obtained.
        DataQualityError: an obtained dataset failed a critical check.
    """
    settings.ensure_directories()
    season_list = seasons or settings.all_seasons
    target_season = settings.target_season

    cache = DataCache(
        settings.path("cache_dir"),
        ttl_hours=settings.project_config.ingestion.cache_ttl_hours,
        offline=settings.project_config.ingestion.offline,
    )
    adapter = NflverseAdapter(
        cache,
        max_retries=settings.project_config.ingestion.max_retries,
        backoff_initial=settings.project_config.ingestion.backoff_initial_seconds,
        backoff_max=settings.project_config.ingestion.backoff_max_seconds,
        offline=settings.project_config.ingestion.offline,
        force_refresh=force_refresh,
    )

    report = ValidationReport()
    coverage: list[DatasetStatus] = []
    raw: dict[str, pl.DataFrame | None] = {}

    def fetch(name: str, request_seasons: list[int] | None) -> pl.DataFrame | None:
        started = time.perf_counter()
        spec = DATASETS[name]
        try:
            frame = adapter.load(name, request_seasons)
        except DataUnavailableError:
            if spec.required:
                raise
            logger.warning("Optional dataset '%s' could not be loaded; continuing.", name)
            frame = None
        raw[name] = frame
        key = adapter.cache_key(spec, request_seasons)
        status = _status_for(name, frame, cache, key, request_seasons or [])
        coverage.append(status)
        if manifest is not None:
            entry = cache.read_manifest("nflverse", key)
            manifest.record_dataset(
                DatasetRecord(
                    name=name,
                    status=status.status,
                    rows=status.rows,
                    columns=status.columns,
                    seasons=status.seasons_present,
                    content_hash=entry.content_hash if entry else "",
                    fetched_at=entry.fetched_at if entry else None,
                    source_identifier=entry.source_identifier if entry else "",
                    licence=spec.licence,
                    required=spec.required,
                    note=status.note,
                )
            )
        logger.debug("Dataset '%s' resolved in %.1fs.", name, time.perf_counter() - started)
        return frame

    logger.info(
        "Ingesting nflverse data for seasons %d-%d (target season %d).",
        min(season_list),
        max(season_list),
        target_season,
    )

    # Roster and depth-chart data for the target season describes where players
    # are *now*. It is used only to establish the projection candidate pool and
    # landing spots, never as a historical training feature.
    roster_seasons = [*season_list, target_season]

    players = fetch("players", None)
    schedules = fetch("schedules", None)
    weekly = fetch("player_stats_week", season_list)
    team_weekly = fetch("team_stats_week", season_list)
    rosters = fetch("rosters", roster_seasons)
    ff_playerids = fetch("ff_playerids", None)
    snap_counts = fetch("snap_counts", season_list)
    depth_charts = fetch("depth_charts", roster_seasons)
    ngs_pass = fetch("nextgen_passing", season_list)
    ngs_rush = fetch("nextgen_rushing", season_list)
    ngs_rec = fetch("nextgen_receiving", season_list)
    pfr_pass_raw = fetch("pfr_pass", season_list)
    pfr_rush_raw = fetch("pfr_rush", season_list)
    pfr_rec_raw = fetch("pfr_rec", season_list)
    draft_picks = fetch("draft_picks", None)
    combine = fetch("combine", None)
    injuries = fetch("injuries", season_list)

    if injuries is None:
        logger.warning(
            "Injury reports are unavailable. This is expected and non-fatal: availability "
            "features are derived from games played, roster status and workload instead. "
            "See docs/LIMITATIONS.md."
        )

    pbp = fetch("pbp", season_list) if include_pbp else None
    if not include_pbp:
        coverage.append(
            DatasetStatus(
                name="pbp",
                status="unavailable",
                missing_seasons=season_list,
                note="Skipped by request (--skip-pbp). Situational features are unavailable.",
            )
        )

    if players is None or weekly is None or team_weekly is None or rosters is None:
        raise DataUnavailableError(
            "One or more required nflverse datasets could not be loaded.",
            hint="Run `ffpm data fetch-nfl --force-refresh` with network access.",
        )

    # -- identity ------------------------------------------------------------

    corrections = _read_manual_csv(
        settings.repo_root / settings.project_config.overrides.id_corrections_file
    )
    resolver = PlayerIdentityResolver(
        players, ff_playerids=ff_playerids, corrections=corrections
    )
    logger.info("Canonical player dimension holds %d players.", resolver.dimension.height)

    # -- season tables -------------------------------------------------------

    player_seasons = aggregate_player_seasons(weekly)
    team_seasons = add_team_scoring(aggregate_team_seasons(team_weekly), schedules)
    games_per_season = games_per_season_from_schedule(schedules)

    snap_seasons = aggregate_snap_counts(snap_counts, resolver)
    depth_seasons = aggregate_depth_charts(depth_charts)
    ngs_passing = aggregate_nextgen(ngs_pass, "passing")
    ngs_rushing = aggregate_nextgen(ngs_rush, "rushing")
    ngs_receiving = aggregate_nextgen(ngs_rec, "receiving")
    pfr_pass_seasons = aggregate_pfr_advstats(pfr_pass_raw, "pass", resolver)
    pfr_rush_seasons = aggregate_pfr_advstats(pfr_rush_raw, "rush", resolver)
    pfr_rec_seasons = aggregate_pfr_advstats(pfr_rec_raw, "rec", resolver)
    pbp_player = aggregate_pbp_player_features(pbp)
    pbp_team = aggregate_pbp_team_features(pbp)

    normalised_rosters = _normalise_rosters(rosters)
    target_rosters = normalised_rosters.filter(pl.col("season") == target_season)
    if target_rosters.is_empty():
        logger.warning(
            "No roster data exists for the target season %d yet. The candidate pool will fall "
            "back to the %d roster, and team assignments may be out of date.",
            target_season,
            settings.feature_end_season,
        )
        target_rosters = normalised_rosters.filter(
            pl.col("season") == settings.feature_end_season
        )

    target_depth = aggregate_depth_charts(depth_charts, season=target_season)

    # -- validation ----------------------------------------------------------

    check_not_empty(player_seasons, dataset="player_seasons", report=report)
    check_required_columns(
        player_seasons,
        [CANONICAL_ID_COLUMN, "season", "games", "position", "team"],
        dataset="player_seasons",
        report=report,
    )
    check_player_season_uniqueness(player_seasons, dataset="player_seasons", report=report)
    check_ratio_consistency(player_seasons, dataset="player_seasons", report=report)
    check_not_empty(team_seasons, dataset="team_seasons", report=report)

    latest = player_seasons.get_column("season").max()
    if latest is None or int(latest) < settings.feature_end_season:
        report.fail(
            "feature_end_season_present",
            f"The player-season table ends at {latest}, but configs/project.yml expects "
            f"data through {settings.feature_end_season}.",
            severity=Severity.ERROR,
            dataset="player_seasons",
        )
    else:
        report.ok(
            "feature_end_season_present",
            f"Observed statistics are present through {latest}.",
            dataset="player_seasons",
        )

    if target_season in games_per_season:
        report.ok(
            "target_schedule_present",
            f"The {target_season} schedule is published: "
            f"{games_per_season[target_season]} regular-season games per team.",
        )
    else:
        report.fail(
            "target_schedule_present",
            f"No {target_season} schedule is published yet; the documented "
            f"{settings.model.constraints.fallback_games_per_season}-game fallback will "
            f"bound projected games.",
            severity=Severity.WARNING,
        )

    logger.info("Ingestion validation: %s", report.summary())

    return IngestedData(
        settings=settings,
        resolver=resolver,
        player_seasons=player_seasons,
        team_seasons=team_seasons,
        rosters=normalised_rosters,
        games_per_season=games_per_season,
        snap_seasons=snap_seasons,
        depth_seasons=depth_seasons,
        ngs_passing=ngs_passing,
        ngs_rushing=ngs_rushing,
        ngs_receiving=ngs_receiving,
        pfr_pass=pfr_pass_seasons,
        pfr_rush=pfr_rush_seasons,
        pfr_rec=pfr_rec_seasons,
        pbp_player=pbp_player,
        pbp_team=pbp_team,
        draft_picks=draft_picks,
        combine=combine,
        target_rosters=target_rosters,
        target_depth=target_depth,
        coverage=coverage,
        validation=report,
    )


def _normalise_rosters(rosters: pl.DataFrame) -> pl.DataFrame:
    """One row per ``(gsis_id, season)`` with normalised team and position."""
    from fantasy_football_prediction_model.data.identities import (
        normalise_position_expr,
        normalise_team_expr,
    )

    frame = rosters.with_columns(
        pl.col("gsis_id").cast(pl.Utf8).alias(CANONICAL_ID_COLUMN),
        pl.col("season").cast(pl.Int64),
        normalise_team_expr("team", "team"),
        normalise_position_expr("position", "fantasy_position"),
    ).filter(pl.col(CANONICAL_ID_COLUMN).is_not_null())

    keep = [
        CANONICAL_ID_COLUMN,
        "season",
        "team",
        "fantasy_position",
        "position",
        "status",
        "years_exp",
        "birth_date",
        "height",
        "weight",
        "college",
        "draft_number",
        "draft_club",
        "rookie_year",
        "entry_year",
        "depth_chart_position",
        "headshot_url",
        "week",
    ]
    available = [column for column in keep if column in frame.columns]
    frame = frame.select(available)

    # Weekly roster rows exist for some seasons; keep the last week so the
    # recorded team is where the player finished the season.
    if "week" in frame.columns:
        frame = (
            frame.sort("week", nulls_last=True)
            .unique(subset=[CANONICAL_ID_COLUMN, "season"], keep="last", maintain_order=True)
            .drop("week")
        )
    else:
        frame = frame.unique(subset=[CANONICAL_ID_COLUMN, "season"], keep="last")

    casts = []
    for column, dtype in (
        ("years_exp", pl.Float64),
        ("height", pl.Float64),
        ("weight", pl.Float64),
        ("draft_number", pl.Float64),
        ("rookie_year", pl.Float64),
        ("entry_year", pl.Float64),
    ):
        if column in frame.columns:
            casts.append(pl.col(column).cast(dtype, strict=False))
    if "birth_date" in frame.columns:
        casts.append(
            pl.col("birth_date").cast(pl.Utf8).str.slice(0, 10).str.to_date(strict=False)
        )
    return frame.with_columns(casts) if casts else frame


def _read_manual_csv(path: Path) -> pl.DataFrame | None:
    """Read an operator-supplied CSV, tolerating absence and emptiness."""
    if not path.is_file():
        return None
    try:
        frame = pl.read_csv(path, infer_schema_length=0)
    except (pl.exceptions.PolarsError, OSError) as exc:
        logger.warning("Could not read the manual file %s: %s", path, exc)
        return None
    if frame.is_empty():
        return None
    logger.info("Loaded %d manual record(s) from %s.", frame.height, path.name)
    return frame


def write_coverage_reports(data: IngestedData) -> tuple[Path, Path]:
    """Write the data-coverage matrix to CSV and JSON."""
    from fantasy_football_prediction_model.schemas import (
        DataCoverageFile,
        DataCoverageRecord,
    )

    settings = data.settings
    frame = data.coverage_frame()
    csv_path = settings.path("feature_research_dir") / "data-coverage.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_csv(csv_path)

    records: list[DataCoverageRecord] = []
    for status in data.coverage:
        spec = DATASETS.get(status.name)
        records.append(
            DataCoverageRecord(
                dataset=status.name,
                description=spec.description if spec else "",
                earliest_season=min(status.seasons_present) if status.seasons_present else None,
                latest_season=max(status.seasons_present) if status.seasons_present else None,
                positions_covered=_positions_for(status.name),
                row_count=status.rows,
                important_columns=status.important_columns[:12],
                missing_seasons=status.missing_seasons,
                last_updated=status.fetched_at,
                licence=spec.licence if spec else "",
                required=bool(spec.required) if spec else False,
                status=status.status,  # type: ignore[arg-type]
                notes=status.note or (spec.notes if spec else ""),
            )
        )

    payload = DataCoverageFile(
        schema_version=settings.project_config.project.schema_version,
        data_mode=data.data_mode,  # type: ignore[arg-type]
        generated_at=datetime.now(UTC),
        datasets=records,
    )
    json_path = settings.path("web_data_dir") / "data-coverage.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        payload.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )
    logger.info("Wrote the data-coverage matrix to %s and %s.", csv_path, json_path)
    return csv_path, json_path
