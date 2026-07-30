import type { DraftSettings, RosterSlot, ScoringPreset } from "./types";

export const TEAM_COUNTS = Array.from({ length: 10 }, (_, index) => 4 + index * 2);
export const ROUND_OPTIONS = Array.from({ length: 30 }, (_, index) => index + 1);
export const TIMER_OPTIONS = [
  { label: "No limit", value: null },
  { label: "10 seconds", value: 10 },
  { label: "15 seconds", value: 15 },
  { label: "30 seconds", value: 30 },
  { label: "45 seconds", value: 45 },
  { label: "1 minute", value: 60 },
  { label: "2 minutes", value: 120 },
  { label: "5 minutes", value: 300 },
  { label: "10 minutes", value: 600 },
  { label: "30 minutes", value: 1800 },
  { label: "1 hour", value: 3600 },
  { label: "2 hours", value: 7200 },
  { label: "4 hours", value: 14400 },
  { label: "8 hours", value: 28800 },
  { label: "12 hours", value: 43200 },
  { label: "24 hours", value: 86400 },
] as const;

export const SCORING_LABELS: Record<ScoringPreset, string> = {
  standard: "Standard",
  half_ppr: "Half PPR",
  ppr: "PPR",
  two_qb: "2QB / Superflex",
  idp: "IDP",
  dynasty_standard: "Dynasty Standard",
  dynasty_half_ppr: "Dynasty Half PPR",
  dynasty_ppr: "Dynasty PPR",
};

export function defaultRoster(): RosterSlot[] {
  const positions = [
    "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF",
    "BENCH", "BENCH", "BENCH", "BENCH", "BENCH",
  ] as const;
  return positions.map((position, index) => ({ id: `slot-${index + 1}`, position }));
}

export const DEFAULT_SETTINGS: DraftSettings = {
  name: "Fantasy Analytics Mock",
  format: "snake",
  scoringPreset: "ppr",
  teamCount: 12,
  rounds: 15,
  pickTimerSeconds: 30,
  cpuAutopick: true,
  playerPool: "all",
  thirdRoundReversal: false,
  alphabeticalPlayers: false,
  showTeamNames: true,
  roster: defaultRoster(),
  auctionBudget: 200,
  minimumBid: 1,
};
