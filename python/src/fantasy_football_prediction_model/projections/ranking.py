"""Overall, positional and risk-adjusted rankings with gap tiers."""

from __future__ import annotations

from dataclasses import dataclass, field

from fantasy_football_prediction_model.config import LeagueConfig
from fantasy_football_prediction_model.constants import FANTASY_POSITIONS
from fantasy_football_prediction_model.projections.replacement_value import (
    PlayerPoints,
    ReplacementLevels,
    compute_replacement_levels,
    vorp,
)


@dataclass
class RankablePlayer:
    player_id: str
    position: str
    points: float
    points_per_game: float
    low_points: float
    high_points: float
    confidence: float = 0.5
    name: str = ""


@dataclass
class RankedPlayer:
    player_id: str
    position: str
    points: float
    points_per_game: float
    vorp: float
    risk_adjusted_value: float
    overall_rank: int
    position_rank: int
    points_rank: int
    points_per_game_rank: int
    vorp_rank: int
    risk_adjusted_rank: int
    tier: int
    low_points: float
    high_points: float


@dataclass
class RankingResult:
    players: list[RankedPlayer] = field(default_factory=list)
    replacement: ReplacementLevels | None = None


def _tie_key(player: RankablePlayer, vorp_value: float, risk_value: float) -> tuple:
    interval = max(player.high_points - player.low_points, 0.0)
    return (
        -vorp_value,
        -player.points_per_game,
        -player.points,
        interval,
        player.player_id,
    )


def assign_gap_tiers(
    sorted_vorp: list[float],
    *,
    gap_sigma: float = 1.0,
    max_tiers: int = 10,
    min_tier_size: int = 2,
) -> list[int]:
    """Assign tiers by drops in VORP relative to observed gap dispersion."""
    n = len(sorted_vorp)
    if n == 0:
        return []
    tiers = [1] * n
    if n == 1:
        return tiers
    gaps = [sorted_vorp[i] - sorted_vorp[i + 1] for i in range(n - 1)]
    mean_gap = sum(gaps) / len(gaps)
    var = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
    std = var**0.5
    threshold = mean_gap + gap_sigma * std if std > 1e-9 else mean_gap * 1.5
    current_tier = 1
    current_size = 1
    for i, gap in enumerate(gaps):
        if (
            gap > threshold
            and current_size >= min_tier_size
            and current_tier < max_tiers
        ):
            current_tier += 1
            current_size = 1
        else:
            current_size += 1
        tiers[i + 1] = current_tier
    return tiers


def rank_players(
    players: list[RankablePlayer],
    league: LeagueConfig,
) -> RankingResult:
    """Produce dense overall and positional ranks with VORP-based draft order."""
    if not players:
        return RankingResult()

    replacement = compute_replacement_levels(
        [PlayerPoints(p.player_id, p.position, p.points) for p in players],
        league,
    )
    penalty = league.risk.penalty_weight

    enriched: list[tuple[RankablePlayer, float, float]] = []
    for player in players:
        value = vorp(player.points, player.position, replacement)
        downside = max(player.points - player.low_points, 0.0) / 2.0
        risk_value = value - penalty * downside
        enriched.append((player, value, risk_value))

    draft_order = sorted(enriched, key=lambda item: _tie_key(item[0], item[1], item[2]))
    points_order = sorted(enriched, key=lambda item: (-item[0].points, item[0].player_id))
    ppg_order = sorted(
        enriched, key=lambda item: (-item[0].points_per_game, item[0].player_id)
    )
    vorp_order = sorted(enriched, key=lambda item: (-item[1], item[0].player_id))
    risk_order = sorted(enriched, key=lambda item: (-item[2], item[0].player_id))

    points_rank = {p.player_id: i + 1 for i, (p, _, _) in enumerate(points_order)}
    ppg_rank = {p.player_id: i + 1 for i, (p, _, _) in enumerate(ppg_order)}
    vorp_rank = {p.player_id: i + 1 for i, (p, _, _) in enumerate(vorp_order)}
    risk_rank = {p.player_id: i + 1 for i, (p, _, _) in enumerate(risk_order)}

    tiers = assign_gap_tiers(
        [v for _, v, _ in draft_order],
        gap_sigma=league.tiers.gap_sigma,
        max_tiers=league.tiers.max_tiers,
        min_tier_size=league.tiers.min_tier_size,
    )

    pos_counters = {pos: 0 for pos in FANTASY_POSITIONS}
    ranked: list[RankedPlayer] = []
    for overall, ((player, value, risk_value), tier) in enumerate(
        zip(draft_order, tiers, strict=True), start=1
    ):
        pos_counters[player.position] = pos_counters.get(player.position, 0) + 1
        ranked.append(
            RankedPlayer(
                player_id=player.player_id,
                position=player.position,
                points=player.points,
                points_per_game=player.points_per_game,
                vorp=value,
                risk_adjusted_value=risk_value,
                overall_rank=overall,
                position_rank=pos_counters[player.position],
                points_rank=points_rank[player.player_id],
                points_per_game_rank=ppg_rank[player.player_id],
                vorp_rank=vorp_rank[player.player_id],
                risk_adjusted_rank=risk_rank[player.player_id],
                tier=tier,
                low_points=player.low_points,
                high_points=player.high_points,
            )
        )
    return RankingResult(players=ranked, replacement=replacement)
