import { describe, expect, it } from "vitest";
import { hasEmoji, splitEmoji } from "./emoji";

const runs = (name: string) => splitEmoji(name).map((s) => `${s.emoji ? "E" : "T"}:${s.text}`);
/** Splitting must never lose or reorder anything. */
const rejoined = (name: string) => splitEmoji(name).map((s) => s.text).join("");

describe("hasEmoji", () => {
  it("is false for ordinary names", () => {
    expect(hasEmoji("Ada Lovelace")).toBe(false);
    expect(hasEmoji("Grumpy Platypus 42")).toBe(false);
  });

  it("does not mistake digits or punctuation for emoji", () => {
    // `\p{Emoji}` matches bare digits and #, which would have wrapped half of
    // every suggested name this app generates
    expect(hasEmoji("42")).toBe(false);
    expect(hasEmoji("#1 seed")).toBe(false);
    expect(hasEmoji("a*b")).toBe(false);
  });

  it("is true once there is a picture in there", () => {
    expect(hasEmoji("Other Will 🦅🤘")).toBe(true);
    expect(hasEmoji("🎩")).toBe(true);
  });
});

describe("splitEmoji", () => {
  it("leaves a plain name in one piece", () => {
    expect(runs("Ada")).toEqual(["T:Ada"]);
  });

  it("separates a trailing emoji from the name", () => {
    expect(runs("Hanna 💖")).toEqual(["T:Hanna ", "E:💖"]);
  });

  it("keeps adjacent emoji in a single run", () => {
    // wrapping each one separately would put a gap between them
    expect(runs("Other Will 🦅🤘")).toEqual(["T:Other Will ", "E:🦅🤘"]);
  });

  it("handles an emoji at the front", () => {
    expect(runs("🎩 Ben")).toEqual(["E:🎩", "T: Ben"]);
  });

  it("handles emoji in the middle", () => {
    expect(runs("a 🦅 b")).toEqual(["T:a ", "E:🦅", "T: b"]);
  });

  it("keeps a skin-tone modifier attached to its hand", () => {
    // split apart, the modifier renders as a stray colour swatch
    const out = splitEmoji("Will 🤘🏽");
    expect(out).toHaveLength(2);
    expect(out[1]).toEqual({ text: "🤘🏽", emoji: true });
  });

  it("keeps a zero-width-joined sequence together", () => {
    const family = "👨‍👩‍👧";
    const out = splitEmoji(`Fam ${family}`);
    expect(out[out.length - 1]).toEqual({ text: family, emoji: true });
  });

  it("keeps a variation selector with its glyph", () => {
    const out = splitEmoji("Heart ❤️");
    expect(out[out.length - 1].text).toBe("❤️");
  });

  it("never loses a character, whatever the name", () => {
    for (const name of [
      "Ada",
      "Other Will 🦅🤘",
      "🎩",
      "a 🦅 b 💖 c",
      "Grumpy Platypus 42",
      "👨‍👩‍👧 and 🤘🏽",
      "",
      "❤️❤️❤️",
    ]) {
      expect(rejoined(name), name).toBe(name);
    }
  });

  it("returns nothing for an empty name", () => {
    expect(splitEmoji("")).toEqual([]);
  });

  it("marks every run as one thing or the other", () => {
    for (const seg of splitEmoji("a 🦅 b")) {
      expect(typeof seg.emoji).toBe("boolean");
      expect(seg.text.length).toBeGreaterThan(0);
    }
  });
});
