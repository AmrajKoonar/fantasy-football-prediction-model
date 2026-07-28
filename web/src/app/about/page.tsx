export const metadata = { title: "About" };

export default function AboutPage() {
  return (
    <article className="mx-auto max-w-3xl space-y-4">
      <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">About</h1>
      <p className="text-muted">
        Field Forecast is an independent, open portfolio project for season-long fantasy football
        draft preparation. It is not affiliated with or endorsed by the NFL, nflverse,
        CollegeFootballData, or any fantasy platform.
      </p>
      <p className="text-muted">
        Projections are estimates. Source data can contain errors. Rankings are for informational
        and entertainment purposes. This application contains no sports-betting, sportsbook, daily
        fantasy wagering, gambling, odds, prize, or monetary-contest functionality.
      </p>
    </article>
  );
}
