# Mock Draft Testing

## Automated suites

```powershell
Set-Location web
npm test
npm run typecheck
npm run build
npm run test:e2e

Set-Location ..
.\.venv\Scripts\python.exe -m pytest python/tests/unit -q
.\.venv\Scripts\python.exe -m fantasy_football_prediction_model.cli project validate

# With Supabase CLI and a local project:
supabase start
supabase db reset
supabase test db
```

Order tests cover every even team count and boundary round counts. Engine tests
cover flex/caps, seeded CPU behavior, K/DEF timing, 2QB, dynasty, auction max bids,
and timers. pgTAP asserts the uniqueness constraints that block race duplicates.

## Manual multiplayer matrix

Use two private browser profiles:

1. Verify stable, different identities after reload.
2. Race one seat; exactly one user wins.
3. Start and confirm open seats become CPUs.
4. Confirm only the on-clock user can pick and double-click creates one pick.
5. Confirm timeout queue, pause/resume, and reconnect state recovery.
6. Confirm auction bid limits, CPU counter-bids, anti-sniping extension, one
   settlement, budget deduction, and nomination rotation.
7. Confirm completion, history, and copyable public results.
8. Check keyboard focus, mobile board scrolling, reduced motion, sounds, and
   notification permission.

Also test offline/reconnect, three tabs advancing one deadline, direct REST pick
inserts rejected by RLS, and missing Supabase env rendering the setup panel.
