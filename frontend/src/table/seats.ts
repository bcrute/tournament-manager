export type Side = "left" | "right" | "bottom";

export interface SeatSlot {
  side: Side;
  /** CSS grid placement, 1-based */
  row: number;
  col: number;
  colSpan: number;
  rowSpan: number;
  /** degrees to rotate so the card faces that seat */
  rotate: number;
}

/** A grid of seats — the table, or the miniature of it on every card. */
export interface TableLayout {
  rows: number;
  cols: number;
  cells: { pid: number; row: number; col: number; colSpan: number; rowSpan: number }[];
}

/**
 * The same table, as it looks from one seat.
 *
 * The damage grid is a map of the table, and a map has to be oriented like the
 * territory. The layout is built in the screen's frame — for six players that
 * is two columns of three, one column per long edge. A player sitting on an
 * edge is looking at the display side-on, so *from their chair* that same table
 * is three across and two deep. Their card is rotated to face them, and drawing
 * the screen-frame grid inside it handed them a 2x3 map of a 3x2 table.
 *
 * Rotating the grid with the card would fix the shape and lay every number on
 * its side. So the cells are re-placed instead: the shape matches what they can
 * see, and the digits stay upright.
 */
export function orientLayout(layout: TableLayout, rotate: number): TableLayout {
  const turn = ((Math.round(rotate) % 360) + 360) % 360;
  if (turn !== 90 && turn !== 270) return layout;
  const { rows, cols, cells } = layout;
  if (turn === 90) {
    // left-hand seat: their "up" is the screen's right, so a screen column
    // becomes a row counted from the far edge inwards
    return {
      rows: cols,
      cols: rows,
      cells: cells.map((c) => ({
        pid: c.pid,
        row: cols + 1 - (c.col + c.colSpan - 1),
        col: c.row,
        colSpan: c.rowSpan,
        rowSpan: c.colSpan,
      })),
    };
  }
  // right-hand seat: the mirror of the above
  return {
    rows: cols,
    cols: rows,
    cells: cells.map((c) => ({
      pid: c.pid,
      row: c.col,
      col: rows + 1 - (c.row + c.rowSpan - 1),
      colSpan: c.rowSpan,
      rowSpan: c.colSpan,
    })),
  };
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
/**
 * The most seats the shared table view can show usefully.
 *
 * Measured rather than guessed. Life totals stay legible up to eight, but the
 * commander-damage squares fall apart at seven — around ten pixels a number,
 * which is unreadable from across a table. The cut is set by the point where
 * the view stops being glanceable, not the point where it stops rendering:
 * needing to tap a card to read damage means the shared screen has already
 * failed at its job.
 *
 * Above this the answer is everyone on their own phone, which works unchanged.
 */
export const MAX_TABLE_VIEW = 6;

export function seatGrid(n: number): SeatGrid {
  if (n <= 0) return { rows: 1, cols: 2, slots: [] };
  const hasBottom = n % 2 === 1;
  const perSide = (n - (hasBottom ? 1 : 0)) / 2;
  const rows = Math.max(perSide, 0) + (hasBottom ? 1 : 0);
  const slots: SeatSlot[] = [];

  for (let i = 0; i < perSide; i++) {
    slots.push({ side: "left", row: i + 1, col: 1, colSpan: 1, rowSpan: 1, rotate: 90 });
  }
  for (let i = 0; i < perSide; i++) {
    slots.push({ side: "right", row: i + 1, col: 2, colSpan: 1, rowSpan: 1, rotate: -90 });
  }
  if (hasBottom) {
    slots.push({ side: "bottom", row: rows, col: 1, colSpan: 2, rowSpan: 1, rotate: 0 });
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

/**
 * Exchange two seats. Dragging one card onto another swaps the pair and leaves
 * every other seat where it is — the point is to match where people actually
 * sit, not to shuffle the whole table.
 */
export function swapSeats(order: number[], a: number, b: number): number[] {
  const i = order.indexOf(a);
  const j = order.indexOf(b);
  if (i < 0 || j < 0 || i === j) return order;
  const next = [...order];
  next[i] = b;
  next[j] = a;
  return next;
}

export interface SeatFonts {
  life: number;
  name: number;
  cmd: number;
  cmdBar: number;
}

/**
 * Type sizes for a seat card, scaled to the card itself rather than the
 * viewport — a phone used as the display has small viewport units but plenty
 * of room inside each card, and the life total has to read across a table.
 */
export function seatFonts(w: number, h: number): SeatFonts {
  const base = Math.max(0, Math.min(w, h));
  const cmd = Math.max(9, base * 0.075);
  return {
    life: Math.max(24, base * 0.42),
    name: Math.max(11, base * 0.1),
    cmd,
    cmdBar: cmd * 2.4,
  };
}

/**
 * Walk the seats the way you'd walk the table: down the left edge, across the
 * bottom, then back up the right edge. That is the physical circle, which is
 * what turn order follows — not the order the grid happens to store them in.
 */
export function ringOrder<T>(players: T[]): T[] {
  const n = players.length;
  if (n <= 2) return [...players];
  const hasBottom = n % 2 === 1;
  const perSide = (n - (hasBottom ? 1 : 0)) / 2;
  const left = players.slice(0, perSide);
  const right = players.slice(perSide, perSide * 2);
  const bottom = hasBottom ? players.slice(perSide * 2) : [];
  return [...left, ...bottom, ...right.reverse()];
}

/**
 * Turn order: the physical ring, rotated to start with whoever goes first.
 * Rearranging seats therefore rearranges the turn order.
 */
export function turnOrder<T extends { pid: number }>(players: T[], firstPid: number | null): T[] {
  const ring = ringOrder(players);
  if (firstPid === null) return ring;
  const start = ring.findIndex((p) => p.pid === firstPid);
  if (start < 0) return ring;
  return [...ring.slice(start), ...ring.slice(0, start)];
}

/** pid -> 1-based seat position in turn order. */
export function turnPositions<T extends { pid: number }>(
  players: T[],
  firstPid: number | null,
): Map<number, number> {
  const out = new Map<number, number>();
  turnOrder(players, firstPid).forEach((p, i) => out.set(p.pid, i + 1));
  return out;
}
