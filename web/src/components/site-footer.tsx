import type { ExportMetadata } from "@/lib/schemas";

export function SiteFooter({ meta }: { meta: ExportMetadata | null }) {
  return (
    <footer className="mt-12 border-t border-border">
      <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-6 text-sm text-muted sm:px-6 lg:px-8">
        <p>
          Field Forecast is an independent portfolio project. Not affiliated with the NFL, nflverse,
          or any fantasy platform.
        </p>
        <p>
          Model {meta?.modelVersion ?? "—"} · Schema {meta?.schemaVersion ?? "—"} · Release{" "}
          {meta?.projectionRelease ?? "—"} · Mode {meta?.dataMode ?? "unknown"}
        </p>
      </div>
    </footer>
  );
}
