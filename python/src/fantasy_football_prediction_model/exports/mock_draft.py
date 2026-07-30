"""Build the broad, versioned player pool used by persistent mock drafts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from fantasy_football_prediction_model.config import Settings
from fantasy_football_prediction_model.projections.generate import ProjectionBundle

NFL_TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LV", "LAC", "LA", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]
BASELINE_POSITIONS = {"K", "DL", "LB", "DB"}


def _stable_unit(value: str) -> float:
    return int(hashlib.sha256(value.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _latest(cache_dir: Path, prefix: str) -> Path | None:
    matches = sorted((cache_dir / "nflverse").glob(f"{prefix}*.parquet"))
    return matches[-1] if matches else None


def _baseline_points(stats: dict[str, Any], position: str, player_id: str) -> float:
    if position == "K":
        return round(
            float(stats.get("fg_made") or 0) * 3
            + float(stats.get("fg_made_50_59") or 0)
            + float(stats.get("fg_made_60_") or 0) * 2
            + float(stats.get("pat_made") or 0),
            2,
        )
    points = (
        float(stats.get("def_tackles_solo") or 0) * 1.5
        + float(stats.get("def_tackle_assists") or 0) * 0.75
        + float(stats.get("def_sacks") or 0) * 4
        + float(stats.get("def_interceptions") or 0) * 5
        + float(stats.get("def_fumbles_forced") or 0) * 3
        + float(stats.get("def_fumbles") or 0) * 3
        + float(stats.get("def_pass_defended") or 0)
        + float(stats.get("def_tds") or 0) * 6
        + float(stats.get("def_safeties") or 0) * 2
    )
    if points <= 0:
        points = {"LB": 82, "DL": 72, "DB": 68}.get(position, 60) + _stable_unit(player_id) * 18
    return round(points, 2)


def build_mock_draft_pool(bundle: ProjectionBundle, settings: Settings) -> dict[str, Any]:
    """Return 600+ offense, special-team, and IDP entries.

    Veteran K/IDP values use the latest completed season's nflverse defensive and
    kicking stats as transparent baselines. Team defense values are intentionally
    conservative and deterministic because the projection model is player based.
    """
    players: list[dict[str, Any]] = []
    seen: set[str] = set()
    position_counts: dict[str, int] = {}

    def add(entry: dict[str, Any]) -> None:
        if entry["playerId"] in seen:
            return
        seen.add(entry["playerId"])
        position = entry["primaryPosition"]
        position_counts[position] = position_counts.get(position, 0) + 1
        entry["positionRank"] = position_counts[position]
        entry["overallRank"] = len(players) + 1
        entry["adp"] = round(float(entry.get("adp") or entry["overallRank"]), 2)
        players.append(entry)

    for player in sorted(bundle.players, key=lambda item: item.fantasy.overall_rank):
        add(
            {
                "playerId": player.player_id,
                "name": player.name,
                "team": player.team or "FA",
                "primaryPosition": player.position,
                "eligiblePositions": [player.position],
                "rookie": player.rookie,
                "age": player.age,
                "overallRank": 1,
                "positionRank": 1,
                "tier": player.fantasy.tier,
                "projectedPoints": round(player.fantasy.default_ppr_points, 2),
                "pointsPerGame": round(player.fantasy.points_per_game, 2),
                "adp": player.fantasy.overall_rank,
                "source": "projection",
            }
        )

    cache = settings.path("cache_dir")
    roster_path = _latest(cache, "rosters-")
    stats_path = _latest(cache, "player_stats_week-")
    if roster_path:
        rosters = (
            pl.read_parquet(roster_path)
            .filter(
                (pl.col("season") == settings.target_season)
                & pl.col("position").is_in(list(BASELINE_POSITIONS))
                & pl.col("gsis_id").is_not_null()
            )
            .unique("gsis_id", keep="last")
        )
        stats_by_id: dict[str, dict[str, Any]] = {}
        if stats_path:
            stat_columns = [
                "fg_made", "fg_made_50_59", "fg_made_60_", "pat_made",
                "def_tackles_solo", "def_tackle_assists", "def_sacks",
                "def_interceptions", "def_fumbles_forced", "def_fumbles",
                "def_pass_defended", "def_tds", "def_safeties",
            ]
            stats = (
                pl.read_parquet(stats_path)
                .filter(pl.col("season") == settings.feature_end_season)
                .group_by("player_id")
                .agg([pl.col(column).sum() for column in stat_columns])
            )
            stats_by_id = {str(row["player_id"]): row for row in stats.to_dicts()}

        baseline: list[dict[str, Any]] = []
        for row in rosters.to_dicts():
            player_id = str(row["gsis_id"])
            position = str(row["position"])
            points = _baseline_points(stats_by_id.get(player_id, {}), position, player_id)
            games = 17
            birth_date = row.get("birth_date")
            age = None
            if birth_date:
                try:
                    age = settings.target_season - int(str(birth_date)[:4])
                except ValueError:
                    age = None
            baseline.append(
                {
                    "playerId": player_id,
                    "name": str(row.get("full_name") or row.get("football_name") or player_id),
                    "team": str(row.get("team") or "FA"),
                    "primaryPosition": position,
                    "eligiblePositions": [position],
                    "rookie": int(row.get("years_exp") or 0) == 0,
                    "age": age,
                    "overallRank": 1,
                    "positionRank": 1,
                    "tier": 10,
                    "projectedPoints": points,
                    "pointsPerGame": round(points / games, 2),
                    "adp": 999,
                    "source": "roster-baseline",
                }
            )
        baseline.sort(key=lambda entry: (-entry["projectedPoints"], entry["name"]))
        baseline_limits = {"K": 40, "DL": 60, "LB": 60, "DB": 60}
        baseline_added: dict[str, int] = {}
        for entry in baseline:
            baseline_position = entry["primaryPosition"]
            if baseline_added.get(baseline_position, 0) >= baseline_limits[baseline_position]:
                continue
            entry["tier"] = max(1, 1 + position_counts.get(entry["primaryPosition"], 0) // 12)
            add(entry)
            baseline_added[baseline_position] = baseline_added.get(baseline_position, 0) + 1

    for team_index, team in enumerate(NFL_TEAMS):
        points = round(112 - team_index * 0.7 + _stable_unit(team) * 8, 2)
        add(
            {
                "playerId": f"DEF-{team}",
                "name": f"{team} Defense",
                "team": team,
                "primaryPosition": "DEF",
                "eligiblePositions": ["DEF"],
                "rookie": False,
                "age": None,
                "overallRank": 1,
                "positionRank": 1,
                "tier": 1 + team_index // 8,
                "projectedPoints": points,
                "pointsPerGame": round(points / 17, 2),
                "adp": 999,
                "source": "team-defense",
            }
        )

    return {
        "schemaVersion": "1.0.0",
        "generatedAt": datetime.now(UTC).isoformat(),
        "projectionSeason": settings.target_season,
        "source": "Fantasy Analytics projections + nflverse prior-season baselines",
        "players": players,
    }
