import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";

function mockFetch(
  status: number,
  body: unknown,
  jsonThrows = false,
  headers: Record<string, string> = {},
) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: `HTTP ${status}`,
    // a real Response always has these; the client reads Retry-After off a 429
    headers: new Headers(headers),
    json: jsonThrows ? () => Promise.reject(new Error("not json")) : () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("GETs and parses json", async () => {
    const fn = mockFetch(200, { ok: true });
    const out = await api<{ ok: boolean }>("/rooms/X/me", { token: "tok" });
    expect(out).toEqual({ ok: true });
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/table/rooms/X/me");
    expect((init.headers as Record<string, string>)["X-Player-Token"]).toBe("tok");
    expect(init.body).toBeUndefined();
  });

  it("POSTs json bodies with content-type", async () => {
    const fn = mockFetch(200, {});
    await api("/rooms", { method: "POST", body: { name: "ben" } });
    const [, init] = fn.mock.calls[0];
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ name: "ben" }));
  });

  it("throws ApiError with server detail on failure", async () => {
    mockFetch(409, { detail: "that name is taken in this room" });
    const err = (await api("/rooms/X/join", { method: "POST", body: {} }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.message).toBe("that name is taken in this room");
  });

  it("falls back to statusText when the error body is not json", async () => {
    mockFetch(500, null, true);
    const err = (await api("/x").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("HTTP 500");
  });
});

describe("being rate limited", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("tells the player how long to wait, from Retry-After", async () => {
    mockFetch(429, { detail: "too many requests — slow down" }, false, { "Retry-After": "45" });
    const err = (await api("/rooms/join", { method: "POST" }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(429);
    expect(err.message).toBe("Too many requests from this network. Try again in 45 seconds.");
  });

  it("still says something useful when the header is absent", async () => {
    mockFetch(429, { detail: "too many requests — slow down" });
    const err = (await api("/rooms/join", { method: "POST" }).catch((e: unknown) => e)) as ApiError;
    expect(err.message).toBe("Too many requests from this network. Try again shortly.");
  });
});
