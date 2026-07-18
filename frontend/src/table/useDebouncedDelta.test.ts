import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDebouncedDelta } from "./useDebouncedDelta";

describe("useDebouncedDelta", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("accumulates rapid taps and commits one net delta", () => {
    const commit = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useDebouncedDelta(commit, 1400));

    act(() => {
      result.current.bump(1);
      result.current.bump(1);
      result.current.bump(-5);
    });
    expect(result.current.pending).toBe(-3);
    expect(commit).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1400));
    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit).toHaveBeenCalledWith(-3);
    expect(result.current.pending).toBe(0);
  });

  it("each tap restarts the quiet window", () => {
    const commit = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useDebouncedDelta(commit, 1000));

    act(() => result.current.bump(1));
    act(() => vi.advanceTimersByTime(800));
    act(() => result.current.bump(1));
    act(() => vi.advanceTimersByTime(800));
    expect(commit).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(200));
    expect(commit).toHaveBeenCalledWith(2);
  });

  it("a net-zero burst commits nothing", () => {
    const commit = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useDebouncedDelta(commit, 500));
    act(() => {
      result.current.bump(3);
      result.current.bump(-3);
    });
    act(() => vi.advanceTimersByTime(500));
    expect(commit).not.toHaveBeenCalled();
  });

  it("flushes pending delta on unmount (regression: taps must not be lost)", () => {
    const commit = vi.fn().mockResolvedValue(undefined);
    const { result, unmount } = renderHook(() => useDebouncedDelta(commit, 1400));
    act(() => result.current.bump(4));
    unmount();
    expect(commit).toHaveBeenCalledWith(4);
  });
});
