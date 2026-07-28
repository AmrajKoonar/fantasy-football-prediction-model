import Link from "next/link";
import { loadMetadata, loadProjections, loadRankings } from "@/lib/data";
import { formatPoints } from "@/lib/utils";
import { PositionBadge } from "@/components/position-badge";

export default async function HomePage() {
  const [meta, projections, rankings] = await Promise.all([
    loadMetadata(),
    loadProjections(),
    loadRankings(),
  ]);
  const top = rankings.slice(0, 8);
  const leaders = (["QB", "RB", "WR", "TE"] as const).map((pos) =>
    rankings.find((entry) => entry.position === pos),
  );

  return (
    <div className="space-y-10">
      <section className="grid gap-6 lg:grid-cols-[1.4fr_1fr] lg:items-end">
        <div className="space-y-4">
          <p className="text-sm uppercase tracking-[0.2em] text-muted">Open NFL analytics</p>
          <h1 className="font-[family-name:var(--font-display)] text-4xl font-semibold tracking-tight sm:text-5xl">
            Field Forecast
          </h1>
          <p className="max-w-2xl text-lg text-muted">
            Reproducible fantasy football projections for the {meta?.projectionSeason ?? 2026}{" "}
            season, built from free nflverse data through {meta?.sourceSeason ?? 2025}.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/rankings"
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground"
            >
              View rankings
            </Link>
            <Link
              href="/methodology"
              className="rounded-md border border-border px-4 py-2 text-sm font-medium"
            >
              Methodology
            </Link>
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-card p-4 text-sm">
          <div>
            <dt className="text-muted">Projection season</dt>
            <dd className="text-xl font-semibold">{meta?.projectionSeason ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-muted">Data through</dt>
            <dd className="text-xl font-semibold">{meta?.sourceSeason ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-muted">Model</dt>
            <dd className="font-medium">{meta?.modelVersion ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-muted">Players published</dt>
            <dd className="font-medium">{meta?.playerCount ?? projections.players.length}</dd>
          </div>
          <div className="col-span-2">
            <dt className="text-muted">Last updated</dt>
            <dd className="font-medium">
              {meta?.generatedAt ? new Date(meta.generatedAt).toLocaleString() : "—"}
            </dd>
          </div>
        </dl>
      </section>

      {projections.schemaMismatch ? (
        <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm">
          Schema version mismatch between the web app and generated data.
        </p>
      ) : null}

      <section className="space-y-3">
        <h2 className="font-[family-name:var(--font-display)] text-2xl font-semibold">
          Top projected players
        </h2>
        <ol className="divide-y divide-border rounded-lg border border-border bg-card">
          {top.map((entry) => (
            <li key={entry.playerId} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="flex items-center gap-3">
                <span className="w-6 text-sm text-muted">{entry.overallRank}</span>
                <PositionBadge position={entry.position} />
                <Link href={`/players/${entry.slug}`} className="font-medium hover:underline">
                  {entry.name}
                </Link>
                <span className="text-sm text-muted">{entry.team}</span>
              </div>
              <span className="tabular-nums">{formatPoints(entry.pprPoints)} PPR</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="space-y-3">
        <h2 className="font-[family-name:var(--font-display)] text-2xl font-semibold">
          Position leaders
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {leaders.map((entry) =>
            entry ? (
              <Link
                key={entry.playerId}
                href={`/players/${entry.slug}`}
                className="rounded-lg border border-border bg-card p-4 transition hover:border-accent"
              >
                <div className="mb-2 flex items-center gap-2">
                  <PositionBadge position={entry.position} />
                  <span className="text-sm text-muted">{entry.team}</span>
                </div>
                <p className="font-medium">{entry.name}</p>
                <p className="text-sm text-muted">{formatPoints(entry.pprPoints)} PPR</p>
              </Link>
            ) : null,
          )}
        </div>
      </section>

      <p className="text-sm text-muted">
        Projections are estimates for informational and entertainment use. See{" "}
        <Link href="/about" className="underline">
          About
        </Link>{" "}
        and{" "}
        <Link href="/sources" className="underline">
          Sources
        </Link>
        .
      </p>
    </div>
  );
}
