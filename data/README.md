# `data/`

Working directories for the pipeline. **Almost nothing here is committed.**

## What lives where

| Directory | Committed? | Contents |
| --- | --- | --- |
| `raw/` | No | Untouched source downloads kept for debugging a schema change |
| `cache/` | No | Parquet cache plus provenance manifests, keyed by dataset and season range |
| `interim/` | No | Intermediate season tables built during ingestion |
| `processed/` | No | The final player-season modelling table (`player-seasons.parquet`) |
| `manual/` | **Yes** (examples and corrections) | Operator-supplied factual corrections and optional overrides |
| `manifests/` | **Yes** | Run manifests recording exactly which data produced which output |

## Why raw and cached data are not committed

1. **Size.** A full 2012-2025 pull is roughly 2-4 GB, dominated by play-by-play.
2. **Reproducibility does not require it.** Every file is re-downloadable from
   [nflverse-data releases](https://github.com/nflverse/nflverse-data/releases), and the
   manifests in `manifests/` record the content hash of what was actually used.
3. **Licensing.** Some nflverse components carry share-alike terms. Redistributing bulk
   copies inside an unrelated repository would create obligations this project does not
   need to take on. See [`../NOTICE.md`](../NOTICE.md).

## Approximate disk requirements

| Content | Size |
| --- | --- |
| Play-by-play, 2012-2025 | ~2.5 GB |
| Weekly player and team statistics | ~180 MB |
| Rosters, depth charts, snap counts | ~120 MB |
| Next Gen Stats and PFR advanced | ~25 MB |
| Processed modelling table | ~15 MB |
| Model artifacts | ~40 MB |
| **Total after a full run** | **~3 GB** |

Skip play-by-play with `ffpm data fetch-nfl --skip-pbp` to stay under about 400 MB. Red-zone
and situational features are then unavailable and the affected model inputs are marked
missing rather than guessed.

Inspect and clean up the cache with:

```bash
ffpm pipeline status          # shows cache size and per-dataset freshness
ffpm data fetch-nfl --force-refresh
```

## `manual/`

Two deliberately separate systems, described fully in
[`../docs/USER_ACTIONS.md`](../docs/USER_ACTIONS.md).

### `player-context.csv` - factual corrections

Applied by the production pipeline. Only for things that are objectively true and simply
not yet reflected upstream: a player's team after a signing, a position reclassification,
active status. Copy `player-context.example.csv` to `player-context.csv` to start.

### `projection-overrides.csv` - subjective adjustments

**Disabled by default** (`overrides.apply_projection_overrides` in `configs/project.yml`).
When enabled, an override never replaces the model value: the export carries both
`projectedStats` (adjusted) and `modelProjectedStats` (original), the player is flagged
`isAdjusted`, and the UI labels the row. Copy `projection-overrides.example.csv` to start.

### `player-id-corrections.csv` - identifier fixes

Committed, because identifier corrections are facts about the data rather than opinions
about players. Used by the identity resolver.

### `ranking-inclusions.csv` - ranking coverage exceptions

Committed and audited. This file keeps a small set of fantasy-relevant players visible when
recent injuries, short seasons, or free-agent status push their honest model rank below the
normal publication cutoff. It does not alter projected statistics or pretend that the
reference rank came from this model. The exported display ranks remain dense; each player's
full-pool model rank is retained in `context.modelOverallRank`, and forced rows receive a
`ranking_coverage_inclusion` warning. `allow_unsigned` must be explicitly true to publish a
listed free agent.
