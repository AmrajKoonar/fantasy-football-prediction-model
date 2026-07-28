# `fantasy_football_prediction_model` (Python analytics package)

The Python half of the [fantasy-football-prediction-model](../README.md) monorepo. It owns
everything from raw data ingestion through to the validated JSON that the Next.js application
reads.

Full documentation lives in [`../docs`](../docs). This file is the short version for people
working inside `python/`.

## Install

```bash
# From the repository root.
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e "./python[dev,explain]"
```

`uv` is supported and faster:

```bash
uv venv
uv pip install -e "./python[dev,explain]"
```

## Layout

| Path | Responsibility |
| --- | --- |
| `data_sources/` | Adapters for nflverse and CollegeFootballData, plus the on-disk cache |
| `data/` | Ingestion orchestration, schema validation, identity resolution, aggregation, manifests |
| `features/` | Position-specific feature engineering and the feature-research pipeline |
| `models/` | Baselines, preprocessing, training, tuning, ensembling, uncertainty, registry |
| `evaluation/` | Metrics, rolling-origin backtesting, leakage checks, reports |
| `projections/` | Projection generation, football constraints, scoring, VORP, ranking, explanations |
| `exports/` | Pydantic export contract, JSON/CSV writers, metadata |
| `cli.py` | The `ffpm` Typer command-line interface |

## Common commands

```bash
ffpm --help
ffpm pipeline run-all                 # full pipeline, real data
ffpm pipeline run-all --fixture       # full pipeline, synthetic fixtures
ffpm pipeline status
ffpm data audit
ffpm research features
ffpm model backtest --position WR
ffpm project generate --target-season 2026
ffpm project validate
```

## Quality gates

```bash
ruff check .
ruff format --check .
mypy
pytest
pytest -m "not slow and not network"   # fast subset used by CI
```
