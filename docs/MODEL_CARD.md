# Model card

| Field | Value |
|-------|-------|
| Intended use | Season-long fantasy draft preparation |
| Out of scope | Betting, DFS contests, injury diagnosis |
| Training window | Configurable; default feature seasons from 2012 |
| Target season | 2026 (configurable) |
| Algorithms | Baselines + sklearn ensembles; optional boosting |
| Uncertainty | Residual intervals + confidence score |
| Reproducibility | Fixed seed 371, YAML configs, manifests |
| Model version | 2026.1.0 |
| Schema version | 1.0.0 |

Known biases and limitations: see `docs/LIMITATIONS.md`. Metrics are only trustworthy after a real `ffpm model backtest` on production data—not fixture mode.
