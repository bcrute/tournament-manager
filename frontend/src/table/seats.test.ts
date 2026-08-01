import { describe, expect, it } from "vitest";
import {
  TableLayout,
  assignSeats,
  orientLayout,
  ringOrder,
  seatFonts,
  seatGrid,
  swapSeats,
  turnOrder,
  turnPositions,
} from "./seats";

const P = (pid: number) => ({ pid, name: `p${pid}` });

describe("seatGrid", () => {
  it("seats two players facing each other across the display", () => {
    const g = seatGrid(2);
    expect(g.rows).toBe(1);
    expect(g.slots.map((s) => s.side)).toEqual(["left", "right"]);
    expect(g.slots.map((s) => s.rotate)).toEqual([90, -90]);
  });

  it("puts the odd player out on the bottom edge, facing normally", () => {
    const g = seatGrid(3);
    expect(g.slots.map((s) => s.side)).toEqual(["left", "right", "bottom"]);
    const bottom = g.slots[2];
    expect(bottom.rotate).toBe(0);
    expect(bottom.colSpan).toBe(2); // spans the full width
    expect(bottom.row).toBe(g.rows);
  });

  it("splits an even table evenly down both sides", () => {
    const g = seatGrid(6);
    expect(g.rows).toBe(3);
    expect(g.slots.filter((s) => s.side === "left")).toHaveLength(3);
    expect(g.slots.filter((s) => s.side === "right")).toHaveLength(3);
    expect(g.slots.some((s) => s.side === "bottom")).toBe(false);
  });

  it("handles a five player table (2 + 2 + 1)", () => {
    const g = seatGrid(5);
    expect(g.rows).toBe(3);
    expect(g.slots.filter((s) => s.side === "left")).toHaveLength(2);
    expect(g.slots.filter((s) => s.side === "right")).toHaveLength(2);
    expect(g.slots.filter((s) => s.side === "bottom")).toHaveLength(1);
  });

  it("gives a single player the whole bottom", () => {
    const g = seatGrid(1);
    expect(g.slots).toHaveLength(1);
    expect(g.slots[0]).toMatchObject({ side: "bottom", colSpan: 2, rotate: 0 });
  });

  it("survives an empty table", () => {
    expect(seatGrid(0).slots).toEqual([]);
  });

  it("every player gets exactly one slot", () => {
    for (const n of [1, 2, 3, 4, 5, 6, 7, 8]) {
      expect(seatGrid(n).slots).toHaveLength(n);
    }
  });

  it("rows always fit the seats they hold", () => {
    for (const n of [1, 2, 3, 4, 5, 6, 7, 8]) {
      const g = seatGrid(n);
      for (const s of g.slots) {
        expect(s.row).toBeGreaterThanOrEqual(1);
        expect(s.row).toBeLessThanOrEqual(g.rows);
      }
    }
  });
});

describe("swapSeats", () => {
  it("exchanges the two seats and leaves the rest alone", () => {
    expect(swapSeats([1, 2, 3, 4, 5], 2, 5)).toEqual([1, 5, 3, 4, 2]);
  });

  it("is symmetric", () => {
    expect(swapSeats([1, 2, 3], 3, 1)).toEqual(swapSeats([1, 2, 3], 1, 3));
  });

  it("no-ops when a seat is missing or is itself", () => {
    const order = [1, 2, 3];
    expect(swapSeats(order, 1, 1)).toEqual([1, 2, 3]);
    expect(swapSeats(order, 1, 99)).toEqual([1, 2, 3]);
  });

  it("does not mutate the original order", () => {
    const order = [1, 2, 3];
    swapSeats(order, 1, 3);
    expect(order).toEqual([1, 2, 3]);
  });

  it("keeps the same players, just repositioned", () => {
    const out = swapSeats([1, 2, 3, 4], 1, 4);
    expect([...out].sort()).toEqual([1, 2, 3, 4]);
  });
});

describe("seatFonts", () => {
  it("scales the life total with the card, not the viewport", () => {
    const small = seatFonts(200, 400);
    const big = seatFonts(500, 900);
    expect(big.life).toBeGreaterThan(small.life);
    expect(small.life).toBeCloseTo(200 * 0.42);
  });

  it("uses the narrow side so digits always fit", () => {
    expect(seatFonts(300, 900).life).toBeCloseTo(seatFonts(300, 400).life);
  });

  it("keeps a readable floor for tiny cards", () => {
    const f = seatFonts(10, 10);
    expect(f.life).toBe(24);
    expect(f.name).toBe(11);
    expect(f.cmd).toBe(9);
  });

  it("survives an unmeasured card", () => {
    const f = seatFonts(0, 0);
    expect(f.life).toBe(24);
    expect(Number.isFinite(f.cmdBar)).toBe(true);
  });

  it("reserves a commander bar proportional to its text", () => {
    const f = seatFonts(400, 600);
    expect(f.cmdBar).toBeCloseTo(f.cmd * 2.4);
  });
});

describe("ringOrder", () => {
  it("walks down the left edge, across the bottom, then up the right edge", () => {
    // 5 seats: L0 L1 | R0 R1 | B  →  ring: L0 L1 B R1 R0
    const ring = ringOrder([P(1), P(2), P(3), P(4), P(5)]);
    expect(ring.map((p) => p.pid)).toEqual([1, 2, 5, 4, 3]);
  });

  it("closes the circle for an even table", () => {
    // 6 seats: L0 L1 L2 | R0 R1 R2  →  ring: L0 L1 L2 R2 R1 R0
    const ring = ringOrder([P(1), P(2), P(3), P(4), P(5), P(6)]);
    expect(ring.map((p) => p.pid)).toEqual([1, 2, 3, 6, 5, 4]);
  });

  it("leaves tiny tables alone", () => {
    expect(ringOrder([P(1), P(2)]).map((p) => p.pid)).toEqual([1, 2]);
    expect(ringOrder([P(1)]).map((p) => p.pid)).toEqual([1]);
    expect(ringOrder([])).toEqual([]);
  });

  it("keeps every player exactly once", () => {
    for (const n of [3, 4, 5, 6, 7, 8]) {
      const players = Array.from({ length: n }, (_, i) => P(i + 1));
      const ring = ringOrder(players);
      expect(new Set(ring.map((p) => p.pid)).size).toBe(n);
    }
  });
});

describe("turnOrder", () => {
  const five = [P(1), P(2), P(3), P(4), P(5)]; // ring: 1 2 5 4 3

  it("starts with whoever goes first and follows the ring", () => {
    expect(turnOrder(five, 5).map((p) => p.pid)).toEqual([5, 4, 3, 1, 2]);
  });

  it("is the plain ring when nobody has been picked yet", () => {
    expect(turnOrder(five, null).map((p) => p.pid)).toEqual([1, 2, 5, 4, 3]);
  });

  it("falls back to the ring if the first player has left", () => {
    expect(turnOrder(five, 999).map((p) => p.pid)).toEqual([1, 2, 5, 4, 3]);
  });

  it("rearranging seats rearranges turn order", () => {
    const swapped = [P(2), P(1), P(3), P(4), P(5)]; // p2 dragged to the top-left seat
    expect(turnOrder(swapped, 2).map((p) => p.pid)).toEqual([2, 1, 5, 4, 3]);
  });
});

describe("turnPositions", () => {
  it("numbers seats from the first player around the ring", () => {
    const pos = turnPositions([P(1), P(2), P(3), P(4), P(5)], 5);
    expect(pos.get(5)).toBe(1);
    expect(pos.get(4)).toBe(2);
    expect(pos.get(3)).toBe(3);
    expect(pos.get(1)).toBe(4);
    expect(pos.get(2)).toBe(5);
  });

  it("covers every player", () => {
    const players = Array.from({ length: 7 }, (_, i) => P(i + 1));
    expect(turnPositions(players, 3).size).toBe(7);
  });
});

describe("assignSeats", () => {
  it("pairs players with slots in order", () => {
    const out = assignSeats(["a", "b", "c"]);
    expect(out.map((x) => x.player)).toEqual(["a", "b", "c"]);
    expect(out.map((x) => x.slot.side)).toEqual(["left", "right", "bottom"]);
  });

  it("returns nothing for an empty table", () => {
    expect(assignSeats([])).toEqual([]);
  });
});

describe("orientLayout — the damage grid as each seat sees it", () => {
  /** Six players: two columns of three, one column per long edge. */
  const six = (): TableLayout => ({
    rows: 3,
    cols: 2,
    cells: [
      { pid: 1, row: 1, col: 1, colSpan: 1, rowSpan: 1 }, // left edge, top
      { pid: 2, row: 2, col: 1, colSpan: 1, rowSpan: 1 },
      { pid: 3, row: 3, col: 1, colSpan: 1, rowSpan: 1 },
      { pid: 4, row: 1, col: 2, colSpan: 1, rowSpan: 1 }, // right edge, top
      { pid: 5, row: 2, col: 2, colSpan: 1, rowSpan: 1 },
      { pid: 6, row: 3, col: 2, colSpan: 1, rowSpan: 1 },
    ],
  });

  const at = (l: TableLayout, pid: number) => l.cells.find((c) => c.pid === pid)!;

  it("leaves the bottom seat's view alone — they face the screen squarely", () => {
    const l = six();
    expect(orientLayout(l, 0)).toBe(l);
  });

  it("turns 2x3 into 3x2 for a seat on the left", () => {
    // the reported bug: six players are three-across-and-two-deep from a chair
    // on the long edge, but the grid drew them two-across-and-three-deep
    const o = orientLayout(six(), 90);
    expect({ rows: o.rows, cols: o.cols }).toEqual({ rows: 2, cols: 3 });
  });

  it("and for a seat on the right", () => {
    const o = orientLayout(six(), -90);
    expect({ rows: o.rows, cols: o.cols }).toEqual({ rows: 2, cols: 3 });
  });

  it("puts your own edge nearest you", () => {
    // from a left-hand chair, the players sharing that edge are the near row
    const o = orientLayout(six(), 90);
    expect([1, 2, 3].map((p) => at(o, p).row)).toEqual([2, 2, 2]);
    expect([4, 5, 6].map((p) => at(o, p).row)).toEqual([1, 1, 1]);
  });

  it("and keeps that edge in order along it", () => {
    const o = orientLayout(six(), 90);
    expect([1, 2, 3].map((p) => at(o, p).col)).toEqual([1, 2, 3]);
  });

  it("mirrors for the opposite edge, so both read left-to-right correctly", () => {
    const o = orientLayout(six(), -90);
    // a right-hand chair looks the other way down the table
    expect([4, 5, 6].map((p) => at(o, p).row)).toEqual([2, 2, 2]);
    expect([1, 2, 3].map((p) => at(o, p).row)).toEqual([1, 1, 1]);
  });

  it("never loses or duplicates a seat", () => {
    for (const turn of [0, 90, -90]) {
      const o = orientLayout(six(), turn);
      expect(o.cells.map((c) => c.pid).sort()).toEqual([1, 2, 3, 4, 5, 6]);
      const taken = new Set(o.cells.map((c) => `${c.row}:${c.col}`));
      expect(taken.size, `turn ${turn} put two players in one square`).toBe(6);
    }
  });

  it("keeps every seat inside the grid it reports", () => {
    for (const turn of [0, 90, -90]) {
      const o = orientLayout(six(), turn);
      for (const c of o.cells) {
        expect(c.row).toBeGreaterThanOrEqual(1);
        expect(c.col).toBeGreaterThanOrEqual(1);
        expect(c.row + c.rowSpan - 1).toBeLessThanOrEqual(o.rows);
        expect(c.col + c.colSpan - 1).toBeLessThanOrEqual(o.cols);
      }
    }
  });

  it("turns the odd seat's span the right way round", () => {
    // five players: two a side plus one across the bottom, spanning both
    // columns. Seen from an edge that seat is one column deep by two rows.
    const five: TableLayout = {
      rows: 3,
      cols: 2,
      cells: [
        { pid: 1, row: 1, col: 1, colSpan: 1, rowSpan: 1 },
        { pid: 2, row: 2, col: 1, colSpan: 1, rowSpan: 1 },
        { pid: 3, row: 1, col: 2, colSpan: 1, rowSpan: 1 },
        { pid: 4, row: 2, col: 2, colSpan: 1, rowSpan: 1 },
        { pid: 5, row: 3, col: 1, colSpan: 2, rowSpan: 1 },
      ],
    };
    const o = orientLayout(five, 90);
    const odd = o.cells.find((c) => c.pid === 5)!;
    expect({ colSpan: odd.colSpan, rowSpan: odd.rowSpan }).toEqual({ colSpan: 1, rowSpan: 2 });
    // and they sit at the far end of the table from this chair
    expect(odd.col).toBe(o.cols);
  });

  it("matches the real six-player table produced by seatGrid", () => {
    // the guard that keeps this honest if the seating ever changes shape
    const grid = seatGrid(6);
    const layout: TableLayout = {
      rows: grid.rows,
      cols: grid.cols,
      cells: grid.slots.map((s, i) => ({
        pid: i + 1,
        row: s.row,
        col: s.col,
        colSpan: s.colSpan,
        rowSpan: s.rowSpan,
      })),
    };
    expect({ rows: layout.rows, cols: layout.cols }).toEqual({ rows: 3, cols: 2 });
    const seen = orientLayout(layout, grid.slots[0].rotate);
    expect({ rows: seen.rows, cols: seen.cols }).toEqual({ rows: 2, cols: 3 });
  });
});
