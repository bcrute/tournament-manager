export type Side = "left" | "right" | "bottom";

export interface SeatSlot {
  side: Side;
  /** CSS grid placement, 1-based */
  row: number;
  col: number;
  colSpan: number;
  /** degrees to rotate so the card faces that seat */
  rotate: number;
}

export interface SeatGrid {
  rows: number;
  cols: number;
  slots: SeatSlot[];
}

/**
 * Split the display evenly among players, seating them down the left and right
 * edges so each card faces its player. An odd player out takes the bottom edge.
 *
 * Rotation is from the viewer's seat: someone on the left reads with "up"
 * pointing at the screen's right edge (90deg), the right seat is the mirror
 * (-90deg), and the bottom seat reads normally (0deg).
 */
export function seatGrid(n: number): SeatGrid {
  if (n <= 0) return { rows: 1, cols: 2, slots: [] };
  const hasBottom = n % 2 === 1;
  const perSide = (n - (hasBottom ? 1 : 0)) / 2;
  const rows = Math.max(perSide, 0) + (hasBottom ? 1 : 0);
  const slots: SeatSlot[] = [];

  for (let i = 0; i < perSide; i++) {
    slots.push({ side: "left", row: i + 1, col: 1, colSpan: 1, rotate: 90 });
  }
  for (let i = 0; i < perSide; i++) {
    slots.push({ side: "right", row: i + 1, col: 2, colSpan: 1, rotate: -90 });
  }
  if (hasBottom) {
    slots.push({ side: "bottom", row: rows, col: 1, colSpan: 2, rotate: 0 });
  }
  return { rows: Math.max(rows, 1), cols: 2, slots };
}

/**
 * Seat assignment in table order: left side top-to-bottom, then right side,
 * then the odd seat. Interleaving keeps neighbours adjacent when dragging.
 */
export function assignSeats<T>(players: T[]): Array<{ player: T; slot: SeatSlot }> {
  const { slots } = seatGrid(players.length);
  return players.map((player, i) => ({ player, slot: slots[i] }));
}
