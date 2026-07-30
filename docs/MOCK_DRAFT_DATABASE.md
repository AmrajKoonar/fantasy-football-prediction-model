# Mock Draft Database

The canonical schema is
`supabase/migrations/202607290001_mock_draft_v5.sql`.

| Table | Purpose | Important invariant |
|---|---|---|
| `profiles` | anonymous display names | one row per Auth user |
| `drafts` | configuration/state machine | authoritative deadline |
| `draft_slots` | human/CPU seats and budget | unique seat and user |
| `draft_player_snapshots` | immutable pool | unique player per draft |
| `draft_picks` | all results | unique player and pick number |
| `draft_queues` | private queue | owner-only RLS |
| `draft_messages` | participant chat | participant-only |
| `draft_auctions` | nomination/current bid | locked settlement |
| `draft_bids` | append-only bids | complete bid trace |

State moves `lobby → active ↔ paused → completed`; `cancelled` is reserved.
Completed drafts are public/read-only. Active data is participant-only, while
public-by-link lobby lookup reveals enough metadata to claim a seat.

All tables use RLS. Direct writes are limited to owner queues and participant chat.
State transitions use `SECURITY DEFINER`, explicit `search_path`, revoked public
execution, row locks, and authenticated grants. The service-role key is unnecessary.

Supabase RLS reference:
https://supabase.com/docs/guides/database/postgres/row-level-security

If storage approaches plan limits, export old completed results and delete selected
`drafts` rows in a controlled migration; dependent rows cascade.

