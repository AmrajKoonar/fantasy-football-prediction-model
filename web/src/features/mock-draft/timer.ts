export function remainingSeconds(deadline: string | null, now = Date.now()): number | null {
  if (!deadline) return null;
  return Math.max(0, Math.ceil((new Date(deadline).getTime() - now) / 1000));
}

export function formatTimer(seconds: number | null): string {
  if (seconds === null) return "No limit";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

