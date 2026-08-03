import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { publishAccount, resetAccountCache, useAccount } from "./useAccount";

const ADA = {
  username: "ada",
  displayName: "Grumpy Platypus 42",
  // no address, none pending — and the deployment could send one if there were
  hasEmail: false,
  emailPending: false,
  mailConfigured: true,
  createdAt: 1,
};

function mockMe(account: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    json: () => Promise.resolve({ account }),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => resetAccountCache());
afterEach(() => vi.unstubAllGlobals());

describe("useAccount", () => {
  it("starts undefined, not null — 'not asked' is not 'signed out'", () => {
    mockMe(ADA);
    const { result } = renderHook(() => useAccount());
    // rendering the signed-out nav through this gap is the bug it prevents
    expect(result.current).toBeUndefined();
  });

  it("resolves to the account", async () => {
    mockMe(ADA);
    const { result } = renderHook(() => useAccount());
    await waitFor(() => expect(result.current).toEqual(ADA));
  });

  it("resolves to null when nobody is signed in", async () => {
    mockMe(null);
    const { result } = renderHook(() => useAccount());
    await waitFor(() => expect(result.current).toBeNull());
  });

  it("asks the server once however many components need the answer", async () => {
    const fn = mockMe(ADA);
    const a = renderHook(() => useAccount());
    const b = renderHook(() => useAccount());
    const c = renderHook(() => useAccount());
    await waitFor(() => expect(a.result.current).toEqual(ADA));
    await waitFor(() => expect(b.result.current).toEqual(ADA));
    await waitFor(() => expect(c.result.current).toEqual(ADA));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("treats a failed request as signed out rather than hanging", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const { result } = renderHook(() => useAccount());
    await waitFor(() => expect(result.current).toBeNull());
  });

  it("pushes a change to everyone, so the nav can't show a stale name", async () => {
    mockMe(ADA);
    const nav = renderHook(() => useAccount());
    const page = renderHook(() => useAccount());
    await waitFor(() => expect(nav.result.current).toEqual(ADA));

    act(() => publishAccount({ ...ADA, username: "renamed" }));
    expect(nav.result.current?.username).toBe("renamed");
    expect(page.result.current?.username).toBe("renamed");
  });

  it("propagates a sign-out to every consumer", async () => {
    mockMe(ADA);
    const { result } = renderHook(() => useAccount());
    await waitFor(() => expect(result.current).toEqual(ADA));
    act(() => publishAccount(null));
    expect(result.current).toBeNull();
  });

  it("serves a later mount from the cache without a second request", async () => {
    const fn = mockMe(ADA);
    const first = renderHook(() => useAccount());
    await waitFor(() => expect(first.result.current).toEqual(ADA));
    const later = renderHook(() => useAccount());
    await waitFor(() => expect(later.result.current).toEqual(ADA));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("stops updating a component once it unmounts", async () => {
    mockMe(ADA);
    const { result, unmount } = renderHook(() => useAccount());
    await waitFor(() => expect(result.current).toEqual(ADA));
    unmount();
    // no listener left behind: publishing must not throw on a dead setter
    expect(() => publishAccount(null)).not.toThrow();
  });
});
