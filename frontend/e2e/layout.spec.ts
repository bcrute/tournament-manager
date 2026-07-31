import { expect, Page, test } from "@playwright/test";

/**
 * Layout regressions that actually shipped.
 *
 * Every case here is a real defect that reached production while every unit
 * test stayed green, because none of them are about behaviour — the controls
 * were rendered, wired, and reachable by a selector the whole time. They were
 * the wrong size, or on top of each other, or a screen apart. Only a browser
 * can see that.
 *
 * The recurring cause is worth naming: `table.css` is one flat stylesheet, so
 * two components that happen to use the same class name share rules whether
 * they mean to or not, and anything positioned near the room bar guesses an
 * offset. These tests pin the *relationships* each surface needs — this row is
 * a line not a thumb target, that panel clears the bar — rather than exact
 * pixels, so they survive design changes and still fail on a collision.
 */

/** A room with the host alone: enough for anything about the bar or the shell. */
async function soloRoom(page: Page) {
  await page.goto("/table");
  await page.getByRole("button", { name: /^create$/i }).click();
  await page.getByPlaceholder(/your name/i).fill("Ada");
  await page.getByRole("button", { name: /create room/i }).click();
  await page.waitForURL(/\/table\/r\/.+/);
  await expect(page.locator(".room-bar")).toBeVisible();
}

/** A real four-player game, for the things that are about a table. */
async function seatedRoom(page: Page, browser: import("@playwright/test").Browser) {
  await soloRoom(page);
  const code = (await page.locator(".bar-code").first().textContent())!.trim();
  for (const name of ["Bram", "Cleo", "Dev"]) {
    const ctx = await browser.newContext();
    const p = await ctx.newPage();
    await p.goto("/table");
    await p.evaluate((x) => localStorage.setItem("table.name", x), name);
    await p.goto(`/table?join=${code}`);
    await expect(p).toHaveURL(/\/table\/r\/.+/, { timeout: 15_000 });
    await p.close();
    await ctx.close();
  }
  await expect(page.locator(".tr-players li")).toHaveCount(4, { timeout: 20_000 });
  await page.getByRole("button", { name: /^start/i }).first().click();
  await expect(page.getByRole("button", { name: /i.m dead/i })).toBeVisible({ timeout: 15_000 });
}

/** Move to the shared table view this device can show without giving up its seat. */
async function showTableView(page: Page) {
  const menu = page.getByRole("button", { name: /menu/i });
  if (await menu.isVisible().catch(() => false)) await menu.click();
  await page.getByRole("button", { name: /show table view here/i }).click();
  await expect(page.locator(".tracker-bar")).toBeVisible({ timeout: 10_000 });
}

test.describe("the player's own screen", () => {
  test("commander damage stays a compact list, and does not push the exits away", async ({
    page,
    browser,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "a phone is where the fold is tightest");
    await seatedRoom(page, browser);

    await page.getByRole("button", { name: /commander damage/i }).click();
    const rows = page.locator(".cmd-row");
    await expect(rows).toHaveCount(4);

    // The table display's sheet uses this same class name. When its thumb-sized
    // min-height leaked here, every row grew to 64px, the +/- buttons stretched
    // into towers, and "I'm dead" was pushed off the bottom of the screen.
    for (let i = 0; i < 4; i++) {
      const box = (await rows.nth(i).boundingBox())!;
      expect(box.height, "a player's own damage row is a line, not a thumb target").toBeLessThan(52);
    }

    // the property that actually matters: everything is still reachable
    await expect(page.getByRole("button", { name: /i.m dead/i })).toBeInViewport();
    await expect(page.getByText(/commander damage is damage/i)).toBeInViewport();
  });
});

test.describe("the shared table view", () => {
  test("the damage sheet keeps rows a thumb can hit", async ({ page, browser }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "touch targets are a phone concern");
    await seatedRoom(page, browser);
    await showTableView(page);

    await page.locator(".seat-cmd-grid").first().click();
    const rows = page.locator(".cmd-panel .cmd-row");
    await expect(rows).toHaveCount(4);
    // the mirror of the test above: scoping the sheet's rules away from the
    // player's panel must not cost the sheet the size it was scoped for
    for (let i = 0; i < 4; i++) {
      const box = (await rows.nth(i).boundingBox())!;
      expect(box.height, "a row split into two tap halves needs a thumb").toBeGreaterThanOrEqual(44);
    }
  });

  test("the sheet's header sits on its rows, not a page-title's margin away", async ({
    page,
    browser,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "one viewport is enough for a gap");
    await seatedRoom(page, browser);
    await showTableView(page);
    await page.locator(".seat-cmd-grid").first().click();
    await expect(page.locator(".cmd-panel")).toBeVisible();

    // The global `header { margin-bottom: 2.5rem }` is meant for a page title.
    // Inside a card it put 40px of nothing under the heading, which read as a
    // phantom empty row above the first player.
    const header = (await page.locator(".cmd-panel header").boundingBox())!;
    const firstRow = (await page.locator(".cmd-panel .cmd-row").first().boundingBox())!;
    expect(firstRow.y - (header.y + header.height)).toBeLessThan(6);
  });

  test("every damage square shows its number, including zero", async ({ page, browser }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "the grid is the same at any width");
    await seatedRoom(page, browser);
    await showTableView(page);

    // a blank square reads as "no data"; the grid is a map of the table, and
    // every seat on it has a total even when that total is nothing yet
    const cells = page.locator(".seat-cmd-grid").first().locator(".cmd-cell");
    await expect(cells).toHaveCount(4);
    for (let i = 0; i < 4; i++) {
      await expect(cells.nth(i)).toHaveText(/^\d+$/);
    }
  });
});

test.describe("the room bar", () => {
  test("keeps the room code and name clear of its own menu", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "the menu is only inline on a pointer device");
    await soloRoom(page);

    // Past 60rem the menu stops being a dropdown and lays itself along the bar.
    // It used to run straight over the code and truncate the player's name.
    const name = (await page.locator(".bar-name").boundingBox())!;
    const menu = (await page.locator(".bar-menu").boundingBox())!;
    const overlaps = name.x < menu.x + menu.width && menu.x < name.x + name.width;
    expect(overlaps, "the inline menu is sitting on top of the player's name").toBe(false);
  });

  test("is never covered by what floats beneath it", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "the bar is fixed to the top on a phone");
    await soloRoom(page);
    await page.getByRole("button", { name: /^start/i }).first().click();

    // Starting announces who goes first. That toast is fixed-positioned and
    // offset from the top by hand: the offset was a guess (3.2rem) against a
    // bar that is 3.65rem, so it covered the room code and the way out.
    //
    // Polled rather than measured once: the toast slides in from above, so its
    // resting position is the claim, not wherever it is mid-animation.
    const toast = page.locator(".toast").first();
    await expect(toast).toBeVisible({ timeout: 15_000 });
    await expect
      .poll(
        async () => {
          const bar = await page.locator(".room-bar").boundingBox();
          const box = await toast.boundingBox();
          if (!bar || !box) return -1;
          return Math.round(box.y - (bar.y + bar.height));
        },
        { timeout: 5_000, message: "a toast settles on top of the room bar" },
      )
      .toBeGreaterThanOrEqual(0);
  });
});

test.describe("the shell's content column", () => {
  test("the front page is the same width as the play surfaces", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "the two only diverge once there is room");

    // These drifted apart: the site went to 80% of the viewport while the play
    // shell stayed capped, so walking from the front page to /table narrowed
    // the content by a few hundred pixels and read as two different sites.
    // They share a declaration now; this is what stops it separating again.
    await page.goto("/");
    const site = (await page.locator("main.site-body").boundingBox())!;

    await page.goto("/table");
    const play = (await page.locator("main.play-body").boundingBox())!;

    expect(Math.round(site.width), "front page vs table page width").toBe(
      Math.round(play.width),
    );
    expect(Math.round(site.x), "the two columns start at the same edge").toBe(
      Math.round(play.x),
    );
  });

  test("neither one lets the page scroll sideways on a phone", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "horizontal overflow is a phone problem");
    for (const path of ["/", "/table", "/account"]) {
      await page.goto(path);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} scrolls sideways`).toBeLessThanOrEqual(1);
    }
  });
});
