import { canAddPlayer, remainingNeeds } from "./roster";
import { isDynasty, presetValue } from "./scoring";
import type { CpuContext, DraftPlayer } from "./types";

function stableUnit(seed: number, key: string): number {
  let value = seed ^ 0x9e3779b9;
  for (let index = 0; index < key.length; index += 1) {
    value = Math.imul(value ^ key.charCodeAt(index), 2654435761);
  }
  return ((value >>> 0) % 1_000_003) / 1_000_003;
}

export function cpuScore(player: DraftPlayer, context: CpuContext): number {
  if (!canAddPlayer(context.drafted, player, context.roster)) return Number.NEGATIVE_INFINITY;
  const needs = remainingNeeds(context.drafted, context.roster);
  const needBoost = (needs[player.primaryPosition] ?? 0) > 0 ? 24 : 0;
  const replacementValue = presetValue(player, context.scoringPreset) - player.overallRank * 0.24;
  const noise = stableUnit(
    context.seed,
    `${context.slotNumber}:${context.round}:${player.playerId}`,
  ) * 13;
  const lateSpecial =
    ["K", "DEF"].includes(player.primaryPosition) && context.round < context.totalRounds - 2
      ? -120
      : 0;
  const twoQb =
    context.scoringPreset === "two_qb" && player.primaryPosition === "QB"
      ? Math.max(0, 46 - context.drafted.filter((item) => item.primaryPosition === "QB").length * 22)
      : 0;
  const youth =
    isDynasty(context.scoringPreset) && player.age
      ? Math.max(-20, (27 - player.age) * 4)
      : 0;
  return replacementValue + needBoost + noise + lateSpecial + twoQb + youth;
}

export function chooseCpuPlayer(
  available: DraftPlayer[],
  context: CpuContext,
): DraftPlayer | null {
  return [...available]
    .map((player) => ({ player, score: cpuScore(player, context) }))
    .filter((entry) => Number.isFinite(entry.score))
    .sort((a, b) => b.score - a.score || a.player.playerId.localeCompare(b.player.playerId))[0]
    ?.player ?? null;
}

