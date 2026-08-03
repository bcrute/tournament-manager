import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRoom } from "./useRoom";

/**
 * The busiest logic in the client, and until now the least tested.
 *
 * What it has to get right is not the happy path — the browser suite covers
 * that — but the behaviour around a server that goes away. This app is
 * deployed while games are in progress, so "the backend restarted mid-turn"
 * is a routine event rather than an incident, and the required behaviour is
 * specific: keep the game on screen, mark it stale, poll quietly, recover
 * without anybody noticing. The failure that matters is a table full of
 * players losing their life totals because a deploy took four seconds.
 *
 * The other half is the distinction `fetchPolicy.classifyFetchError` draws.
 * A 403 once you have had state means the seat is gone and the session must be
 * cleared; a network blip means the opposite — hold everything and retry.
 * Treating either as the other is a bug you cannot see locally, because
 * locally the server never goes away.
 */

const ROOM = { room: { code: "AB123", status: "playing" }, players: [], log: [] };

/** A WebSocket that never connects, so the tests drive state through fetch. */
class SilentSocket {
  static instances: SilentSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];
  closed = false;

  constructor(public url: string) {
    SilentSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.closed = true;
  }

  /** Pretend the server accepted the connection. */
  open() {
    this.onopen?.();
  }

  deliver(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

function respond(...responses: Array<{ status: number; body?: unknown } | "network">) {
  const fn = vi.fn();
  for (const r of responses) {
    if (r === "network") {
      fn.mockImplementationOnce(() => Promise.reject(new TypeError("Failed to fetch")));
    } else {
      fn.mockResolvedValueOnce({
        ok: r.status < 400,
        status: r.status,
        statusText: "Mocked",
        headers: new Headers(),
        json: () => Promise.resolve(r.body ?? {}),
      });
    }
  }
  // anything past the scripted responses keeps answering the last thing
  const last = responses.at(-1);
  if (last && last !== "network") {
    fn.mockResolvedValue({
      ok: last.status < 400,
      status: last.status,
      statusText: "Mocked",
      headers: new Headers(),
      json: () => Promise.resolve(last.body ?? {}),
    });
  }
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("useRoom", () => {
  beforeEach(() => {
    SilentSocket.instances = [];
    vi.stubGlobal("WebSocket", SilentSocket as unknown as typeof WebSocket);
    localStorage.clear();
  });

  afterEach(() => {
    // Explicit, because this project does not enable vitest `globals` and so
    // testing-library never registers its automatic cleanup. Without it every
    // previously mounted hook stays subscribed to `visibilitychange`, and a
    // single dispatch fires one refetch per test that has ever run — which is
    // how "stops listening after unmount" saw fifteen calls instead of one.
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    localStorage.clear();
  });

  describe("getting the state at all", () => {
    it("fetches on mount and reports it", async () => {
      respond({ status: 200, body: ROOM });
      const { result } = renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(result.current.state).not.toBeNull());
      expect(result.current.error).toBeNull();
      expect(result.current.stale).toBe(false);
      expect(result.current.gone).toBe(false);
    });

    it("sends the player token as a header, never in the URL", async () => {
      // A room URL with a token in it lands in an access log and a browser
      // history; the header does neither.
      const fn = respond({ status: 200, body: ROOM });
      renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(fn).toHaveBeenCalled());
      const [url, opts] = fn.mock.calls[0] as [string, RequestInit];
      expect(url).not.toContain("tok");
      expect((opts.headers as Record<string, string>)["X-Player-Token"]).toBe("tok");
    });
  });

  describe("when the server goes away mid-game", () => {
    it("keeps the last state on screen and marks it stale", async () => {
      // A deploy takes a few seconds. Blanking four players' life totals for
      // those seconds is the outcome this exists to prevent.
      const fn = respond({ status: 200, body: ROOM }, "network");
      const { result } = renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(result.current.state).not.toBeNull());

      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.stale).toBe(true);
      expect(result.current.state).not.toBeNull(); // the game is still there
      expect(result.current.error).toBeNull(); // and it is not an error state
      expect(fn).toHaveBeenCalledTimes(2);
    });

    it("polls while stale and clears it on recovery", async () => {
      vi.useFakeTimers();
      respond({ status: 200, body: ROOM }, "network", { status: 200, body: ROOM });
      const { result } = renderHook(() => useRoom("AB123", "tok"));
      await act(async () => {
        await Promise.resolve();
      });

      await act(async () => {
        await result.current.refetch();
      });
      expect(result.current.stale).toBe(true);

      // the retry loop runs on its own, without anybody touching the page
      await act(async () => {
        vi.advanceTimersByTime(1600);
        await Promise.resolve();
      });
      await act(async () => {
        await Promise.resolve();
      });
      expect(result.current.stale).toBe(false);
    });

    it("does not poll when nothing is stale", async () => {
      vi.useFakeTimers();
      const fn = respond({ status: 200, body: ROOM });
      renderHook(() => useRoom("AB123", "tok"));
      await act(async () => {
        await Promise.resolve();
      });
      const calls = fn.mock.calls.length;

      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      expect(fn.mock.calls.length).toBe(calls);
    });
  });

  describe("when the seat is actually gone", () => {
    it("clears the session and says so", async () => {
      // 403 *after* we have had state means the seat was reclaimed or the game
      // ended — the opposite of a blip, and holding the screen would strand
      // the player looking at a game they are no longer in.
      localStorage.setItem("table.session", JSON.stringify({ code: "AB123", token: "tok" }));
      respond({ status: 200, body: ROOM }, { status: 403, body: { detail: "not a player" } });
      const { result } = renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(result.current.state).not.toBeNull());

      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.gone).toBe(true);
      expect(localStorage.getItem("table.session")).toBeNull();
    });

    it("a first-load failure is an error, not a lost seat", async () => {
      // Before any state has arrived there is nothing to protect and nothing
      // to conclude — clearing the session here would log out someone whose
      // wifi dropped as the page opened.
      localStorage.setItem("table.session", JSON.stringify({ code: "AB123", token: "tok" }));
      respond({ status: 500, body: { detail: "boom" } });
      const { result } = renderHook(() => useRoom("AB123", "tok"));

      await waitFor(() => expect(result.current.error).not.toBeNull());
      expect(result.current.gone).toBe(false);
      expect(localStorage.getItem("table.session")).not.toBeNull();
    });
  });

  describe("the push socket", () => {
    it("authenticates by message rather than in the URL", async () => {
      // Same reasoning as the fetch header: a token in a WebSocket URL is a
      // token in an access log.
      respond({ status: 200, body: ROOM });
      renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(SilentSocket.instances).toHaveLength(1));

      const socket = SilentSocket.instances[0];
      expect(socket.url).not.toContain("tok");
      socket.open();
      expect(JSON.parse(socket.sent[0])).toEqual({ token: "tok" });
    });

    it("takes pushed state without another fetch", async () => {
      // The point of the socket: a life-total change should not cost a request
      // from every device at the table.
      const fn = respond({ status: 200, body: ROOM });
      const { result } = renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(SilentSocket.instances).toHaveLength(1));
      const calls = fn.mock.calls.length;

      act(() => {
        SilentSocket.instances[0].deliver({
          type: "state",
          state: { ...ROOM, room: { code: "AB123", status: "ended" } },
        });
      });

      await waitFor(() =>
        expect(result.current.state?.room.status).toBe("ended"),
      );
      expect(fn.mock.calls.length).toBe(calls);
    });

    it("falls back to a fetch when a message is not usable", async () => {
      const fn = respond({ status: 200, body: ROOM });
      renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(SilentSocket.instances).toHaveLength(1));
      const calls = fn.mock.calls.length;

      act(() => {
        SilentSocket.instances[0].onmessage?.({ data: "not json at all" });
      });
      await waitFor(() => expect(fn.mock.calls.length).toBeGreaterThan(calls));
    });

    it("a pushed state clears staleness", async () => {
      respond({ status: 200, body: ROOM }, "network");
      const { result } = renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(SilentSocket.instances).toHaveLength(1));
      await act(async () => {
        await result.current.refetch();
      });
      expect(result.current.stale).toBe(true);

      act(() => {
        SilentSocket.instances[0].deliver({ type: "state", state: ROOM });
      });
      await waitFor(() => expect(result.current.stale).toBe(false));
    });

    it("reconnects after the server drops it", async () => {
      // Which is what a deploy does to every open socket at once.
      vi.useFakeTimers();
      respond({ status: 200, body: ROOM });
      renderHook(() => useRoom("AB123", "tok"));
      await act(async () => {
        await Promise.resolve();
      });
      expect(SilentSocket.instances).toHaveLength(1);

      act(() => {
        SilentSocket.instances[0].onclose?.();
      });
      await act(async () => {
        vi.advanceTimersByTime(2100);
      });
      expect(SilentSocket.instances).toHaveLength(2);
    });

    it("stops reconnecting once the component is gone", async () => {
      // Otherwise leaving a room leaves a socket reconnecting forever, and a
      // long session accumulates one per room visited.
      vi.useFakeTimers();
      respond({ status: 200, body: ROOM });
      const { unmount } = renderHook(() => useRoom("AB123", "tok"));
      await act(async () => {
        await Promise.resolve();
      });
      const socket = SilentSocket.instances[0];

      unmount();
      expect(socket.closed).toBe(true);

      act(() => {
        socket.onclose?.();
      });
      await act(async () => {
        vi.advanceTimersByTime(5000);
      });
      expect(SilentSocket.instances).toHaveLength(1);
    });
  });

  describe("coming back to the tab", () => {
    it("refetches when the page becomes visible", async () => {
      // A phone that was in a pocket has missed every push in the meantime.
      const fn = respond({ status: 200, body: ROOM });
      renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(fn).toHaveBeenCalled());
      const calls = fn.mock.calls.length;

      vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await waitFor(() => expect(fn.mock.calls.length).toBeGreaterThan(calls));
    });

    it("ignores the event when the page is being hidden", async () => {
      const fn = respond({ status: 200, body: ROOM });
      renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(fn).toHaveBeenCalled());
      const calls = fn.mock.calls.length;

      vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await new Promise((r) => setTimeout(r, 20));
      expect(fn.mock.calls.length).toBe(calls);
    });

    it("stops listening after unmount", async () => {
      const fn = respond({ status: 200, body: ROOM });
      const { unmount } = renderHook(() => useRoom("AB123", "tok"));
      await waitFor(() => expect(fn).toHaveBeenCalled());
      unmount();
      const calls = fn.mock.calls.length;

      vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await new Promise((r) => setTimeout(r, 20));
      expect(fn.mock.calls.length).toBe(calls);
    });
  });
});
