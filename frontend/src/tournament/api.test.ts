import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ackCall,
  addEntrants,
  callOfficial,
  claimSeat,
  clearSeat,
  closeRound,
  createTournament,
  dropEntrant,
  formatClock,
  getRoster,
  getState,
  loadSeat,
  openRound,
  releaseEntrant,
  reportResult,
  resolveCall,
  saveSeat,
  secondsLeft,
  tapi,
  timerAction,
  TourneyError,
} from "./api";

/** Records the last fetch and replies with `body`. */
function mockFetch(body: unknown = { ok: true }, init: { status?: number } = {}) {
  const status = init.status ?? 200;
  const fn = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: "Mocked",
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function lastCall(fn: ReturnType<typeof vi.fn>) {
  const [url, opts] = fn.mock.calls[fn.mock.calls.length - 1] as [string, RequestInit];
  return { url, opts, body: opts.body ? JSON.parse(opts.body as string) : undefined };
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("tapi transport", () => {
  it("sends the session cookie so the organizer is recognised", async () => {
    const fn = mockFetch();
    await tapi("/ABC12");
    expect(lastCall(fn).opts.credentials).toBe("same-origin");
  });

  it("omits a JSON content-type when there is no body", async () => {
    const fn = mockFetch();
    await tapi("/ABC12");
    expect(lastCall(fn).opts.headers).toEqual({});
  });

  it("surfaces the server's detail message, not the HTTP status text", async () => {
    mockFetch({ detail: "that name is already claimed" }, { status: 409 });
    await expect(tapi("/ABC12/claim", { method: "POST", body: {} })).rejects.toThrow(
      "that name is already claimed",
    );
  });

  it("falls back to status text when the error body isn't JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: () => Promise.reject(new Error("not json")),
      }),
    );
    await expect(tapi("/ABC12")).rejects.toThrow("Internal Server Error");
  });

  it("carries the status on the error so callers can branch on 409", async () => {
    mockFetch({ detail: "taken" }, { status: 409 });
    const err = await tapi("/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(TourneyError);
    expect((err as TourneyError).status).toBe(409);
  });
});

describe("endpoints", () => {
  it("creates a tournament with its settings", async () => {
    const fn = mockFetch({ code: "AB123" });
    await createTournament("Friday Night", "life", { podSize: 4 });
    const { url, opts, body } = lastCall(fn);
    expect(url).toBe("/api/tournament");
    expect(opts.method).toBe("POST");
    expect(body).toEqual({ name: "Friday Night", mode: "life", settings: { podSize: 4 } });
  });

  it("passes an entrant token as a query parameter when one is held", async () => {
    const fn = mockFetch({});
    await getState("AB123", "tok en/+");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123?token=tok%20en%2F%2B");
  });

  it("omits the token entirely for an organizer read", async () => {
    const fn = mockFetch({});
    await getState("AB123");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123");
    await getState("AB123", null);
    expect(lastCall(fn).url).toBe("/api/tournament/AB123");
  });

  it("reads the roster without a token — a player has none yet", async () => {
    const fn = mockFetch({ name: "x", status: "setup", entrants: [] });
    await getRoster("AB123");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/roster");
  });

  it("claims a seat by id, not by name", async () => {
    const fn = mockFetch({ entrantToken: "t", entrantId: 7, name: "Ada" });
    await claimSeat("AB123", 7);
    expect(lastCall(fn).body).toEqual({ entrantId: 7 });
  });

  it("adds entrants as a batch", async () => {
    const fn = mockFetch({ added: [] });
    await addEntrants("AB123", ["Ada", "Grace"]);
    expect(lastCall(fn).body).toEqual({ names: ["Ada", "Grace"] });
  });

  it("routes release and drop to distinct endpoints", async () => {
    const fn = mockFetch();
    await releaseEntrant("AB123", 4);
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/entrants/4/release");
    await dropEntrant("AB123", 4);
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/entrants/4/drop");
  });

  it("opens a round, and re-pairs only when asked", async () => {
    const fn = mockFetch({ round: 1, pods: [] });
    await openRound("AB123");
    expect(lastCall(fn).body).toEqual({ reroll: false });
    await openRound("AB123", true);
    expect(lastCall(fn).body).toEqual({ reroll: true });
  });

  it("closes a round", async () => {
    const fn = mockFetch();
    await closeRound("AB123");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/rounds/close");
  });

  it("reports a placement result for a pod", async () => {
    const fn = mockFetch({ ok: true, version: 2 });
    await reportResult("AB123", 9, { kind: "placement", places: [{ entrantId: 1, place: 1 }] });
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/pods/9/result");
    expect(lastCall(fn).body.kind).toBe("placement");
  });

  it("sends timer actions with their arguments", async () => {
    const fn = mockFetch();
    await timerAction("AB123", "start");
    expect(lastCall(fn).body).toEqual({ action: "start" });
    await timerAction("AB123", "extend", { minutes: 5, podId: 3 });
    expect(lastCall(fn).body).toEqual({ action: "extend", minutes: 5, podId: 3 });
  });

  it("calls an official with the entrant's token", async () => {
    const fn = mockFetch();
    await callOfficial("AB123", 9, "tok", "judge please");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/pods/9/call?token=tok");
    expect(lastCall(fn).body).toEqual({ note: "judge please" });
  });

  it("sends an explicit null note when a call carries no text", async () => {
    const fn = mockFetch();
    await callOfficial("AB123", 9, "tok");
    expect(lastCall(fn).body).toEqual({ note: null });
  });

  it("acknowledges and resolves calls", async () => {
    const fn = mockFetch();
    await ackCall("AB123", 2);
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/calls/2/ack");
    await resolveCall("AB123", 2, "warning issued");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/calls/2/resolve");
    expect(lastCall(fn).body).toEqual({ note: "warning issued" });
    await resolveCall("AB123", 2);
    expect(lastCall(fn).body).toEqual({ note: null });
  });
});

describe("seat session", () => {
  const seat = { code: "AB123", token: "tok", entrantId: 4, name: "Ada" };

  it("round-trips a claimed seat", () => {
    saveSeat(seat);
    expect(loadSeat()).toEqual(seat);
  });

  it("returns null when nothing is stored", () => {
    expect(loadSeat()).toBeNull();
  });

  it("survives corrupted storage rather than throwing on load", () => {
    localStorage.setItem("tournament.seat", "{not json");
    expect(loadSeat()).toBeNull();
  });

  it("rejects a stored value missing its token — it can't authenticate anything", () => {
    localStorage.setItem("tournament.seat", JSON.stringify({ code: "AB123" }));
    expect(loadSeat()).toBeNull();
  });

  it("rejects a stored null", () => {
    localStorage.setItem("tournament.seat", "null");
    expect(loadSeat()).toBeNull();
  });

  it("clears the seat when checking in as someone else", () => {
    saveSeat(seat);
    clearSeat();
    expect(loadSeat()).toBeNull();
  });
});

describe("round clock", () => {
  const round = (over: Partial<NonNullable<Parameters<typeof secondsLeft>[0]>> = {}) => ({
    number: 1,
    status: "active" as const,
    endsAt: 1_000_000,
    pausedAt: null,
    now: 999_400,
    ...over,
  });

  it("counts down from the server's deadline", () => {
    expect(secondsLeft(round(), 999_400_000, 0)).toBe(600);
  });

  it("corrects for a client clock that is wrong — every device shows the same time", () => {
    // this device is 30s behind the server; the deadline must not shift with it
    expect(secondsLeft(round(), 999_370_000, 30_000)).toBe(600);
  });

  it("freezes while the round is paused", () => {
    const paused = round({ pausedAt: 999_700 });
    expect(secondsLeft(paused, 999_900_000, 0)).toBe(300);
    // and stays frozen as real time keeps passing
    expect(secondsLeft(paused, 999_999_000, 0)).toBe(300);
  });

  it("floors at zero rather than counting negative once time is called", () => {
    expect(secondsLeft(round(), 1_000_600_000, 0)).toBe(0);
  });

  it("has no clock before the round has started", () => {
    expect(secondsLeft(null, 0, 0)).toBeNull();
    expect(secondsLeft(round({ endsAt: null }), 0, 0)).toBeNull();
  });

  it("formats as minutes and padded seconds", () => {
    expect(formatClock(600)).toBe("10:00");
    expect(formatClock(65)).toBe("1:05");
    expect(formatClock(9)).toBe("0:09");
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(null)).toBe("—");
  });
});
