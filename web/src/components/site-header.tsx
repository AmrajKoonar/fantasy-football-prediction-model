"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";

const links = [
  { href: "/", label: "Home" },
  { href: "/rankings", label: "Rankings" },
  { href: "/compare", label: "Compare" },
  { href: "/methodology", label: "Methodology" },
  { href: "/performance", label: "Performance" },
  { href: "/about", label: "About" },
];

export function SiteHeader() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();

  return (
    <header className="border-b border-border bg-card/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex items-center gap-6">
          <Link href="/" className="font-[family-name:var(--font-display)] text-xl font-semibold tracking-tight">
            Fantasy Analytics
          </Link>
          <nav aria-label="Primary" className="hidden items-center gap-1 md:flex">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-sm text-muted transition hover:text-foreground",
                  pathname === link.href && "bg-accent/10 text-foreground",
                )}
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
        <button
          type="button"
          aria-label="Toggle colour theme"
          className="rounded-md border border-border p-2 text-muted hover:text-foreground"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          <Sun className="h-4 w-4 dark:hidden" />
          <Moon className="hidden h-4 w-4 dark:block" />
        </button>
      </div>
      <nav aria-label="Mobile" className="flex gap-2 overflow-x-auto px-4 pb-3 md:hidden">
        {links.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "whitespace-nowrap rounded-md border border-border px-2.5 py-1 text-xs",
              pathname === link.href && "border-accent text-accent",
            )}
          >
            {link.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
