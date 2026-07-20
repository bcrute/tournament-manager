import { afterEach, describe, expect, it, vi } from "vitest";
import { getItem, removeItem, setItem, storageAvailable } from "./storage";

afterEach(() => vi.unstubAllGlobals());

/** A browser that refuses storage — a privacy extension, or private mode. */
function refuseStorage() {
  vi.stubGlobal("localStorage", {
    getItem: () => {
      throw new DOMException("denied");
    },
    setItem: () => {
      throw new DOMException("denied");
    },
    removeItem: () => {
      throw new DOMException("denied");
    },
  });
}

describe("storage that assumes the user blocks things", () => {
  it("round-trips normally when storage works", () => {
    expect(setItem("k", "v")).toBe(true);
    expect(getItem("k")).toBe("v");
    removeItem("k");
    expect(getItem("k")).toBeNull();
  });

  it("never throws when writes are refused", () => {
    refuseStorage();
    // the room is already created server-side by this point — throwing here
    // stranded the player, which is exactly the bug this replaces
    expect(() => setItem("k", "v")).not.toThrow();
    expect(setItem("k", "v")).toBe(false);
  });

  it("never throws when reads are refused", () => {
    refuseStorage();
    expect(() => getItem("k")).not.toThrow();
    expect(getItem("k")).toBeNull();
  });

  it("never throws when removal is refused", () => {
    refuseStorage();
    expect(() => removeItem("k")).not.toThrow();
  });

  it("reports availability honestly", () => {
    expect(storageAvailable()).toBe(true);
    refuseStorage();
    expect(storageAvailable()).toBe(false);
  });

  it("a write that fails reports it, so callers can degrade rather than assume", () => {
    refuseStorage();
    expect(setItem("seat", "abc")).toBe(false);
  });
});
