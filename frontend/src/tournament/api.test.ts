import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ackCall,
  addEntrants,
  callOfficial,
  callTime,
  claimSeat,
  clearSeat,
  closeRound,
  createTournament,
  dropEntrant,
  endTournament,
  formatClock,
  getRoster,
  getState,
  listGames,
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
  undropEntrant,
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
    expect(body).toEqual({
      name: "Friday Night", game: "mtg", mode: "life", settings: { podSize: 4 },
    });
  });

  it("lists the game profiles this server can run", async () => {
    const fn = mockFetch({ games: [{ key: "mtg" }] });
    const r = await listGames();
    expect(lastCall(fn).url).toBe("/api/tournament/games");
    expect(r.games[0].key).toBe("mtg");
  });

  it("defaults to mtg but sends the game explicitly", async () => {
    const fn = mockFetch({ code: "AB123", game: "mtg" });
    await createTournament("Night", "life", {});
    expect(lastCall(fn).body.game).toBe("mtg");
    await createTournament("Night", "life", {}, "lorcana");
    expect(lastCall(fn).body.game).toBe("lorcana");
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
    await claimSeat("AB123", "e_7xk");
    expect(lastCall(fn).body).toEqual({ entrantId: "e_7xk", wizardsEmail: null });
  });

  it("sends a Wizards email only when one was given", async () => {
    const fn = mockFetch({ entrantToken: "t", entrantId: 7, name: "Ada" });
    await claimSeat("AB123", "e_7xk", "a@b.com");
    expect(lastCall(fn).body).toEqual({ entrantId: "e_7xk", wizardsEmail: "a@b.com" });
  });

  it("calls time on the round", async () => {
    const fn = mockFetch({ ok: true, decided: 2, policy: "draw_all" });
    const r = await callTime("AB123");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/rounds/time");
    expect(r.decided).toBe(2);
  });

  it("brings a dropped entrant back", async () => {
    const fn = mockFetch();
    await undropEntrant("AB123", "e_4qz");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/entrants/e_4qz/undrop");
  });

  it("ends the tournament and returns frozen standings", async () => {
    const fn = mockFetch({ ok: true, standings: [] });
    const r = await endTournament("AB123");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/end");
    expect(r.standings).toEqual([]);
  });

  it("adds entrants as a batch", async () => {
    const fn = mockFetch({ added: [] });
    await addEntrants("AB123", ["Ada", "Grace"]);
    expect(lastCall(fn).body).toEqual({ names: ["Ada", "Grace"] });
  });

  it("routes release and drop to distinct endpoints", async () => {
    const fn = mockFetch();
    await releaseEntrant("AB123", "e_4qz");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/entrants/e_4qz/release");
    await dropEntrant("AB123", "e_4qz");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/entrants/e_4qz/drop");
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
    await reportResult("AB123", 9, { kind: "placement", places: [{ entrantId: "e_1ab", place: 1 }] });
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
    await resolveCall("AB123", 2, 5, "warning issued");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/calls/2/resolve");
    expect(lastCall(fn).body).toEqual({ note: "warning issued", extendMinutes: 5 });
  });

  it("omits the extension so the server gives back what it measured", async () => {
    const fn = mockFetch({ ok: true });
    await resolveCall("AB123", 2);
    expect(lastCall(fn).body).toEqual({ note: null, extendMinutes: null });
  });

  it("sends an explicit zero when the judge grants no time", async () => {
    const fn = mockFetch({ ok: true });
    await resolveCall("AB123", 2, 0);
    expect(lastCall(fn).body).toEqual({ note: null, extendMinutes: 0 });
  });
});

describe("seat session", () => {
  const seat = { code: "AB123", token: "tok", entrantId: "e_4qz", name: "Ada" };

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

describe("organizer entry points", () => {
  it("lists this organizer's own events", async () => {
    const fn = mockFetch({ tournaments: [] });
    const { listMine } = await import("./api");
    await listMine();
    expect(lastCall(fn).url).toBe("/api/tournament/mine");
  });

  it("asks for a plan against the live roster by default", async () => {
    const fn = mockFetch({ swissRounds: 3 });
    const { getPlan } = await import("./api");
    await getPlan("AB123");
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/plan");
  });

  it("can ask what a hypothetical turnout would need", async () => {
    const fn = mockFetch({ swissRounds: 6 });
    const { getPlan } = await import("./api");
    await getPlan("AB123", 40);
    expect(lastCall(fn).url).toBe("/api/tournament/AB123/plan?players=40");
  });
});
