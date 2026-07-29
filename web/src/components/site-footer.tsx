import Link from "next/link";
import type { ExportMetadata } from "@/lib/schemas";

const GITHUB_URL = "https://github.com/AmrajKoonar/fantasy-football-prediction-model";
const LINKEDIN_URL = "https://www.linkedin.com/in/amraj-koonar/";

export function SiteFooter({ meta }: { meta: ExportMetadata | null }) {
  return (
    <footer className="mt-12 border-t border-border">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-6 text-sm text-muted sm:px-6 lg:px-8">
        <p>
          Fantasy Analytics is an independent portfolio project. Not affiliated with the NFL, nflverse,
          or any fantasy platform.
        </p>
        <p>
          Model {meta?.modelVersion ?? "-"} · Schema {meta?.schemaVersion ?? "-"} · Release{" "}
          {meta?.projectionRelease ?? "-"} · Mode {meta?.dataMode ?? "unknown"}
        </p>
        <p className="flex flex-wrap gap-x-4 gap-y-1">
          <Link
            href={GITHUB_URL}
            className="underline hover:text-foreground"
            target="_blank"
            rel="noreferrer"
          >
            GitHub
          </Link>
          <Link
            href={LINKEDIN_URL}
            className="underline hover:text-foreground"
            target="_blank"
            rel="noreferrer"
          >
            LinkedIn
          </Link>
        </p>
      </div>
    </footer>
  );
}
