# Contributing

1. Use branch `main` for this portfolio project unless collaborating.
2. Prefer Conventional Commit messages.
3. Run Python tests: `pytest python/tests/unit -q`
4. Run web checks: `cd web && npm run typecheck && npm run test && npm run build`
5. Never commit `.env`, API keys, or raw `data/cache` downloads.
6. Fixture exports must keep `dataMode: "fixture"`.
7. Do not add paid services or betting features.
