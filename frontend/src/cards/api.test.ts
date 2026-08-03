import { afterEach, describe, expect, it, vi } from "vitest";
import { CardError, getRulings, suggestCards } from "./api";

/**
 * The transport for card lookups.
 *
 * Two things here are easy to get wrong and invisible when they are: card
 * names are full of characters that change a URL if they are not encoded, and
 * a failed lookup has to arrive as a *failure* rather than as an empty answer.
 * "No rulings found" and "we could not ask" look identical to a user unless
 * this layer keeps them apart.
 */

function mockFetch(body: unknown, status = 200, headers: Record<string, string> = {}) {
  const fn = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: "Mocked",
    headers: new Headers(headers),
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const url = (fn: ReturnType<typeof vi.fn>) => fn.mock.calls.at(-1)![0] as string;

describe("card api transport", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks our own server, never Scryfall", async () => {
    // The whole reason this is proxied: the CSP forbids a third-party request,
    // and going direct would hand Scryfall the player's address on every
    // keystroke.
    const fn = mockFetch({ suggestions: [], ready: true });
    await suggestCards("bolt");
    expect(url(fn).startsWith("/api/cards/")).toBe(true);
    expect(url(fn)).not.toContain("scryfall");
  });

  it("encodes a card name that would otherwise change the request", async () => {
    const fn = mockFetch({ name: "x", rulings: [], scryfallUrl: "https://scryfall.com/x" });
    await getRulings("Jace, the Mind Sculptor");
    expect(url(fn)).not.toContain(" ");
    expect(new URL(url(fn), "http://x").searchParams.get("name")).toBe(
      "Jace, the Mind Sculptor",
    );
  });

  it("survives the characters that actually appear in card names", async () => {
    // ampersands, apostrophes, accents, slashes on split cards — every one of
    // these silently becomes a different request when pasted in raw
    for (const name of [
      "Gaea's Cradle",
      "Lim-Dûl the Necromancer",
      "Fire // Ice",
      "Look at Me, I'm the DCI",
      "Bruna, Light of Alabaster & Gisela",
      "100% Real Card?",
    ]) {
      const fn = mockFetch({ name, rulings: [], scryfallUrl: "https://scryfall.com/x" });
      await getRulings(name);
      expect(new URL(url(fn), "http://x").searchParams.get("name"), name).toBe(name);
    }
  });

  it("returns the parsed payload", async () => {
    mockFetch({
      name: "Doubling Season",
      typeLine: "Enchantment",
      manaCost: "{4}{G}",
      oracleText: "…",
      setName: "Foundations",
      scryfallUrl: "https://scryfall.com/card/fdn/216/doubling-season",
      rulings: [{ at: "2024-11-08", text: "Planeswalkers…", source: "wotc" }],
    });
    const card = await getRulings("Doubling Season");
    expect(card.name).toBe("Doubling Season");
    expect(card.rulings).toHaveLength(1);
    expect(card.rulings[0].source).toBe("wotc");
  });

  it("raises the server's message for an unknown card", async () => {
    mockFetch({ detail: "no card by that name" }, 404);
    const err = (await getRulings("Not A Card").catch((e: unknown) => e)) as CardError;
    expect(err).toBeInstanceOf(CardError);
    expect(err.status).toBe(404);
    expect(err.message).toBe("no card by that name");
  });

  it("raises rather than resolving empty when the lookup fails", async () => {
    // The distinction the UI depends on: a card with no rulings is a
    // successful answer, and an upstream outage is not. Resolving both to an
    // empty list would show "no rulings" for a card that has plenty.
    mockFetch({ detail: "card rulings are unavailable right now" }, 503);
    await expect(getRulings("Doubling Season")).rejects.toBeInstanceOf(CardError);
  });

  it("folds a rate limit into the wait, like every other transport", async () => {
    mockFetch({ detail: "too many requests — slow down" }, 429, { "Retry-After": "30" });
    const err = (await suggestCards("bolt").catch((e: unknown) => e)) as CardError;
    expect(err.status).toBe(429);
    expect(err.message).toBe("Too many requests from this network. Try again in 30 seconds.");
  });

  it("falls back to the status text when the error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        statusText: "Bad Gateway",
        headers: new Headers(),
        json: () => Promise.reject(new Error("not json")),
      }),
    );
    const err = (await suggestCards("bolt").catch((e: unknown) => e)) as CardError;
    expect(err.message).toBe("Bad Gateway");
  });

  it("passes the readiness flag through untouched", async () => {
    // The UI needs it to say "still loading the card list" instead of blaming
    // the person typing for a card that does exist.
    mockFetch({ suggestions: [], ready: false });
    expect((await suggestCards("bolt")).ready).toBe(false);
  });
});
