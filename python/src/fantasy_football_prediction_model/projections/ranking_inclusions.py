"""Auditable manual inclusions for fantasy-relevant ranking coverage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.schemas import PlayerProjection, PlayerWarning

logger = get_logger(__name__)


@dataclass(frozen=True)
class RankingInclusion:
    """One player who must remain visible even when the model rank misses the output cut."""

    player_id: str
    player_name: str | None
    reason: str
    source_note: str | None
    date_entered: str | None
    reference_rank: int | None
    allow_unsigned: bool = False


def _as_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def load_ranking_inclusions(path: Path) -> list[RankingInclusion]:
    """Load committed, non-statistical ranking coverage directives."""
    if not path.is_file():
        return []
    frame = pl.read_csv(path, infer_schema_length=1000)
    if frame.is_empty():
        return []
    if "player_id" not in frame.columns:
        logger.warning("Ranking inclusion file %s has no player_id column; ignoring.", path)
        return []

    inclusions: list[RankingInclusion] = []
    seen: set[str] = set()
    for row in frame.to_dicts():
        player_id = str(row.get("player_id") or "").strip()
        if not player_id or player_id in seen:
            continue
        rank_raw = row.get("reference_rank")
        try:
            reference_rank = int(rank_raw) if rank_raw is not None else None
        except (TypeError, ValueError):
            reference_rank = None
        inclusions.append(
            RankingInclusion(
                player_id=player_id,
                player_name=str(row["player_name"]) if row.get("player_name") else None,
                reason=str(row.get("reason") or "Manual ranking coverage inclusion"),
                source_note=str(row["source_note"]) if row.get("source_note") else None,
                date_entered=str(row["date_entered"]) if row.get("date_entered") else None,
                reference_rank=reference_rank,
                allow_unsigned=_as_bool(row.get("allow_unsigned")),
            )
        )
        seen.add(player_id)
    logger.info("Loaded %d ranking inclusions from %s.", len(inclusions), path)
    return inclusions


def select_published_players(
    ranked_players: list[PlayerProjection],
    inclusions: list[RankingInclusion],
    *,
    limit: int,
) -> tuple[list[PlayerProjection], list[str]]:
    """Return the model top-N plus configured fantasy-relevant coverage exceptions.

    The published list can be longer than ``limit``. Display ranks are made dense
    after selection, while every player's full-pool model rank is retained in
    ``context.modelOverallRank``. Forced rows also surface that rank in a warning.
    """
    published = list(ranked_players[:limit])
    published_ids = {player.player_id for player in published}
    all_by_id = {player.player_id: player for player in ranked_players}
    warnings: list[str] = []

    for inclusion in inclusions:
        if inclusion.player_id in published_ids:
            continue
        player = all_by_id.get(inclusion.player_id)
        if player is None:
            warnings.append(
                f"Ranking inclusion missing from candidate pool: "
                f"{inclusion.player_name or inclusion.player_id}."
            )
            continue

        model_rank = player.fantasy.overall_rank
        details = inclusion.reason
        if inclusion.reference_rank is not None:
            details += f" Reference PPR rank: {inclusion.reference_rank}."
        player.warnings.append(
            PlayerWarning(
                code="ranking_coverage_inclusion",
                severity="warning",
                message=(
                    f"Published outside the model top-{limit} for coverage. "
                    f"Full-pool model rank: {model_rank}. {details}"
                ),
            )
        )
        published.append(player)
        published_ids.add(player.player_id)

    published.sort(key=lambda player: player.fantasy.overall_rank)
    forced_count = max(len(published) - min(limit, len(ranked_players)), 0)
    if forced_count:
        warnings.append(
            f"Published {forced_count} manual ranking coverage inclusion(s) outside "
            f"the model top-{limit}; full-pool model ranks are preserved in player context."
        )

    position_counts: dict[str, int] = {}
    for overall_rank, player in enumerate(published, start=1):
        player.context["modelOverallRank"] = float(player.fantasy.overall_rank)
        player.fantasy.overall_rank = overall_rank
        position_counts[player.position] = position_counts.get(player.position, 0) + 1
        player.fantasy.position_rank = position_counts[player.position]
    return published, warnings
