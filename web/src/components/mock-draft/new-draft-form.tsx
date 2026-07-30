"use client";

import { ArrowDown, ArrowUp, Copy, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  DEFAULT_SETTINGS,
  ROUND_OPTIONS,
  SCORING_LABELS,
  TEAM_COUNTS,
  TIMER_OPTIONS,
  defaultRoster,
} from "@/features/mock-draft/constants";
import { loadDraftPlayerPool } from "@/features/mock-draft/data";
import type { DraftSettings, RosterPosition } from "@/features/mock-draft/types";
import { ROSTER_POSITIONS } from "@/features/mock-draft/types";
import { DraftSettingsSchema } from "@/features/mock-draft/validation";
import {
  ensureAnonymousUser,
  getDisplayName,
  getSupabase,
  setDisplayName,
} from "@/lib/supabase";

const inputClass = "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm";

export function NewDraftForm() {
  const router = useRouter();
  const [settings, setSettings] = useState<DraftSettings>(DEFAULT_SETTINGS);
  const [displayName, setName] = useState(() => getDisplayName());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function patch<K extends keyof DraftSettings>(key: K, value: DraftSettings[K]) {
    setSettings((current) => ({ ...current, [key]: value }));
  }

  function setRounds(rounds: number) {
    setSettings((current) => {
      const roster = [...current.roster];
      while (roster.length < rounds) roster.push({ id: crypto.randomUUID(), position: "BENCH" });
      return { ...current, rounds, roster: roster.slice(0, rounds) };
    });
  }

  function moveRoster(index: number, offset: number) {
    const target = index + offset;
    if (target < 0 || target >= settings.roster.length) return;
    const roster = [...settings.roster];
    [roster[index], roster[target]] = [roster[target], roster[index]];
    patch("roster", roster);
  }

  async function createDraft(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    const parsed = DraftSettingsSchema.safeParse(settings);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Review the draft settings.");
      return;
    }
    setBusy(true);
    try {
      await ensureAnonymousUser();
      setDisplayName(displayName);
      const players = await loadDraftPlayerPool();
      const result = await getSupabase().rpc("create_mock_draft", {
        draft_settings: parsed.data,
        player_snapshot: players,
        display_name: displayName.trim(),
      });
      if (result.error) throw result.error;
      router.push(`/mock-drafts/${result.data}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create the draft.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={createDraft} className="mx-auto max-w-5xl space-y-8">
      <header>
        <p className="text-sm uppercase tracking-[0.2em] text-accent">New room</p>
        <h1 className="mt-2 font-[family-name:var(--font-display)] text-4xl font-semibold">
          Create a mock draft
        </h1>
        <p className="mt-2 text-muted">Every setting is frozen when the room starts.</p>
      </header>

      <section className="grid gap-4 rounded-xl border border-border bg-card p-5 md:grid-cols-2">
        <h2 className="text-lg font-semibold md:col-span-2">League</h2>
        <label className="text-sm">Draft name
          <input className={inputClass} value={settings.name}
            onChange={(event) => patch("name", event.target.value)} maxLength={80} />
        </label>
        <label className="text-sm">Your display name
          <input className={inputClass} value={displayName}
            onChange={(event) => setName(event.target.value)} minLength={2} maxLength={30} />
        </label>
        <label className="text-sm">Format
          <select className={inputClass} value={settings.format}
            onChange={(event) => patch("format", event.target.value as DraftSettings["format"])}>
            <option value="snake">Snake</option><option value="linear">Linear</option>
            <option value="auction">Auction</option>
          </select>
        </label>
        <label className="text-sm">Scoring
          <select className={inputClass} value={settings.scoringPreset}
            onChange={(event) => patch("scoringPreset", event.target.value as DraftSettings["scoringPreset"])}>
            {Object.entries(SCORING_LABELS).map(([value, label]) =>
              <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="text-sm">Teams
          <select className={inputClass} value={settings.teamCount}
            onChange={(event) => patch("teamCount", Number(event.target.value))}>
            {TEAM_COUNTS.map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label className="text-sm">Rounds / roster size
          <select className={inputClass} value={settings.rounds}
            onChange={(event) => setRounds(Number(event.target.value))}>
            {ROUND_OPTIONS.map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label className="text-sm">Pick timer
          <select className={inputClass} value={settings.pickTimerSeconds ?? ""}
            onChange={(event) => patch("pickTimerSeconds", event.target.value ? Number(event.target.value) : null)}>
            {TIMER_OPTIONS.map((option) =>
              <option key={option.label} value={option.value ?? ""}>{option.label}</option>)}
          </select>
        </label>
        <label className="text-sm">Player pool
          <select className={inputClass} value={settings.playerPool}
            onChange={(event) => patch("playerPool", event.target.value as DraftSettings["playerPool"])}>
            <option value="all">All players</option><option value="rookies">Rookies only</option>
            <option value="veterans">Veterans only</option>
          </select>
        </label>
        {settings.format === "auction" ? (
          <>
            <label className="text-sm">Starting budget
              <input className={inputClass} type="number" min={20} max={1000}
                value={settings.auctionBudget}
                onChange={(event) => patch("auctionBudget", Number(event.target.value))} />
            </label>
            <label className="text-sm">Minimum bid / increment
              <input className={inputClass} type="number" min={1} max={100}
                value={settings.minimumBid}
                onChange={(event) => patch("minimumBid", Number(event.target.value))} />
            </label>
          </>
        ) : null}
        <div className="grid gap-2 text-sm md:col-span-2 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["cpuAutopick", "CPU autopick"],
            ["thirdRoundReversal", "Third-round reversal"],
            ["alphabeticalPlayers", "Alphabetical player list"],
            ["showTeamNames", "Show team names"],
          ].map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 rounded-md border border-border p-3">
              <input type="checkbox"
                disabled={key === "thirdRoundReversal" && settings.format !== "snake"}
                checked={Boolean(settings[key as keyof DraftSettings])}
                onChange={(event) => patch(key as keyof DraftSettings, event.target.checked as never)} />
              {label}
            </label>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Roster editor</h2>
            <p className="text-sm text-muted">Reorder, duplicate, remove, or add any supported slot.</p>
          </div>
          <button type="button" onClick={() => {
            const roster = defaultRoster(); setSettings((current) => ({ ...current, roster, rounds: roster.length }));
          }} className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm">
            <RotateCcw className="h-4 w-4" /> Reset
          </button>
        </div>
        <ol className="mt-4 grid gap-2 sm:grid-cols-2">
          {settings.roster.map((slot, index) => (
            <li key={slot.id} className="flex items-center gap-2 rounded-md border border-border bg-background p-2">
              <span className="w-6 text-xs text-muted">{index + 1}</span>
              <select aria-label={`Roster slot ${index + 1}`} value={slot.position}
                onChange={(event) => {
                  const roster = [...settings.roster];
                  roster[index] = { ...slot, position: event.target.value as RosterPosition };
                  patch("roster", roster);
                }} className="min-w-0 flex-1 bg-transparent text-sm">
                {ROSTER_POSITIONS.map((position) => <option key={position}>{position}</option>)}
              </select>
              <button type="button" aria-label="Move up" onClick={() => moveRoster(index, -1)}><ArrowUp className="h-4 w-4" /></button>
              <button type="button" aria-label="Move down" onClick={() => moveRoster(index, 1)}><ArrowDown className="h-4 w-4" /></button>
              <button type="button" aria-label="Duplicate slot" onClick={() => {
                if (settings.roster.length >= 30) return;
                const roster = [...settings.roster];
                roster.splice(index + 1, 0, { ...slot, id: crypto.randomUUID() });
                setSettings((current) => ({ ...current, roster, rounds: roster.length }));
              }}><Copy className="h-4 w-4" /></button>
              <button type="button" aria-label="Remove slot" disabled={settings.roster.length === 1}
                onClick={() => {
                  const roster = settings.roster.filter((_, rosterIndex) => rosterIndex !== index);
                  setSettings((current) => ({ ...current, roster, rounds: roster.length }));
                }}><Trash2 className="h-4 w-4" /></button>
            </li>
          ))}
        </ol>
        <button type="button" disabled={settings.roster.length >= 30}
          onClick={() => {
            const roster = [...settings.roster, { id: crypto.randomUUID(), position: "BENCH" as const }];
            setSettings((current) => ({ ...current, roster, rounds: roster.length }));
          }} className="mt-3 inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm">
          <Plus className="h-4 w-4" /> Add slot
        </button>
      </section>

      {error ? <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm">{error}</p> : null}
      <button disabled={busy || displayName.trim().length < 2}
        className="rounded-md bg-accent px-5 py-3 font-medium text-accent-foreground disabled:opacity-50">
        {busy ? "Creating persistent room…" : "Create draft room"}
      </button>
    </form>
  );
}

