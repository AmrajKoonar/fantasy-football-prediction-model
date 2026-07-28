# Troubleshooting

| Symptom | Fix |
|---------|-----|
| `nflreadpy` download failure | Retry; use `--offline` with warm cache; check network |
| Missing optional dataset | Pipeline continues; coverage report marks partial |
| No CFBD key | Reduced rookie mode — expected |
| CFBD rate limit | Rely on cache; wait for monthly reset |
| Polars schema mismatch | Re-fetch with `--force-refresh`; inspect validation report |
| XGBoost install fails | Optional; HistGBM fallback is used |
| Offline missing cache | Remove `--offline` or restore `data/cache` |
| Node version mismatch | Use Node 20+ |
| Python version mismatch | Use 3.11–3.13 |
| Vercel build fails | Root directory must be `web`; ensure JSON present |
| Stale JSON | Re-run `ffpm project generate` / refresh workflow |
| Fixture banner in prod | Rebuild with production pipeline; check `dataMode` |
| PowerShell execution policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Large cache disk use | Delete `data/cache` play-by-play seasons you do not need |
