import { describe, expect, it } from "vitest";
import { ADMIN_SECTIONS, CONSOLE_SECTIONS, consolePath, SITE_NAV } from "./nav";

describe("navigation structure", () => {
  it("routes the organizer console per section", () => {
    expect(consolePath("AB123", "pods")).toBe("/tournament/AB123/organize/pods");
    expect(consolePath("AB123", "calls")).toBe("/tournament/AB123/organize/calls");
  });

  it("keeps every destination absolute so nav works from any depth", () => {
    for (const item of SITE_NAV) {
      expect(item.to.startsWith("/")).toBe(true);
    }
  });

  it("gives every entry an icon — the nav renders icon-first for language reasons", () => {
    for (const item of [...SITE_NAV, ...CONSOLE_SECTIONS, ...ADMIN_SECTIONS]) {
      expect(item.icon).toBeTruthy();
    }
  });

  it("has unique section ids, since they are URL segments", () => {
    const ids = CONSOLE_SECTIONS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    const adminIds = ADMIN_SECTIONS.map((s) => s.id);
    expect(new Set(adminIds).size).toBe(adminIds.length);
  });

  it("keeps the site nav short — past a handful it stops being navigation", () => {
    expect(SITE_NAV.length).toBeLessThanOrEqual(5);
  });
});
