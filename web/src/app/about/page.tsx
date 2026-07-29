export const metadata = { title: "About" };

const sources = [
  {
    name: "nflverse / nflreadpy",
    licence: "CC BY 4.0 (dataset-dependent; see nflverse licences)",
    url: "https://github.com/nflverse/nflverse-data",
    notes: "Player stats, rosters, schedules, snaps, NGS, PFR advanced, draft, combine.",
  },
  {
    name: "CollegeFootballData",
    licence: "See collegefootballdata.com terms",
    url: "https://collegefootballdata.com/",
    notes: "Optional free API for rookie college production. Cached locally. Not required.",
  },
];

export default function AboutPage() {
  return (
    <article className="mx-auto max-w-3xl space-y-8">
      <div className="space-y-4">
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">About</h1>
        <p className="text-muted">
          Fantasy Analytics is an independent, open portfolio project for season-long fantasy football
          draft preparation. It is not affiliated with or endorsed by the NFL, nflverse,
          CollegeFootballData, or any fantasy platform.
        </p>
        <p className="text-muted">
          Projections are estimates. Source data can contain errors. Rankings are for informational
          and entertainment purposes. This application contains no sports-betting, sportsbook, daily
          fantasy wagering, gambling, odds, prize, or monetary-contest functionality.
        </p>
      </div>

      <section className="space-y-4">
        <div>
          <h2 className="text-xl font-semibold">Data sources</h2>
          <p className="text-muted">
            Attribution for public datasets used by the projection pipeline.
          </p>
        </div>
        <ul className="space-y-4">
          {sources.map((source) => (
            <li key={source.name} className="rounded-lg border border-border bg-card p-4">
              <h3 className="font-semibold">{source.name}</h3>
              <p className="text-sm text-muted">{source.notes}</p>
              <p className="mt-2 text-sm">Licence: {source.licence}</p>
              <a href={source.url} className="text-sm text-accent underline" rel="noreferrer">
                {source.url}
              </a>
            </li>
          ))}
        </ul>
        <p className="text-sm text-muted">
          This project does not scrape prohibited sites and does not redistribute copyrighted player
          photography as a dependency of the UI.
        </p>
      </section>
    </article>
  );
}
