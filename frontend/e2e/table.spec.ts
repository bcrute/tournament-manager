import { expect, Page, test } from "@playwright/test";

/** Start a game and return its room code. */
async function createRoom(page: Page, name: string) {
  await page.goto("/table");
  await page.getByRole("button", { name: /create game/i }).click();
  await page.getByPlaceholder(/your name/i).fill(name);
  await page.getByRole("button", { name: /create room/i }).click();
  await expect(page).toHaveURL(/\/table\/r\/.+/);
  // the address bar carries an opaque id now, not the joinable code — read the
  // code from the page instead
  const code = (await page.locator(".bar-code").first().textContent())!.trim();
  return code;
}

test.describe("a game at the table", () => {
  test("a player creates a room and lands in it", async ({ page }) => {
    const code = await createRoom(page, "ada");
    expect(code).toMatch(/^[A-Z0-9]{5}$/);
    // the code shows in the bar and again in the lobby heading; either proves it
    await expect(page.getByText(code).first()).toBeVisible();
  });

  test("the menu offers the options a player actually has", async ({ page, isMobile }) => {
    await createRoom(page, "ada");
    // a hamburger is a phone affordance: on a pointer device the same actions
    // are simply shown, so there is nothing to open
    const trigger = page.getByRole("button", { name: /menu/i });
    if (isMobile) {
      await trigger.click();
    } else {
      await expect(trigger).toBeHidden();
    }
    // scope to the menu: the lobby has its own Rename control, which now has a
    // real accessible name since it stopped being a bare glyph
    const menu = page.locator(".bar-menu");
    await expect(menu.getByRole("button", { name: /rename/i })).toBeVisible();
    await expect(menu.getByRole("button", { name: /show table view here/i })).toBeVisible();
    await expect(menu.getByRole("button", { name: /use as table display/i })).toBeVisible();
    // present in the lobby too, not only mid-game: someone always arrives late
    await expect(menu.getByRole("button", { name: /show qr code/i })).toBeVisible();
    // no tournament entry in an ordinary room — it only belongs in a pod
    await expect(menu.getByRole("button", { name: /tournament standings/i })).toHaveCount(0);
    // and no "your games" while signed out, where it would lead to a wall
    await expect(menu.getByRole("button", { name: /your games/i })).toHaveCount(0);
  });

  test("a second player can join by code and both are seated", async ({ browser, page }) => {
    const code = await createRoom(page, "ada");

    const second = await browser.newContext();
    const p2 = await second.newPage();
    await p2.goto(`/table?join=${code}`);
    await expect(p2).toHaveURL(/\/table\/r\/.+/, { timeout: 15_000 });

    // the first player sees them arrive, without reloading
    await expect(page.getByText(/joined/i).first()).toBeVisible({ timeout: 15_000 });
    await second.close();
  });

  test("switching to the table view keeps the seat and can be switched back", async ({
    page,
    isMobile,
  }) => {
    await createRoom(page, "ada");
    if (isMobile) await page.getByRole("button", { name: /menu/i }).click();
    await page.getByRole("button", { name: /show table view here/i }).click();

    const back = page.getByRole("button", { name: /back to my view/i });
    await expect(back).toBeVisible({ timeout: 10_000 });
    // scope to the bar: the event log also mentions it, which would be ambiguous
    await expect(page.locator(".tracker-bar")).toContainText(/keeping score/i);

    await back.click();
    // back in the player view — assert on the bar itself, since a pointer
    // device has no menu button to look for
    await expect(page.locator(".room-bar")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".tracker-bar")).toHaveCount(0);
  });
});

test.describe("room addresses", () => {
  test("the address bar never carries the joinable code", async ({ page }) => {
    await page.goto("/table");
    await page.getByRole("button", { name: /create game/i }).click();
    await page.getByPlaceholder(/your name/i).fill("ada");
    await page.getByRole("button", { name: /create room/i }).click();
    await expect(page).toHaveURL(/\/table\/r\/.+/);

    const code = (await page.locator(".bar-code").first().textContent())!.trim();
    const urlId = page.url().split("/table/r/")[1];
    expect(code).toMatch(/^[A-Z0-9]{5}$/);
    // a screenshot of the address bar, or a link in someone's history, must not
    // hand over something that joins the game
    expect(urlId).not.toBe(code);
    expect(urlId.length).toBeGreaterThan(15);
  });
});

test.describe("the commander damage grid", () => {
  test("is a miniature of the table, one square per seat", async ({ page, browser, isMobile }) => {
    await page.goto("/table");
    await page.getByRole("button", { name: /create game/i }).click();
    await page.getByPlaceholder(/your name/i).fill("Ada");
    await page.getByRole("button", { name: /create room/i }).click();
    await page.waitForURL(/\/table\/r\/.+/);
    const code = (await page.locator(".bar-code").first().textContent())!.trim();

    for (const n of ["Bram", "Cleo", "Dev"]) {
      const ctx = await browser.newContext();
      const p = await ctx.newPage();
      await p.goto("/table");
      await p.evaluate((x) => localStorage.setItem("table.name", x), n);
      await p.goto(`/table?join=${code}`);
      await expect(p).toHaveURL(/\/table\/r\/.+/, { timeout: 15_000 });
      await p.close();
      await ctx.close();
    }

    // wait for all four seats before starting, then for the game to actually
    // be under way — clicking straight through raced the joins
    await expect(page.locator(".tr-players li")).toHaveCount(4, { timeout: 15_000 });
    await page.getByRole("button", { name: /start/i }).first().click();
    await expect(page.getByRole("button", { name: /i.m dead/i })).toBeVisible({
      timeout: 15_000,
    });

    if (isMobile) await page.getByRole("button", { name: /menu/i }).click();
    await page.getByRole("button", { name: /show table view here/i }).click();
    await expect(page.locator(".tracker-bar")).toBeVisible({ timeout: 10_000 });

    const grid = page.locator(".seat-cmd-grid").first();
    // one square per seat, including the card's own — a commander can be
    // turned against its owner
    await expect(grid.locator(".cmd-cell")).toHaveCount(4);
    await expect(grid.locator(".cmd-cell.own")).toHaveCount(1);

    // it must have real size: the sizing style was silently dropped once and
    // every square collapsed to zero while still being in the DOM
    const box = await grid.boundingBox();
    expect(box!.width).toBeGreaterThan(30);
    expect(box!.height).toBeGreaterThan(30);

    // and no seat numbers or names — position is the label
    await expect(grid).not.toContainText(/[A-Za-z]/);
  });
});

test.describe("cards that say you can't lose", () => {
  test("the offer appears only at a threshold, and silences it once taken", async ({
    page,
    isMobile,
  }) => {
    const code = await createRoom(page, "ada");
    expect(code).toMatch(/^[A-Z0-9]{5}$/);
    await page.getByRole("button", { name: /^start/i }).first().click();
    await expect(page.getByRole("button", { name: /i.m dead/i })).toBeVisible({
      timeout: 15_000,
    });

    // nothing on offer while the player is comfortably alive
    await expect(page.getByRole("button", { name: /i.m alive/i })).toHaveCount(0);

    // drop to zero — the app still doesn't kill anyone, it just stops nagging
    for (let i = 0; i < 4; i++) await page.getByRole("button", { name: "−5" }).click();
    await expect(page.getByRole("button", { name: /i.m alive/i })).toBeVisible({
      timeout: 10_000,
    });

    await page.getByRole("button", { name: /i.m alive/i }).click();
    await expect(page.getByText(/can.t lose the game/i).first()).toBeVisible({
      timeout: 10_000,
    });
    // and it can be handed back when the card leaves the battlefield
    await expect(page.getByRole("button", { name: /can lose again/i })).toBeVisible();
    void isMobile;
  });
});
