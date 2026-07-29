"use client";

import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import type { PlayerProjection, RankingEntry } from "@/lib/schemas";
import { PositionBadge } from "@/components/position-badge";
import { RookieBadge } from "@/components/rookie-badge";
import { cn, formatPoints } from "@/lib/utils";
import { getPreset, scoreStats } from "@/lib/scoring";
import { DEFAULT_LEAGUE, computeReplacementLevels, vorp, type LeagueSettings } from "@/lib/vorp";

type Props = {
  rankings: RankingEntry[];
  players: PlayerProjection[];
};

type SortKey = "overall" | "points" | "ppg" | "vorp" | "confidence";

export function RankingsTable({ rankings, players }: Props) {
  const byId = useMemo(() => new Map(players.map((p) => [p.playerId, p])), [players]);
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState("ALL");
  const [rookie, setRookie] = useState("ALL");
  const [preset, setPreset] = useState("ppr");
  const [sortKey, setSortKey] = useState<SortKey>("overall");
  const [superflex, setSuperflex] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [league] = useState<LeagueSettings>(DEFAULT_LEAGUE);

  const rows = useMemo(() => {
    const rules = getPreset(preset);
    const leagueSettings = { ...league, superflex: superflex ? 1 : league.superflex };
    const scored = rankings.map((entry) => {
      const player = byId.get(entry.playerId);
      const points = player ? scoreStats(player.projectedStats, rules) : entry.pprPoints;
      return { entry, player, points };
    });
    const levels = computeReplacementLevels(
      scored.map((row) => ({
        playerId: row.entry.playerId,
        position: row.entry.position,
        points: row.points,
      })),
      leagueSettings,
    );
    const withVorp = scored.map((row) => ({
      ...row,
      vorp: vorp(row.points, row.entry.position, levels),
      ppg: row.points / Math.max(row.entry.games, 1),
    }));
    let filtered = withVorp.filter((row) => {
      if (position !== "ALL" && row.entry.position !== position) return false;
      if (rookie === "YES" && !row.entry.rookie) return false;
      if (rookie === "NO" && row.entry.rookie) return false;
      if (query && !row.entry.name.toLowerCase().includes(query.toLowerCase())) return false;
      return true;
    });
    filtered = [...filtered].sort((a, b) => {
      if (sortKey === "points") return b.points - a.points;
      if (sortKey === "ppg") return b.ppg - a.ppg;
      if (sortKey === "vorp") return b.vorp - a.vorp;
      if (sortKey === "confidence") return b.entry.confidenceScore - a.entry.confidenceScore;
      return b.vorp - a.vorp || b.ppg - a.ppg || a.entry.playerId.localeCompare(b.entry.playerId);
    });
    return filtered.map((row, index) => ({ ...row, displayRank: index + 1 }));
  }, [rankings, byId, query, position, rookie, preset, sortKey, superflex, league]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-lg border border-border bg-card p-4 md:grid-cols-3 lg:grid-cols-6">
        <label className="text-sm">
          <span className="mb-1 block text-muted">Search</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5"
            placeholder="Player name"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted">Position</span>
          <select
            aria-label="Position"
            value={position}
            onChange={(e) => setPosition(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5"
          >
            {["ALL", "QB", "RB", "WR", "TE"].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted">Rookies</span>
          <select
            value={rookie}
            onChange={(e) => setRookie(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5"
          >
            <option value="ALL">All</option>
            <option value="YES">Rookies only</option>
            <option value="NO">Veterans only</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted">Scoring</span>
          <select
            aria-label="Scoring"
            value={preset}
            onChange={(e) => setPreset(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5"
          >
            <option value="ppr">Full PPR</option>
            <option value="half_ppr">Half PPR</option>
            <option value="standard">Standard</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted">Sort</span>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5"
          >
            <option value="overall">Draft value (VORP)</option>
            <option value="points">Projected points</option>
            <option value="ppg">Points per game</option>
            <option value="vorp">VORP</option>
            <option value="confidence">Confidence</option>
          </select>
        </label>
        <label className="flex items-end gap-2 text-sm">
          <input
            type="checkbox"
            checked={superflex}
            onChange={(e) => setSuperflex(e.target.checked)}
          />
          Superflex
        </label>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="min-w-full text-left text-sm">
          <caption className="sr-only">Fantasy football draft rankings</caption>
          <thead className="sticky top-0 z-10 bg-card">
            <tr className="border-b border-border text-muted">
              <th className="px-3 py-2">Rank</th>
              <th className="px-3 py-2">Player</th>
              <th className="px-3 py-2">Pos</th>
              <th className="px-3 py-2">Tier</th>
              <th className="px-3 py-2">Pts</th>
              <th className="px-3 py-2">PPG</th>
              <th className="px-3 py-2">VORP</th>
              <th className="px-3 py-2">Range</th>
              <th className="px-3 py-2">Conf</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const banded = index % 2 === 1;
              return (
                <Fragment key={row.entry.playerId}>
                  <tr
                    className={cn(
                      "border-b border-border/60 transition-colors hover:bg-accent/10",
                      banded ? "bg-[color:var(--row-band)]" : "bg-transparent",
                    )}
                  >
                    <td className="px-3 py-2 tabular-nums">{row.displayRank}</td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          className="text-left font-medium leading-none hover:underline"
                          onClick={() =>
                            setExpanded(
                              expanded === row.entry.playerId ? null : row.entry.playerId,
                            )
                          }
                        >
                          {row.entry.name}
                        </button>
                        {row.entry.rookie ? <RookieBadge /> : null}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
                        <span>{row.entry.team}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <PositionBadge position={row.entry.position} />
                      <span className="ml-2 text-xs text-muted">{row.entry.positionRank}</span>
                    </td>
                    <td className="px-3 py-2">{row.entry.tier}</td>
                    <td className="px-3 py-2 tabular-nums">{formatPoints(row.points)}</td>
                    <td className="px-3 py-2 tabular-nums">{formatPoints(row.ppg)}</td>
                    <td className="px-3 py-2 tabular-nums">{formatPoints(row.vorp)}</td>
                    <td className="px-3 py-2 tabular-nums text-xs text-muted">
                      {formatPoints(row.entry.pprPoints * 0.85)}-
                      {formatPoints(row.entry.pprPoints * 1.15)}
                    </td>
                    <td className="px-3 py-2 capitalize">{row.entry.confidenceLabel}</td>
                  </tr>
                  {expanded === row.entry.playerId && row.player ? (
                    <tr
                      className={cn(
                        "border-b border-border/60",
                        banded ? "bg-[color:var(--row-band)]" : "bg-accent/5",
                      )}
                    >
                      <td colSpan={9} className="px-4 py-3 text-sm">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <p className="max-w-3xl text-muted">
                            {row.player.explanation.summary || "No explanation available."}
                          </p>
                          <div className="flex gap-2">
                            <Link
                              href={`/players/${row.entry.slug}`}
                              className="rounded-md border border-border px-3 py-1"
                            >
                              Player page
                            </Link>
                            <Link
                              href={`/compare?ids=${row.entry.playerId}`}
                              className="rounded-md border border-border px-3 py-1"
                            >
                              Compare
                            </Link>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {!rows.length ? (
        <p className="text-sm text-muted">No players match the current filters.</p>
      ) : null}
    </div>
  );
}
