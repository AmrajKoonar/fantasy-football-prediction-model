"use client";

import { Bell, BellOff, Clipboard, Pause, Play, RotateCcw, Send, Volume2, VolumeX } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PositionBadge } from "@/components/position-badge";
import { buildDraftOrder } from "@/features/mock-draft/order";
import { assignRoster, canAddPlayer } from "@/features/mock-draft/roster";
import { formatTimer, remainingSeconds } from "@/features/mock-draft/timer";
import type { BasePosition, DraftPlayer, DraftSettings } from "@/features/mock-draft/types";
import { ensureAnonymousUser, getDisplayName, getSupabase } from "@/lib/supabase";
import type { User } from "@supabase/supabase-js";

type DbDraft = {
  id: string; public_slug: string; name: string; host_user_id: string;
  status: "lobby" | "active" | "paused" | "completed" | "cancelled";
  format: "snake" | "linear" | "auction"; scoring_preset: string;
  team_count: number; rounds: number; current_pick_number: number;
  current_round: number; current_nomination_slot: number;
  pick_deadline_at: string | null; settings: DraftSettings; seed: number;
};
type DbSlot = {
  id: string; slot_number: number; user_id: string | null; display_name: string;
  team_name: string; is_cpu: boolean; budget_remaining: number;
};
type DbPick = {
  id: string; player_id: string; slot_number: number; round: number;
  pick_number: number; price: number | null; is_cpu: boolean; created_at: string;
};
type DbMessage = { id: number; user_id: string; display_name: string; body: string; created_at: string };
type DbAuction = {
  id: string; player_id: string; current_bid: number; highest_bidder_slot: number;
  deadline_at: string; status: string; nominating_slot: number;
};
type PublicRoom = { draft: DbDraft; slots: DbSlot[] };
type Tab = "roster" | "queue" | "chat";

const inputClass = "rounded-md border border-border bg-background px-3 py-2 text-sm";

function fromSnapshot(row: Record<string, unknown>): DraftPlayer {
  return {
    playerId: String(row.player_id), name: String(row.name), team: String(row.team),
    primaryPosition: String(row.primary_position) as BasePosition,
    eligiblePositions: row.eligible_positions as BasePosition[],
    rookie: Boolean(row.rookie), age: row.age === null ? null : Number(row.age),
    overallRank: Number(row.overall_rank), positionRank: Number(row.position_rank),
    tier: Number(row.tier), projectedPoints: Number(row.projected_points),
    pointsPerGame: Number(row.points_per_game), adp: Number(row.adp),
    source: row.source as DraftPlayer["source"],
  };
}

export function MockDraftRoom({ draftKey }: { draftKey: string }) {
  const [user, setUser] = useState<User | null>(null);
  const [draft, setDraft] = useState<DbDraft | null>(null);
  const [slots, setSlots] = useState<DbSlot[]>([]);
  const [players, setPlayers] = useState<DraftPlayer[]>([]);
  const [picks, setPicks] = useState<DbPick[]>([]);
  const [messages, setMessages] = useState<DbMessage[]>([]);
  const [queue, setQueue] = useState<string[]>([]);
  const [auction, setAuction] = useState<DbAuction | null>(null);
  const [search, setSearch] = useState("");
  const [position, setPosition] = useState("ALL");
  const [tab, setTab] = useState<Tab>("roster");
  const [chat, setChat] = useState("");
  const [bid, setBid] = useState(1);
  const [clock, setClock] = useState<number | null>(null);
  const [sound, setSound] = useState(true);
  const [notifications, setNotifications] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const previousPickCount = useRef(0);

  const reload = useCallback(async () => {
    const client = getSupabase();
    const publicResult = await client.rpc("get_draft_by_slug", { target_slug: draftKey });
    if (publicResult.error || !publicResult.data) throw publicResult.error ?? new Error("Draft not found.");
    const publicRoom = publicResult.data as PublicRoom;
    setDraft(publicRoom.draft);
    setSlots(publicRoom.slots ?? []);
    const participant = publicRoom.slots?.some((slot) => slot.user_id === user?.id)
      || publicRoom.draft.host_user_id === user?.id
      || publicRoom.draft.status === "completed";
    if (participant) {
      const [snapshotResult, pickResult, messageResult, queueResult, auctionResult] = await Promise.all([
        client.from("draft_player_snapshots").select("*").eq("draft_id", publicRoom.draft.id).order("overall_rank"),
        client.from("draft_picks").select("*").eq("draft_id", publicRoom.draft.id).order("pick_number"),
        client.from("draft_messages").select("*").eq("draft_id", publicRoom.draft.id).order("created_at").limit(150),
        user ? client.from("draft_queues").select("player_id").eq("draft_id", publicRoom.draft.id).eq("user_id", user.id).order("priority") : Promise.resolve({ data: [], error: null }),
        client.from("draft_auctions").select("*").eq("draft_id", publicRoom.draft.id).eq("status", "open").maybeSingle(),
      ]);
      if (snapshotResult.error) throw snapshotResult.error;
      setPlayers((snapshotResult.data ?? []).map((row) => fromSnapshot(row)));
      setPicks((pickResult.data ?? []) as DbPick[]);
      setMessages((messageResult.data ?? []) as DbMessage[]);
      setQueue((queueResult.data ?? []).map((row) => String(row.player_id)));
      setAuction((auctionResult.data as DbAuction | null) ?? null);
    }
  }, [draftKey, user?.id]);

  useEffect(() => {
    let cancelled = false;
    ensureAnonymousUser().then((value) => {
      if (!cancelled) setUser(value);
    }).catch((caught) => setError(caught instanceof Error ? caught.message : "Sign-in failed."));
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!user) return;
    reload().catch((caught) => setError(caught instanceof Error ? caught.message : "Room failed to load."))
      .finally(() => setLoading(false));
  }, [user, reload]);

  useEffect(() => {
    if (!draft?.id) return;
    const client = getSupabase();
    const channel = client.channel(`draft-${draft.id}`);
    channel.on("postgres_changes", {
      event: "*", schema: "public", table: "drafts", filter: `id=eq.${draft.id}`,
    }, () => { void reload(); });
    for (const table of ["draft_slots", "draft_picks", "draft_messages", "draft_auctions", "draft_bids"]) {
      channel.on("postgres_changes", {
        event: "*", schema: "public", table, filter: `draft_id=eq.${draft.id}`,
      }, () => { void reload(); });
    }
    channel.subscribe();
    return () => { void client.removeChannel(channel); };
  }, [draft?.id, reload]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClock(remainingSeconds(draft?.pick_deadline_at ?? null));
      if (draft?.status === "active") {
        void getSupabase().rpc("advance_mock_draft", { target_draft: draft.id }).then((result) => {
          if (result.data) void reload();
        });
        if (auction?.deadline_at && new Date(auction.deadline_at).getTime() <= Date.now()) {
          void getSupabase().rpc("settle_auction", { target_auction: auction.id }).then(() => reload());
        }
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [draft, auction, reload]);

  useEffect(() => {
    if (picks.length > previousPickCount.current && previousPickCount.current > 0) {
      if (sound) {
        const audio = new AudioContext();
        const oscillator = audio.createOscillator();
        oscillator.connect(audio.destination); oscillator.frequency.value = 660;
        oscillator.start(); oscillator.stop(audio.currentTime + 0.09);
      }
      const nextSlot = slots.find((slot) => slot.slot_number === currentSlotNumber(draft));
      if (notifications && nextSlot?.user_id === user?.id && Notification.permission === "granted") {
        new Notification("You are on the clock", { body: draft?.name });
      }
    }
    previousPickCount.current = picks.length;
  }, [picks.length, sound, notifications, slots, user?.id, draft]);

  const mySlot = slots.find((slot) => slot.user_id === user?.id);
  const host = draft?.host_user_id === user?.id;
  const pickedIds = useMemo(() => new Set(picks.map((pick) => pick.player_id)), [picks]);
  const myDrafted = useMemo(() => picks.filter((pick) => pick.slot_number === mySlot?.slot_number)
    .map((pick) => players.find((player) => player.playerId === pick.player_id))
    .filter((player): player is DraftPlayer => Boolean(player)), [picks, players, mySlot?.slot_number]);
  const available = useMemo(() => players.filter((player) => {
    if (pickedIds.has(player.playerId)) return false;
    if (draft?.settings.playerPool === "rookies" && !player.rookie) return false;
    if (draft?.settings.playerPool === "veterans" && player.rookie) return false;
    if (position !== "ALL" && player.primaryPosition !== position) return false;
    const term = search.toLowerCase();
    return !term || `${player.name} ${player.team}`.toLowerCase().includes(term);
  }).sort((a, b) => draft?.settings.alphabeticalPlayers
    ? a.name.localeCompare(b.name) : a.overallRank - b.overallRank), [players, pickedIds, draft, position, search]);
  const onClock = currentSlotNumber(draft);
  const canPick = draft?.status === "active" && draft.format !== "auction"
    && mySlot?.slot_number === onClock;

  async function action(name: string, args: Record<string, unknown>) {
    setError("");
    const result = await getSupabase().rpc(name, args);
    if (result.error) setError(result.error.message);
    else await reload();
  }

  async function claim(slot: number) {
    await action("claim_draft_slot", {
      target_draft: draft!.id, target_slot: slot,
      display_name: getDisplayName(), team_name: getDisplayName(),
    });
  }

  async function toggleQueue(playerId: string) {
    if (!draft || !user) return;
    const client = getSupabase();
    if (queue.includes(playerId)) {
      await client.from("draft_queues").delete().eq("draft_id", draft.id).eq("user_id", user.id).eq("player_id", playerId);
    } else {
      await client.from("draft_queues").insert({
        draft_id: draft.id, user_id: user.id, player_id: playerId, priority: queue.length,
      });
    }
    await reload();
  }

  async function sendMessage(event: React.FormEvent) {
    event.preventDefault();
    if (!chat.trim() || !draft || !user) return;
    const result = await getSupabase().from("draft_messages").insert({
      draft_id: draft.id, user_id: user.id, display_name: getDisplayName(), body: chat.trim(),
    });
    if (result.error) setError(result.error.message); else setChat("");
  }

  if (loading) return <p className="text-muted">Loading persistent draft room…</p>;
  if (!draft) return <p role="alert" className="text-danger">{error || "Draft not found."}</p>;
  if (draft.status === "completed") {
    return <div className="rounded-xl border border-border bg-card p-8 text-center">
      <h1 className="text-3xl font-semibold">Draft complete</h1>
      <Link href={`/mock-drafts/${draft.public_slug}/results`}
        className="mt-5 inline-block rounded-md bg-accent px-4 py-2 text-accent-foreground">View results</Link>
    </div>;
  }

  if (draft.status === "lobby") {
    return (
      <div className="space-y-6">
        <RoomHeader draft={draft} sound={sound} setSound={setSound}
          notifications={notifications} setNotifications={setNotifications} />
        <section className="rounded-xl border border-border bg-card p-5">
          <h2 className="text-xl font-semibold">Lobby</h2>
          <p className="mt-1 text-sm text-muted">Claim one slot. Open seats become CPUs when the host starts.</p>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {slots.map((slot) => (
              <div key={slot.id} className="flex items-center justify-between rounded-lg border border-border p-4">
                <div><p className="text-xs text-muted">Pick {slot.slot_number}</p>
                  <p className="font-medium">{slot.user_id ? slot.display_name : "Open seat"}</p></div>
                {!slot.user_id && !mySlot ? <button onClick={() => claim(slot.slot_number)}
                  className="rounded-md border border-accent px-3 py-1.5 text-sm text-accent">Claim</button> : null}
              </div>
            ))}
          </div>
          <div className="mt-5 flex flex-wrap gap-3">
            {host ? <button onClick={() => action("start_mock_draft", { target_draft: draft.id })}
              className="rounded-md bg-accent px-4 py-2 font-medium text-accent-foreground">Start draft</button> : null}
            {mySlot && !host ? <button onClick={() => action("release_draft_slot", { target_draft: draft.id })}
              className="rounded-md border border-border px-4 py-2">Leave slot</button> : null}
          </div>
        </section>
        {error ? <p role="alert" className="rounded-md bg-danger/10 p-3 text-sm">{error}</p> : null}
      </div>
    );
  }

  const activeAuctionPlayer = players.find((player) => player.playerId === auction?.player_id);
  return (
    <div className="space-y-4">
      <RoomHeader draft={draft} sound={sound} setSound={setSound}
        notifications={notifications} setNotifications={setNotifications} />
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-4">
        <div>
          <p className="text-xs uppercase tracking-wider text-muted">{draft.status === "paused" ? "Paused" : "On the clock"}</p>
          <p className="font-semibold">{slots.find((slot) => slot.slot_number === onClock)?.display_name ?? `Slot ${onClock}`}</p>
        </div>
        <div aria-live="polite" className="text-2xl font-semibold tabular-nums">{formatTimer(clock)}</div>
        {host ? <div className="flex gap-2">
          {draft.status === "active" ? <button aria-label="Pause draft" onClick={() => action("pause_mock_draft", { target_draft: draft.id })}
            className="rounded-md border border-border p-2"><Pause className="h-4 w-4" /></button>
            : <button aria-label="Resume draft" onClick={() => action("resume_mock_draft", { target_draft: draft.id })}
              className="rounded-md border border-border p-2"><Play className="h-4 w-4" /></button>}
          {draft.format !== "auction" ? <button aria-label="Undo last pick" onClick={() => action("undo_last_mock_pick", { target_draft: draft.id })}
            className="rounded-md border border-border p-2"><RotateCcw className="h-4 w-4" /></button> : null}
        </div> : null}
      </div>

      {draft.format === "auction" ? (
        <section className="rounded-xl border border-accent/40 bg-accent/10 p-4">
          {auction ? <div className="flex flex-wrap items-center justify-between gap-4">
            <div><p className="text-xs text-muted">Current nomination</p>
              <p className="text-xl font-semibold">{activeAuctionPlayer?.name}</p>
              <p className="text-sm text-muted">${auction.current_bid} · {slots.find((slot) => slot.slot_number === auction.highest_bidder_slot)?.display_name}</p></div>
            <form onSubmit={(event) => { event.preventDefault(); void action("place_auction_bid", { target_auction: auction.id, bid_amount: bid }); }}
              className="flex gap-2"><input aria-label="Bid amount" type="number" min={auction.current_bid + draft.settings.minimumBid}
                value={bid} onChange={(event) => setBid(Number(event.target.value))} className={inputClass} />
              <button className="rounded-md bg-accent px-4 py-2 text-accent-foreground">Bid</button></form>
          </div> : <p className="text-sm">Slot {draft.current_nomination_slot} nominates from the player table.</p>}
        </section>
      ) : null}

      <DraftBoard draft={draft} slots={slots} picks={picks} players={players} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="min-w-0 rounded-xl border border-border bg-card">
          <div className="flex flex-wrap gap-2 border-b border-border p-3">
            <input aria-label="Search players" placeholder="Search player or team" value={search}
              onChange={(event) => setSearch(event.target.value)} className={`${inputClass} flex-1`} />
            <select aria-label="Filter position" value={position} onChange={(event) => setPosition(event.target.value)} className={inputClass}>
              {["ALL","QB","RB","WR","TE","K","DEF","DL","LB","DB"].map((value) => <option key={value}>{value}</option>)}
            </select>
          </div>
          <div className="max-h-[520px] overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-card"><tr className="border-b border-border text-muted">
                <th className="p-3">Rank</th><th className="p-3">Player</th><th className="p-3">Proj</th><th className="p-3">Action</th>
              </tr></thead>
              <tbody>{available.map((player) => {
                const eligible = canAddPlayer(myDrafted, player, draft.settings.roster);
                return <tr key={player.playerId} className="border-b border-border/70">
                  <td className="p-3 tabular-nums">{player.overallRank}</td>
                  <td className="p-3"><div className="flex items-center gap-2">
                    <PositionBadge position={player.primaryPosition as "QB" | "RB" | "WR" | "TE"} />
                    <div><p className="font-medium">{player.name}</p><p className="text-xs text-muted">{player.team}{player.rookie ? " · Rookie" : ""}</p></div>
                  </div></td>
                  <td className="p-3 tabular-nums">{player.projectedPoints.toFixed(1)}</td>
                  <td className="p-3"><div className="flex gap-1">
                    {draft.format === "auction" && !auction && mySlot?.slot_number === draft.current_nomination_slot
                      ? <button onClick={() => action("nominate_auction_player", { target_draft: draft.id, target_player: player.playerId })}
                        className="rounded border border-accent px-2 py-1 text-xs text-accent">Nominate</button>
                      : <button disabled={!canPick || !eligible} onClick={() => action("make_mock_pick", { target_draft: draft.id, target_player: player.playerId })}
                        className="rounded bg-accent px-2 py-1 text-xs text-accent-foreground disabled:opacity-30">Draft</button>}
                    <button onClick={() => toggleQueue(player.playerId)}
                      className="rounded border border-border px-2 py-1 text-xs">{queue.includes(player.playerId) ? "Queued" : "+ Queue"}</button>
                  </div></td>
                </tr>;
              })}</tbody>
            </table>
          </div>
        </section>

        <aside className="rounded-xl border border-border bg-card">
          <div className="grid grid-cols-3 border-b border-border">
            {(["roster","queue","chat"] as Tab[]).map((value) => <button key={value} onClick={() => setTab(value)}
              className={`px-2 py-3 text-sm capitalize ${tab === value ? "border-b-2 border-accent text-accent" : "text-muted"}`}>{value}</button>)}
          </div>
          <div className="max-h-[520px] overflow-auto p-3">
            {tab === "roster" ? <RosterView drafted={myDrafted} settings={draft.settings} /> : null}
            {tab === "queue" ? <ol className="space-y-2">{queue.map((id, index) => {
              const player = players.find((item) => item.playerId === id);
              return player ? <li key={id} className="flex items-center justify-between rounded-md border border-border p-2 text-sm">
                <span>{index + 1}. {player.name}</span><button onClick={() => toggleQueue(id)} className="text-danger">×</button>
              </li> : null;
            })}</ol> : null}
            {tab === "chat" ? <div className="space-y-3">
              <div aria-live="polite" className="space-y-2">{messages.map((message) => <div key={message.id} className="text-sm">
                <span className="font-medium">{message.display_name}</span>
                <span className="ml-2 text-xs text-muted">{new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                <p className="text-muted">{message.body}</p></div>)}</div>
              <form onSubmit={sendMessage} className="sticky bottom-0 flex gap-2 bg-card pt-2">
                <input aria-label="Chat message" value={chat} maxLength={500} onChange={(event) => setChat(event.target.value)}
                  className={`${inputClass} min-w-0 flex-1`} /><button aria-label="Send chat" className="rounded-md bg-accent p-2 text-accent-foreground"><Send className="h-4 w-4" /></button>
              </form>
            </div> : null}
          </div>
        </aside>
      </div>
      {error ? <p role="alert" className="rounded-md bg-danger/10 p-3 text-sm">{error}</p> : null}
    </div>
  );
}

function currentSlotNumber(draft: DbDraft | null): number {
  if (!draft) return 1;
  if (draft.format === "auction") return draft.current_nomination_slot;
  return buildDraftOrder(draft.team_count, draft.rounds, draft.format,
    draft.settings.thirdRoundReversal)[draft.current_pick_number - 1]?.slotNumber ?? 1;
}

function RoomHeader({ draft, sound, setSound, notifications, setNotifications }: {
  draft: DbDraft; sound: boolean; setSound: (value: boolean) => void;
  notifications: boolean; setNotifications: (value: boolean) => void;
}) {
  async function toggleNotifications() {
    if (!notifications && "Notification" in window) {
      const permission = await Notification.requestPermission();
      setNotifications(permission === "granted");
    } else setNotifications(false);
  }
  return <header className="flex flex-wrap items-start justify-between gap-4">
    <div><p className="text-sm capitalize text-accent">{draft.format} · {draft.scoring_preset.replaceAll("_"," ")}</p>
      <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">{draft.name}</h1>
      <p className="text-sm text-muted">{draft.team_count} teams · {draft.rounds} rounds · saved in realtime</p></div>
    <div className="flex gap-2">
      <button aria-label={sound ? "Mute draft sounds" : "Enable draft sounds"} onClick={() => setSound(!sound)}
        className="rounded-md border border-border p-2">{sound ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}</button>
      <button aria-label="Toggle turn notifications" onClick={toggleNotifications}
        className="rounded-md border border-border p-2">{notifications ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}</button>
      <button onClick={() => navigator.clipboard.writeText(window.location.href)}
        className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm"><Clipboard className="h-4 w-4" /> Share</button>
    </div>
  </header>;
}

function DraftBoard({ draft, slots, picks, players }: {
  draft: DbDraft; slots: DbSlot[]; picks: DbPick[]; players: DraftPlayer[];
}) {
  const byNumber = new Map(picks.map((pick) => [pick.pick_number, pick]));
  if (draft.format === "auction") {
    return <section className="overflow-x-auto rounded-xl border border-border bg-card p-3">
      <div className="grid min-w-[720px] gap-2" style={{ gridTemplateColumns: `repeat(${draft.team_count}, minmax(110px,1fr))` }}>
        {slots.map((slot) => <div key={slot.id} className="rounded-md border border-border p-2">
          <p className="truncate text-xs font-medium">{slot.display_name}</p><p className="text-xs text-muted">${slot.budget_remaining}</p>
          {picks.filter((pick) => pick.slot_number === slot.slot_number).map((pick) => {
            const player = players.find((item) => item.playerId === pick.player_id);
            return <p key={pick.id} className="mt-1 truncate text-xs">{player?.name} · ${pick.price}</p>;
          })}
        </div>)}
      </div>
    </section>;
  }
  const order = buildDraftOrder(draft.team_count, draft.rounds, draft.format, draft.settings.thirdRoundReversal);
  return <section aria-label="Draft board" className="overflow-x-auto rounded-xl border border-border bg-card p-3">
    <div className="grid min-w-[760px] gap-1" style={{ gridTemplateColumns: `repeat(${draft.team_count}, minmax(105px,1fr))` }}>
      {slots.map((slot) => <div key={`head-${slot.id}`} className="truncate rounded bg-row-band p-2 text-center text-xs font-medium">{slot.display_name}</div>)}
      {order.map((ordered) => {
        const pick = byNumber.get(ordered.overall);
        const player = players.find((item) => item.playerId === pick?.player_id);
        return <div key={ordered.overall} className={`min-h-14 rounded border p-2 text-xs ${ordered.overall === draft.current_pick_number ? "border-accent bg-accent/10" : "border-border"}`}
          style={{ gridColumn: ordered.slotNumber, gridRow: ordered.round + 1 }}>
          <span className="text-muted">{ordered.round}.{ordered.pickInRound}</span>
          {player ? <><p className="truncate font-medium">{player.name}</p><p className="text-muted">{player.primaryPosition} · {player.team}</p></> : null}
        </div>;
      })}
    </div>
  </section>;
}

function RosterView({ drafted, settings }: { drafted: DraftPlayer[]; settings: DraftSettings }) {
  const assigned = assignRoster(drafted, settings.roster);
  return <ol className="space-y-2">{settings.roster.map((slot, index) => {
    const player = assigned[index];
    return <li key={slot.id} className="flex items-center justify-between rounded-md border border-border p-2 text-sm">
      <span className="w-20 text-xs text-muted">{slot.position}</span>
      <span className="truncate">{player?.name ?? "Empty"}</span>
    </li>;
  })}</ol>;
}
