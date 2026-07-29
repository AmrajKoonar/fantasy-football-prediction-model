"""Rookie enrichment: draft/combine + optional CollegeFootballData production."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import polars as pl

from fantasy_football_prediction_model.config import Settings
from fantasy_football_prediction_model.data_sources.college_football_data import (
    CollegeFootballDataAdapter,
    resolve_rookie_mode,
)
from fantasy_football_prediction_model.data_sources.local_cache import DataCache
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)

RookieModeLabel = Literal["full", "reduced", "fixture"]

#: CFBD long-format pivot keys remapped onto the project's college_* features.
_STAT_ALIASES: dict[str, str] = {
    "passing_att": "college_final_pass_attempts",
    "passing_yds": "college_final_pass_yards",
    "passing_td": "college_final_pass_td",
    "passing_ypa": "college_final_yards_per_attempt",
    "rushing_car": "college_final_rush_attempts",
    "rushing_yds": "college_final_rush_yards",
    "rushing_td": "college_final_rush_td",
    "receiving_rec": "college_final_receptions",
    "receiving_yds": "college_final_rec_yards",
    "receiving_td": "college_final_rec_td",
}


def load_dotenv_file(repo_root: Path | str | None = None) -> None:
    """Load ``.env`` from the repo root if present (never overrides existing env)."""
    env_path: Path | None = None
    if repo_root is not None:
        candidate = Path(repo_root) / ".env"
        if candidate.is_file():
            env_path = candidate
    if env_path is None:
        cwd_env = Path.cwd() / ".env"
        if cwd_env.is_file():
            env_path = cwd_env
        else:
            for parent in Path(__file__).resolve().parents:
                maybe = parent / ".env"
                if maybe.is_file():
                    env_path = maybe
                    break
    if env_path is None:
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def detect_rookie_mode(*, fixture: bool = False) -> RookieModeLabel:
    mode = resolve_rookie_mode(fixture=fixture)
    return mode.value  # type: ignore[return-value]


def _normalise_name(value: str | None) -> str:
    if not value:
        return ""
    text = value.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_college_seasons(
    settings: Settings,
    *,
    seasons: list[int] | None = None,
    force_refresh: bool = False,
) -> dict[str, object]:
    """Download/cache CFBD season stats, usage, and conference tiers.

    Default seasons cover the final college years that feed the target NFL draft.
    """
    cache = DataCache(
        settings.path("cache_dir"),
        ttl_hours=settings.project_config.ingestion.cache_ttl_hours,
        offline=settings.project_config.ingestion.offline,
    )
    adapter = CollegeFootballDataAdapter(
        cache,
        offline=settings.project_config.ingestion.offline,
        force_refresh=force_refresh,
    )
    if seasons is None:
        end = settings.target_season - 1
        seasons = list(range(end - 2, end + 1))

    if not adapter.enabled:
        logger.warning(
            "CFBD_API_KEY missing or offline — fetch-rookies will only report reduced mode."
        )
        return {
            "mode": "reduced",
            "stats": None,
            "usage": None,
            "usage_report": adapter.usage_report(),
        }

    stats_frames: list[pl.DataFrame] = []
    usage_frames: list[pl.DataFrame] = []
    conference_maps: dict[str, int] = {}

    for season in seasons:
        logger.info("Fetching CFBD college data for season %d...", season)
        stats = adapter.load_player_season_stats(season)
        if stats is not None and not stats.is_empty():
            stats_frames.append(stats)
        usage = adapter.load_player_usage(season)
        if usage is not None and not usage.is_empty():
            usage_frames.append(usage)
        conf = adapter.load_conference_map(season)
        if conf:
            conference_maps.update(conf)

    out_dir = settings.path("processed_dir")
    out_dir.mkdir(parents=True, exist_ok=True)

    college_stats = pl.concat(stats_frames, how="diagonal_relaxed") if stats_frames else None
    college_usage = pl.concat(usage_frames, how="diagonal_relaxed") if usage_frames else None

    if college_stats is not None:
        college_stats.write_parquet(out_dir / "college_player_season_stats.parquet")
        logger.info("Wrote %d college season-stat rows.", college_stats.height)
    if college_usage is not None:
        college_usage.write_parquet(out_dir / "college_player_usage.parquet")
        logger.info("Wrote %d college usage rows.", college_usage.height)
    if conference_maps:
        pl.DataFrame(
            {
                "school": list(conference_maps.keys()),
                "college_conference_tier": list(conference_maps.values()),
            }
        ).write_parquet(out_dir / "college_conference_tiers.parquet")

    usage_report = adapter.usage_report()
    logger.info(
        "CFBD local usage: month=%s requests=%s (machine-local count only).",
        usage_report.get("current_month"),
        usage_report.get("current_month_requests"),
    )
    return {
        "mode": "full",
        "stats": college_stats,
        "usage": college_usage,
        "usage_report": usage_report,
        "seasons": seasons,
    }


def _rename_college_stats(frame: pl.DataFrame) -> pl.DataFrame:
    renames = {src: dst for src, dst in _STAT_ALIASES.items() if src in frame.columns}
    if renames:
        frame = frame.rename(renames)
    for candidate in ("passing_gp", "rushing_gp", "receiving_gp", "gp", "games"):
        if candidate in frame.columns and "college_final_games" not in frame.columns:
            frame = frame.with_columns(pl.col(candidate).alias("college_final_games"))
            break
    return frame


def build_college_feature_lookup(settings: Settings) -> pl.DataFrame | None:
    """One row per college player name with final-season production features."""
    path = settings.path("processed_dir") / "college_player_season_stats.parquet"
    if not path.is_file():
        return None
    frame = pl.read_parquet(path)
    if frame.is_empty():
        return None
    frame = _rename_college_stats(frame)

    id_col = "playerId" if "playerId" in frame.columns else None
    name_col = "player" if "player" in frame.columns else None
    if name_col is None:
        return None
    sort_cols = ["college_season"] if "college_season" in frame.columns else []
    if id_col:
        descending = [*([True] * len(sort_cols)), False]
        frame = frame.sort([*sort_cols, id_col], descending=descending)
        frame = frame.unique(subset=[id_col], keep="first")
    else:
        descending = [*([True] * len(sort_cols)), False]
        frame = frame.sort([*sort_cols, name_col], descending=descending)
        frame = frame.unique(subset=[name_col], keep="first")

    frame = frame.with_columns(
        pl.col(name_col)
        .map_elements(_normalise_name, return_dtype=pl.Utf8)
        .alias("college_name_key")
    )

    tier_path = settings.path("processed_dir") / "college_conference_tiers.parquet"
    if tier_path.is_file() and "team" in frame.columns:
        tiers = pl.read_parquet(tier_path)
        frame = frame.join(tiers, left_on="team", right_on="school", how="left")

    keep = [
        c
        for c in [
            "college_name_key",
            "playerId",
            "player",
            "team",
            "college_season",
            "college_final_games",
            "college_final_pass_attempts",
            "college_final_pass_yards",
            "college_final_pass_td",
            "college_final_yards_per_attempt",
            "college_final_rush_attempts",
            "college_final_rush_yards",
            "college_final_rush_td",
            "college_final_receptions",
            "college_final_rec_yards",
            "college_final_rec_td",
            "college_conference_tier",
        ]
        if c in frame.columns
    ]
    return frame.select(keep)


def load_draft_rookies(settings: Settings) -> pl.DataFrame:
    """Offensive players drafted in the target season."""
    draft_path = settings.path("cache_dir") / "nflverse" / "draft_picks.parquet"
    if not draft_path.is_file():
        raise FileNotFoundError(
            f"Missing {draft_path}. Run `ffpm data fetch-nfl` before fetch-rookies."
        )
    draft = pl.read_parquet(draft_path)
    rookies = draft.filter(
        (pl.col("season") == settings.target_season)
        & pl.col("position").is_in(["QB", "RB", "WR", "TE"])
    )
    rename_map: dict[str, str] = {}
    if "pfr_player_name" in rookies.columns:
        rename_map["pfr_player_name"] = "display_name"
    if "pick" in rookies.columns:
        rename_map["pick"] = "draft_pick"
    if "round" in rookies.columns:
        rename_map["round"] = "draft_round"
    if rename_map:
        rookies = rookies.rename(rename_map)

    if "display_name" not in rookies.columns:
        rookies = rookies.with_columns(pl.lit("Unknown Rookie").alias("display_name"))

    rookies = rookies.with_columns(
        pl.col("display_name")
        .map_elements(_normalise_name, return_dtype=pl.Utf8)
        .alias("college_name_key"),
        pl.lit(True).alias("rookie"),
        pl.lit(0).alias("experience_at_target_season"),
        pl.lit(1).alias("is_rookie_season"),
    )
    return rookies


def enrich_rookies_with_college(
    rookies: pl.DataFrame, college: pl.DataFrame | None
) -> pl.DataFrame:
    if college is None or college.is_empty() or "college_name_key" not in rookies.columns:
        return rookies

    if "cfb_player_id" in rookies.columns and "playerId" in college.columns:
        left = rookies.with_columns(pl.col("cfb_player_id").cast(pl.Utf8))
        right = college.with_columns(pl.col("playerId").cast(pl.Utf8))
        joined = left.join(
            right,
            left_on="cfb_player_id",
            right_on="playerId",
            how="left",
            suffix="_cfbd",
        )
        yard_col = (
            "college_final_rec_yards"
            if "college_final_rec_yards" in joined.columns
            else "college_final_pass_yards"
            if "college_final_pass_yards" in joined.columns
            else None
        )
        matched = int(joined.get_column(yard_col).is_not_null().sum()) if yard_col else 0
        if matched > 0:
            logger.info("Joined %d rookies to CFBD via cfb_player_id.", matched)
            return joined

    joined = rookies.join(college, on="college_name_key", how="left", suffix="_cfbd")
    yard_col = (
        "college_final_rec_yards"
        if "college_final_rec_yards" in joined.columns
        else "college_final_pass_yards"
        if "college_final_pass_yards" in joined.columns
        else None
    )
    matched = int(joined.get_column(yard_col).is_not_null().sum()) if yard_col else 0
    logger.info("Joined %d rookies to CFBD via normalised name.", matched)
    return joined


def has_college_cache(settings: Settings) -> bool:
    return (settings.path("processed_dir") / "college_player_season_stats.parquet").is_file()


def build_rookie_projection_rows(settings: Settings) -> tuple[pl.DataFrame, RookieModeLabel]:
    """Return enriched target-season draft rookies and the active rookie mode."""
    key_mode = detect_rookie_mode()
    rookies = load_draft_rookies(settings)
    college: pl.DataFrame | None = None
    mode: RookieModeLabel = "reduced"
    if key_mode == "full" and has_college_cache(settings):
        college = build_college_feature_lookup(settings)
        if college is not None:
            mode = "full"
        else:
            logger.warning("CFBD key present but college lookup empty; using reduced mode.")
    elif key_mode == "full":
        logger.warning(
            "Full rookie mode requested but no college parquet found. "
            "Run `ffpm data fetch-rookies` after setting CFBD_API_KEY."
        )

    enriched = enrich_rookies_with_college(rookies, college)

    if "draft_pick" in enriched.columns:
        enriched = enriched.with_columns(
            (1.0 / pl.col("draft_pick").cast(pl.Float64).clip(1, None)).alias(
                "draft_capital_inverse"
            ),
            pl.col("draft_pick").cast(pl.Float64).log1p().alias("draft_capital_log"),
        )

    # Persist a slim enrichment table for audits / re-runs.
    out = settings.path("processed_dir")
    out.mkdir(parents=True, exist_ok=True)
    enriched.write_parquet(out / "rookie_enrichment.parquet")
    return enriched, mode


def college_fields_present(row: dict) -> bool:
    """True when at least one college production field is populated."""
    keys = (
        "college_final_pass_attempts",
        "college_final_rush_attempts",
        "college_final_receptions",
        "college_final_pass_yards",
        "college_final_rush_yards",
        "college_final_rec_yards",
    )
    return any(row.get(k) is not None for k in keys)


def rookie_stat_priors(
    position: str, draft_pick: float | None, college_row: dict
) -> dict[str, float]:
    """Transparent opportunity priors for rookies without a trained rookie ML model.

    Uses draft capital as the primary lever and scales by available college volume.
    Labelled ``model_architecture=rookie`` in exports.
    """
    pick = float(draft_pick) if draft_pick and draft_pick > 0 else 180.0
    # Inverse-pick curve: early picks clearly ahead, mid-rounds still usable.
    capital = max(0.18, min(1.0, 1.0 / (1.0 + (pick - 1.0) / 55.0)))
    games = 15.0 * (0.85 + 0.15 * capital)

    if position == "QB":
        attempts = 450 * capital
        college_att = college_row.get("college_final_pass_attempts")
        if college_att:
            attempts = 0.6 * attempts + 0.4 * min(float(college_att), 600.0)
        ypa = float(college_row.get("college_final_yards_per_attempt") or 7.2)
        ypa = max(5.5, min(9.5, ypa))
        return {
            "games": games,
            "pass_attempts": attempts,
            "completions": attempts * 0.64,
            "passing_yards": attempts * ypa,
            "passing_tds": attempts * 0.045,
            "interceptions": attempts * 0.022,
            "carries": 30 * capital,
            "rushing_yards": 140 * capital,
            "rushing_tds": 1.5 * capital,
            "fumbles_lost": 0.6,
        }
    if position == "RB":
        carries = 180 * capital
        targets = 35 * capital
        college_rush = college_row.get("college_final_rush_attempts")
        if college_rush:
            carries = 0.55 * carries + 0.45 * min(float(college_rush) * 0.7, 280.0)
        return {
            "games": games,
            "carries": carries,
            "rushing_yards": carries * 4.2,
            "rushing_tds": 6 * capital,
            "targets": targets,
            "receptions": targets * 0.72,
            "receiving_yards": targets * 7.5,
            "receiving_tds": 1.5 * capital,
            "fumbles_lost": 0.7,
        }
    # WR / TE
    base_targets = (110 if position == "WR" else 70) * capital
    college_rec = college_row.get("college_final_receptions")
    if college_rec:
        base_targets = 0.55 * base_targets + 0.45 * min(float(college_rec) * 1.1, 160.0)
    ypt = 12.0 if position == "WR" else 10.0
    return {
        "games": games,
        "targets": base_targets,
        "receptions": base_targets * (0.62 if position == "WR" else 0.68),
        "receiving_yards": base_targets * ypt,
        "receiving_touchdowns": (6 if position == "WR" else 4) * capital,
        "receiving_tds": (6 if position == "WR" else 4) * capital,
        "carries": 2 * capital,
        "rushing_yards": 10 * capital,
        "rushing_tds": 0.1,
        "fumbles_lost": 0.4,
    }
