import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutoHide } from "./useAutoHide";

describe("useAutoHide", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("starts visible so the control is discoverable", () => {
    const { result } = renderHook(() => useAutoHide(2500));
    expect(result.current.visible).toBe(true);
  });

  it("hides after the quiet period", () => {
    const { result } = renderHook(() => useAutoHide(2500));
    act(() => vi.advanceTimersByTime(2500));
    expect(result.current.visible).toBe(false);
  });

  it("poke() reveals it again", () => {
    const { result } = renderHook(() => useAutoHide(2500));
    act(() => vi.advanceTimersByTime(2500));
    act(() => result.current.poke());
    expect(result.current.visible).toBe(true);
  });

  it("each poke restarts the countdown", () => {
    const { result } = renderHook(() => useAutoHide(2000));
    act(() => vi.advanceTimersByTime(1500));
    act(() => result.current.poke());
    act(() => vi.advanceTimersByTime(1500));
    expect(result.current.visible).toBe(true); // would have hidden without the poke
    act(() => vi.advanceTimersByTime(500));
    expect(result.current.visible).toBe(false);
  });

  it("clears its timer on unmount", () => {
    const { unmount } = renderHook(() => useAutoHide(2500));
    unmount();
    expect(() => vi.advanceTimersByTime(5000)).not.toThrow();
  });
});
