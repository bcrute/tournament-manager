import { afterEach, describe, expect, it, vi } from "vitest";
import { adm, AdminError, ago, closeRoom, endTournament, getOverview, getSecurity, liftBan } from "./api";

function mockFetch(body: unknown = { ok: true }, status = 200, headers: Record<string, string> = {}) {
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

const last = (fn: ReturnType<typeof vi.fn>) => {
  const [url, opts] = fn.mock.calls.at(-1) as [string, RequestInit];
  return { url, opts, body: opts.body ? JSON.parse(opts.body as string) : undefined };
};

afterEach(() => vi.unstubAllGlobals());

describe("admin transport", () => {
  it("sends the session cookie — the surface is unlisted, not unauthenticated", async () => {
    const fn = mockFetch();
    await adm("/overview");
    expect(last(fn).opts.credentials).toBe("same-origin");
  });

  it("surfaces a 404 as such, so the caller can't distinguish denied from absent", async () => {
    mockFetch({ detail: "Not Found" }, 404);
    const err = await getOverview().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(AdminError);
    expect((err as AdminError).status).toBe(404);
  });
});

describe("actions", () => {
  it("sends a reason so the audit log records why", async () => {
    const fn = mockFetch();
    await closeRoom("AB123", "stuck game");
    expect(last(fn).url).toBe("/api/admin/rooms/AB123/close");
    expect(last(fn).body).toEqual({ reason: "stuck game" });
  });

  it("sends an explicit null when no reason was given", async () => {
    const fn = mockFetch();
    await endTournament("AB123");
    expect(last(fn).body).toEqual({ reason: null });
  });

  it("escapes a ban subject rather than pasting it into the path", async () => {
    const fn = mockFetch();
    await liftBan("a/b+c=");
    expect(last(fn).url).toBe("/api/admin/bans/a%2Fb%2Bc%3D/lift");
  });
});

describe("security log", () => {
  it("reads the security log separately from the admin log", async () => {
    const fn = mockFetch({ entries: [], last24h: [] });
    await getSecurity();
    expect(last(fn).url).toBe("/api/admin/security");
  });

  it("filters by kind without breaking on an odd value", async () => {
    const fn = mockFetch({ entries: [], last24h: [] });
    await getSecurity("auth.fail");
    expect(last(fn).url).toBe("/api/admin/security?kind=auth.fail");
  });
});

describe("ago", () => {
  const now = 1_000_000_000_000;
  it("reads at a glance", () => {
    expect(ago(now / 1000 - 30, now)).toBe("30s");
    expect(ago(now / 1000 - 300, now)).toBe("5m");
    expect(ago(now / 1000 - 7200, now)).toBe("2h");
    expect(ago(now / 1000 - 172800, now)).toBe("2d");
  });
  it("has nothing to say about a missing timestamp", () => {
    expect(ago(null, now)).toBe("—");
  });
  it("never shows a negative age when clocks disagree", () => {
    expect(ago(now / 1000 + 500, now)).toBe("0s");
  });
});
