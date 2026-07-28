"""CollegeFootballData (CFBD) adapter for rookie college-production features.

CFBD is free but requires an API key and applies a monthly call allowance, so
this adapter is built around three rules:

1. **Batch, never per-player.** Season-level endpoints return every player at
   once. One request covers a whole recruiting class.
2. **Cache permanently.** College seasons never change once played, so a
   cached response is reused indefinitely unless ``--force-refresh`` is given.
3. **Degrade, never fail.** With no key the rookie pipeline runs in *reduced*
   mode from nflverse draft, combine, roster and depth-chart data. The veteran
   pipeline never touches CFBD at all.

API docs: https://collegefootballdata.com/ and https://api.collegefootballdata.com/
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import httpx
import polars as pl

from fantasy_football_prediction_model.data_sources.local_cache import DataCache
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)

SOURCE_NAME = "collegefootballdata"
API_BASE_URL = "https://api.collegefootballdata.com"
SIGNUP_URL = "https://collegefootballdata.com/key"

#: Local counter file so `ffpm data fetch-rookies --usage` can report how many
#: calls this machine has made. The authoritative limit lives with CFBD.
USAGE_FILE_KEY = "request-usage"


class RookieMode(str, Enum):
    """How much information the rookie models get to work with."""

    FULL = "full"
    """CFBD key present: college production features are available."""

    REDUCED = "reduced"
    """No key: draft capital, combine testing and landing spot only."""

    FIXTURE = "fixture"
    """Synthetic fixtures. Never valid for a production export."""


@dataclass(frozen=True, slots=True)
class CfbdEndpoint:
    """A season-level CFBD endpoint and the columns the pipeline needs."""

    name: str
    path: str
    description: str
    expected_fields: tuple[str, ...] = ()


ENDPOINTS: dict[str, CfbdEndpoint] = {
    "player_season_stats": CfbdEndpoint(
        name="player_season_stats",
        path="/stats/player/season",
        description="Season aggregate statistics for every FBS player.",
        expected_fields=("playerId", "player", "statType", "stat"),
    ),
    "player_usage": CfbdEndpoint(
        name="player_usage",
        path="/player/usage",
        description="Share of team plays, passing, rushing and receiving usage.",
        expected_fields=("id", "name", "usage"),
    ),
    "teams": CfbdEndpoint(
        name="teams",
        path="/teams/fbs",
        description="FBS team list with conference, used for competition tiers.",
        expected_fields=("school", "conference"),
    ),
}

#: Conference strength tiers. A deterministic, documented grouping used as a
#: crude competition-level control; it is not a power ranking.
CONFERENCE_TIERS: dict[str, int] = {
    "SEC": 1,
    "Big Ten": 1,
    "Big 12": 2,
    "ACC": 2,
    "Pac-12": 2,
    "American Athletic": 3,
    "Mountain West": 3,
    "Sun Belt": 4,
    "Conference USA": 4,
    "Mid-American": 4,
    "FBS Independents": 3,
}
DEFAULT_CONFERENCE_TIER = 5


def resolve_api_key(explicit: str | None = None) -> str | None:
    """Return the CFBD key from the argument or ``CFBD_API_KEY``."""
    key = explicit or os.environ.get("CFBD_API_KEY")
    key = (key or "").strip()
    return key or None


def resolve_rookie_mode(
    api_key: str | None = None, *, fixture: bool = False
) -> RookieMode:
    """Decide which rookie mode this run can use."""
    if fixture:
        return RookieMode.FIXTURE
    return RookieMode.FULL if resolve_api_key(api_key) else RookieMode.REDUCED


class CollegeFootballDataAdapter:
    """Cached, rate-aware CFBD client.

    Every method returns ``None`` rather than raising when the data cannot be
    obtained, because no CFBD feature is ever required for the pipeline to
    finish. Failures are logged and recorded in the run metadata.
    """

    def __init__(
        self,
        cache: DataCache,
        *,
        api_key: str | None = None,
        offline: bool = False,
        force_refresh: bool = False,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        min_seconds_between_requests: float = 0.4,
    ) -> None:
        self.cache = cache
        self.api_key = resolve_api_key(api_key)
        self.offline = offline
        self.force_refresh = force_refresh
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.min_seconds_between_requests = min_seconds_between_requests
        self._last_request_at = 0.0
        self._session_requests = 0

    @property
    def enabled(self) -> bool:
        """True when a key is configured and the run is allowed to call out."""
        return self.api_key is not None and not self.offline

    @property
    def mode(self) -> RookieMode:
        return RookieMode.FULL if self.api_key else RookieMode.REDUCED

    # -- usage accounting ----------------------------------------------------

    def _read_usage(self) -> dict[str, Any]:
        payload = self.cache.read_json(SOURCE_NAME, USAGE_FILE_KEY)
        if isinstance(payload, dict):
            return payload
        return {"total_requests": 0, "by_month": {}, "first_recorded": None}

    def _record_request(self) -> None:
        usage = self._read_usage()
        month = datetime.now(UTC).strftime("%Y-%m")
        usage["total_requests"] = int(usage.get("total_requests", 0)) + 1
        by_month = usage.setdefault("by_month", {})
        by_month[month] = int(by_month.get(month, 0)) + 1
        usage.setdefault("first_recorded", datetime.now(UTC).isoformat())
        usage["last_recorded"] = datetime.now(UTC).isoformat()
        self.cache.write_json(SOURCE_NAME, USAGE_FILE_KEY, usage)
        self._session_requests += 1

    def usage_report(self) -> dict[str, Any]:
        """Locally observed request counts.

        This machine's view only. CFBD enforces the real allowance server-side
        and it may differ; treat this as a guide, not an authority.
        """
        usage = self._read_usage()
        usage["session_requests"] = self._session_requests
        usage["current_month"] = datetime.now(UTC).strftime("%Y-%m")
        usage["current_month_requests"] = usage.get("by_month", {}).get(
            usage["current_month"], 0
        )
        usage["note"] = (
            "Counts requests made from this machine only. The authoritative monthly "
            "allowance is enforced by CollegeFootballData."
        )
        return usage

    # -- HTTP ----------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_seconds_between_requests:
            time.sleep(self.min_seconds_between_requests - elapsed)
        self._last_request_at = time.monotonic()

    def _request(self, path: str, params: dict[str, Any]) -> Any | None:
        """Perform one GET with retries. Returns ``None`` on failure."""
        if not self.api_key:
            return None

        url = f"{API_BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "fantasy-football-prediction-model/1.0 (open-source portfolio project)",
        }

        delay = 1.0
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = httpx.get(
                    url, params=params, headers=headers, timeout=self.timeout_seconds
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "CFBD request to %s failed (%s). Attempt %d/%d.",
                    path,
                    exc,
                    attempt,
                    self.max_retries,
                )
                if attempt >= self.max_retries:
                    return None
                time.sleep(delay)
                delay *= 2
                continue

            self._record_request()

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    logger.warning("CFBD returned non-JSON content for %s.", path)
                    return None

            if response.status_code in (401, 403):
                logger.error(
                    "CollegeFootballData rejected the API key (HTTP %d). Rookie features "
                    "will fall back to reduced mode. Check CFBD_API_KEY, or request a new "
                    "free key at %s.",
                    response.status_code,
                    SIGNUP_URL,
                )
                self.api_key = None
                return None

            if response.status_code == 429:
                logger.error(
                    "CollegeFootballData rate limit reached (HTTP 429). The monthly free "
                    "allowance may be exhausted. Cached responses will still be used; new "
                    "college features are unavailable until the allowance resets."
                )
                return None

            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                logger.warning(
                    "CFBD server error %d for %s; retrying in %.0fs.",
                    response.status_code,
                    path,
                    delay,
                )
                time.sleep(delay)
                delay *= 2
                continue

            logger.warning("CFBD returned HTTP %d for %s.", response.status_code, path)
            return None

        return None

    # -- cached endpoint access ---------------------------------------------

    def _cached_get(self, endpoint: CfbdEndpoint, params: dict[str, Any]) -> Any | None:
        """Fetch an endpoint through the permanent JSON cache."""
        param_part = "-".join(f"{k}_{v}" for k, v in sorted(params.items()))
        key = f"{endpoint.name}-{param_part}" if param_part else endpoint.name

        if not self.force_refresh:
            cached = self.cache.read_json(SOURCE_NAME, key)
            if cached is not None:
                logger.debug("Using cached CFBD response for %s.", key)
                return cached

        if self.offline:
            logger.warning("Offline mode: CFBD response '%s' is not cached; skipping.", key)
            return None

        if not self.api_key:
            logger.info(
                "No CFBD_API_KEY configured; skipping college data for '%s'. "
                "Rookie projections will use reduced mode.",
                key,
            )
            return None

        payload = self._request(endpoint.path, params)
        if payload is None:
            return None
        self.cache.write_json(SOURCE_NAME, key, payload)
        return payload

    # -- public loaders ------------------------------------------------------

    def load_player_season_stats(self, season: int) -> pl.DataFrame | None:
        """Season aggregate statistics for one college season.

        CFBD returns long-format rows (one per player-category-stat). They are
        pivoted to one row per player here.
        """
        payload = self._cached_get(
            ENDPOINTS["player_season_stats"], {"year": season, "seasonType": "regular"}
        )
        if not payload:
            return None
        try:
            frame = pl.DataFrame(payload, infer_schema_length=None)
        except (TypeError, ValueError) as exc:
            logger.warning("Could not parse CFBD season stats for %d: %s", season, exc)
            return None

        required = {"playerId", "player", "category", "statType", "stat"}
        missing = sorted(required - set(frame.columns))
        if missing:
            logger.warning(
                "CFBD season stats for %d are missing columns %s; skipping this season. "
                "The API schema may have changed - see %s.",
                season,
                missing,
                "https://blog.collegefootballdata.com/api-v2-is-now-in-general-availability/",
            )
            return None

        wide = (
            frame.with_columns(
                pl.col("stat").cast(pl.Float64, strict=False),
                (pl.col("category").cast(pl.Utf8) + "_" + pl.col("statType").cast(pl.Utf8))
                .str.to_lowercase()
                .alias("stat_key"),
            )
            .pivot(on="stat_key", index=["playerId", "player", "team"], values="stat",
                   aggregate_function="sum")
            .with_columns(pl.lit(season).alias("college_season"))
        )
        return wide

    def load_player_usage(self, season: int) -> pl.DataFrame | None:
        """Team-share usage for one college season."""
        payload = self._cached_get(ENDPOINTS["player_usage"], {"year": season})
        if not payload:
            return None
        try:
            frame = pl.json_normalize(payload, separator="_", infer_schema_length=None)
        except (TypeError, ValueError) as exc:
            logger.warning("Could not parse CFBD usage for %d: %s", season, exc)
            return None
        return frame.with_columns(pl.lit(season).alias("college_season"))

    def load_conference_map(self, season: int) -> dict[str, int] | None:
        """Map each FBS school to its documented conference tier."""
        payload = self._cached_get(ENDPOINTS["teams"], {"year": season})
        if not payload:
            return None
        mapping: dict[str, int] = {}
        for team in payload:
            if not isinstance(team, dict):
                continue
            school = team.get("school")
            conference = team.get("conference")
            if isinstance(school, str):
                mapping[school] = CONFERENCE_TIERS.get(
                    conference if isinstance(conference, str) else "", DEFAULT_CONFERENCE_TIER
                )
        return mapping or None
