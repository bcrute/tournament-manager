import { describe, expect, it } from "vitest";
import {
  ACCOUNT_SECTIONS,
  accountNavItem,
  accountPath,
  ADMIN_SECTIONS,
  CONSOLE_SECTIONS,
  consolePath,
  SITE_NAV,
} from "./nav";

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

  it("advertises the account area, which was reachable but unlinked before", () => {
    expect(SITE_NAV.some((n) => n.to === "/account" && n.listed)).toBe(true);
  });
});

describe("the account entry", () => {
  it("offers a visitor both actions, not just signing in", () => {
    // "Sign in" alone was the old label, and it never told anyone an account
    // was something they could make — which is how the app went this long
    // with no sign-up link anywhere.
    const label = accountNavItem(null).label;
    expect(label).toMatch(/sign up/i);
    expect(label).toMatch(/sign in/i);
  });

  it("says who you are once you are signed in", () => {
    expect(accountNavItem("ada").label).toBe("ada");
  });

  it("points at the same place either way, so the route never forks", () => {
    expect(accountNavItem(null).to).toBe("/account");
    expect(accountNavItem("ada").to).toBe("/account");
  });
});

describe("account sections", () => {
  it("keeps the overview at the bare path, so /account is never a redirect", () => {
    expect(accountPath("overview")).toBe("/account");
  });

  it("routes the rest as segments, so each one is bookmarkable", () => {
    expect(accountPath("games")).toBe("/account/games");
    expect(accountPath("notes")).toBe("/account/notes");
    expect(accountPath("settings")).toBe("/account/settings");
  });

  it("has unique ids, since they are URL segments", () => {
    const ids = ACCOUNT_SECTIONS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("gives every section an icon, like every other nav list", () => {
    for (const s of ACCOUNT_SECTIONS) expect(s.icon).toBeTruthy();
  });
});
