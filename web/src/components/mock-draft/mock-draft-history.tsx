"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ensureAnonymousUser, getSupabase } from "@/lib/supabase";

type HistoryRow = {
  draft: {
    id: string;
    public_slug: string;
    name: string;
    format: string;
    scoring_preset: string;
    team_count: number;
    rounds: number;
    completed_at: string;
  };
  total_count: number;
};

export function MockDraftHistory() {
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [page, setPage] = useState(1);
  const [format, setFormat] = useState("");
  const [scoring, setScoring] = useState("");
  const [status, setStatus] = useState("Loading completed drafts…");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setStatus("Loading completed drafts…");
      try {
        await ensureAnonymousUser();
        const result = await getSupabase().rpc("list_completed_drafts", {
          page_no: page,
          page_size: 12,
          format_filter: format || null,
          scoring_filter: scoring || null,
        });
        if (result.error) throw result.error;
        if (!cancelled) {
          setRows((result.data ?? []) as HistoryRow[]);
          setStatus(result.data?.length ? "" : "No completed drafts match these filters yet.");
        }
      } catch (error) {
        if (!cancelled) setStatus(error instanceof Error ? error.message : "Unable to load history.");
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [page, format, scoring]);

  const total = Number(rows[0]?.total_count ?? 0);
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-[family-name:var(--font-display)] text-2xl font-semibold">
            Completed drafts
          </h2>
          <p className="text-sm text-muted">Public, read-only draft history.</p>
        </div>
        <div className="flex gap-2">
          <label className="text-xs text-muted">
            Format
            <select value={format} onChange={(event) => { setFormat(event.target.value); setPage(1); }}
              className="mt-1 block rounded-md border border-border bg-card px-3 py-2 text-foreground">
              <option value="">All</option><option value="snake">Snake</option>
              <option value="linear">Linear</option><option value="auction">Auction</option>
            </select>
          </label>
          <label className="text-xs text-muted">
            Scoring
            <select value={scoring} onChange={(event) => { setScoring(event.target.value); setPage(1); }}
              className="mt-1 block rounded-md border border-border bg-card px-3 py-2 text-foreground">
              <option value="">All</option><option value="ppr">PPR</option>
              <option value="half_ppr">Half PPR</option><option value="standard">Standard</option>
              <option value="two_qb">2QB</option><option value="idp">IDP</option>
            </select>
          </label>
        </div>
      </div>
      {status ? <p className="rounded-lg border border-border bg-card p-5 text-sm text-muted">{status}</p> : null}
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {rows.map(({ draft }) => (
          <Link key={draft.id} href={`/mock-drafts/${draft.public_slug}/results`}
            className="rounded-xl border border-border bg-card p-5 transition hover:border-accent">
            <h3 className="font-semibold">{draft.name}</h3>
            <p className="mt-2 text-sm capitalize text-muted">
              {draft.format} · {draft.scoring_preset.replaceAll("_", " ")}
            </p>
            <p className="text-sm text-muted">{draft.team_count} teams · {draft.rounds} rounds</p>
            <p className="mt-3 text-xs text-muted">{new Date(draft.completed_at).toLocaleDateString()}</p>
          </Link>
        ))}
      </div>
      {total > 12 ? (
        <div className="flex items-center justify-between">
          <button disabled={page === 1} onClick={() => setPage((value) => value - 1)}
            className="rounded-md border border-border px-3 py-2 text-sm disabled:opacity-40">Previous</button>
          <span className="text-sm text-muted">Page {page} of {Math.ceil(total / 12)}</span>
          <button disabled={page * 12 >= total} onClick={() => setPage((value) => value + 1)}
            className="rounded-md border border-border px-3 py-2 text-sm disabled:opacity-40">Next</button>
        </div>
      ) : null}
    </section>
  );
}

