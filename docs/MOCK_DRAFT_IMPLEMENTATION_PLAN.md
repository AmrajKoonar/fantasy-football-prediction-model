# Mock Draft V5 Implementation Plan

Status: implementation in progress on `FB.mock.draft.v5`.

## Product boundary

Mock Draft V5 adds a persistent, shareable draft room to Fantasy Analytics. It is
deliberately separated from the projection/rankings UI: the projection pipeline
publishes a versioned draft-player pool, while each created draft stores an
immutable snapshot of the players and scoring values it started with.

The feature has four public routes:

- `/mock-drafts` — create CTA, explainer, and paginated completed-draft history.
- `/mock-drafts/new` — complete league, timer, pool, and roster configuration.
- `/mock-drafts/[draftId]` — lobby, live draft, auction room, chat, queue, and roster.
- `/mock-drafts/[draftId]/results` — read-only board, rosters, and copyable summary.

## Architecture

1. **Static projection input**
   - The Python export produces `web/public/data/mock-draft-player-pool.json`.
   - The pool contains at least 600 draftable entries across offense, kicker,
     defense/special teams, and IDP.
   - Client scoring derives preset-specific values without mutating rankings data.
2. **Supabase authority**
   - Anonymous Supabase Auth provides a durable user id; a local display name is
     synchronized to a database profile.
   - PostgreSQL tables store draft configuration, immutable player snapshots,
     slots, picks, auctions, bids, queues, and chat.
   - RLS protects user-owned and participant-only data.
   - `SECURITY DEFINER` RPC functions lock draft rows and atomically claim/release
     slots, start/pause/resume/complete drafts, make/undo picks, nominate, and bid.
   - The database clock and `pick_deadline_at` are authoritative.
3. **Realtime client**
   - A single room subscription listens to filtered changes for that draft.
   - Reconnect always reloads a complete room snapshot, so dropped events cannot
     corrupt the visible board.
   - Clients may ask the database to advance an expired/CPU turn; the locked RPC is
     idempotent, so concurrent callers cannot create duplicate picks.
4. **Deterministic engine**
   - Pure TypeScript modules own order generation (snake, linear, 3RR), roster
     eligibility, scoring presets, timer formatting, auction validation, and
     seeded CPU candidate weighting.
   - The SQL functions mirror critical invariants and remain the final authority.
5. **Progressive fallback**
   - If Supabase environment variables are absent, routes render a setup panel and
     the creation form remains inspectable. They never silently create a local-only
     draft that could be mistaken for persistent multiplayer.

## Database objects

- `profiles`
- `drafts`
- `draft_slots`
- `draft_player_snapshots`
- `draft_picks`
- `draft_auctions`
- `draft_bids`
- `draft_queues`
- `draft_messages`
- RPCs for draft creation, membership, lifecycle, picks, timeouts, auction actions,
  undo, and history/results reads.

Every mutable table has indexes for room/user lookups and RLS enabled. Unique
constraints cover one owner per slot and one selected player per draft. RPCs use
row locks and explicit search paths.

## Delivery slices

1. Engine types, settings validation, order/roster/scoring/CPU/auction modules.
2. Supabase migration, generated database types, client helpers, auth, room store.
3. Extended player-pool export and static data validation.
4. Landing, creation form, lobby, live board, auction UI, results, nav/home CTA.
5. Unit, database concurrency, integration, and Playwright coverage.
6. Operations, architecture, database, CPU, setup, and testing documentation.
7. Full Python and web validation, logical commits, and clean final worktree.

## Acceptance checkpoints

- Human and CPU slot ownership cannot race or duplicate.
- A player cannot be selected twice and a turn cannot advance twice.
- Order tests cover even team counts 4–22, rounds 1–30, snake, linear, and 3RR.
- CPU tests are seeded and prove roster-aware weighting, late K/DEF behavior,
  two-quarterback awareness, and dynasty age adjustments.
- Auction tests cover nomination, bid increments, budget/max-bid enforcement,
  deadlines, winner assignment, and pause/resume.
- Reconnect/reload reconstructs the same board and deadline from persisted state.
- Completed drafts appear in public history and are immutable/read-only.
