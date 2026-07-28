export type ScoringRules = {
  passingYardsPerPoint: number;
  passingTouchdown: number;
  interception: number;
  rushingYardsPerPoint: number;
  rushingTouchdown: number;
  reception: number;
  receivingYardsPerPoint: number;
  receivingTouchdown: number;
  fumbleLost: number;
};

export const PRESETS: Record<string, ScoringRules> = {
  standard: {
    passingYardsPerPoint: 25,
    passingTouchdown: 4,
    interception: -2,
    rushingYardsPerPoint: 10,
    rushingTouchdown: 6,
    reception: 0,
    receivingYardsPerPoint: 10,
    receivingTouchdown: 6,
    fumbleLost: -2,
  },
  half_ppr: {
    passingYardsPerPoint: 25,
    passingTouchdown: 4,
    interception: -2,
    rushingYardsPerPoint: 10,
    rushingTouchdown: 6,
    reception: 0.5,
    receivingYardsPerPoint: 10,
    receivingTouchdown: 6,
    fumbleLost: -2,
  },
  ppr: {
    passingYardsPerPoint: 25,
    passingTouchdown: 4,
    interception: -2,
    rushingYardsPerPoint: 10,
    rushingTouchdown: 6,
    reception: 1,
    receivingYardsPerPoint: 10,
    receivingTouchdown: 6,
    fumbleLost: -2,
  },
};

export type StatLine = {
  passingYards?: number | null;
  passingTouchdowns?: number | null;
  interceptions?: number | null;
  rushingYards?: number | null;
  rushingTouchdowns?: number | null;
  receptions?: number | null;
  receivingYards?: number | null;
  receivingTouchdowns?: number | null;
  fumblesLost?: number | null;
};

export function scoreStats(stats: StatLine, rules: ScoringRules): number {
  const passingYards = stats.passingYards ?? 0;
  const passingTds = stats.passingTouchdowns ?? 0;
  const interceptions = stats.interceptions ?? 0;
  const rushingYards = stats.rushingYards ?? 0;
  const rushingTds = stats.rushingTouchdowns ?? 0;
  const receptions = stats.receptions ?? 0;
  const receivingYards = stats.receivingYards ?? 0;
  const receivingTds = stats.receivingTouchdowns ?? 0;
  const fumbles = stats.fumblesLost ?? 0;

  let total = 0;
  if (rules.passingYardsPerPoint) total += passingYards / rules.passingYardsPerPoint;
  total += passingTds * rules.passingTouchdown;
  total += interceptions * rules.interception;
  if (rules.rushingYardsPerPoint) total += rushingYards / rules.rushingYardsPerPoint;
  total += rushingTds * rules.rushingTouchdown;
  total += receptions * rules.reception;
  if (rules.receivingYardsPerPoint) total += receivingYards / rules.receivingYardsPerPoint;
  total += receivingTds * rules.receivingTouchdown;
  total += fumbles * rules.fumbleLost;
  return total;
}

export function getPreset(name: string): ScoringRules {
  return PRESETS[name] ?? PRESETS.ppr;
}
