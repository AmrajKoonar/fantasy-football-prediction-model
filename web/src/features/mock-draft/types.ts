export const BASE_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"] as const;
export const ROSTER_POSITIONS = [
  ...BASE_POSITIONS,
  "FLEX",
  "SUPERFLEX",
  "IDP_FLEX",
  "BENCH",
] as const;

export type BasePosition = (typeof BASE_POSITIONS)[number];
export type RosterPosition = (typeof ROSTER_POSITIONS)[number];
export type DraftFormat = "snake" | "linear" | "auction";
export type ScoringPreset =
  | "standard"
  | "half_ppr"
  | "ppr"
  | "two_qb"
  | "idp"
  | "dynasty_standard"
  | "dynasty_half_ppr"
  | "dynasty_ppr";
export type PlayerPoolFilter = "all" | "rookies" | "veterans";
export type DraftStatus = "lobby" | "active" | "paused" | "completed" | "cancelled";

export type RosterSlot = {
  id: string;
  position: RosterPosition;
};

export type DraftSettings = {
  name: string;
  format: DraftFormat;
  scoringPreset: ScoringPreset;
  teamCount: number;
  rounds: number;
  pickTimerSeconds: number | null;
  cpuAutopick: boolean;
  playerPool: PlayerPoolFilter;
  thirdRoundReversal: boolean;
  alphabeticalPlayers: boolean;
  showTeamNames: boolean;
  roster: RosterSlot[];
  auctionBudget: number;
  minimumBid: number;
};

export type DraftPlayer = {
  playerId: string;
  name: string;
  team: string;
  primaryPosition: BasePosition;
  eligiblePositions: BasePosition[];
  rookie: boolean;
  age: number | null;
  overallRank: number;
  positionRank: number;
  tier: number;
  projectedPoints: number;
  pointsPerGame: number;
  adp: number;
  source: "projection" | "roster-baseline" | "team-defense";
};

export type DraftPick = {
  id: string;
  draftId: string;
  playerId: string;
  slotNumber: number;
  round: number;
  pickNumber: number;
  price: number | null;
  madeBy: string | null;
  isCpu: boolean;
  createdAt: string;
};

export type DraftSlot = {
  id: string;
  slotNumber: number;
  userId: string | null;
  displayName: string;
  teamName: string;
  isCpu: boolean;
  budgetRemaining: number;
};

export type DraftSummary = {
  id: string;
  publicSlug: string;
  name: string;
  format: DraftFormat;
  scoringPreset: ScoringPreset;
  teamCount: number;
  rounds: number;
  status: DraftStatus;
  hostUserId: string;
  currentPickNumber: number;
  pickDeadlineAt: string | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  settings: DraftSettings;
  seed: number;
};

export type CpuContext = {
  drafted: DraftPlayer[];
  roster: RosterSlot[];
  scoringPreset: ScoringPreset;
  round: number;
  totalRounds: number;
  seed: number;
  slotNumber: number;
};

