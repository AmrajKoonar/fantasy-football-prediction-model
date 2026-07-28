export function SampleDataBanner({ dataMode }: { dataMode?: string | null }) {
  if (dataMode !== "fixture") return null;
  return (
    <div
      role="status"
      className="border-b border-warning/40 bg-warning/15 px-4 py-2 text-center text-sm text-foreground"
    >
      Sample / fixture data is loaded. These are not real NFL projections. Run the production
      pipeline before publishing rankings.
    </div>
  );
}
