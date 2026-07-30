import { describe, expect, it } from "vitest";
import { maxAuctionBid, validateBid } from "@/features/mock-draft/auction";
import { chooseCpuPlayer, cpuScore } from "@/features/mock-draft/cpu";
import { canAddPlayer, slotAccepts } from "@/features/mock-draft/roster";
import { formatTimer, remainingSeconds } from "@/features/mock-draft/timer";
import type { DraftPlayer, RosterSlot } from "@/features/mock-draft/types";
import { DEFAULT_SETTINGS } from "@/features/mock-draft/constants";

const player = (id: string, position: DraftPlayer["primaryPosition"], rank: number, age = 25): DraftPlayer => ({
  playerId: id, name: id, team: "FA", primaryPosition: position, eligiblePositions: [position],
  rookie: age <= 22, age, overallRank: rank, positionRank: rank, tier: 1,
  projectedPoints: 300 - rank, pointsPerGame: 15, adp: rank, source: "projection",
});

describe("roster eligibility", () => {
  it("supports flex, superflex, IDP flex, bench, and hard position caps", () => {
    expect(slotAccepts("RB", "FLEX")).toBe(true);
    expect(slotAccepts("QB", "FLEX")).toBe(false);
    expect(slotAccepts("QB", "SUPERFLEX")).toBe(true);
    expect(slotAccepts("LB", "IDP_FLEX")).toBe(true);
    expect(slotAccepts("K", "BENCH")).toBe(true);
    const roster: RosterSlot[] = [{ id: "1", position: "QB" }, { id: "2", position: "RB" }];
    expect(canAddPlayer([player("qb", "QB", 1)], player("qb2", "QB", 2), roster)).toBe(false);
    expect(canAddPlayer([player("qb", "QB", 1)], player("rb", "RB", 2), roster)).toBe(true);
  });
});

describe("seeded CPU strategy", () => {
  const roster: RosterSlot[] = [
    { id: "1", position: "QB" }, { id: "2", position: "QB" },
    { id: "3", position: "RB" }, { id: "4", position: "WR" },
    { id: "5", position: "K" }, { id: "6", position: "DEF" },
  ];
  const available = [
    player("qb-young", "QB", 3, 22), player("rb", "RB", 1, 25),
    player("k", "K", 2, 27), player("def", "DEF", 4, 0),
  ];

  it("is reproducible and avoids early kicker/defense", () => {
    const context = { drafted: [], roster, scoringPreset: "ppr" as const, round: 1, totalRounds: 6, seed: 371, slotNumber: 2 };
    expect(chooseCpuPlayer(available, context)?.playerId).toBe(chooseCpuPlayer(available, context)?.playerId);
    expect(cpuScore(available[2], context)).toBeLessThan(cpuScore(available[1], context));
  });

  it("boosts quarterbacks in 2QB and youth in dynasty", () => {
    const base = { drafted: [], roster, round: 1, totalRounds: 6, seed: 371, slotNumber: 2 };
    expect(cpuScore(available[0], { ...base, scoringPreset: "two_qb" }))
      .toBeGreaterThan(cpuScore(available[0], { ...base, scoringPreset: "ppr" }));
    expect(cpuScore(player("young", "WR", 10, 21), { ...base, scoringPreset: "dynasty_ppr" }))
      .toBeGreaterThan(cpuScore(player("old", "WR", 10, 31), { ...base, scoringPreset: "dynasty_ppr" }));
  });
});

describe("auction and timer rules", () => {
  it("defaults new rooms to a 30-second timer", () => {
    expect(DEFAULT_SETTINGS.pickTimerSeconds).toBe(30);
  });
  it("reserves minimum money for every empty roster slot", () => {
    expect(maxAuctionBid(40, 5, 1)).toBe(36);
    expect(validateBid(37, { currentBid: 20, minimumBid: 1, highestBidderSlot: 2 }, 40, 5).valid).toBe(false);
    expect(validateBid(21, { currentBid: 20, minimumBid: 1, highestBidderSlot: 2 }, 40, 5).valid).toBe(true);
  });

  it("formats short and long authoritative deadlines", () => {
    expect(formatTimer(65)).toBe("1:05");
    expect(formatTimer(90061)).toBe("1d 1h");
    expect(formatTimer(null)).toBe("No limit");
    expect(remainingSeconds(new Date(10_000).toISOString(), 8_100)).toBe(2);
  });
});
