# User actions (outside the codebase)

Exact steps the repository owner must perform. Nothing here is optional if you want a public production site with real data.

## 1. GitHub

1. Confirm the repository is named `fantasy-football-prediction-model`.
2. Confirm the default branch is `main`.
3. Make the repository **public** if you want standard free public-repo GitHub Actions usage (subject to GitHub’s current policy).
4. Push this codebase:

```powershell
git push -u origin main
```

5. Open the **Actions** tab and enable workflows if GitHub asks.
6. Run **Refresh projections** manually (`workflow_dispatch`).
7. Review artifacts and any PR created by the workflow.
8. Under **Settings → Actions → General**, allow read/write permissions if the refresh workflow should open PRs.
9. Optionally protect `main` after the first successful green CI.
10. Disable the scheduled refresh cron in `.github/workflows/refresh-projections.yml` (or pause the workflow) if you do not want periodic runs.
11. Monitor GitHub’s free Actions policy changes.

## 2. CollegeFootballData (rookies) — do this on your machine

Without a key, rookies still appear in rankings using **reduced** mode (nflverse draft / landing spot only). With a free CFBD key you get **full** mode (college production blended in).

1. Open https://collegefootballdata.com/key and create a free account / API key.
2. Review the current free-tier monthly request limit on that site (do not burn it with per-player calls — this repo only uses season-batch endpoints).
3. From the repo root, create `.env` if you do not have one:
   ```powershell
   Copy-Item .env.example .env
   ```
4. Edit `.env` and set (no quotes needed):
   ```
   CFBD_API_KEY=your_key_here
   ```
5. Confirm `.env` is gitignored and **never commit** it. Do **not** put `CFBD_API_KEY` on Vercel.
6. Optional for GitHub Actions refresh only: repo **Settings → Secrets and variables → Actions → New repository secret** named `CFBD_API_KEY` with the same value.
7. Activate the venv, then fetch college data and rebuild rankings:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m fantasy_football_prediction_model.cli data fetch-rookies
   python -m fantasy_football_prediction_model.cli project generate
   python -m fantasy_football_prediction_model.cli project validate
   ```
8. Confirm `web/public/data/metadata.json` shows `"rookieMode": "full"` (or `"reduced"` if the key/fetch failed).
9. Without a key, step 7 still works in reduced mode after you have already run `data fetch-nfl` (draft picks required).

## Manual projection overrides

1. Copy `data/manual/projection-overrides.example.csv` to `data/manual/projection-overrides.csv` (gitignored).
2. Add rows with real `player_id` (gsis id), `field` (e.g. `targets`, `games`, `role_multiplier`), and `new_value`.
3. Ensure `configs/project.yml` has `overrides.apply_projection_overrides: true`.
4. Re-run `python -m fantasy_football_prediction_model.cli project generate`.

## Ranking coverage audit

`data/manual/ranking-inclusions.csv` contains reviewed visibility exceptions for recognizable
fantasy players who fall below the model's normal publication cutoff. Review it whenever you
refresh rankings:

1. Compare the current PPR consensus top-player list with `web/public/data/rankings.json`.
2. Remove an inclusion when the player naturally returns to the model top-N.
3. Add a player only with their canonical `gsis_id`, a dated reason, and a source note.
4. Set `allow_unsigned=true` only when an unsigned player is intentionally useful to show.
5. Re-run `project generate` and `project validate`; forced players retain their full-pool
   model rank in `context.modelOverallRank` and carry a machine-readable warning.

## Offseason roster patch (2026)

The file `data/manual/2026_offseason_transactions.csv` is a **point-in-time** patch (`as_of_date`). It never rewrites 2025 historical teams; it only drives 2026 week-1 / projection / vacated-opportunity context.

Before publishing rankings after training-camp moves:

```powershell
.\.venv\Scripts\Activate.ps1
python -m fantasy_football_prediction_model.cli data fetch-nfl --force-refresh
python -m fantasy_football_prediction_model.cli data build-dataset
python -m fantasy_football_prediction_model.cli data transactions --season 2026 --as-of 2026-07-29
python -m fantasy_football_prediction_model.cli data audit-rosters --season 2026
python -m fantasy_football_prediction_model.cli project generate
python -m fantasy_football_prediction_model.cli project validate
```

Checklist:

1. Re-check every player marked `FA` / `unsigned` against a current roster source.
2. Re-check uncertain QB competitions (MIA, ATL, LV, ARI, etc.).
3. Re-check every `P1` row in the CSV.
4. Update `as_of_date` in the CSV when you edit it.
5. Confirm `web/public/data/metadata.json` includes `rosterDataAsOf` and no player is still on their 2025 team after a confirmed 2026 move.
6. `audit-rosters` fails the process when a P1 conflict is unresolved — fix the CSV or refresh nflverse data before exporting.

## 3. Local setup

### Version checks

```powershell
git --version
node --version   # 20+ recommended
python --version # 3.11–3.13
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".\python\[dev]"
Copy-Item .env.example .env
python -m fantasy_football_prediction_model.cli pipeline run-all --fixture
cd web; npm install; npm run dev
```

If PowerShell blocks scripts: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### WSL / Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e "./python[dev]"
cp .env.example .env
python -m fantasy_football_prediction_model.cli pipeline run-all --fixture
cd web && npm install && npm run dev
```

## 4. Production data generation

Approximate first download: several GB if play-by-play is included. Cache lives under `data/cache` (gitignored).

```powershell
# Online pipeline (requires network). Rookie enrichment needs CFBD_API_KEY in .env.
python -m fantasy_football_prediction_model.cli data fetch-nfl
python -m fantasy_football_prediction_model.cli data fetch-rookies
python -m fantasy_football_prediction_model.cli data build-dataset
python -m fantasy_football_prediction_model.cli model backtest
python -m fantasy_football_prediction_model.cli model train
python -m fantasy_football_prediction_model.cli project generate
python -m fantasy_football_prediction_model.cli project validate
```

Confirm `web/public/data/metadata.json` has `"dataMode": "production"` before publishing. After a successful CFBD fetch it should also show `"rookieMode": "full"`.

Offline: `ffpm ... --offline` uses only cache and fails loudly if required data is missing.

## 5. Vercel

1. Visit https://vercel.com and sign in with GitHub.
2. Import this repository.
3. Set **Root Directory** to `web`.
4. Confirm Next.js is detected.
5. Add env `NEXT_PUBLIC_SITE_URL` = your Vercel URL (after first deploy if needed).
6. Do **not** add `CFBD_API_KEY` to Vercel — the site never calls CFBD.
7. Deploy.
8. Copy the production URL, set `NEXT_PUBLIC_SITE_URL`, redeploy if needed.
9. Verify: home, rankings, scoring change, player pages, compare, mobile layout, sources/about.
10. Vercel Hobby is for personal, non-commercial use; policies can change.

Optional custom domains cost money and are not required.

## 6. Final verification checklist

```text
[ ] Production site loads
[ ] Rankings contain validated data
[ ] Projection season is correct
[ ] Model version is displayed
[ ] Last updated timestamp is displayed
[ ] Scoring settings work
[ ] Filters work
[ ] Player pages work
[ ] Comparison works
[ ] Mobile layout works
[ ] Data-source attribution is visible
[ ] No secret appears in the browser bundle
[ ] No fixture-data banner appears in production
[ ] GitHub Actions pass
[ ] Vercel build passes
```
