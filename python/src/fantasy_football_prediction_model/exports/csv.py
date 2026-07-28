"""CSV downloads for projections and rankings."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.projections.generate import ProjectionBundle

logger = get_logger(__name__)


def write_projection_csv(bundle: ProjectionBundle, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for player in bundle.players:
        stats = player.projected_stats
        rows.append(
            {
                "player_id": player.player_id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "overall_rank": player.fantasy.overall_rank,
                "position_rank": player.fantasy.position_rank,
                "tier": player.fantasy.tier,
                "ppr_points": player.fantasy.default_ppr_points,
                "points_per_game": player.fantasy.points_per_game,
                "vorp": player.fantasy.replacement_value,
                "low_ppr": player.range.low_ppr_points,
                "high_ppr": player.range.high_ppr_points,
                "confidence": player.confidence.score,
                "games": stats.games,
                "pass_attempts": stats.pass_attempts,
                "completions": stats.completions,
                "passing_yards": stats.passing_yards,
                "passing_touchdowns": stats.passing_touchdowns,
                "interceptions": stats.interceptions,
                "carries": stats.carries,
                "rushing_yards": stats.rushing_yards,
                "rushing_touchdowns": stats.rushing_touchdowns,
                "targets": stats.targets,
                "receptions": stats.receptions,
                "receiving_yards": stats.receiving_yards,
                "receiving_touchdowns": stats.receiving_touchdowns,
                "fumbles_lost": stats.fumbles_lost,
                "data_mode": bundle.data_mode,
                "model_version": bundle.model_version,
                "projection_season": bundle.projection_season,
            }
        )
    pl.DataFrame(rows).write_csv(path)
    logger.info("Wrote projection CSV to %s", path)
    return path
