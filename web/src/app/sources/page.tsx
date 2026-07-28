export const metadata = { title: "Data sources" };

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

export default function SourcesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">
          Data sources
        </h1>
        <p className="text-muted">
          Attribution for public datasets used by the projection pipeline.
        </p>
      </div>
      <ul className="space-y-4">
        {sources.map((source) => (
          <li key={source.name} className="rounded-lg border border-border bg-card p-4">
            <h2 className="font-semibold">{source.name}</h2>
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
    </div>
  );
}
