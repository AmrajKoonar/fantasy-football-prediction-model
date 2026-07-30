import type { DraftFormat } from "./types";

export type OrderedPick = {
  overall: number;
  round: number;
  slotNumber: number;
  pickInRound: number;
};

export function roundSlots(
  teamCount: number,
  round: number,
  format: Exclude<DraftFormat, "auction">,
  thirdRoundReversal = false,
): number[] {
  if (teamCount < 2 || round < 1) throw new Error("Invalid team count or round");
  const forward = Array.from({ length: teamCount }, (_, index) => index + 1);
  if (format === "linear") return forward;
  const reverse = [...forward].reverse();
  if (!thirdRoundReversal) return round % 2 === 1 ? forward : reverse;
  if (round === 1) return forward;
  if (round === 2 || round === 3) return reverse;
  return round % 2 === 0 ? forward : reverse;
}

export function buildDraftOrder(
  teamCount: number,
  rounds: number,
  format: Exclude<DraftFormat, "auction">,
  thirdRoundReversal = false,
): OrderedPick[] {
  const picks: OrderedPick[] = [];
  for (let round = 1; round <= rounds; round += 1) {
    roundSlots(teamCount, round, format, thirdRoundReversal).forEach((slotNumber, index) => {
      picks.push({
        overall: picks.length + 1,
        round,
        slotNumber,
        pickInRound: index + 1,
      });
    });
  }
  return picks;
}

export function currentOrderedPick(
  pickNumber: number,
  teamCount: number,
  rounds: number,
  format: Exclude<DraftFormat, "auction">,
  thirdRoundReversal = false,
) {
  return buildDraftOrder(teamCount, rounds, format, thirdRoundReversal)[pickNumber - 1] ?? null;
}

