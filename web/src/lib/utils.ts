import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatPoints(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export function formatRank(value: number | null | undefined): string {
  if (value == null) return "—";
  return String(value);
}
