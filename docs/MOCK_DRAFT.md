# Mock Draft

Fantasy Analytics includes persistent multiplayer mock drafts at `/mock-drafts`.
Rooms support 4–22 teams, 1–30 roster rounds, snake, linear, third-round
reversal, and auction formats. Scoring presets include standard, half PPR, PPR,
2QB/superflex, IDP, and dynasty variants.

## Typical flow

1. Open **Mock Drafts → Create a mock draft**.
2. Choose the format, scoring, timer, pool, and roster.
3. Enter a display name and create the room.
4. Claim a slot, copy the share link, and let other users claim their slots.
5. The host starts; unclaimed seats become CPUs.
6. Draft, queue players, review rosters, and chat. Reloading is safe.
7. The completed room redirects to a permanent, public results board.

Anonymous users get a stable Supabase identity stored by the browser. Clearing site
data creates a new identity, so do not clear it during a draft.

## Supported settings

- Formats: snake, linear, auction
- Timers: no limit; 10/15/30/45 seconds; 1/2/5/10/30 minutes;
  1/2/4/8/12/24 hours
- Pools: all, rookie-only, veteran-only
- Roster positions: QB, RB, WR, TE, FLEX, SUPERFLEX, K, DEF, BENCH,
  DL, LB, DB, IDP_FLEX
- Host controls: start, pause, resume, undo the last standard pick
- Room tools: queue, roster, chat, sound, browser notifications, copy link

The player list is intentionally separate from the headline rankings export. Each
draft stores an immutable copy, so regenerating rankings cannot change a draft in
progress.

## Limitations

- Anonymous identities are device/browser-profile specific.
- Free Supabase projects pause after inactivity and have finite database/realtime quotas.
- K and IDP values are transparent prior-season nflverse baselines; team DEF values
  are deterministic baselines, not offensive projection-model outputs.
- Initial realtime uses filtered Postgres Changes. Broadcast is preferable for
  thousands of simultaneous subscribers.

