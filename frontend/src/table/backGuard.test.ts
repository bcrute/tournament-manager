import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createBackGuard } from "./backGuard";

function actions() {
  return { warn: vi.fn(), leave: vi.fn(), rearm: vi.fn() };
}

describe("createBackGuard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(100_000);
  });
  afterEach(() => vi.useRealTimers());

  it("first back warns and rearms, never leaves", () => {
    const guard = createBackGuard(2500);
    const a = actions();
    guard.onBack(a);
    expect(a.warn).toHaveBeenCalledTimes(1);
    expect(a.rearm).toHaveBeenCalledTimes(1);
    expect(a.leave).not.toHaveBeenCalled();
  });

  it("second back within the window leaves", () => {
    const guard = createBackGuard(2500);
    const a = actions();
    guard.onBack(a);
    vi.setSystemTime(101_000);
    guard.onBack(a);
    expect(a.leave).toHaveBeenCalledTimes(1);
    expect(a.warn).toHaveBeenCalledTimes(1); // no second warning
  });

  it("second back after the window re-warns instead of leaving", () => {
    const guard = createBackGuard(2500);
    const a = actions();
    guard.onBack(a);
    vi.setSystemTime(103_000);
    guard.onBack(a);
    expect(a.leave).not.toHaveBeenCalled();
    expect(a.warn).toHaveBeenCalledTimes(2);
    expect(a.rearm).toHaveBeenCalledTimes(2);
  });

  it("window resets after an expired attempt", () => {
    const guard = createBackGuard(2500);
    const a = actions();
    guard.onBack(a); // arm @100s
    vi.setSystemTime(103_000);
    guard.onBack(a); // expired -> re-arm @103s
    vi.setSystemTime(104_000);
    guard.onBack(a); // within window of the re-arm -> leave
    expect(a.leave).toHaveBeenCalledTimes(1);
  });
});
