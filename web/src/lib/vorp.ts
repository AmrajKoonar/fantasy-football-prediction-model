import type { Position } from "./schemas";

export type LeagueSettings = {
  teams: number;
  qb: number;
  rb: number;
  wr: number;
  te: number;
  flex: number;
  superflex: number;
};

export const DEFAULT_LEAGUE: LeagueSettings = {
  teams: 12,
  qb: 1,
  rb: 2,
  wr: 2,
  te: 1,
  flex: 1,
  superflex: 0,
};

export type ScoredPlayer = {
  playerId: string;
  position: Position;
  points: number;
};

export function computeReplacementLevels(
  players: ScoredPlayer[],
  league: LeagueSettings,
): Record<Position, number> {
  const byPos: Record<Position, ScoredPlayer[]> = { QB: [], RB: [], WR: [], TE: [] };
  for (const player of players) {
    byPos[player.position].push(player);
  }
  (Object.keys(byPos) as Position[]).forEach((pos) => {
    byPos[pos].sort((a, b) => b.points - a.points || a.playerId.localeCompare(b.playerId));
  });

  const base: Record<Position, number> = {
    QB: league.teams * league.qb,
    RB: league.teams * league.rb,
    WR: league.teams * league.wr,
    TE: league.teams * league.te,
  };

  const flexDemand = league.teams * (league.flex + league.superflex);
  const remaining: ScoredPlayer[] = [];
  (["RB", "WR", "TE", "QB"] as Position[]).forEach((pos) => {
    const eligible =
      pos !== "QB" || league.superflex > 0;
    if (!eligible) return;
    remaining.push(...byPos[pos].slice(Math.floor(base[pos])));
  });
  remaining.sort((a, b) => b.points - a.points || a.playerId.localeCompare(b.playerId));
  const extra: Record<Position, number> = { QB: 0, RB: 0, WR: 0, TE: 0 };
  remaining.slice(0, flexDemand).forEach((player) => {
    extra[player.position] += 1;
  });

  const levels: Record<Position, number> = { QB: 0, RB: 0, WR: 0, TE: 0 };
  (Object.keys(byPos) as Position[]).forEach((pos) => {
    const rank = Math.max(1, Math.round(base[pos] + extra[pos]));
    const list = byPos[pos];
    if (!list.length) {
      levels[pos] = 0;
      return;
    }
    const idx = Math.min(rank - 1, list.length - 1);
    const window = list.slice(Math.max(0, idx - 1), Math.min(list.length, idx + 2));
    levels[pos] = window.reduce((sum, p) => sum + p.points, 0) / window.length;
  });
  return levels;
}

export function vorp(
  points: number,
  position: Position,
  levels: Record<Position, number>,
): number {
  return points - (levels[position] ?? 0);
}
