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
    // reachable from the nav and the footer; either proves the point
    await page.getByRole("link", { name: /^privacy$/i }).first().click();
    await expect(page).toHaveURL(/\/privacy$/);
    await expect(page.getByRole("heading", { name: /privacy/i })).toBeVisible();
    await expect(page.getByText(/no cookie banner/i).first()).toBeVisible();
    await expect(page.locator(".privacy-table")).toBeVisible();
  });
});

test.describe("browser-enforced policy", () => {
  test("a strict CSP doesn't break the app", async ({ page }) => {
    // a policy that silently blocks the app's own assets is worse than none —
    // it fails at runtime, in a browser, long after the tests passed
    const violations: string[] = [];
    page.on("console", (m) => {
      const text = m.text();
      if (/content security policy|refused to/i.test(text)) violations.push(text);
    });
    page.on("pageerror", (e) => violations.push(String(e)));

    await page.goto("/");
    await page.goto("/table");
    await page.getByRole("button", { name: /create game/i }).click();
    await page.getByPlaceholder(/your name/i).fill("ada");
    await page.getByRole("button", { name: /create room/i }).click();
    await page.waitForURL(/\/table\/r\/.+/);
    // the websocket has to survive connect-src 'self'
    await expect(page.locator(".room-bar")).toBeVisible();
    if (test.info().project.use.isMobile) {
      await page.getByRole("button", { name: /menu/i }).click();
    }
    await page.getByRole("button", { name: /show qr code/i }).click();
    await expect(page.locator(".qr-holder")).toBeVisible();

    expect(violations, `CSP/runtime errors: ${violations.join(" | ")}`).toEqual([]);
  });

  test("the policy actually blocks a third-party load", async ({ page }) => {
    await page.goto("/");
    const blocked = await page.evaluate(async () => {
      try {
        await fetch("https://example.com/beacon", { mode: "no-cors" });
        return false; // the policy let it through
      } catch {
        return true;
      }
    });
    expect(blocked, "connect-src 'self' should stop an off-origin beacon").toBe(true);
  });
});
