import { z } from "zod";

export const SCHEMA_VERSION = "1.0.0";

export const PositionSchema = z.enum(["QB", "RB", "WR", "TE"]);
export const DataModeSchema = z.enum(["production", "fixture"]);
export const ConfidenceLabelSchema = z.enum(["low", "medium", "high"]);

export const ProjectedStatsSchema = z.object({
  games: z.number().nonnegative(),
  passAttempts: z.number().nonnegative().nullable().optional(),
  completions: z.number().nonnegative().nullable().optional(),
  passingYards: z.number().nullable().optional(),
  passingTouchdowns: z.number().nonnegative().nullable().optional(),
  interceptions: z.number().nonnegative().nullable().optional(),
  carries: z.number().nonnegative().nullable().optional(),
  rushingYards: z.number().nullable().optional(),
  rushingTouchdowns: z.number().nonnegative().nullable().optional(),
  targets: z.number().nonnegative().nullable().optional(),
  receptions: z.number().nonnegative().nullable().optional(),
  receivingYards: z.number().nullable().optional(),
  receivingTouchdowns: z.number().nonnegative().nullable().optional(),
  fumblesLost: z.number().nonnegative().nullable().optional(),
});

export const PlayerProjectionSchema = z.object({
  playerId: z.string().min(1),
  slug: z.string().min(1),
  name: z.string(),
  shortName: z.string(),
  team: z.string(),
  position: PositionSchema,
  age: z.number().nullable().optional(),
  experience: z.number().int().nullable().optional(),
  rookie: z.boolean(),
  headshotUrl: z.string().nullable().optional(),
  projectionSeason: z.number(),
  sourceSeason: z.number(),
  modelVersion: z.string(),
  modelArchitecture: z.enum(["direct", "component", "rookie"]).optional(),
  projectedStats: ProjectedStatsSchema,
  fantasy: z.object({
    defaultPprPoints: z.number(),
    pointsPerGame: z.number(),
    replacementValue: z.number(),
    overallRank: z.number().int().positive(),
    positionRank: z.number().int().positive(),
    tier: z.number().int().positive(),
    pointsRank: z.number().int().positive(),
    pointsPerGameRank: z.number().int().positive(),
    vorpRank: z.number().int().positive(),
    riskAdjustedRank: z.number().int().positive(),
    riskAdjustedValue: z.number(),
  }),
  range: z.object({
    lowPprPoints: z.number(),
    medianPprPoints: z.number(),
    highPprPoints: z.number(),
    lowQuantile: z.number(),
    highQuantile: z.number(),
  }),
  confidence: z.object({
    score: z.number().min(0).max(1),
    label: ConfidenceLabelSchema,
    reasons: z.array(z.string()).default([]),
  }),
  explanation: z
    .object({
      positiveFactors: z.array(z.any()).default([]),
      negativeFactors: z.array(z.any()).default([]),
      summary: z.string().default(""),
      optimisticNote: z.string().default(""),
      cautiousNote: z.string().default(""),
      method: z.enum(["shap", "permutation", "unavailable"]).default("unavailable"),
    })
    .default({}),
  history: z.array(z.any()).default([]),
  warnings: z.array(z.any()).default([]),
  isAdjusted: z.boolean().default(false),
  context: z.record(z.number().nullable()).default({}),
});

export const ProjectionsFileSchema = z.object({
  schemaVersion: z.string(),
  dataMode: DataModeSchema,
  projectionSeason: z.number(),
  generatedAt: z.string(),
  players: z.array(PlayerProjectionSchema),
});

export const RankingEntrySchema = z.object({
  playerId: z.string(),
  slug: z.string(),
  name: z.string(),
  team: z.string(),
  position: PositionSchema,
  overallRank: z.number(),
  positionRank: z.number(),
  tier: z.number(),
  pprPoints: z.number(),
  pointsPerGame: z.number(),
  vorp: z.number(),
  riskAdjustedValue: z.number(),
  confidenceScore: z.number(),
  confidenceLabel: ConfidenceLabelSchema,
  rookie: z.boolean(),
  games: z.number(),
  previousSeasonPprPoints: z.number().nullable().optional(),
  keyOpportunityLabel: z.string().nullable().optional(),
  keyOpportunityValue: z.number().nullable().optional(),
});

export const RankingsFileSchema = z.object({
  schemaVersion: z.string(),
  dataMode: DataModeSchema,
  projectionSeason: z.number(),
  generatedAt: z.string(),
  scoringPreset: z.string(),
  entries: z.array(RankingEntrySchema),
});

export const MetadataSchema = z.object({
  schemaVersion: z.string(),
  modelVersion: z.string(),
  projectionRelease: z.string(),
  dataMode: DataModeSchema,
  projectionSeason: z.number(),
  sourceSeason: z.number(),
  dataStartSeason: z.number(),
  generatedAt: z.string(),
  gitCommit: z.string().nullable().optional(),
  datasetHash: z.string().nullable().optional(),
  playerCount: z.number(),
  candidatePoolSize: z.number(),
  positions: z.array(PositionSchema),
  rookieMode: z.enum(["full", "reduced", "fixture"]),
  limitations: z.array(z.string()).default([]),
  rosterDataAsOf: z.string().nullable().optional(),
});

export const ModelPerformanceSchema = z.object({
  schemaVersion: z.string(),
  dataMode: DataModeSchema,
  generatedAt: z.string(),
  modelVersion: z.string(),
  backtestSeasons: z.array(z.number()).default([]),
  statMetrics: z.array(z.any()).default([]),
  fantasyMetrics: z.array(z.any()).default([]),
  rankMetrics: z.array(z.any()).default([]),
  calibration: z.array(z.any()).default([]),
  knownWeaknesses: z.array(z.string()).default([]),
  selectedModels: z.record(z.string()).default({}),
});

export type PlayerProjection = z.infer<typeof PlayerProjectionSchema>;
export type RankingEntry = z.infer<typeof RankingEntrySchema>;
export type ExportMetadata = z.infer<typeof MetadataSchema>;
export type ProjectedStats = z.infer<typeof ProjectedStatsSchema>;
export type Position = z.infer<typeof PositionSchema>;
