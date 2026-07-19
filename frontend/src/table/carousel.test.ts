import { describe, expect, it } from "vitest";
import { CardInfo, PlayerInfo } from "./api";
import { carouselEntries, clampIndex, indexOfPid, step } from "./carousel";

const card = (id: number): CardInfo => ({
  id,
  name: `Card ${id}`,
  role: "Assassin",
  rarity: "R",
  text: "",
  uri: "",
  artist: "Test Artist",
  image: `/cards/trd/${id}.jpg`,
});

const player = (over: Partial<PlayerInfo> & { pid: number }): PlayerInfo => ({
  name: `p${over.pid}`,
  isHost: false,
  revealed: false,
  left: false,
  eliminated: false,
  isMe: false,
  life: 40,
  cmdDamage: {},
  card: null,
  ...over,
});

describe("carouselEntries", () => {
  it("puts my card first, then revealed players in seat order", () => {
    const players = [
      player({ pid: 1, card: card(11) }), // revealed leader
      player({ pid: 2, isMe: true, card: card(22) }),
      player({ pid: 3 }), // hidden
      player({ pid: 4, card: card(44) }), // revealed
    ];
    const e = carouselEntries(players);
    expect(e.map((x) => x.pid)).toEqual([2, 1, 4]);
    expect(e[0].isMe).toBe(true);
  });

  it("never exposes hidden players' cards", () => {
    const players = [player({ pid: 1, isMe: true, card: card(11) }), player({ pid: 2 })];
    expect(carouselEntries(players).map((x) => x.pid)).toEqual([1]);
  });

  it("keeps my entry even before the deal (no card yet)", () => {
    const e = carouselEntries([player({ pid: 1, isMe: true, card: null })]);
    expect(e).toHaveLength(1);
    expect(e[0].card).toBeNull();
  });

  it("handles a display session with no 'me' player", () => {
    expect(carouselEntries([player({ pid: 1, card: card(1) })]).map((x) => x.pid)).toEqual([1]);
  });
});

describe("step", () => {
  it("advances and wraps forward", () => {
    expect(step(0, 1, 3)).toBe(1);
    expect(step(2, 1, 3)).toBe(0);
  });

  it("advances and wraps backward", () => {
    expect(step(0, -1, 3)).toBe(2);
    expect(step(1, -1, 3)).toBe(0);
  });

  it("is a no-op for an empty list", () => {
    expect(step(0, 1, 0)).toBe(0);
  });

  it("stays put with a single card", () => {
    expect(step(0, 1, 1)).toBe(0);
    expect(step(0, -1, 1)).toBe(0);
  });
});

describe("clampIndex", () => {
  it("clamps into range as the list shrinks", () => {
    expect(clampIndex(5, 3)).toBe(2);
    expect(clampIndex(-1, 3)).toBe(0);
    expect(clampIndex(1, 3)).toBe(1);
  });

  it("returns 0 for an empty list", () => {
    expect(clampIndex(3, 0)).toBe(0);
  });
});

describe("indexOfPid", () => {
  const entries = carouselEntries([
    player({ pid: 7, isMe: true, card: card(1) }),
    player({ pid: 9, card: card(2) }),
  ]);

  it("finds a revealed player's slot (toast tap target)", () => {
    expect(indexOfPid(entries, 9)).toBe(1);
  });

  it("returns -1 when that player is not in the carousel", () => {
    expect(indexOfPid(entries, 123)).toBe(-1);
  });
});
