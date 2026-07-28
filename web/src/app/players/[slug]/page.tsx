import Link from "next/link";
import { notFound } from "next/navigation";
import { loadPlayerBySlug, loadProjections } from "@/lib/data";
import { PositionBadge } from "@/components/position-badge";
import { formatPoints } from "@/lib/utils";

type Props = { params: Promise<{ slug: string }> };

export async function generateStaticParams() {
  const { players } = await loadProjections();
  return players.map((player) => ({ slug: player.slug }));
}

export async function generateMetadata({ params }: Props) {
  const { slug } = await params;
  const player = await loadPlayerBySlug(slug);
  return {
    title: player ? `${player.name} projection` : "Player",
  };
}

export default async function PlayerPage({ params }: Props) {
  const { slug } = await params;
  const player = await loadPlayerBySlug(slug);
  if (!player) notFound();
  const stats = player.projectedStats;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <div className="flex h-14 w-14 items-center justify-center rounded-full border border-border bg-card text-lg font-semibold">
              {player.shortName
                .split(" ")
                .map((part) => part[0])
                .join("")
                .slice(0, 2)}
            </div>
            <div>
              <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">
                {player.name}
              </h1>
              <div className="flex items-center gap-2 text-sm text-muted">
                <PositionBadge position={player.position} />
                <span>{player.team}</span>
                {player.rookie ? <span>Rookie</span> : null}
              </div>
            </div>
          </div>
        </div>
        <Link
          href={`/compare?ids=${player.playerId}`}
          className="rounded-md border border-border px-3 py-2 text-sm"
        >
          Compare
        </Link>
      </div>

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Overall rank", player.fantasy.overallRank],
          ["Position rank", player.fantasy.positionRank],
          ["Tier", player.fantasy.tier],
          ["PPR points", formatPoints(player.fantasy.defaultPprPoints)],
          ["PPG", formatPoints(player.fantasy.pointsPerGame)],
          ["VORP", formatPoints(player.fantasy.replacementValue)],
          ["Low", formatPoints(player.range.lowPprPoints)],
          ["High", formatPoints(player.range.highPprPoints)],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-lg border border-border bg-card p-4">
            <dt className="text-sm text-muted">{label}</dt>
            <dd className="text-xl font-semibold">{value}</dd>
          </div>
        ))}
      </dl>

      <section className="space-y-2">
        <h2 className="font-[family-name:var(--font-display)] text-2xl font-semibold">
          Projected stats
        </h2>
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="min-w-full text-sm">
            <tbody>
              {Object.entries(stats).map(([key, value]) =>
                value == null ? null : (
                  <tr key={key} className="border-b border-border/60">
                    <th className="px-3 py-2 text-left font-medium capitalize text-muted">
                      {key.replace(/([A-Z])/g, " $1")}
                    </th>
                    <td className="px-3 py-2 tabular-nums">{formatPoints(Number(value))}</td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-2 font-semibold">Why the model is optimistic</h2>
          <p className="text-sm text-muted">
            {player.explanation.optimisticNote || player.explanation.summary || "—"}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-2 font-semibold">Why the model is cautious</h2>
          <p className="text-sm text-muted">{player.explanation.cautiousNote || "—"}</p>
        </div>
      </section>

      <p className="text-sm text-muted">
        Confidence: {player.confidence.label} ({formatPoints(player.confidence.score, 2)}). Model{" "}
        {player.modelVersion}.
      </p>
    </div>
  );
}
