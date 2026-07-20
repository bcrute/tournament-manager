import { expect, test } from "@playwright/test";

/**
 * "We don't need a cookie banner" is only true while nothing non-essential is
 * stored and nothing third-party is fetched. Both are easy to break by adding
 * one convenient library, so both are asserted.
 */
test.describe("privacy posture", () => {
  test("no third-party requests are made anywhere in a session", async ({ page }) => {
    const foreign: string[] = [];
    const ownHost = new URL(test.info().project.use.baseURL!).host;
    page.on("request", (r) => {
      const url = r.url();
      if (url.startsWith("data:") || url.startsWith("blob:")) return;
      if (new URL(url).host !== ownHost) foreign.push(url);
    });

    await page.goto("/");
    await page.goto("/privacy");
    await page.goto("/table");
    await page.getByRole("button", { name: /create game/i }).click();
    await page.getByPlaceholder(/your name/i).fill("ada");
    await page.getByRole("button", { name: /create room/i }).click();
    await page.waitForURL(/\/table\/r\//);

    expect(foreign, `third-party requests: ${foreign.join(", ")}`).toEqual([]);
  });

  test("a signed-out player is given no cookies at all", async ({ page, context }) => {
    await page.goto("/table");
    await page.getByRole("button", { name: /create game/i }).click();
    await page.getByPlaceholder(/your name/i).fill("ada");
    await page.getByRole("button", { name: /create room/i }).click();
    await page.waitForURL(/\/table\/r\//);

    // playing needs no account, so it should need no cookie either
    expect(await context.cookies()).toEqual([]);
  });

  test("the app still works when storage is refused", async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    // deny localStorage the way a hardened browser does
    await page.addInitScript(() => {
      const deny = () => {
        throw new DOMException("denied");
      };
      Object.defineProperty(window, "localStorage", {
        configurable: true,
        get: () => ({ getItem: deny, setItem: deny, removeItem: deny, clear: deny }),
      });
    });

    await page.goto("/table");
    await page.getByRole("button", { name: /create game/i }).click();
    await page.getByPlaceholder(/your name/i).fill("ada");
    await page.getByRole("button", { name: /create room/i }).click();
    // the room is created server-side before anything is stored; an unguarded
    // write threw here and stranded the player
    await expect(page).toHaveURL(/\/table\/r\/.+/, { timeout: 15_000 });
    await ctx.close();
  });

  test("the privacy page lists what is stored, and is reachable", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /^privacy$/i }).click();
    await expect(page).toHaveURL(/\/privacy$/);
    await expect(page.getByRole("heading", { name: /privacy/i })).toBeVisible();
    await expect(page.getByText(/no cookie banner/i).first()).toBeVisible();
    await expect(page.locator(".privacy-table")).toBeVisible();
  });
});
