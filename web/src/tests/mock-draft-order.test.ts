import { describe, expect, it } from "vitest";
import { buildDraftOrder, roundSlots } from "@/features/mock-draft/order";

describe("mock draft order", () => {
  it("builds every supported even team count and round count without duplicates", () => {
    for (let teams = 4; teams <= 22; teams += 2) {
      for (const rounds of [1, 2, 3, 15, 30]) {
        const order = buildDraftOrder(teams, rounds, "snake");
        expect(order).toHaveLength(teams * rounds);
        expect(new Set(order.map((pick) => pick.overall)).size).toBe(order.length);
        for (let round = 1; round <= rounds; round += 1) {
          expect(new Set(order.filter((pick) => pick.round === round).map((pick) => pick.slotNumber)).size).toBe(teams);
        }
      }
    }
  });

  it("uses a fixed order for linear drafts", () => {
    expect(roundSlots(4, 1, "linear")).toEqual([1, 2, 3, 4]);
    expect(roundSlots(4, 2, "linear")).toEqual([1, 2, 3, 4]);
  });

  it("implements snake and third-round reversal", () => {
    expect(roundSlots(4, 2, "snake")).toEqual([4, 3, 2, 1]);
    expect(roundSlots(4, 3, "snake")).toEqual([1, 2, 3, 4]);
    expect(roundSlots(4, 3, "snake", true)).toEqual([4, 3, 2, 1]);
    expect(roundSlots(4, 4, "snake", true)).toEqual([1, 2, 3, 4]);
  });
});

