import { describe, expect, it } from "vitest";
import { getPreset, scoreStats } from "@/lib/scoring";
import { computeReplacementLevels, vorp } from "@/lib/vorp";

describe("scoring", () => {
  it("scores full PPR receiving", () => {
    const points = scoreStats(
      {
        receptions: 80,
        receivingYards: 1000,
        receivingTouchdowns: 8,
      },
      getPreset("ppr"),
    );
    expect(points).toBeCloseTo(80 + 100 + 48, 5);
  });

  it("scores half PPR differently", () => {
    const ppr = scoreStats({ receptions: 10 }, getPreset("ppr"));
    const half = scoreStats({ receptions: 10 }, getPreset("half_ppr"));
    expect(ppr - half).toBeCloseTo(5, 5);
  });
});

describe("vorp", () => {
  it("computes replacement and vorp", () => {
    const players = Array.from({ length: 40 }, (_, index) => ({
      playerId: `p${index}`,
      position: index < 10 ? ("QB" as const) : index < 25 ? ("RB" as const) : ("WR" as const),
      points: 300 - index * 5,
    }));
    const levels = computeReplacementLevels(players, {
      teams: 12,
      qb: 1,
      rb: 2,
      wr: 2,
      te: 1,
      flex: 1,
      superflex: 0,
    });
    expect(levels.QB).toBeGreaterThan(0);
    expect(vorp(300, "QB", levels)).toBeGreaterThan(0);
  });
});
