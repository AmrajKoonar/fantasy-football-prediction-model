import { loadPerformance } from "@/lib/data";

export const metadata = { title: "Model performance" };

export default async function PerformancePage() {
  const performance = await loadPerformance();
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">
          Model performance
        </h1>
        <p className="text-muted">
          Out-of-sample rolling-origin results. Favourable and unfavourable outcomes are both shown.
        </p>
      </div>
      {!performance ? (
        <p className="text-sm text-muted">No performance file found.</p>
      ) : (
        <>
          <dl className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-border bg-card p-4">
              <dt className="text-sm text-muted">Model version</dt>
              <dd className="font-semibold">{performance.modelVersion}</dd>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <dt className="text-sm text-muted">Backtest seasons</dt>
              <dd className="font-semibold">
                {performance.backtestSeasons.length
                  ? performance.backtestSeasons.join(", ")
                  : "Not yet run"}
              </dd>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <dt className="text-sm text-muted">Data mode</dt>
              <dd className="font-semibold capitalize">{performance.dataMode}</dd>
            </div>
          </dl>
          <section className="space-y-2">
            <h2 className="text-xl font-semibold">Known weaknesses</h2>
            <ul className="list-disc space-y-1 pl-5 text-muted">
              {performance.knownWeaknesses.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
          <section className="space-y-2">
            <h2 className="text-xl font-semibold">Fantasy metrics</h2>
            {!performance.fantasyMetrics.length ? (
              <p className="text-sm text-muted">
                Run <code>ffpm model backtest</code> to populate baseline and candidate metrics.
              </p>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-border bg-card">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-muted">
                      <th className="px-3 py-2 text-left">Position</th>
                      <th className="px-3 py-2 text-left">Model</th>
                      <th className="px-3 py-2 text-left">MAE</th>
                      <th className="px-3 py-2 text-left">RMSE</th>
                      <th className="px-3 py-2 text-left">Selected</th>
                    </tr>
                  </thead>
                  <tbody>
                    {performance.fantasyMetrics.map((row, index) => (
                      <tr key={index} className="border-b border-border/60">
                        <td className="px-3 py-2">{row.position}</td>
                        <td className="px-3 py-2">{row.model}</td>
                        <td className="px-3 py-2">{row.mae?.toFixed?.(2) ?? "-"}</td>
                        <td className="px-3 py-2">{row.rmse?.toFixed?.(2) ?? "-"}</td>
                        <td className="px-3 py-2">{row.isSelected ? "yes" : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
