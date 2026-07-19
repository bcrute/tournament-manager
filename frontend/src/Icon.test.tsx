import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Icon, { ICON_NAMES } from "./Icon";

afterEach(cleanup);

describe("Icon", () => {
  it("renders every registered icon", () => {
    for (const name of ICON_NAMES) {
      const { container } = render(<Icon name={name} />);
      expect(container.querySelector("svg"), name).toBeTruthy();
      cleanup();
    }
  });

  it("inherits colour so themes can restyle it", () => {
    const { container } = render(<Icon name="heart" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    // no hardcoded fills would survive a theme change
    expect(svg.getAttribute("fill")).toBe("none");
  });

  it("is hidden from screen readers when text sits beside it", () => {
    const { container } = render(<Icon name="book" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.getAttribute("role")).toBeNull();
  });

  it("announces itself when it stands alone", () => {
    const { container } = render(<Icon name="hand" label="Call an official" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("role")).toBe("img");
    expect(svg.getAttribute("aria-label")).toBe("Call an official");
    expect(svg.getAttribute("aria-hidden")).toBeNull();
  });

  it("scales", () => {
    const { container } = render(<Icon name="crown" size={40} />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("40");
    expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
  });

  it("keeps every glyph on the same grid", () => {
    for (const name of ICON_NAMES) {
      const { container } = render(<Icon name={name} />);
      expect(container.querySelector("svg")!.getAttribute("viewBox"), name).toBe("0 0 24 24");
      cleanup();
    }
  });
});
