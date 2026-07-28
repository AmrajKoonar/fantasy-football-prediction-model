import { loadProjections, loadRankings } from "@/lib/data";
import { RankingsTable } from "@/features/rankings/rankings-table";

export const metadata = {
  title: "Rankings",
};

export default async function RankingsPage() {
  const [rankings, projections] = await Promise.all([loadRankings(), loadProjections()]);
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">Rankings</h1>
        <p className="text-muted">
          Sortable draft board with client-side scoring and value-over-replacement recalculation.
        </p>
      </div>
      <RankingsTable rankings={rankings} players={projections.players} />
    </div>
  );
}
