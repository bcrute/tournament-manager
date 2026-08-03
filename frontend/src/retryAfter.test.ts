import { describe, expect, it } from "vitest";
import { apiMessage, waitPhrase } from "./retryAfter";

describe("waitPhrase", () => {
  it("counts seconds while seconds are useful", () => {
    expect(waitPhrase(45)).toBe("in 45 seconds");
    expect(waitPhrase(59)).toBe("in 59 seconds");
  });

  it("rounds up, so the advice is never early", () => {
    expect(waitPhrase(12.2)).toBe("in 13 seconds");
    expect(waitPhrase(61)).toBe("in about 2 minutes");
  });

  it("goes vague past a minute, where a count would be false precision", () => {
    expect(waitPhrase(60)).toBe("in about a minute");
    expect(waitPhrase(300)).toBe("in about 5 minutes");
  });

  it("says something for a wait too short to name", () => {
    expect(waitPhrase(1)).toBe("in a moment");
    expect(waitPhrase(0)).toBe("in a moment");
  });
});

describe("apiMessage", () => {
  it("leaves every other status alone", () => {
    expect(apiMessage(404, "room not found", null)).toBe("room not found");
    expect(apiMessage(403, "not a player in this room", "30")).toBe("not a player in this room");
  });

  it("replaces the server's scolding with the wait", () => {
    // "too many requests — slow down" is true and useless; the wait is the
    // one thing the person on the other end can act on
    expect(apiMessage(429, "too many requests — slow down", "45")).toBe(
      "Too many requests from this network. Try again in 45 seconds.",
    );
  });

  it("blames the network, not the person", () => {
    // the usual 429 at a table is forty people behind one shop NAT
    const msg = apiMessage(429, "too many requests — slow down", "120");
    expect(msg).toContain("this network");
    expect(msg).not.toContain("slow down");
  });

  it("never produces NaN when the header is missing or junk", () => {
    for (const header of [null, "", "soon", "-5", "0"]) {
      const msg = apiMessage(429, "too many requests — slow down", header);
      expect(msg).not.toContain("NaN");
      expect(msg).toBe("Too many requests from this network. Try again shortly.");
    }
  });

  it("handles the HTTP-date form of Retry-After by falling back", () => {
    // the app only ever sends seconds, but a proxy may rewrite it, and a date
    // parsed as a number is NaN
    const msg = apiMessage(429, "too many requests — slow down", "Wed, 21 Oct 2026 07:28:00 GMT");
    expect(msg).toBe("Too many requests from this network. Try again shortly.");
  });
});
