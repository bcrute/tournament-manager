import { describe, expect, it, vi } from "vitest";
import { goBack } from "./goBack";

describe("goBack", () => {
  it("returns to the previous page when there is one", () => {
    vi.spyOn(window.history, "length", "get").mockReturnValue(4);
    const navigate = vi.fn();
    goBack(navigate as never, "/table");
    expect(navigate).toHaveBeenCalledWith(-1);
  });

  it("falls back when the tab opened straight onto this URL", () => {
    // navigate(-1) with no history does nothing, leaving a dead button
    vi.spyOn(window.history, "length", "get").mockReturnValue(1);
    const navigate = vi.fn();
    goBack(navigate as never, "/table");
    expect(navigate).toHaveBeenCalledWith("/table", { replace: true });
  });

  it("replaces rather than pushes on the fallback, so back doesn't loop", () => {
    vi.spyOn(window.history, "length", "get").mockReturnValue(1);
    const navigate = vi.fn();
    goBack(navigate as never);
    expect(navigate).toHaveBeenCalledWith("/", { replace: true });
  });
});
