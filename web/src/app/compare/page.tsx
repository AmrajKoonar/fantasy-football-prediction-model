import Link from "next/link";
import { loadProjections } from "@/lib/data";
import { PositionBadge } from "@/components/position-badge";
import { RookieBadge } from "@/components/rookie-badge";
import { cn, formatPoints } from "@/lib/utils";

type Props = { searchParams: Promise<{ ids?: string }> };

export const metadata = { title: "Compare" };

export default async function ComparePage({ searchParams }: Props) {
  const params = await searchParams;
  const ids = (params.ids ?? "").split(",").filter(Boolean).slice(0, 4);
  const { players } = await loadProjections();
  const selected = players.filter((player) => ids.includes(player.playerId));
  const options = players.slice(0, 40);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">Compare</h1>
        <p className="text-muted">Compare two to four players side by side. Share via URL.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {options.map((player) => {
          const active = ids.includes(player.playerId);
          const next = active
            ? ids.filter((id) => id !== player.playerId)
            : [...ids, player.playerId].slice(0, 4);
          return (
            <Link
              key={player.playerId}
              href={`/compare?ids=${next.join(",")}`}
              className={`rounded-md border px-2 py-1 text-xs ${
                active ? "border-accent bg-accent/10" : "border-border"
              }`}
            >
              {player.shortName}
            </Link>
          );
        })}
      </div>

      {!selected.length ? (
        <p className="text-sm text-muted">Select players above to begin a comparison.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted">
                <th className="px-3 py-2 text-left">Metric</th>
                {selected.map((player) => (
                  <th key={player.playerId} className="px-3 py-2 text-left">
                    <div className="flex items-center gap-2">
                      <PositionBadge position={player.position} />
                      <Link href={`/players/${player.slug}`} className="hover:underline">
                        {player.name}
                      </Link>
                      {player.rookie ? <RookieBadge /> : null}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                ["Team", (p: (typeof selected)[number]) => p.team],
                ["Overall rank", (p: (typeof selected)[number]) => p.fantasy.overallRank],
                ["PPR points", (p: (typeof selected)[number]) => formatPoints(p.fantasy.defaultPprPoints)],
                ["PPG", (p: (typeof selected)[number]) => formatPoints(p.fantasy.pointsPerGame)],
                ["VORP", (p: (typeof selected)[number]) => formatPoints(p.fantasy.replacementValue)],
                ["Low", (p: (typeof selected)[number]) => formatPoints(p.range.lowPprPoints)],
                ["High", (p: (typeof selected)[number]) => formatPoints(p.range.highPprPoints)],
                ["Confidence", (p: (typeof selected)[number]) => p.confidence.label],
                ["Games", (p: (typeof selected)[number]) => formatPoints(p.projectedStats.games)],
                ["Targets", (p: (typeof selected)[number]) => formatPoints(p.projectedStats.targets ?? null)],
                ["Carries", (p: (typeof selected)[number]) => formatPoints(p.projectedStats.carries ?? null)],
                ["Pass attempts", (p: (typeof selected)[number]) => formatPoints(p.projectedStats.passAttempts ?? null)],
              ].map(([label, getter], index) => (
                <tr
                  key={String(label)}
                  className={cn(
                    "border-b border-border/60",
                    index % 2 === 1 && "bg-[color:var(--row-band)]",
                  )}
                >
                  <th className="px-3 py-2 text-left font-medium text-muted">{label as string}</th>
                  {selected.map((player) => (
                    <td key={player.playerId} className="px-3 py-2 tabular-nums">
                      {(getter as (p: (typeof selected)[number]) => string | number)(player)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
