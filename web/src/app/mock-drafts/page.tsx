import type { Metadata } from "next";
import Link from "next/link";
import { Clock3, Gavel, Radio, ShieldCheck, Users } from "lucide-react";
import { MockDraftHistory } from "@/components/mock-draft/mock-draft-history";
import { SetupRequired } from "@/components/mock-draft/setup-required";

export const metadata: Metadata = {
  title: "Mock Drafts",
  description: "Create a persistent multiplayer fantasy football mock draft.",
};

export default function MockDraftsPage() {
  const configured = Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
  );
  return (
    <div className="space-y-10">
      <section className="overflow-hidden rounded-2xl border border-border bg-card">
        <div className="grid gap-8 p-6 sm:p-10 lg:grid-cols-[1.4fr_1fr] lg:items-center">
          <div>
            <p className="text-sm font-medium uppercase tracking-[0.2em] text-accent">
              Live draft room
            </p>
            <h1 className="mt-3 font-[family-name:var(--font-display)] text-4xl font-semibold sm:text-5xl">
              Mock draft with people, CPUs, or both.
            </h1>
            <p className="mt-4 max-w-2xl text-muted">
              Build the league you actually play: snake, linear, auction, 3RR, dynasty,
              superflex, IDP, custom rosters, and timers from ten seconds to 24 hours.
              Every room is persistent and shareable.
            </p>
            <Link
              href="/mock-drafts/new"
              className="mt-6 inline-flex rounded-md bg-accent px-5 py-2.5 font-medium text-accent-foreground"
            >
              Create a mock draft
            </Link>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm">
            {[
              [Radio, "Realtime rooms"],
              [Users, "4–22 teams"],
              [Gavel, "Full auctions"],
              [Clock3, "Persistent timers"],
              [ShieldCheck, "Atomic picks"],
            ].map(([Icon, label]) => {
              const FeatureIcon = Icon as typeof Radio;
              return (
                <div key={String(label)} className="rounded-lg border border-border bg-background p-4">
                  <FeatureIcon className="mb-3 h-5 w-5 text-accent" />
                  <span>{String(label)}</span>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {!configured ? <SetupRequired /> : <MockDraftHistory />}

      <section className="grid gap-4 md:grid-cols-3">
        <article className="rounded-xl border border-border bg-card p-5">
          <h2 className="font-semibold">Create and invite</h2>
          <p className="mt-2 text-sm text-muted">
            Configure every setting, claim your seat, then copy one link for the league.
          </p>
        </article>
        <article className="rounded-xl border border-border bg-card p-5">
          <h2 className="font-semibold">Draft without fear</h2>
          <p className="mt-2 text-sm text-muted">
            Reload or reconnect at any time. The board, queues, clock, chat, and budgets persist.
          </p>
        </article>
        <article className="rounded-xl border border-border bg-card p-5">
          <h2 className="font-semibold">Study the result</h2>
          <p className="mt-2 text-sm text-muted">
            Completed boards stay public, searchable, and easy to copy into league chat.
          </p>
        </article>
      </section>
    </div>
  );
}

