export type AuctionState = {
  currentBid: number;
  minimumBid: number;
  highestBidderSlot: number | null;
};

export function maxAuctionBid(
  budgetRemaining: number,
  emptyRosterSlots: number,
  minimumBid: number,
): number {
  if (emptyRosterSlots <= 0) return 0;
  return budgetRemaining - Math.max(0, emptyRosterSlots - 1) * minimumBid;
}

export function nextMinimumBid(state: AuctionState): number {
  return state.highestBidderSlot === null
    ? state.minimumBid
    : state.currentBid + state.minimumBid;
}

export function validateBid(
  amount: number,
  state: AuctionState,
  budgetRemaining: number,
  emptyRosterSlots: number,
): { valid: boolean; reason?: string } {
  if (!Number.isInteger(amount)) return { valid: false, reason: "Bids must be whole dollars." };
  if (amount < nextMinimumBid(state)) {
    return { valid: false, reason: `Bid must be at least $${nextMinimumBid(state)}.` };
  }
  if (amount > maxAuctionBid(budgetRemaining, emptyRosterSlots, state.minimumBid)) {
    return { valid: false, reason: "Bid would leave too little budget to fill the roster." };
  }
  return { valid: true };
}

