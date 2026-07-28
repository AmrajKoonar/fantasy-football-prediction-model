"""Value-over-replacement calculations."""

from __future__ import annotations

from dataclasses import dataclass

from fantasy_football_prediction_model.config import LeagueConfig, ReplacementSettings
from fantasy_football_prediction_model.constants import FANTASY_POSITIONS, FLEX_POSITIONS
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class PlayerPoints:
    player_id: str
    position: str
    points: float


@dataclass(slots=True)
class ReplacementLevels:
    levels: dict[str, float]
    ranks: dict[str, int]
    method: str


def starter_demand(league: LeagueConfig) -> dict[str, float]:
    """Base starter demand before flex allocation."""
    teams = league.league.teams
    starters = league.league.starters
    return {
        "QB": teams * starters.qb,
        "RB": teams * starters.rb,
        "WR": teams * starters.wr,
        "TE": teams * starters.te,
    }


def allocate_flex_demand(
    ranked_by_position: dict[str, list[PlayerPoints]],
    league: LeagueConfig,
) -> dict[str, float]:
    """Distribute flex (+ superflex) demand across eligible positions.

    Remaining players after base starters are pooled by points. The top
    ``flex_demand`` remaining flex-eligible players determine how many
    replacement slots each position absorbs. Deterministic and documented.
    """
    demand = starter_demand(league)
    flex_slots = league.league.teams * (
        league.league.starters.flex + league.league.starters.superflex
    )
    remaining: list[PlayerPoints] = []
    for position, players in ranked_by_position.items():
        start = int(demand.get(position, 0))
        # Superflex also considers QBs beyond the QB starter demand.
        eligible = position in FLEX_POSITIONS or (
            position == "QB" and league.league.starters.superflex > 0
        )
        if not eligible:
            continue
        remaining.extend(players[start:])
    remaining.sort(key=lambda p: (-p.points, p.player_id))
    flex_taken = remaining[: int(flex_slots)]
    extra = {pos: 0.0 for pos in FANTASY_POSITIONS}
    for player in flex_taken:
        extra[player.position] = extra.get(player.position, 0.0) + 1.0
    return {pos: demand.get(pos, 0.0) + extra.get(pos, 0.0) for pos in FANTASY_POSITIONS}


def compute_replacement_levels(
    players: list[PlayerPoints],
    league: LeagueConfig,
) -> ReplacementLevels:
    """Compute replacement fantasy points by position."""
    settings: ReplacementSettings = league.replacement
    by_pos: dict[str, list[PlayerPoints]] = {pos: [] for pos in FANTASY_POSITIONS}
    for player in players:
        if player.position in by_pos:
            by_pos[player.position].append(player)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: (-p.points, p.player_id))

    if settings.method == "fixed_rank":
        ranks = dict(settings.fixed_rank)
    else:
        demand = allocate_flex_demand(by_pos, league)
        ranks = {pos: max(int(round(demand[pos])), 1) for pos in FANTASY_POSITIONS}
        # Sanity floor from fixed_rank when a position is thin.
        for pos, floor in settings.fixed_rank.items():
            ranks[pos] = max(ranks.get(pos, floor), 1)

    window = max(settings.smoothing_window, 1)
    levels: dict[str, float] = {}
    for pos, players_at_pos in by_pos.items():
        if len(players_at_pos) < settings.min_players_per_position:
            levels[pos] = players_at_pos[-1].points if players_at_pos else 0.0
            continue
        rank = min(ranks.get(pos, len(players_at_pos)), len(players_at_pos))
        start = max(rank - window // 2 - 1, 0)
        end = min(start + window, len(players_at_pos))
        slice_players = players_at_pos[start:end]
        levels[pos] = sum(p.points for p in slice_players) / max(len(slice_players), 1)

    logger.debug("Replacement levels: %s (ranks=%s)", levels, ranks)
    return ReplacementLevels(levels=levels, ranks=ranks, method=settings.method)


def vorp(points: float, position: str, levels: ReplacementLevels) -> float:
    return float(points - levels.levels.get(position, 0.0))
