"""Manual projection overrides from ``data/manual/projection-overrides.csv``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.schemas import AdjustmentRecord, PlayerProjection

logger = get_logger(__name__)

#: Map override CSV field names → ProjectedStats attribute names.
STAT_ATTR: dict[str, str] = {
    "games": "games",
    "pass_attempts": "pass_attempts",
    "completions": "completions",
    "passing_yards": "passing_yards",
    "passing_tds": "passing_touchdowns",
    "passing_touchdowns": "passing_touchdowns",
    "interceptions": "interceptions",
    "carries": "carries",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_touchdowns",
    "rushing_touchdowns": "rushing_touchdowns",
    "targets": "targets",
    "receptions": "receptions",
    "receiving_yards": "receiving_yards",
    "receiving_tds": "receiving_touchdowns",
    "receiving_touchdowns": "receiving_touchdowns",
    "fumbles_lost": "fumbles_lost",
}

ROLE_MULTIPLIER_FIELDS: tuple[str, ...] = (
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
)


@dataclass(frozen=True)
class OverrideRow:
    player_id: str
    player_name: str | None
    field: str
    new_value: float
    reason: str
    source_note: str | None
    date_entered: str | None


def load_projection_overrides(path: Path) -> list[OverrideRow]:
    if not path.is_file():
        return []
    frame = pl.read_csv(path, infer_schema_length=1000)
    if frame.is_empty():
        return []
    required = {"player_id", "field", "new_value"}
    missing = required - set(frame.columns)
    if missing:
        logger.warning("Override file %s missing columns %s; ignoring.", path, sorted(missing))
        return []

    rows: list[OverrideRow] = []
    for item in frame.to_dicts():
        player_id = str(item.get("player_id") or "").strip()
        field = str(item.get("field") or "").strip()
        # Skip documented example placeholder rows.
        if player_id.startswith("00-000000"):
            continue
        if not player_id or not field:
            continue
        try:
            new_value = float(item["new_value"])
        except (TypeError, ValueError, KeyError):
            continue
        rows.append(
            OverrideRow(
                player_id=player_id,
                player_name=str(item["player_name"]) if item.get("player_name") else None,
                field=field,
                new_value=new_value,
                reason=str(item.get("reason") or "Manual override"),
                source_note=str(item["source_note"]) if item.get("source_note") else None,
                date_entered=str(item["date_entered"]) if item.get("date_entered") else None,
            )
        )
    logger.info("Loaded %d projection overrides from %s", len(rows), path)
    return rows


def _set_stat(player: PlayerProjection, field: str, value: float) -> float | None:
    attr = STAT_ATTR.get(field)
    if attr is None:
        return None
    before = getattr(player.projected_stats, attr)
    setattr(player.projected_stats, attr, float(value))
    return float(before) if before is not None else None


def apply_overrides_to_players(
    players: list[PlayerProjection],
    overrides: list[OverrideRow],
) -> list[PlayerProjection]:
    """Mutate players with overrides; preserve model values on ``model_projected_stats``."""
    if not overrides:
        return players

    by_id: dict[str, list[OverrideRow]] = {}
    by_name: dict[str, list[OverrideRow]] = {}
    for row in overrides:
        by_id.setdefault(row.player_id, []).append(row)
        if row.player_name:
            by_name.setdefault(row.player_name.lower(), []).append(row)

    for player in players:
        rows = list(by_id.get(player.player_id, []))
        if not rows:
            rows = list(by_name.get(player.name.lower(), []))
        if not rows:
            continue
        if player.model_projected_stats is None:
            player.model_projected_stats = player.projected_stats.model_copy(deep=True)

        for row in rows:
            if row.field == "role_multiplier":
                for field in ROLE_MULTIPLIER_FIELDS:
                    attr = STAT_ATTR[field]
                    current = getattr(player.projected_stats, attr)
                    if current is None:
                        continue
                    before = float(current)
                    after = before * row.new_value
                    setattr(player.projected_stats, attr, after)
                    player.adjustments.append(
                        AdjustmentRecord(
                            field=field,
                            model_value=before,
                            adjusted_value=after,
                            reason=row.reason,
                            source_note=row.source_note,
                            date_entered=row.date_entered,
                        )
                    )
                player.is_adjusted = True
                continue

            before = _set_stat(player, row.field, row.new_value)
            if before is None and row.field not in STAT_ATTR:
                logger.warning("Unknown override field %s for %s", row.field, player.player_id)
                continue
            player.adjustments.append(
                AdjustmentRecord(
                    field=row.field,
                    model_value=before if before is not None else 0.0,
                    adjusted_value=row.new_value,
                    reason=row.reason,
                    source_note=row.source_note,
                    date_entered=row.date_entered,
                )
            )
            player.is_adjusted = True
    return players


def stats_dict_from_player(player: PlayerProjection) -> dict[str, float | None]:
    stats = player.projected_stats
    return {
        "games": stats.games,
        "pass_attempts": stats.pass_attempts,
        "completions": stats.completions,
        "passing_yards": stats.passing_yards,
        "passing_tds": stats.passing_touchdowns,
        "interceptions": stats.interceptions,
        "carries": stats.carries,
        "rushing_yards": stats.rushing_yards,
        "rushing_tds": stats.rushing_touchdowns,
        "targets": stats.targets,
        "receptions": stats.receptions,
        "receiving_yards": stats.receiving_yards,
        "receiving_tds": stats.receiving_touchdowns,
        "fumbles_lost": stats.fumbles_lost,
    }


def rescore_after_overrides(
    players: list[PlayerProjection],
    score_fn: Callable[[dict[str, float | None]], float],
) -> None:
    for player in players:
        if not player.is_adjusted:
            continue
        points = float(score_fn(stats_dict_from_player(player)))
        player.fantasy.default_ppr_points = points
        games = max(float(player.projected_stats.games or 1.0), 1.0)
        player.fantasy.points_per_game = points / games
        band = 0.2
        player.range.low_ppr_points = points * (1 - band)
        player.range.median_ppr_points = points
        player.range.high_ppr_points = points * (1 + band)
