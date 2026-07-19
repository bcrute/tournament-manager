import { describe, expect, it } from "vitest";
import { assignSeats, ringOrder, seatFonts, seatGrid, turnOrder, turnPositions } from "./seats";

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
