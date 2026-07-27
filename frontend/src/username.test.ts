import { describe, expect, it } from "vitest";
import {
  looksLikeEmail,
  suggestTableName,
  suggestUsername,
  WORD_COUNTS,
  WORDS,
} from "./username";

describe("suggestUsername", () => {
  it("produces adjective-noun-number", () => {
    for (let i = 0; i < 50; i++) {
      expect(suggestUsername()).toMatch(/^[a-z]+-[a-z]+-\d{2}$/);
    }
  });

  it("is readable aloud — lowercase letters, hyphens and digits only", () => {
    // someone may have to tell a friend their username across a table
    for (let i = 0; i < 50; i++) {
      expect(suggestUsername()).not.toMatch(/[^a-z0-9-]/);
    }
  });

  it("never suggests something that looks like an email", () => {
    for (let i = 0; i < 50; i++) {
      expect(looksLikeEmail(suggestUsername())).toBe(false);
    }
  });

  it("varies — a fixed suggestion would collide for everyone at once", () => {
    const seen = new Set(Array.from({ length: 100 }, () => suggestUsername()));
    expect(seen.size).toBeGreaterThan(80);
  });

  it("has a large enough space that collisions are rare", () => {
    const space = WORD_COUNTS.adjectives * WORD_COUNTS.nouns * 90;
    expect(space).toBeGreaterThan(100_000);
  });

  it("keeps both word lists free of duplicates", () => {
    // a duplicate silently biases the distribution toward that word
    expect(WORD_COUNTS.adjectives).toBeGreaterThan(20);
    expect(WORD_COUNTS.nouns).toBeGreaterThan(20);
    expect(new Set(WORDS.ADJECTIVES).size).toBe(WORDS.ADJECTIVES.length);
    expect(new Set(WORDS.NOUNS).size).toBe(WORDS.NOUNS.length);
  });
});

describe("suggestTableName", () => {
  it("reads as a name, not a slug — Adjective Noun 42", () => {
    for (let i = 0; i < 50; i++) {
      expect(suggestTableName()).toMatch(/^[A-Z][a-z]+ [A-Z][a-z]+ \d{2}$/);
    }
  });

  it("always fits the 24-character name field", () => {
    // the input and the server both cap at 24; a suggestion that overflowed
    // would be silently truncated into nonsense
    const longest =
      Math.max(...WORDS.ADJECTIVES.map((w) => w.length)) +
      Math.max(...WORDS.NOUNS.map((w) => w.length)) +
      " ".length * 2 +
      2;
    expect(longest).toBeLessThanOrEqual(24);
    for (let i = 0; i < 100; i++) {
      expect(suggestTableName().length).toBeLessThanOrEqual(24);
    }
  });

  it("varies — everyone at one table shouldn't get the same name", () => {
    const seen = new Set(Array.from({ length: 100 }, () => suggestTableName()));
    expect(seen.size).toBeGreaterThan(80);
  });
});

describe("the word lists stay safe to combine unsupervised", () => {
  it("uses no word that describes a person", () => {
    // these land on a real human being at a real table; an adjective about a
    // body or a mind is not a joke, it's an insult with a random noun attached
    const banned = [
      "fat", "skinny", "chunky", "pudgy", "lanky", "tiny", "huge", "ugly",
      "pretty", "sexy", "hot", "old", "young", "dumb", "stupid", "crazy",
      "insane", "mad", "lazy", "smelly", "stinky", "greasy", "hairy", "bald",
      "blind", "deaf", "lame", "dopey", "nutty", "loopy", "dizzy", "tipsy",
      "drunk",
    ];
    for (const w of [...WORDS.ADJECTIVES, ...WORDS.NOUNS]) {
      expect(banned).not.toContain(w);
    }
  });

  it("keeps every word lowercase letters only, so casing is ours to choose", () => {
    for (const w of [...WORDS.ADJECTIVES, ...WORDS.NOUNS]) {
      expect(w).toMatch(/^[a-z]+$/);
    }
  });
});

describe("looksLikeEmail", () => {
  it("prompts on an address", () => {
    expect(looksLikeEmail("ben@example.com")).toBe(true);
    expect(looksLikeEmail("a@b")).toBe(true);
  });

  it("leaves ordinary usernames alone", () => {
    expect(looksLikeEmail("swift-lantern-27")).toBe(false);
    expect(looksLikeEmail("ben")).toBe(false);
    expect(looksLikeEmail("")).toBe(false);
  });
});
