import { describe, expect, it } from "vitest";
import { assignSeats, seatGrid } from "./seats";

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
