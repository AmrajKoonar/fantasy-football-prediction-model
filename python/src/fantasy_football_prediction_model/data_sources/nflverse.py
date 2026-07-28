"""nflverse data adapter.

Wraps :mod:`nflreadpy` (the maintained successor to ``nfl_data_py``) with the
guarantees the pipeline needs and the library does not provide on its own:
season-scoped caching, provenance manifests, retry with exponential backoff,
offline mode, schema drift detection and graceful optional-dataset handling.

The loader functions are resolved by name at call time and their signatures
are inspected before use. nflverse ships new datasets and occasionally renames
parameters; that would otherwise turn into a ``TypeError`` deep in a pipeline
run. Here it becomes a named, actionable error instead.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from typing import Any

import polars as pl

from fantasy_football_prediction_model.data_sources.local_cache import DataCache
from fantasy_football_prediction_model.logging import (
    DataQualityError,
    DataUnavailableError,
    get_logger,
)

logger = get_logger(__name__)

SOURCE_NAME = "nflverse"
NFLVERSE_RELEASES_URL = "https://github.com/nflverse/nflverse-data/releases"


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """Declarative description of one nflverse dataset.

    Attributes:
        name: Internal dataset name used across the pipeline and configs.
        loader: ``nflreadpy`` function name.
        description: Human-readable summary for the coverage report.
        required: Whether the pipeline aborts when it cannot be loaded.
        seasonal: Whether the loader accepts a ``seasons`` argument.
        loader_kwargs: Extra fixed keyword arguments (for example
            ``stat_type="passing"``).
        expected_columns: Columns that must be present. Missing ones mean the
            upstream schema changed and the feature code would silently break.
        earliest_season: First season the source is known to cover. Requests
            below this are trimmed rather than failing.
        licence: Licence string reproduced in the attribution export.
        notes: Extra caveats shown on the data-sources page.
    """

    name: str
    loader: str
    description: str
    required: bool
    seasonal: bool = True
    loader_kwargs: dict[str, Any] | None = None
    expected_columns: tuple[str, ...] = ()
    earliest_season: int = 1999
    licence: str = "CC BY 4.0 (nflverse-data)"
    notes: str = ""


#: Every nflverse dataset the pipeline knows how to load.
#:
#: ``earliest_season`` values reflect the coverage nflverse actually
#: publishes: snap counts begin in 2012, Next Gen Stats in 2016, PFR advanced
#: splits in 2018. Requests are clamped to these bounds so asking for the full
#: 2012-2025 window never produces a spurious download failure.
DATASETS: dict[str, DatasetSpec] = {
    "player_stats_week": DatasetSpec(
        name="player_stats_week",
        loader="load_player_stats",
        description="Weekly player box-score and advanced statistics.",
        required=True,
        loader_kwargs={"summary_level": "week"},
        expected_columns=("player_id", "season", "week", "position"),
        earliest_season=1999,
    ),
    "player_stats_season": DatasetSpec(
        name="player_stats_season",
        loader="load_player_stats",
        description="Regular-season player statistics as calculated by nflverse.",
        required=False,
        loader_kwargs={"summary_level": "reg"},
        expected_columns=("player_id", "season"),
        earliest_season=1999,
    ),
    "team_stats_week": DatasetSpec(
        name="team_stats_week",
        loader="load_team_stats",
        description="Weekly team offensive and defensive statistics.",
        required=True,
        loader_kwargs={"summary_level": "week"},
        expected_columns=("team", "season", "week"),
        earliest_season=1999,
    ),
    "players": DatasetSpec(
        name="players",
        loader="load_players",
        description="Canonical player dimension with cross-source identifiers.",
        required=True,
        seasonal=False,
        expected_columns=("gsis_id", "display_name", "position"),
    ),
    "rosters": DatasetSpec(
        name="rosters",
        loader="load_rosters",
        description="Season-level rosters: team, position, status, age.",
        required=True,
        expected_columns=("season", "team", "position", "status"),
        earliest_season=1999,
    ),
    "weekly_rosters": DatasetSpec(
        name="weekly_rosters",
        loader="load_rosters_weekly",
        description="Week-by-week roster status, used for availability features.",
        required=False,
        expected_columns=("season", "week", "team"),
        earliest_season=2002,
    ),
    "schedules": DatasetSpec(
        name="schedules",
        loader="load_schedules",
        description="Game schedules and results; source of games-per-season.",
        required=True,
        seasonal=False,
        expected_columns=("season", "game_id", "home_team", "away_team"),
    ),
    "pbp": DatasetSpec(
        name="pbp",
        loader="load_pbp",
        description="Play-by-play with EPA, air yards, CPOE and situational context.",
        required=False,
        expected_columns=("season", "play_id", "posteam", "epa"),
        earliest_season=1999,
        notes="Large. Cached locally and never committed; only aggregates are stored.",
    ),
    "snap_counts": DatasetSpec(
        name="snap_counts",
        loader="load_snap_counts",
        description="Weekly offensive, defensive and special-teams snap counts.",
        required=False,
        expected_columns=("season", "player", "offense_snaps", "pfr_player_id"),
        earliest_season=2012,
        licence="CC BY-SA 4.0 (Pro Football Reference via nflverse)",
        notes="Keyed on pfr_player_id, joined to GSIS through the player dimension.",
    ),
    "depth_charts": DatasetSpec(
        name="depth_charts",
        loader="load_depth_charts",
        description="Published depth charts, used for role and starter signals.",
        required=False,
        # Only gsis_id is stable. nflverse changed this dataset's shape for the
        # 2025 season: earlier seasons carry season/week/club_code/depth_team,
        # 2025 onward carry dated snapshots with team/pos_rank instead. Both
        # layouts are handled in data/aggregation.py.
        expected_columns=("gsis_id",),
        earliest_season=2001,
        notes=(
            "Two incompatible layouts exist: 2001-2024 (season/week/club_code/depth_team) "
            "and 2025 onward (dated snapshots with team/pos_rank)."
        ),
    ),
    "nextgen_passing": DatasetSpec(
        name="nextgen_passing",
        loader="load_nextgen_stats",
        description="Next Gen Stats passing: time to throw, CPOE, aggressiveness.",
        required=False,
        loader_kwargs={"stat_type": "passing"},
        expected_columns=("season", "player_gsis_id"),
        earliest_season=2016,
        licence="NFL Next Gen Stats, redistributed by nflverse",
    ),
    "nextgen_rushing": DatasetSpec(
        name="nextgen_rushing",
        loader="load_nextgen_stats",
        description="Next Gen Stats rushing: rush yards over expected, box counts.",
        required=False,
        loader_kwargs={"stat_type": "rushing"},
        expected_columns=("season", "player_gsis_id"),
        earliest_season=2016,
        licence="NFL Next Gen Stats, redistributed by nflverse",
    ),
    "nextgen_receiving": DatasetSpec(
        name="nextgen_receiving",
        loader="load_nextgen_stats",
        description="Next Gen Stats receiving: separation, cushion, YAC over expected.",
        required=False,
        loader_kwargs={"stat_type": "receiving"},
        expected_columns=("season", "player_gsis_id"),
        earliest_season=2016,
        licence="NFL Next Gen Stats, redistributed by nflverse",
    ),
    "pfr_pass": DatasetSpec(
        name="pfr_pass",
        loader="load_pfr_advstats",
        description="PFR advanced passing: pressure, pocket time, bad-throw rate.",
        required=False,
        loader_kwargs={"stat_type": "pass", "summary_level": "season"},
        expected_columns=("season", "pfr_id"),
        earliest_season=2018,
        licence="CC BY-SA 4.0 (Pro Football Reference via nflverse)",
    ),
    "pfr_rush": DatasetSpec(
        name="pfr_rush",
        loader="load_pfr_advstats",
        description="PFR advanced rushing: yards before/after contact, broken tackles.",
        required=False,
        loader_kwargs={"stat_type": "rush", "summary_level": "season"},
        expected_columns=("season", "pfr_id"),
        earliest_season=2018,
        licence="CC BY-SA 4.0 (Pro Football Reference via nflverse)",
    ),
    "pfr_rec": DatasetSpec(
        name="pfr_rec",
        loader="load_pfr_advstats",
        description="PFR advanced receiving: drops, broken tackles, average depth.",
        required=False,
        loader_kwargs={"stat_type": "rec", "summary_level": "season"},
        expected_columns=("season", "pfr_id"),
        earliest_season=2018,
        licence="CC BY-SA 4.0 (Pro Football Reference via nflverse)",
    ),
    "draft_picks": DatasetSpec(
        name="draft_picks",
        loader="load_draft_picks",
        description="NFL draft results, the strongest rookie prior available for free.",
        required=False,
        seasonal=False,
        expected_columns=("season", "round", "pick"),
    ),
    "combine": DatasetSpec(
        name="combine",
        loader="load_combine",
        description="NFL Scouting Combine measurements and athletic testing.",
        required=False,
        seasonal=False,
        expected_columns=("season", "player_name"),
    ),
    "ff_playerids": DatasetSpec(
        name="ff_playerids",
        loader="load_ff_playerids",
        description="Cross-platform fantasy player identifier crosswalk.",
        required=False,
        seasonal=False,
        expected_columns=("gsis_id",),
        licence="MIT (DynastyProcess), redistributed by ffverse",
    ),
    "ff_opportunity": DatasetSpec(
        name="ff_opportunity",
        loader="load_ff_opportunity",
        description="Expected fantasy points and expected opportunity (ffopportunity).",
        required=False,
        loader_kwargs={"stat_type": "weekly"},
        expected_columns=("season",),
        earliest_season=2006,
        licence="MIT (ffverse ffopportunity)",
    ),
    "injuries": DatasetSpec(
        name="injuries",
        loader="load_injuries",
        description="Official weekly injury reports.",
        required=False,
        expected_columns=("season", "week"),
        earliest_season=2009,
        notes=(
            "Optional by design. The upstream feed has not reliably covered seasons "
            "after 2024, so availability features are built from games played, roster "
            "status and workload instead. See docs/LIMITATIONS.md."
        ),
    ),
}


def nflverse_package_versions() -> dict[str, str]:
    """Versions of the packages that determine what the data looks like."""
    versions: dict[str, str] = {}
    for package in ("nflreadpy", "polars", "pyarrow"):
        try:
            versions[package] = importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError:  # pragma: no cover
            versions[package] = "unknown"
    return versions


def _import_nflreadpy() -> Any:
    try:
        import nflreadpy  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - install-time failure
        raise DataUnavailableError(
            "The nflreadpy package is not installed, so no NFL data can be fetched.",
            hint=(
                'Install the project dependencies: pip install -e "./python[dev]" '
                "(or `uv pip install -e ./python`)."
            ),
        ) from exc
    return nflreadpy


def _to_polars(result: Any) -> pl.DataFrame:
    """Normalise whatever a loader returns into an eager Polars frame."""
    if isinstance(result, pl.DataFrame):
        return result
    if isinstance(result, pl.LazyFrame):
        return result.collect()
    if hasattr(result, "to_pandas") and not hasattr(result, "columns"):  # pragma: no cover
        return pl.from_pandas(result.to_pandas())
    try:
        return pl.from_pandas(result)
    except (TypeError, ValueError) as exc:  # pragma: no cover
        raise DataQualityError(
            f"An nflverse loader returned an unsupported type: {type(result)!r}.",
            hint="Check whether the installed nflreadpy version changed its return type.",
        ) from exc


class NflverseAdapter:
    """Cached, retrying, offline-capable access to nflverse datasets."""

    def __init__(
        self,
        cache: DataCache,
        *,
        max_retries: int = 4,
        backoff_initial: float = 1.0,
        backoff_max: float = 30.0,
        offline: bool = False,
        force_refresh: bool = False,
    ) -> None:
        self.cache = cache
        self.max_retries = max_retries
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max
        self.offline = offline
        self.force_refresh = force_refresh
        self._versions = nflverse_package_versions()
        self._loader_cache: dict[str, Callable[..., Any]] = {}

    # -- loader resolution ---------------------------------------------------

    def _resolve_loader(self, spec: DatasetSpec) -> Callable[..., Any] | None:
        if spec.loader in self._loader_cache:
            return self._loader_cache[spec.loader]
        module = _import_nflreadpy()
        loader = getattr(module, spec.loader, None)
        if loader is None or not callable(loader):
            logger.warning(
                "nflreadpy has no loader named '%s'; dataset '%s' will be skipped. "
                "Installed nflreadpy version: %s.",
                spec.loader,
                spec.name,
                self._versions.get("nflreadpy", "unknown"),
            )
            return None
        self._loader_cache[spec.loader] = loader
        return loader

    @staticmethod
    def _supported_kwargs(loader: Callable[..., Any], proposed: dict[str, Any]) -> dict[str, Any]:
        """Drop keyword arguments the installed loader does not accept."""
        try:
            signature = inspect.signature(loader)
        except (TypeError, ValueError):  # pragma: no cover - builtins
            return proposed
        if any(
            param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
        ):
            return proposed
        accepted = set(signature.parameters)
        kept = {key: value for key, value in proposed.items() if key in accepted}
        dropped = sorted(set(proposed) - set(kept))
        if dropped:
            logger.debug("Loader %s does not accept %s; omitting.", loader.__name__, dropped)
        return kept

    # -- keys ----------------------------------------------------------------

    @staticmethod
    def cache_key(spec: DatasetSpec, seasons: Sequence[int] | None) -> str:
        if not spec.seasonal or not seasons:
            return spec.name
        return f"{spec.name}-{min(seasons)}-{max(seasons)}"

    def _clamp_seasons(self, spec: DatasetSpec, seasons: Iterable[int]) -> list[int]:
        requested = sorted({int(season) for season in seasons})
        kept = [season for season in requested if season >= spec.earliest_season]
        dropped = [season for season in requested if season < spec.earliest_season]
        if dropped:
            logger.debug(
                "Dataset '%s' starts in %d; not requesting %s.",
                spec.name,
                spec.earliest_season,
                dropped,
            )
        return kept

    # -- fetching ------------------------------------------------------------

    def _download(self, spec: DatasetSpec, seasons: list[int] | None) -> pl.DataFrame:
        """Call the loader with retries and exponential backoff."""
        loader = self._resolve_loader(spec)
        if loader is None:
            raise DataUnavailableError(
                f"nflreadpy does not expose a loader for dataset '{spec.name}'.",
                hint=(
                    "Upgrade nflreadpy (pip install -U nflreadpy) or mark the dataset "
                    "optional in configs/project.yml."
                ),
            )

        kwargs: dict[str, Any] = dict(spec.loader_kwargs or {})
        if spec.seasonal and seasons:
            kwargs["seasons"] = seasons
        kwargs = self._supported_kwargs(loader, kwargs)

        delay = self.backoff_initial
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    "Fetching nflverse dataset '%s'%s (attempt %d/%d)",
                    spec.name,
                    f" for {min(seasons)}-{max(seasons)}" if seasons else "",
                    attempt,
                    self.max_retries,
                )
                return _to_polars(loader(**kwargs))
            except Exception as exc:  # noqa: BLE001 - retry any transport failure
                last_error = exc
                if attempt >= self.max_retries:
                    break
                logger.warning(
                    "Fetch of '%s' failed (%s: %s). Retrying in %.1fs.",
                    spec.name,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                time.sleep(delay)
                delay = min(delay * 2, self.backoff_max)

        raise DataUnavailableError(
            f"Could not download nflverse dataset '{spec.name}' after {self.max_retries} "
            f"attempts. Last error: {type(last_error).__name__}: {last_error}",
            hint=(
                f"Check your network connection and {NFLVERSE_RELEASES_URL}. "
                "If the data is already cached, rerun with --offline to use it."
            ),
        )

    def _validate_schema(self, spec: DatasetSpec, frame: pl.DataFrame) -> None:
        missing = [column for column in spec.expected_columns if column not in frame.columns]
        if missing:
            raise DataQualityError(
                f"nflverse dataset '{spec.name}' is missing expected columns {missing}. "
                f"Received columns: {sorted(frame.columns)[:25]}"
                f"{' ...' if frame.width > 25 else ''}.",
                hint=(
                    "The upstream schema changed. Update the expected_columns entry for this "
                    "dataset in python/src/fantasy_football_prediction_model/data_sources/"
                    "nflverse.py and adjust the feature code that reads the renamed field. "
                    "See https://nflreadr.nflverse.com/articles/ for current dictionaries."
                ),
            )

    def load(
        self,
        dataset: str,
        seasons: Iterable[int] | None = None,
        *,
        force_refresh: bool | None = None,
    ) -> pl.DataFrame | None:
        """Load one dataset, using the cache when it is fresh.

        Args:
            dataset: Key from :data:`DATASETS`.
            seasons: Seasons to request. Ignored for non-seasonal datasets.
            force_refresh: Bypass the cache for this call.

        Returns:
            The dataset, or ``None`` when an optional dataset is unavailable.

        Raises:
            DataUnavailableError: a required dataset could not be obtained.
            DataQualityError: the dataset arrived with an unexpected schema.
        """
        spec = DATASETS.get(dataset)
        if spec is None:
            raise KeyError(
                f"Unknown nflverse dataset '{dataset}'. Known datasets: {sorted(DATASETS)}."
            )

        season_list = self._clamp_seasons(spec, seasons) if (spec.seasonal and seasons) else None
        if spec.seasonal and seasons is not None and not season_list:
            logger.info(
                "Dataset '%s' has no coverage for the requested seasons; skipping.", spec.name
            )
            return None

        key = self.cache_key(spec, season_list)
        refresh = self.force_refresh if force_refresh is None else force_refresh

        if self.offline:
            frame = self.cache.read(SOURCE_NAME, key)
            if frame is None:
                if spec.required:
                    raise DataUnavailableError(
                        f"Offline mode is on and required dataset '{spec.name}' "
                        f"(cache key '{key}') is not cached.",
                        hint=(
                            "Run `ffpm data fetch-nfl` once with network access to populate "
                            "data/cache/, then rerun offline."
                        ),
                    )
                logger.warning(
                    "Offline mode: optional dataset '%s' is not cached and will be skipped.",
                    spec.name,
                )
                return None
            logger.info("Using cached '%s' (offline): %d rows.", spec.name, frame.height)
            return frame

        if not refresh and self.cache.is_fresh(SOURCE_NAME, key):
            frame = self.cache.read(SOURCE_NAME, key)
            if frame is not None:
                logger.info("Using cached '%s': %d rows.", spec.name, frame.height)
                self._validate_schema(spec, frame)
                return frame

        try:
            frame = self._download(spec, season_list)
        except DataUnavailableError:
            stale = self.cache.read(SOURCE_NAME, key)
            if stale is not None:
                logger.warning(
                    "Refresh of '%s' failed; falling back to the cached copy (%d rows). "
                    "The projection metadata will record this dataset as stale.",
                    spec.name,
                    stale.height,
                )
                return stale
            if spec.required:
                raise
            logger.warning(
                "Optional dataset '%s' is unavailable and not cached. The pipeline will "
                "continue without it and mark the affected features missing.",
                spec.name,
            )
            return None

        if frame.is_empty():
            message = f"nflverse dataset '{spec.name}' returned zero rows."
            if spec.required:
                raise DataQualityError(
                    message,
                    hint=(
                        "This usually means the requested seasons are not published yet. "
                        "Check configs/project.yml feature_end_season against "
                        f"{NFLVERSE_RELEASES_URL}."
                    ),
                )
            logger.warning("%s Skipping this optional dataset.", message)
            return None

        self._validate_schema(spec, frame)
        self.cache.write(
            SOURCE_NAME,
            key,
            frame,
            source_identifier=f"{NFLVERSE_RELEASES_URL} :: {spec.loader}",
            seasons=season_list or [],
            package_versions=self._versions,
            notes=spec.notes,
        )
        return frame

    def load_required(self, dataset: str, seasons: Iterable[int] | None = None) -> pl.DataFrame:
        """Load a dataset that the caller cannot proceed without."""
        frame = self.load(dataset, seasons)
        if frame is None:
            raise DataUnavailableError(
                f"Required nflverse dataset '{dataset}' is unavailable.",
                hint="Run `ffpm data fetch-nfl --force-refresh` with network access.",
            )
        return frame
