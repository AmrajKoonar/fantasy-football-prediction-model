# Mock Draft Setup

## ACTION REQUIRED FROM YOU

These are the only manual infrastructure steps.

1. In Supabase, create or select a project.
2. Open **Authentication → Providers → Anonymous Sign-Ins** and enable anonymous
   sign-ins. Consider CAPTCHA before broad promotion.
3. Open **SQL Editor**, paste all of
   `supabase/migrations/202607290001_mock_draft_v5.sql`, and run it once.
4. Open **Project Settings → API** and copy the Project URL and Publishable key.
   Older projects may label the latter the public `anon` key.
5. In Vercel **Project Settings → Environment Variables**, add:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
   Apply both to Production, Preview, and Development if used.
6. Redeploy the latest commit.
7. Locally, copy `.env.example` to `web/.env.local` and fill the same public values.
   Never add a service-role key.

The migration adds required tables to `supabase_realtime`; no separate table toggle
is needed. Reference:
https://supabase.com/docs/guides/realtime/postgres-changes

## Local commands

```powershell
.\.venv\Scripts\Activate.ps1
python -m fantasy_football_prediction_model.cli project generate
python -m fantasy_football_prediction_model.cli project validate

Set-Location web
npm install
npm run typecheck
npm test
npm run build
npm run dev
```

Open `http://localhost:3000/mock-drafts`. Test multiplayer with two separate browser
profiles so each has a different anonymous identity.

