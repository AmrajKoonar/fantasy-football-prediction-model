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

## 2. CollegeFootballData (optional)

1. Visit https://collegefootballdata.com/
2. Create a free account if currently required.
3. Obtain a free API key.
4. Review the current free-tier monthly limit.
5. Add locally: `CFBD_API_KEY=...` in `.env` (never commit `.env`).
6. Add the same value as a GitHub Actions secret named `CFBD_API_KEY`.
7. Run `ffpm data fetch-rookies`.
8. Without a key, the pipeline stays in **reduced** rookie mode. Veteran projections still work.

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
# Online veteran pipeline (requires network)
python -m fantasy_football_prediction_model.cli data fetch-nfl
python -m fantasy_football_prediction_model.cli data build-dataset
python -m fantasy_football_prediction_model.cli model backtest
python -m fantasy_football_prediction_model.cli model train
python -m fantasy_football_prediction_model.cli project generate
python -m fantasy_football_prediction_model.cli project validate
```

Confirm `web/public/data/metadata.json` has `"dataMode": "production"` before publishing.

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
