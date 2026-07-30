import Link from "next/link";

export function SetupRequired() {
  return (
    <section className="rounded-xl border border-warning/40 bg-warning/10 p-6">
      <h2 className="text-lg font-semibold">Mock draft database setup required</h2>
      <p className="mt-2 max-w-2xl text-sm text-muted">
        This deployment does not have its public Supabase URL and publishable key yet. Rankings
        remain available; persistent multiplayer drafts will activate after the documented setup.
      </p>
      <Link href="/about" className="mt-4 inline-block text-sm font-medium text-accent underline">
        About Fantasy Analytics
      </Link>
    </section>
  );
}

