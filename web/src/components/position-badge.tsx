import { cn } from "@/lib/utils";
import type { Position } from "@/lib/schemas";

const styles: Record<Position, string> = {
  QB: "text-[color:var(--qb)] border-[color:var(--qb)]",
  RB: "text-[color:var(--rb)] border-[color:var(--rb)]",
  WR: "text-[color:var(--wr)] border-[color:var(--wr)]",
  TE: "text-[color:var(--te)] border-[color:var(--te)]",
};

export function PositionBadge({ position }: { position: Position }) {
  return (
    <span
      className={cn(
        "inline-flex min-w-9 items-center justify-center rounded border px-1.5 py-0.5 text-xs font-semibold",
        styles[position],
      )}
      aria-label={`Position ${position}`}
    >
      {position}
    </span>
  );
}
