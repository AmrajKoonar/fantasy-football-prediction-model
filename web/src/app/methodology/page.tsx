export const metadata = { title: "Methodology" };

export default function MethodologyPage() {
  return (
    <article className="prose-like mx-auto max-w-3xl space-y-8">
      <div className="space-y-4">
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">
          Methodology
        </h1>
        <p className="text-muted">
          Field Forecast predicts next-season football statistics from information available through
          the completed prior season, then converts those statistics into configurable fantasy
          points and draft rankings.
        </p>
      </div>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">How it works</h2>
        <p className="text-muted">
          Below is the full path from raw NFL data to the rankings on this site, explained in plain
          language first, then with a short technical note for each step.
        </p>

        <ol className="list-decimal space-y-5 pl-5">
          <li className="space-y-1">
            <p className="font-medium text-foreground">Collect historical NFL data</p>
            <p className="text-muted">
              Easy: We download free public NFL datasets (stats, teams, drafts, snaps, and similar)
              and store them on disk so runs are repeatable.
            </p>
            <p className="text-sm text-muted">
              Technical: nflverse tables are ingested via nflreadpy into a local parquet cache
              (optional CollegeFootballData season-batch pulls for rookies).
            </p>
          </li>
          <li className="space-y-1">
            <p className="font-medium text-foreground">Build player-season features</p>
            <p className="text-muted">
              Easy: For each player and season we summarize what was knowable at the time - usage,
              production, age, draft capital, team context - without peeking at next year&apos;s
              results.
            </p>
            <p className="text-sm text-muted">
              Technical: Feature engineering produces season-t rows with leakage controls; modelling
              pairs join season-t features to season-(t+1) outcomes (including true zeros for
              attrition).
            </p>
          </li>
          <li className="space-y-1">
            <p className="font-medium text-foreground">Train and check models over time</p>
            <p className="text-muted">
              Easy: We teach separate models for quarterbacks, running backs, receivers, and tight
              ends, then test them on past seasons as if we were forecasting those years before they
              happened.
            </p>
            <p className="text-sm text-muted">
              Technical: Position-target regressors (e.g. HistGradientBoosting) are rolling-origin
              backtested against baselines such as previous-season totals, per-game rates, and
              age-group means.
            </p>
          </li>
          <li className="space-y-1">
            <p className="font-medium text-foreground">Project next-season box-score stats</p>
            <p className="text-muted">
              Easy: The models (plus safeguards like age and role context) estimate games, targets,
              carries, yards, touchdowns, and related stats for the upcoming season. Rookies without
              NFL history use draft history, landing-spot context, and optional college production.
            </p>
            <p className="text-sm text-muted">
              Technical: Registered models predict each projection target; hybrid mean-reversion /
              context multipliers fill gaps; rookies use year-1 draft-bucket curves blended with CFBD
              when available. Football consistency constraints are applied afterward.
            </p>
          </li>
          <li className="space-y-1">
            <p className="font-medium text-foreground">Convert stats into fantasy points</p>
            <p className="text-muted">
              Easy: Those football stats are scored with your league&apos;s rules (default full PPR).
              Changing scoring on the rankings page recalculates points in the browser.
            </p>
            <p className="text-sm text-muted">
              Technical: Component stats are mapped through a configurable scoring ruleset
              (passing/rushing/receiving/fumbles) to season totals and points per game.
            </p>
          </li>
          <li className="space-y-1">
            <p className="font-medium text-foreground">Rank by value, not only raw points</p>
            <p className="text-muted">
              Easy: Players are ordered for drafting using value over a typical replacement starter
              at their position, so scarce positions are not buried under high-scoring but easily
              replaced ones.
            </p>
            <p className="text-sm text-muted">
              Technical: Default overall order uses VORP against league-size replacement levels,
              with position ranks, gap-based tiers, and risk-adjusted views derived from projection
              ranges.
            </p>
          </li>
          <li className="space-y-1">
            <p className="font-medium text-foreground">Publish to this website</p>
            <p className="text-muted">
              Easy: The pipeline writes JSON files the site reads statically - no live betting feeds,
              no paid APIs in the browser.
            </p>
            <p className="text-sm text-muted">
              Technical: Validated exports land in web/public/data (projections, rankings, metadata)
              and are consumed by the Next.js App Router UI.
            </p>
          </li>
        </ol>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Season naming</h2>
        <p className="text-muted">
          The 2025 season is the NFL regular season that began in 2025. Projections for the 2026
          season use information available through 2025.
        </p>
      </section>
      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Player-season modelling</h2>
        <p className="text-muted">
          Each training row pairs season-t features with season-(t+1) outcomes. Features never use
          future information. Players without a next-season statistical record receive a true zero
          outcome so the model learns attrition, not only survival.
        </p>
      </section>
      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Models and baselines</h2>
        <p className="text-muted">
          Position-specific models are compared against previous-season totals, per-game rates,
          multi-year averages, age-group means, ridge regression, and opportunity medians.
          Rolling-origin backtests choose the winner.
        </p>
      </section>
      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Fantasy scoring and VORP</h2>
        <p className="text-muted">
          Default rankings use full PPR. Changing scoring or league settings recalculates points and
          value over replacement in the browser without retraining. Default draft order uses VORP,
          not raw points.
        </p>
      </section>
      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Limitations</h2>
        <ul className="list-disc space-y-1 pl-5 text-muted">
          <li>Injury reports after 2024 are not automatically ingested.</li>
          <li>CollegeFootballData enrichment is optional; rookies may use reduced features.</li>
          <li>Projections are estimates. They are not guarantees.</li>
          <li>Current roster news after the last data refresh is not automatic.</li>
        </ul>
      </section>
    </article>
  );
}
