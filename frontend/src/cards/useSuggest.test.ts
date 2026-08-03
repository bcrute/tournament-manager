import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEBOUNCE_MS, useSuggest } from "./useSuggest";

/**
 * The two ways an autocomplete box feels broken.
 *
 * One is latency, which debouncing handles. The other is the ordering bug:
 * four requests in flight, any of them free to land last, and the list settles
 * on the answer for a prefix the box no longer contains. That reads as the
 * search being *wrong* rather than late, and it is invisible on a fast local
 * network — which is exactly why it wants a test rather than a manual check.
 */

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const ok = (suggestions: string[], ready = true) => ({
  ok: true,
  status: 200,
  statusText: "OK",
  headers: new Headers(),
  json: () => Promise.resolve({ suggestions, ready }),
});

describe("useSuggest", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  /**
   * Advance past the debounce and let the fetch promise chain resolve.
   *
   * Deliberately not `waitFor`: it polls on real timers, so with fake timers
   * installed it waits forever for a clock that only moves when told. Two
   * flushes — one to run the timer callback, one for the `.then` after the
   * mocked fetch resolves.
   */
  const settle = async () => {
    await act(async () => {
      vi.advanceTimersByTime(DEBOUNCE_MS + 5);
    });
    await act(async () => {
      await Promise.resolve();
    });
  };

  it("asks for nothing until two characters are typed", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok([]));
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = renderHook(({ q }) => useSuggest(q), {
      initialProps: { q: "l" },
    });
    await settle();
    expect(fetchMock).not.toHaveBeenCalled();

    rerender({ q: "li" });
    await settle();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("debounces a burst of typing into one request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok(["Lightning Bolt"]));
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = renderHook(({ q }) => useSuggest(q), {
      initialProps: { q: "li" },
    });
    for (const q of ["lig", "ligh", "light", "lightn"]) {
      rerender({ q });
      act(() => {
        vi.advanceTimersByTime(20); // faster than the debounce
      });
    }
    await settle();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("lightn");
  });

  it("ignores a slow answer that a newer keystroke has overtaken", async () => {
    // The bug this prevents: "bol" resolves after "bolt", and the list settles
    // on suggestions for text the box no longer contains.
    const slow = deferred<Response>();
    const fast = deferred<Response>();
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(slow.promise)
      .mockReturnValueOnce(fast.promise);
    vi.stubGlobal("fetch", fetchMock);

    const { result, rerender } = renderHook(({ q }) => useSuggest(q), {
      initialProps: { q: "bol" },
    });
    await settle();
    rerender({ q: "bolt" });
    await settle();

    // the newer request answers first, then the older one lands
    await act(async () => {
      fast.resolve(ok(["Lightning Bolt"]) as unknown as Response);
    });
    await act(async () => {
      slow.resolve(ok(["Bolas's Citadel", "Bola Kicker"]) as unknown as Response);
    });

    expect(result.current.suggestions).toEqual(["Lightning Bolt"]);
  });

  it("clears the list when the box is emptied", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok(["Lightning Bolt"])));
    const { result, rerender } = renderHook(({ q }) => useSuggest(q), {
      initialProps: { q: "lightn" },
    });
    await settle();
    expect(result.current.suggestions).toHaveLength(1);

    rerender({ q: "" });
    await settle();
    expect(result.current.suggestions).toEqual([]);
  });

  it("reports a server still building its index, rather than 'no results'", async () => {
    // "Still loading the card list" and "no such card" are different problems,
    // and blaming the person typing for the second one is the bad outcome.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok([], false)));
    const { result } = renderHook(() => useSuggest("lightn"));
    await settle();
    expect(result.current.warmingUp).toBe(true);
    expect(result.current.failed).toBe(false);
  });

  it("reports a failure as a failure, not as an empty result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        headers: new Headers(),
        json: () => Promise.resolve({ detail: "upstream is down" }),
      }),
    );
    const { result } = renderHook(() => useSuggest("lightn"));
    await settle();
    expect(result.current.failed).toBe(true);
    expect(result.current.suggestions).toEqual([]);
  });

  it("asks for nothing at all while disabled", async () => {
    // Which is what happens once a card is chosen: the query still holds that
    // card's name, and leaving suggestions on would drop a list over the
    // answer the player just asked for.
    const fetchMock = vi.fn().mockResolvedValue(ok(["Lightning Bolt"]));
    vi.stubGlobal("fetch", fetchMock);
    renderHook(() => useSuggest("Lightning Bolt", false));
    await settle();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("encodes a query that would otherwise break the URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok([]));
    vi.stubGlobal("fetch", fetchMock);
    renderHook(() => useSuggest("jace, the mind sculptor & friends"));
    await settle();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain(" ");
    expect(url).not.toContain("&f"); // the ampersand is encoded, not a new param
    expect(new URL(url, "http://x").searchParams.get("q")).toBe(
      "jace, the mind sculptor & friends",
    );
  });
});
