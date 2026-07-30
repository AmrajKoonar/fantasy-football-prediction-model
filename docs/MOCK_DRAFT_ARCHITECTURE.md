# Mock Draft Architecture

## System shape

The Next.js app is a public client of Supabase. There is no custom always-on server
and no service-role key in the browser or Vercel. Supabase Auth creates anonymous
users, PostgreSQL is authoritative, RLS limits visibility, RPC functions serialize
mutations, and Realtime carries room changes back to clients.

```text
Python pipeline
  └─ mock-draft-player-pool.json
         └─ create RPC → immutable draft_player_snapshots
                                │
Browser A ─┐                    ├─ locked lifecycle/pick/auction RPCs
Browser B ─┼─ Supabase Auth/RLS ├─ persisted queues + chat
Browser C ─┘                    └─ filtered realtime subscriptions
```

Supabase documents anonymous users as authenticated users with unique IDs and the
same RLS enforcement as conventional accounts:
https://supabase.com/docs/guides/troubleshooting/security-of-anonymous-sign-ins-iOrGCL

## Reconnect model

Realtime messages are invalidation signals, not the only copy of state. On initial
load, reconnect, or a relevant table change, the room reloads its authoritative
state. Missed or duplicated events are harmless. The database deadline is rendered
locally but never decided locally.

Postgres Changes is the simpler initial setup; Supabase recommends Broadcast for
higher scale:
https://supabase.com/docs/guides/realtime/subscribing-to-database-changes

## Authority and race prevention

- `SELECT ... FOR UPDATE` locks the draft or auction row before mutation.
- Unique draft/slot and draft/user constraints serialize seat claims.
- Unique draft/player and draft/pick-number constraints prevent double picks.
- Turn calculation, deadline checks, budget checks, and settlement happen in SQL.
- Expired/CPU advancement is idempotent, so many clients may safely request it.

## Scale path

Supabase currently advertises 50,000 MAU, a 500 MB database, 5 GB egress, and
unlimited API requests on Free; inactive projects pause:
https://supabase.com/pricing

At larger concurrency, replace Postgres Changes with private Broadcast topics,
archive old snapshots, add CAPTCHA/rate limits, and use a scheduled worker if rooms
must advance with zero connected clients.

