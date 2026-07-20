import { expect, Page, test } from "@playwright/test";

/**
 * Table shapes other than four.
 *
 * Four players is the only arrangement that is a clean 2x2, and it was the only
 * one I checked when building the damage grid. Odd counts add a bottom seat
 * spanning both columns, and seven makes the grid four rows deep — the cases
 * where a miniature of the table is most likely to spill out of a card or
 * collapse.
 *
 * One viewport is enough: this is about layout arithmetic, not input.
 */


const NAMES = ["Ada", "Bram", "Cleo", "Dev", "Esme", "Finn", "Gus", "Hana", "Iris"];

async function table(page: Page, browser: import("@playwright/test").Browser, n: number) {
  await page.goto("/table");
  await page.getByRole("button", { name: /create game/i }).click();
  await page.getByPlaceholder(/your name/i).fill(NAMES[0]);
  await page.getByRole("button", { name: /create room/i }).click();
  await page.waitForURL(/\/table\/r\/.+/);
  const code = (await page.locator(".bar-code").first().textContent())!.trim();
  for (const name of NAMES.slice(1, n)) {
    const ctx = await browser.newContext();
    const p = await ctx.newPage();
    await p.goto("/table");
    await p.evaluate((x) => localStorage.setItem("table.name", x), name);
    await p.goto(`/table?join=${code}`);
    await expect(p).toHaveURL(/\/table\/r\/.+/, { timeout: 15_000 });
    await p.close();
    await ctx.close();
  }
  await expect(page.locator(".tr-players li")).toHaveCount(n, { timeout: 20_000 });
  await page.getByRole("button", { name: /start/i }).first().click();
  await expect(page.getByRole("button", { name: /i.m dead/i })).toBeVisible({ timeout: 15_000 });
  const menu = page.getByRole("button", { name: /menu/i });
  if (await menu.isVisible().catch(() => false)) await menu.click();
  await page.getByRole("button", { name: /show table view here/i }).click();
  await expect(page.locator(".tracker-bar")).toBeVisible({ timeout: 10_000 });
}

for (const n of [2, 3, 5, 6]) {
  test(`the damage grid holds up with ${n} players`, async ({ page, browser }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "layout arithmetic; one viewport suffices");
    await table(page, browser, n);

    const grids = page.locator(".seat-cmd-grid");
    await expect(grids).toHaveCount(n);

    for (let i = 0; i < n; i++) {
      const g = grids.nth(i);
      // one square per seat, exactly one of them the card's own
      await expect(g.locator(".cmd-cell")).toHaveCount(n);
      await expect(g.locator(".cmd-cell.own")).toHaveCount(1);

      // it must have real size, and stay inside its card
      const gb = (await g.boundingBox())!;
      const cb = (await page.locator(".seat-card").nth(i).boundingBox())!;
      expect(gb.width, `grid ${i} width`).toBeGreaterThan(20);
      expect(gb.height, `grid ${i} height`).toBeGreaterThan(20);
      expect(gb.x, `grid ${i} left edge`).toBeGreaterThanOrEqual(cb.x - 2);
      expect(gb.y, `grid ${i} top edge`).toBeGreaterThanOrEqual(cb.y - 2);
      expect(gb.x + gb.width, `grid ${i} right edge`).toBeLessThanOrEqual(cb.x + cb.width + 2);
      expect(gb.y + gb.height, `grid ${i} bottom edge`).toBeLessThanOrEqual(cb.y + cb.height + 2);
    }
    await page.screenshot({ path: `/tmp/players-${n}.png` });
  });
}

test("seven players falls back rather than showing an unreadable grid", async ({
  page,
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "layout arithmetic; one viewport suffices");
  await table(page, browser, 7);

  // no cards at all — this is a refusal, not a squeeze
  await expect(page.locator(".seat-card")).toHaveCount(0);
  await expect(page.locator(".display-toomany")).toBeVisible();
  await expect(page.getByText(/too many for one screen/i)).toBeVisible();

  // but every player is still accounted for, with their life
  await expect(page.locator(".display-compact li")).toHaveCount(7);
  await page.screenshot({ path: "/tmp/players-7-refused.png" });
});

test("six players still gets the full table view", async ({ page, browser }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "layout arithmetic; one viewport suffices");
  await table(page, browser, 6);
  // the boundary is inclusive: six is supported, seven is not
  await expect(page.locator(".seat-card")).toHaveCount(6);
  await expect(page.locator(".display-toomany")).toHaveCount(0);
});
