import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { classifyFetchError } from "./fetchPolicy";

describe("classifyFetchError", () => {
  it("treats a missing room or lost seat as gone", () => {
    for (const status of [403, 404, 410]) {
      expect(classifyFetchError(new ApiError(status, "nope"), true)).toBe("gone");
      expect(classifyFetchError(new ApiError(status, "nope"), false)).toBe("gone");
    }
  });

  it("rides out a server restart when a game is on screen (deploy mid-game)", () => {
    expect(classifyFetchError(new ApiError(502, "bad gateway"), true)).toBe("transient");
    expect(classifyFetchError(new ApiError(500, "boom"), true)).toBe("transient");
  });

  it("rides out a network drop when a game is on screen", () => {
    expect(classifyFetchError(new TypeError("Failed to fetch"), true)).toBe("transient");
  });

  it("surfaces the error when there is nothing to show yet", () => {
    expect(classifyFetchError(new ApiError(502, "bad gateway"), false)).toBe("fatal");
    expect(classifyFetchError(new TypeError("Failed to fetch"), false)).toBe("fatal");
  });
});
