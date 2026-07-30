"use client";

import { Clipboard } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ensureAnonymousUser, getDisplayName, getSupabase } from "@/lib/supabase";

type ResultDraft = {
  id: string; name: string; status: string; format: string; scoring_preset: string;
  team_count: number; rounds: number; completed_at: string | null;
};
type ResultSlot = { slot_number: number; display_name: string; team_name: string; budget_remaining: number };
type ResultPick = { id: string; player_id: string; slot_number: number; round: number; pick_number: number; price: number | null };
type ResultPlayer = { player_id: string; name: string; team: string; primary_position: string };

export function MockDraftResults({ draftKey }: { draftKey: string }) {
  const router = useRouter();
  const [draft, setDraft] = useState<ResultDraft | null>(null);
  const [slots, setSlots] = useState<ResultSlot[]>([]);
  const [picks, setPicks] = useState<ResultPick[]>([]);
  const [players, setPlayers] = useState<ResultPlayer[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        await ensureAnonymousUser();
        const client = getSupabase();
        const room = await client.rpc("get_draft_by_slug", { target_slug: draftKey });
        if (room.error || !room.data) throw room.error ?? new Error("Draft not found.");
        const publicRoom = room.data as { draft: ResultDraft; slots: ResultSlot[] };
        if (publicRoom.draft.status !== "completed") throw new Error("Results publish when the draft completes.");
        const [pickResult, playerResult] = await Promise.all([
          client.from("draft_picks").select("*").eq("draft_id", publicRoom.draft.id).order("pick_number"),
          client.from("draft_player_snapshots").select("player_id,name,team,primary_position").eq("draft_id", publicRoom.draft.id),
        ]);
        if (pickResult.error) throw pickResult.error;
        if (playerResult.error) throw playerResult.error;
        setDraft(publicRoom.draft); setSlots(publicRoom.slots);
        setPicks((pickResult.data ?? []) as ResultPick[]);
        setPlayers((playerResult.data ?? []) as ResultPlayer[]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not load results.");
      }
    }
    void load();
  }, [draftKey]);

  const playerMap = useMemo(() => new Map(players.map((player) => [player.player_id, player])), [players]);
  function copySummary() {
    if (!draft) return;
    const lines = [`${draft.name} — ${draft.format} / ${draft.scoring_preset}`];
    for (const slot of slots) {
      const roster = picks.filter((pick) => pick.slot_number === slot.slot_number)
        .map((pick) => {
          const player = playerMap.get(pick.player_id);
          return `${player?.name ?? pick.player_id}${pick.price === null ? "" : ` ($${pick.price})`}`;
        }).join(", ");
      lines.push(`${slot.slot_number}. ${slot.team_name || slot.display_name}: ${roster}`);
    }
    void navigator.clipboard.writeText(lines.join("\n"));
  }

  async function createCopy() {
    if (!draft) return;
    const result = await getSupabase().rpc("copy_mock_draft", {
      source_draft: draft.id, display_name: getDisplayName(),
    });
    if (result.error) setError(result.error.message);
    else router.push(`/mock-drafts/${result.data}`);
  }

  if (error) return <p role="alert" className="rounded-md bg-danger/10 p-4">{error}</p>;
  if (!draft) return <p className="text-muted">Loading public results…</p>;
  return <div className="space-y-6">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="text-sm uppercase tracking-wider text-accent">Final results</p>
        <h1 className="mt-2 font-[family-name:var(--font-display)] text-4xl font-semibold">{draft.name}</h1>
        <p className="mt-2 capitalize text-muted">{draft.format} · {draft.scoring_preset.replaceAll("_"," ")} · {draft.team_count} teams</p></div>
      <button onClick={copySummary} className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm">
        <Clipboard className="h-4 w-4" /> Copy summary
      </button>
      <button onClick={createCopy} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground">
        Create a Copy
      </button>
    </header>
    <section className="overflow-x-auto rounded-xl border border-border bg-card">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead><tr className="border-b border-border text-muted">
          <th className="p-3">Pick</th><th className="p-3">Team</th><th className="p-3">Player</th>
          <th className="p-3">Pos</th><th className="p-3">NFL</th>{draft.format === "auction" ? <th className="p-3">Price</th> : null}
        </tr></thead>
        <tbody>{picks.map((pick) => {
          const player = playerMap.get(pick.player_id);
          const slot = slots.find((item) => item.slot_number === pick.slot_number);
          return <tr key={pick.id} className="border-b border-border/70">
            <td className="p-3 tabular-nums">{draft.format === "auction" ? pick.pick_number : `${pick.round}.${((pick.pick_number - 1) % draft.team_count) + 1}`}</td>
            <td className="p-3">{slot?.team_name || slot?.display_name}</td>
            <td className="p-3 font-medium">{player?.name}</td><td className="p-3">{player?.primary_position}</td>
            <td className="p-3">{player?.team}</td>{draft.format === "auction" ? <td className="p-3">${pick.price}</td> : null}
          </tr>;
        })}</tbody>
      </table>
    </section>
    <section className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {slots.map((slot) => <article key={slot.slot_number} className="rounded-xl border border-border bg-card p-4">
        <h2 className="font-semibold">{slot.team_name || slot.display_name}</h2>
        <ol className="mt-3 space-y-1 text-sm">{picks.filter((pick) => pick.slot_number === slot.slot_number).map((pick) => {
          const player = playerMap.get(pick.player_id);
          return <li key={pick.id} className="flex justify-between gap-2"><span>{player?.name}</span>
            <span className="text-muted">{player?.primary_position}{pick.price === null ? "" : ` · $${pick.price}`}</span></li>;
        })}</ol>
      </article>)}
    </section>
  </div>;
}
