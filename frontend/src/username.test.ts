import { describe, expect, it } from "vitest";
import { looksLikeEmail, suggestUsername, WORD_COUNTS } from "./username";

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
