import { expect, test } from "@playwright/test";

/**
 * Navigation is the same on every surface.
 *
 * The app used to answer "where is navigation?" three ways — a top bar on the
 * site, duplicated markup plus a bottom tab strip in the play shell, and
 * nothing at all in the organizer console. These run on both the mobile and
 * desktop projects, so "a row on a laptop, a hamburger on a phone" is asserted
 * rather than assumed.
 */

const SURFACES = ["/", "/privacy", "/table", "/tournament"];

test.describe("one navigation bar, everywhere", () => {
  for (const path of SURFACES) {
    test(`${path} carries exactly one site nav`, async ({ page }) => {
      await page.goto(path);
      await expect(page.locator("nav.app-nav")).toHaveCount(1);
      // the logo is part of the same bar, so every surface can get home
      await expect(page.locator(".app-bar .site-logo")).toHaveCount(1);
    });
  }

  test("a phone gets a hamburger; a laptop gets the links", async ({ page, isMobile }) => {
    await page.goto("/");
    const nav = page.locator("nav.app-nav");
    const trigger = page.getByRole("button", { name: /site menu/i });

    if (isMobile) {
      await expect(trigger).toBeVisible();
      await expect(nav).toBeHidden();
      await trigger.click();
      await expect(nav).toBeVisible();
      await expect(page.getByRole("link", { name: "Tournaments" })).toBeVisible();
    } else {
      // a hamburger on a screen with room to spare hides things that fit
      await expect(trigger).toBeHidden();
      await expect(nav).toBeVisible();
      await expect(page.getByRole("link", { name: "Tournaments" })).toBeVisible();
    }
  });

  test("the site menu closes on Escape and hands focus back", async ({ page, isMobile }) => {
    test.skip(!isMobile, "there is no menu to close on a pointer device");
    await page.goto("/");
    const trigger = page.getByRole("button", { name: /site menu/i });
    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    await page.keyboard.press("Escape");
    await expect(page.locator("nav.app-nav")).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("following a link closes the menu behind it", async ({ page, isMobile }) => {
    test.skip(!isMobile, "the menu is always open on a pointer device");
    await page.goto("/");
    await page.getByRole("button", { name: /site menu/i }).click();
    // scoped to the bar: the footer links to /privacy too
    await page.locator("nav.app-nav").getByRole("link", { name: "Privacy" }).click();
    await page.waitForURL(/\/privacy/);
    // nothing else would close it — the bar never unmounts between routes
    await expect(page.locator("nav.app-nav")).toBeHidden();
  });

  test("the organizer console is not a dead end", async ({ page }) => {
    // reaching a real console needs an account; the loading/denied state is the
    // same chrome and is what a stranded organizer would actually see
    await page.goto("/tournament/ZZZZZ/organize/pods");
    await expect(page.locator("nav.app-nav")).toHaveCount(1);
  });
});
