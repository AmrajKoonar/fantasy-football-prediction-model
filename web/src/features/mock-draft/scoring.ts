import type { DraftPlayer, ScoringPreset } from "./types";

export function isDynasty(preset: ScoringPreset) {
  return preset.startsWith("dynasty_");
}

export function scoringMultiplier(player: DraftPlayer, preset: ScoringPreset): number {
  let multiplier = 1;
  if (preset === "standard" || preset === "dynasty_standard") {
    if (player.primaryPosition === "WR" || player.primaryPosition === "TE") multiplier *= 0.9;
    if (player.primaryPosition === "RB") multiplier *= 0.96;
  }
  if (preset === "half_ppr" || preset === "dynasty_half_ppr") {
    if (player.primaryPosition === "WR" || player.primaryPosition === "TE") multiplier *= 0.96;
  }
  if (preset === "two_qb" && player.primaryPosition === "QB") multiplier *= 1.38;
  if (preset === "idp" && ["DL", "LB", "DB"].includes(player.primaryPosition)) multiplier *= 1.25;
  if (isDynasty(preset) && player.age) {
    const prime = player.primaryPosition === "QB" ? 28 : 25;
    multiplier *= Math.max(0.72, 1 + (prime - player.age) * 0.028);
    if (player.rookie) multiplier *= 1.08;
  }
  return multiplier;
}

export function presetValue(player: DraftPlayer, preset: ScoringPreset): number {
  return player.projectedPoints * scoringMultiplier(player, preset);
}

