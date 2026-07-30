import { z } from "zod";
import { BASE_POSITIONS, ROSTER_POSITIONS } from "./types";

export const DraftPlayerSchema = z.object({
  playerId: z.string().min(1),
  name: z.string().min(1),
  team: z.string().min(1),
  primaryPosition: z.enum(BASE_POSITIONS),
  eligiblePositions: z.array(z.enum(BASE_POSITIONS)).min(1),
  rookie: z.boolean(),
  age: z.number().nullable(),
  overallRank: z.number().int().positive(),
  positionRank: z.number().int().positive(),
  tier: z.number().int().positive(),
  projectedPoints: z.number(),
  pointsPerGame: z.number(),
  adp: z.number().positive(),
  source: z.enum(["projection", "roster-baseline", "team-defense"]),
});

export const DraftPlayerPoolSchema = z.object({
  schemaVersion: z.string(),
  generatedAt: z.string(),
  projectionSeason: z.number().int(),
  source: z.string(),
  players: z.array(DraftPlayerSchema).min(450),
});

export const DraftSettingsSchema = z
  .object({
    name: z.string().trim().min(3).max(80),
    format: z.enum(["snake", "linear", "auction"]),
    scoringPreset: z.enum([
      "standard", "half_ppr", "ppr", "two_qb", "idp",
      "dynasty_standard", "dynasty_half_ppr", "dynasty_ppr",
    ]),
    teamCount: z.number().int().min(4).max(22).refine((value) => value % 2 === 0),
    rounds: z.number().int().min(1).max(30),
    pickTimerSeconds: z.number().int().min(10).max(86400).nullable(),
    cpuAutopick: z.boolean(),
    playerPool: z.enum(["all", "rookies", "veterans"]),
    thirdRoundReversal: z.boolean(),
    alphabeticalPlayers: z.boolean(),
    showTeamNames: z.boolean(),
    roster: z.array(z.object({ id: z.string(), position: z.enum(ROSTER_POSITIONS) })).min(1).max(30),
    auctionBudget: z.number().int().min(20).max(1000),
    minimumBid: z.number().int().min(1).max(100),
  })
  .superRefine((settings, context) => {
    if (settings.thirdRoundReversal && settings.format !== "snake") {
      context.addIssue({ code: "custom", path: ["thirdRoundReversal"], message: "3RR requires snake format." });
    }
    if (settings.rounds !== settings.roster.length) {
      context.addIssue({ code: "custom", path: ["rounds"], message: "Rounds must match roster size." });
    }
  });

