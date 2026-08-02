import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HOLD_DELAY_MS, REPEAT_MS, REPEAT_STEP, useHoldRepeat } from "./useHoldRepeat";

describe("useHoldRepeat", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const setup = () => {
    const fire = vi.fn();
    const { result, unmount } = renderHook(() => useHoldRepeat(fire));
    return { fire, result, unmount };
  };

  it("does nothing for a short press — that is still a tap", () => {
    const { fire, result } = setup();
    act(() => result.current.begin(1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS - 1));
    expect(fire).not.toHaveBeenCalled();
    act(() => {
      expect(result.current.end()).toBe(false);
    });
  });

  it("fires the first ten exactly on the second", () => {
    const { fire, result } = setup();
    act(() => result.current.begin(1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS));
    expect(fire).toHaveBeenCalledTimes(1);
    expect(fire).toHaveBeenCalledWith(REPEAT_STEP);
  });

  it("then keeps going every half second", () => {
    const { fire, result } = setup();
    act(() => result.current.begin(1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS));
    act(() => vi.advanceTimersByTime(REPEAT_MS * 3));
    expect(fire).toHaveBeenCalledTimes(4); // one at the second, three since
    expect(fire.mock.calls.every(([d]) => d === REPEAT_STEP)).toBe(true);
  });

  it("runs downwards just the same", () => {
    const { fire, result } = setup();
    act(() => result.current.begin(-1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS + REPEAT_MS));
    expect(fire.mock.calls).toEqual([[-REPEAT_STEP], [-REPEAT_STEP]]);
  });

  it("stops the moment it is released", () => {
    const { fire, result } = setup();
    act(() => result.current.begin(1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS + REPEAT_MS));
    expect(fire).toHaveBeenCalledTimes(2);
    act(() => {
      result.current.end();
    });
    act(() => vi.advanceTimersByTime(REPEAT_MS * 5));
    expect(fire).toHaveBeenCalledTimes(2);
  });

  it("reports that it repeated, so the caller skips the tap", () => {
    // without this every hold would land one extra on release
    const { result } = setup();
    act(() => result.current.begin(1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS));
    act(() => {
      expect(result.current.end()).toBe(true);
    });
  });

  it("a cancelled press counts as neither a tap nor a repeat", () => {
    // dragging a seat across the table must not also change anyone's life
    const { fire, result } = setup();
    act(() => result.current.begin(1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS + REPEAT_MS));
    act(() => result.current.cancel());
    act(() => {
      expect(result.current.end()).toBe(false);
    });
    act(() => vi.advanceTimersByTime(REPEAT_MS * 4));
    expect(fire).toHaveBeenCalledTimes(2); // whatever landed before the drag, no more
  });

  it("keeps its direction even if the pointer wanders across the middle", () => {
    const { fire, result } = setup();
    act(() => result.current.begin(-1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS + REPEAT_MS * 2));
    expect(fire.mock.calls.every(([d]) => d < 0)).toBe(true);
  });

  it("a fresh press starts clean after one that repeated", () => {
    const { fire, result } = setup();
    act(() => result.current.begin(1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS));
    act(() => {
      result.current.end();
    });
    fire.mockClear();

    act(() => result.current.begin(1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS - 1));
    expect(fire).not.toHaveBeenCalled();
    act(() => {
      expect(result.current.end()).toBe(false);
    });
  });

  it("always calls the latest handler, without restarting the run", () => {
    const first = vi.fn();
    const second = vi.fn();
    let handler = first;
    const { result, rerender } = renderHook(() => useHoldRepeat((d) => handler(d)));

    act(() => result.current.begin(1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS));
    expect(first).toHaveBeenCalledTimes(1);

    handler = second;
    rerender();
    act(() => vi.advanceTimersByTime(REPEAT_MS));
    expect(second).toHaveBeenCalledTimes(1);
    expect(first).toHaveBeenCalledTimes(1); // the run carried on, it did not restart
  });

  it("stops when the component goes away", () => {
    const { fire, result, unmount } = setup();
    act(() => result.current.begin(1));
    act(() => vi.advanceTimersByTime(HOLD_DELAY_MS));
    unmount();
    act(() => vi.advanceTimersByTime(REPEAT_MS * 5));
    expect(fire).toHaveBeenCalledTimes(1);
  });
});
