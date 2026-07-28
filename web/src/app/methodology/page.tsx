export const metadata = { title: "Methodology" };

export default function MethodologyPage() {
  return (
    <article className="prose-like mx-auto max-w-3xl space-y-6">
      <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">Methodology</h1>
      <p className="text-muted">
        Field Forecast predicts next-season football statistics from information available through
        the completed prior season, then converts those statistics into configurable fantasy points.
      </p>
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
