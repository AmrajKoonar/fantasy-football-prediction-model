import type { BasePosition, DraftPlayer, RosterPosition, RosterSlot } from "./types";

export function slotAccepts(position: BasePosition, slot: RosterPosition): boolean {
  if (slot === "BENCH") return true;
  if (slot === position) return true;
  if (slot === "FLEX") return ["RB", "WR", "TE"].includes(position);
  if (slot === "SUPERFLEX") return ["QB", "RB", "WR", "TE"].includes(position);
  if (slot === "IDP_FLEX") return ["DL", "LB", "DB"].includes(position);
  return false;
}

function canAssign(positions: BasePosition[], slots: RosterPosition[], index = 0): boolean {
  if (index >= positions.length) return true;
  return slots.some((slot, slotIndex) => {
    if (!slotAccepts(positions[index], slot)) return false;
    return canAssign(positions, slots.filter((_, indexToKeep) => indexToKeep !== slotIndex), index + 1);
  });
}

export function canAddPlayer(
  drafted: Pick<DraftPlayer, "primaryPosition">[],
  candidate: Pick<DraftPlayer, "primaryPosition">,
  roster: RosterSlot[],
): boolean {
  if (drafted.length >= roster.length) return false;
  const positions = [...drafted.map((player) => player.primaryPosition), candidate.primaryPosition];
  const constrained = [...positions].sort((a, b) => {
    const aSlots = roster.filter((slot) => slotAccepts(a, slot.position)).length;
    const bSlots = roster.filter((slot) => slotAccepts(b, slot.position)).length;
    return aSlots - bSlots;
  });
  return canAssign(constrained, roster.map((slot) => slot.position));
}

export function remainingNeeds(
  drafted: Pick<DraftPlayer, "primaryPosition">[],
  roster: RosterSlot[],
): Partial<Record<BasePosition, number>> {
  const needs: Partial<Record<BasePosition, number>> = {};
  const direct = roster.filter((slot) =>
    ["QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"].includes(slot.position),
  );
  for (const slot of direct) {
    const position = slot.position as BasePosition;
    needs[position] = (needs[position] ?? 0) + 1;
  }
  for (const player of drafted) {
    needs[player.primaryPosition] = Math.max(0, (needs[player.primaryPosition] ?? 0) - 1);
  }
  return needs;
}

export function assignRoster(
  drafted: DraftPlayer[],
  roster: RosterSlot[],
): Array<DraftPlayer | null> {
  const assigned: Array<DraftPlayer | null> = roster.map(() => null);
  const ordered = [...drafted].sort((a, b) => {
    const aOptions = roster.filter((slot) => slotAccepts(a.primaryPosition, slot.position)).length;
    const bOptions = roster.filter((slot) => slotAccepts(b.primaryPosition, slot.position)).length;
    return aOptions - bOptions;
  });

  function place(index: number): boolean {
    if (index >= ordered.length) return true;
    const player = ordered[index];
    const candidateSlots = roster
      .map((slot, slotIndex) => ({ slot, slotIndex }))
      .filter(({ slot, slotIndex }) =>
        assigned[slotIndex] === null && slotAccepts(player.primaryPosition, slot.position))
      .sort((a, b) => {
        const aExact = a.slot.position === player.primaryPosition ? 0 : a.slot.position === "BENCH" ? 2 : 1;
        const bExact = b.slot.position === player.primaryPosition ? 0 : b.slot.position === "BENCH" ? 2 : 1;
        return aExact - bExact;
      });
    for (const { slotIndex } of candidateSlots) {
      assigned[slotIndex] = player;
      if (place(index + 1)) return true;
      assigned[slotIndex] = null;
    }
    return false;
  }
  place(0);
  return assigned;
}
