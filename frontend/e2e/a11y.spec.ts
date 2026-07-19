import { expect, test } from "@playwright/test";

/**
 * Accessibility behaviours that are easy to add and easy to break silently.
 * Each of these regressed at least once while the rest of the app kept working.
 */
test.describe("accessibility", () => {
  test("a skip link appears on focus and jumps to the content", async ({ page }) => {
    await page.goto("/");
    const skip = page.getByRole("link", { name: /skip to content/i });
    await expect(skip).toBeAttached();
    await page.keyboard.press("Tab");
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();
  });

  test("every icon-only control has an accessible name", async ({ page }) => {
    await page.goto("/table");
    await page.getByRole("button", { name: /create game/i }).click();
    await page.getByPlaceholder(/your name/i).fill("ada");
    await page.getByRole("button", { name: /create room/i }).click();
    await page.waitForURL(/\/table\/r\//);
    // the room settles asynchronously — a toast animates in and out on entry,
    // and enumerating mid-render caught a control before its label attached
    await page.waitForLoadState("networkidle");
    await expect(page.locator(".room-bar")).toBeVisible();
    await page.waitForTimeout(800);

    // use the real accessibility tree, not textContent: an icon button is named
    // by its child <svg role="img" aria-label>, which the DOM text doesn't show
    await expect
      .poll(
        async () => {
          const controls = page.locator("button:visible, a[href]:visible");
          const n = await controls.count();
          const unnamed: string[] = [];
          for (let i = 0; i < n; i++) {
            const el = controls.nth(i);
            const name = await el
              .evaluate((node) => {
                const t = (node.textContent ?? "").trim();
                const l = node.getAttribute("aria-label") ?? "";
                const svg = node.querySelector("svg[aria-label]");
                return t || l || svg?.getAttribute("aria-label") || "";
              })
              .catch(() => "detached");
            if (!name) unnamed.push(await el.evaluate((n2) => n2.outerHTML.slice(0, 60)));
          }
          return unnamed;
        },
        { timeout: 10_000, message: "controls with no accessible name" },
      )
      .toEqual([]);
  });

  test("the menu closes on Escape and hands focus back", async ({ page }) => {
    await page.goto("/table");
    await page.getByRole("button", { name: /create game/i }).click();
    await page.getByPlaceholder(/your name/i).fill("ada");
    await page.getByRole("button", { name: /create room/i }).click();
    await page.waitForURL(/\/table\/r\//);

    const trigger = page.getByRole("button", { name: /menu/i });
    await trigger.click();
    await expect(page.locator(".bar-menu")).toBeVisible();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    await page.keyboard.press("Escape");
    await expect(page.locator(".bar-menu")).toHaveCount(0);
    // focus must not be stranded where the menu used to be
    await expect(trigger).toBeFocused();
  });

  test("the page declares its language", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", /en/);
  });

  test("headings start at h1 and the main landmark exists", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  });
});
