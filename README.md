# Field Forecast — fantasy-football-prediction-model

Open, reproducible NFL fantasy football projections for the **2026** season using free public data through the completed **2025** season.

> Projections are estimates for informational and entertainment use. This project has no betting or wagering features.

## Features

- nflverse ingestion via `nflreadpy` with local caching
- Position-specific feature engineering (QB / RB / WR / TE) and optional rookie path
- Time-aware backtesting against honest baselines
- Component-stat projections → configurable fantasy scoring → VORP draft ranks
- Static Next.js dashboard (rankings, player pages, compare, methodology, performance)
- Fixture mode for CI/UI without claiming production results

## Architecture

```text
External data (nflverse, optional CFBD)
  → cached raw / parquet
  → validated season tables
  → feature engineering
  → modelling pairs (season t → t+1)
  → rolling-origin backtests
  → trained models + uncertainty
  → 2026 projections + VORP rankings
  → JSON in web/public/data
  → Next.js static site
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

### Windows PowerShell

```powershell
git clone <your-fork-url> fantasy-football-prediction-model
cd fantasy-football-prediction-model
Copy-Item .env.example .env

# Python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".\python\[dev]"

# Fixture projections for the website
python -m fantasy_football_prediction_model.cli pipeline run-all --fixture

# Web
cd web
npm install
npm run dev
```

### WSL / Linux / macOS

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e "./python[dev]"
python -m fantasy_football_prediction_model.cli pipeline run-all --fixture
cd web && npm install && npm run dev
```

## Important commands

```text
ffpm data fetch-nfl
ffpm data build-dataset
ffpm research features
ffpm model backtest
ffpm model train
ffpm project generate [--fixture]
ffpm project validate
ffpm pipeline run-all [--fixture]
ffpm pipeline status
```

## Data mode guard

Every export includes `dataMode`:

- `fixture` — synthetic / sample; website shows a banner
- `production` — built from real pipeline outputs

Never deploy fixture data as production rankings.

## Costs

Everything is designed for free tiers: public GitHub Actions, Vercel Hobby (personal/non-commercial), optional free CollegeFootballData API key. See [docs/COSTS.md](docs/COSTS.md).

## Licence

MIT for project code. Dataset licences and attribution are in [NOTICE.md](NOTICE.md) and [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## What you must do outside the repo

Exact hosting, secrets, and verification steps: **[docs/USER_ACTIONS.md](docs/USER_ACTIONS.md)**.
