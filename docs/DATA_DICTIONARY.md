# Data dictionary (exported JSON)

Primary files under `web/public/data/`:

| File | Purpose |
|------|---------|
| `metadata.json` | Versions, `dataMode`, seasons, counts, limitations |
| `projections.json` | Full player projections + explanations |
| `rankings.json` | Compact ranking rows |
| `players.json` | Search / routing index |
| `model-performance.json` | Backtest metrics |
| `feature-importance.json` | Feature research summary |
| `data-coverage.json` | Source coverage matrix |

## Player projection (selected fields)

| Field | Meaning |
|-------|---------|
| `playerId` | Canonical GSIS id |
| `slug` | URL slug |
| `projectionSeason` / `sourceSeason` | Target and feature-end seasons |
| `projectedStats.*` | Football season totals |
| `fantasy.*` | Default PPR points, ranks, VORP, tier |
| `range.*` | Low / median / high fantasy points |
| `confidence.*` | Score + label independent of quality |
| `explanation.*` | Deterministic positive/negative factors |
| `dataMode` | `production` or `fixture` (on parent file) |

Schema version: `1.0.0`. Frontend Zod schemas mirror Python Pydantic models.
