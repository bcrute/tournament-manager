import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useWakeLock } from "./useWakeLock";

function stubWakeLock() {
  const release = vi.fn().mockResolvedValue(undefined);
  const request = vi.fn().mockResolvedValue({ release });
  Object.defineProperty(navigator, "wakeLock", {
    value: { request },
    configurable: true,
  });
  return { request, release };
}

describe("useWakeLock", () => {
  afterEach(() => {
    cleanup(); // unmount hooks so visibility listeners can't leak across tests
    // @ts-expect-error cleanup of test stub
    delete navigator.wakeLock;
  });

  it("acquires a screen lock when active", async () => {
    const { request } = stubWakeLock();
    renderHook(() => useWakeLock(true));
    await vi.waitFor(() => expect(request).toHaveBeenCalledWith("screen"));
  });

  it("does not acquire when inactive (battery: lobby screens may sleep)", () => {
    const { request } = stubWakeLock();
    renderHook(() => useWakeLock(false));
    expect(request).not.toHaveBeenCalled();
  });

  it("releases on unmount (battery: no lock outlives the game)", async () => {
    const { request, release } = stubWakeLock();
    const { unmount } = renderHook(() => useWakeLock(true));
    await vi.waitFor(() => expect(request).toHaveBeenCalled());
    unmount();
    await vi.waitFor(() => expect(release).toHaveBeenCalled());
  });

  it("releases when active flips false mid-session", async () => {
    const { request, release } = stubWakeLock();
    const hook = renderHook(({ on }) => useWakeLock(on), { initialProps: { on: true } });
    await vi.waitFor(() => expect(request).toHaveBeenCalled());
    hook.rerender({ on: false });
    await vi.waitFor(() => expect(release).toHaveBeenCalled());
  });

  it("re-acquires when the tab becomes visible again", async () => {
    const { request } = stubWakeLock();
    renderHook(() => useWakeLock(true));
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  });

  it("survives an unsupported browser", () => {
    // no navigator.wakeLock defined
    expect(() => renderHook(() => useWakeLock(true))).not.toThrow();
  });
});
