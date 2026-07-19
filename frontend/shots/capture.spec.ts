import { expect, Page, test } from "@playwright/test";

/**
 * Generates the screenshots shown on the front page.
 *
 * Everything here is the real app driven for real — a genuine room with genuine
 * players, not a mockup. A screenshot of a fake is a promise you have to keep
 * later.
 */

const OUT = "public/shots";

async function shot(page: Page, name: string) {
  await page.waitForTimeout(350); // let transitions settle
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

test("front page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shot(page, "site-home");
});

test("a game in progress, four players", async ({ page, browser }) => {
  await page.goto("/table");
  await page.getByRole("button", { name: /create game/i }).click();
  await page.getByPlaceholder(/your name/i).fill("Ada");
  await page.getByRole("button", { name: /create room/i }).click();
  await expect(page).toHaveURL(/\/table\/r\/[A-Z0-9]{5}/);
  const code = page.url().split("/").pop()!;

  // real opponents, so the seats and the log are genuine
  for (const name of ["Bram", "Cleo", "Dev"]) {
    const ctx = await browser.newContext();
    const p = await ctx.newPage();
    // the name has to be stored before the auto-join fires, or the player
    // joins under a generated one
    await p.goto("/table");
    await p.evaluate((n) => localStorage.setItem("table.name", n), name);
    await p.goto(`/table?join=${code}`);
    await expect(p).toHaveURL(new RegExp(`/table/r/${code}`), { timeout: 15_000 });
    await p.close();
    await ctx.close();
  }

  await page.getByRole("button", { name: /start/i }).first().click();
  await page.waitForTimeout(600);
  await shot(page, "table-player");

  // the shared table view, as one player's phone showing it
  await page.getByRole("button", { name: /menu/i }).click();
  await page.getByRole("button", { name: /show table view here/i }).click();
  await expect(page.locator(".tracker-bar")).toBeVisible({ timeout: 10_000 });
  await shot(page, "table-display");

  // commander damage, opened from a seat
  const grid = page.locator(".seat-cmd-grid").first();
  if (await grid.count()) {
    await grid.click();
    const panel = page.locator(".cmd-panel");
    if (await panel.isVisible().catch(() => false)) await shot(page, "table-commander");
  }
});

test("the organizer console", async ({ page }) => {
  const user = `shots${Date.now().toString(36)}`;
  await page.goto("/tournament");
  await page.getByRole("button", { name: /^sign up$/i }).click();
  await page.getByPlaceholder(/username/i).fill(user);
  await page.getByPlaceholder(/^password$/i).fill("a good long password");
  await page.getByRole("button", { name: /create account/i }).click();
  await page.getByRole("button", { name: /saved them/i }).click();
  await page.getByPlaceholder(/you@example/i).fill("organizer@example.com");
  await page.getByRole("button", { name: /save and continue/i }).click();
  await page.getByRole("button", { name: /new tournament/i }).click();
  await page.getByPlaceholder(/friday night/i).fill("Friday Night Commander");
  await page.getByRole("button", { name: /^create tournament$/i }).click();
  await expect(page).toHaveURL(/organize\/pods/, { timeout: 15_000 });

  await page.getByRole("link", { name: /roster/i }).click();
  await page.getByPlaceholder(/one name per line/i).fill(
    ["Ada", "Bram", "Cleo", "Dev", "Esme", "Finn", "Gus", "Hana"].join("\n"),
  );
  await page.getByRole("button", { name: /add players/i }).click();
  await expect(page.getByText("Ada")).toBeVisible({ timeout: 15_000 });

  await page.getByRole("link", { name: /pods/i }).click();
  await page.getByRole("button", { name: /start round 1/i }).click();
  await expect(page.getByText(/table 1/i)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /\+5 min|pause/i }).first().waitFor().catch(() => {});
  await shot(page, "tournament-console");

  await page.getByRole("link", { name: /standings/i }).click();
  await shot(page, "tournament-standings");
});
