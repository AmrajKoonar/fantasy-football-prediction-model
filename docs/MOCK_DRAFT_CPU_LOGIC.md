# Mock Draft CPU Logic

CPU selection has two layers.

1. `web/src/features/mock-draft/cpu.ts` is the explainable, tested strategy used
   for previews and candidate evaluation.
2. `advance_mock_draft` is authoritative. It locks the draft, verifies CPU/expiry,
   respects a human queue, excludes drafted players, delays K/DEF, and picks once.

## Candidate score

The TypeScript strategy combines preset-adjusted projected value with direct
roster-need boosts, deterministic seeded noise, a strong early K/DEF penalty,
extra 2QB value, and dynasty age/rookie adjustments. Candidates that cannot fit
the roster are invalid. A fixed seed makes behavior reproducible.

## Timer and queue

- CPU seats advance when any connected client calls the idempotent RPC.
- Human seats advance only after the database deadline.
- Human timeout first uses the top available queued player.
- An empty queue uses the deterministic database fallback.

The SQL expression is intentionally smaller and auditable. A future edge worker may
share richer strategy code, but must still submit through an atomic database function.

In auctions, CPUs nominate the best roster-valid available value, then make at most
one counter-bid per second. Their maximum price scales with projected points, while
the database reserves the minimum bid needed for every remaining roster slot. Seeded
slot ordering keeps simultaneous CPU interest reproducible, and normal anti-sniping
deadline extensions apply.
