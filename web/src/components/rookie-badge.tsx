import { cn } from "@/lib/utils";

type Props = {
  className?: string;
  size?: "sm" | "md";
};

/** Purple scalloped star with a centered "R" to mark rookies. */
export function RookieBadge({ className, size = "sm" }: Props) {
  const dim = size === "md" ? "h-[18px] w-[18px]" : "h-[15px] w-[15px]";
  return (
    <span
      title="Rookie"
      aria-label="Rookie"
      className={cn(
        "inline-flex shrink-0 translate-y-[1px] items-center justify-center leading-none",
        dim,
        className,
      )}
    >
      <svg
        viewBox="0 0 24 24"
        width="100%"
        height="100%"
        className="block overflow-visible"
        aria-hidden="true"
        focusable="false"
      >
        <path
          fill="var(--rookie)"
          d="M12 1.4L14.07 4.27L17.3 2.82L17.66 6.34L21.18 6.7L19.73 9.93L22.6 12L19.73 14.07L21.18 17.3L17.66 17.66L17.3 21.18L14.07 19.73L12 22.6L9.93 19.73L6.7 21.18L6.34 17.66L2.82 17.3L4.27 14.07L1.4 12L4.27 9.93L2.82 6.7L6.34 6.34L6.7 2.82L9.93 4.27Z"
        />
        <text
          x="12"
          y="12"
          textAnchor="middle"
          dominantBaseline="central"
          fill="#fff"
          fontSize="10.5"
          fontWeight="700"
          fontFamily="ui-sans-serif, system-ui, sans-serif"
          style={{ userSelect: "none" }}
        >
          R
        </text>
      </svg>
    </span>
  );
}
