import { expect, Page, test } from "@playwright/test";

/**
 * Press and hold one side of a control for `ms`. The hold starts running in
 * tens at 1000ms and repeats every 500ms, so 1700ms is reliably two steps —
 * comfortably clear of both the first at 1000 and the third at 2000.
 */
async function holdSide(page: Page, selector: string, ms: number) {
  // `hover()` rather than a computed centre: these cards are rotated, and
  // Playwright hit-tests the element for us instead of us doing the geometry
  // and landing on the neighbouring half.
  await page.locator(selector).hover();
  await page.mouse.down();
  await page.waitForTimeout(ms);
  await page.mouse.up();
}

/** Start a game and return the id an invitation carries. */
async function createRoom(page: Page, name: string) {
  await page.goto("/table");
  await page.getByRole("button", { name: /^create$/i }).click();
  await page.getByPlaceholder(/your name/i).fill(name);
  await page.getByRole("button", { name: /create room/i }).click();
  await expect(page).toHaveURL(/\/table\/r\/.+/);
  // The address is the invitation now: the five-character code in the bar is a
  // label the table can say out loud, and opens nothing.
  return page.url().split("/table/r/")[1];
}

test.describe("a game at the table", () => {
  test("a player creates a room and lands in it", async ({ page }) => {
    const roomId = await createRoom(page, "ada");
    // 128 bits in base64url, not five characters someone could walk
    expect(roomId).toMatch(/^[A-Za-z0-9_-]{16,}$/);
    // the five-character code is still shown, as a label to say out loud
    await expect(page.locator(".bar-code")).toBeVisible();
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
    await p2.goto(`/table#r/${code}`);
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
  test("the address is the invitation, and the code is only a label", async ({ page }) => {
    await page.goto("/table");
    await page.getByRole("button", { name: /^create$/i }).click();
    await page.getByPlaceholder(/your name/i).fill("ada");
    await page.getByRole("button", { name: /create room/i }).click();
    await expect(page).toHaveURL(/\/table\/r\/.+/);

    const roomId = page.url().split("/table/r/")[1];
    const code = (await page.locator(".bar-code").first().textContent())!.trim();

    // This asserted the opposite until the boundary moved: the address used to
    // be deliberately un-joinable and the five-character code was the
    // credential. A code that short is walkable, which is why it needed a
    // strike-and-ban mitigation to stand up. The address carries 128 bits now
    // and is the invitation; the code is a label the table says out loud.
    expect(roomId).toMatch(/^[A-Za-z0-9_-]{16,}$/);
    expect(roomId).not.toBe(code);
    expect(code).toMatch(/^[A-Z0-9]{5}$/);

    // and the code opens nothing
    const ctx = await page.context().browser()!.newContext();
    const stranger = await ctx.newPage();
    await stranger.goto(`/table#r/${code}`);
    await expect(stranger).not.toHaveURL(/\/table\/r\/.+/, { timeout: 5_000 });
    await ctx.close();
  });
});

test.describe("the commander damage grid", () => {
  test("is a miniature of the table, one square per seat", async ({ page, browser, isMobile }) => {
    await page.goto("/table");
    await page.getByRole("button", { name: /^create$/i }).click();
    await page.getByPlaceholder(/your name/i).fill("Ada");
    await page.getByRole("button", { name: /create room/i }).click();
    await page.waitForURL(/\/table\/r\/.+/);
    const code = page.url().split("/table/r/")[1];

    for (const n of ["Bram", "Cleo", "Dev"]) {
      const ctx = await browser.newContext();
      const p = await ctx.newPage();
      await p.goto("/table");
      await p.evaluate((x) => localStorage.setItem("table.name", x), n);
      await p.goto(`/table#r/${code}`);
      await expect(p).toHaveURL(/\/table\/r\/.+/, { timeout: 15_000 });
      await p.close();
      await ctx.close();
    }

    // wait for all four seats before starting, then for the game to actually
    // be under way — clicking straight through raced the joins
    await expect(page.locator(".tr-players li")).toHaveCount(4, { timeout: 15_000 });
    await page.getByRole("button", { name: /start/i }).first().click();
    await expect(page.getByRole("button", { name: /i lost some other way/i })).toBeVisible({
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

test.describe("dying happens to you", () => {
  test("zero life ends it without being asked, and can be argued with", async ({
    page,
    isMobile,
  }) => {
    const code = await createRoom(page, "ada");
    await page.getByRole("button", { name: /^start/i }).first().click();
    await expect(page.getByRole("button", { name: /i lost some other way/i })).toBeVisible({
      timeout: 15_000,
    });

    // nothing about dying on screen while comfortably alive
    await expect(page.getByRole("button", { name: /i.m not dead/i })).toHaveCount(0);

    // 20 life, gone in one hold: two steps of ten
    await holdSide(page, ".life-half.dec", 1_700);

    // the app decides, rather than waiting for the player to confirm it
    await expect(page.getByText(/you.re out/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/you hit 0 life/i)).toBeVisible();

    // the only player, so this death would end the game — and that is the one
    // that gets a countdown, because it is the one nobody can undo afterwards
    await expect(page.getByText(/game ends in \d+s/i)).toBeVisible({ timeout: 5_000 });

    await page.getByRole("button", { name: /i.m not dead/i }).click();

    // back in, still at zero, and the app has stopped calling that lethal —
    // without which the next −1 would kill them all over again
    await expect(page.getByText(/can.t lose the game/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/game ends in/i)).toHaveCount(0);
    await expect(page.getByRole("button", { name: /can lose again/i })).toBeVisible();

    await page.locator(".life-half.dec").click();
    await expect(page.getByText(/you.re out/i)).toHaveCount(0);
    void isMobile;
  });

  test("ten poison does it too, and the table can watch it coming", async ({ page }) => {
    await createRoom(page, "ada");
    await page.getByRole("button", { name: /^start/i }).first().click();
    await expect(page.getByRole("button", { name: /i lost some other way/i })).toBeVisible({
      timeout: 15_000,
    });

    const plus = page.getByRole("button", { name: /add a poison counter/i });
    for (let i = 0; i < 9; i++) await plus.click();
    // nine is not ten, and the app must not round up
    await expect(page.getByText(/you.re out/i)).toHaveCount(0);

    await plus.click();
    await expect(page.getByText(/you.re out/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/you hit 10 poison/i)).toBeVisible();
  });
});

/**
 * The shared table view, on both the devices that can show it.
 *
 * A dedicated display lies in the middle of the table; a player "keeping score"
 * shows the same view on their own phone without giving up their seat. They had
 * drifted apart in two ways nobody had a test for: the player's version flattened
 * every card to 0°, turning a table into a top-to-bottom list, and the server let
 * only a display or the host reorder seats — so a scorekeeper who wasn't the host
 * dragged a seat, watched it snap back, and got a 403 nothing surfaced.
 */
async function fourPlayerTable(page: Page, browser: import("@playwright/test").Browser) {
  await page.goto("/table");
  await page.getByRole("button", { name: /^create$/i }).click();
  await page.getByPlaceholder(/your name/i).fill("Ada");
  await page.getByRole("button", { name: /create room/i }).click();
  await page.waitForURL(/\/table\/r\/.+/);
  const code = page.url().split("/table/r/")[1];

  const contexts = [];
  const others: Record<string, Page> = {};
  for (const name of ["Bram", "Cleo", "Dev"]) {
    const ctx = await browser.newContext();
    const p = await ctx.newPage();
    await p.goto("/table");
    await p.evaluate((x) => localStorage.setItem("table.name", x), name);
    await p.goto(`/table#r/${code}`);
    await expect(p).toHaveURL(/\/table\/r\/.+/, { timeout: 15_000 });
    contexts.push(ctx);
    others[name] = p;
  }
  await expect(page.locator(".tr-players li")).toHaveCount(4, { timeout: 20_000 });
  await page.getByRole("button", { name: /^start/i }).first().click();
  return { code, contexts, others };
}

/** Switch a seated player to the shared table view. */
async function keepScore(p: Page, isMobile: boolean) {
  const menu = p.getByRole("button", { name: /menu/i });
  if (await menu.isVisible().catch(() => false)) await menu.click();
  await p.getByRole("button", { name: /show table view here/i }).click();
  await expect(p.locator(".tracker-bar")).toBeVisible({ timeout: 10_000 });
  void isMobile;
}

/** Rotation of every seat card, in degrees. */
async function seatRotations(p: Page): Promise<number[]> {
  await expect(p.locator(".seat-card").first()).toBeVisible({ timeout: 10_000 });
  return p.locator(".seat-card").evaluateAll((els) =>
    els.map((e) => {
      const m = getComputedStyle(e).transform.match(/matrix\(([^)]+)\)/);
      if (!m) return 0;
      const [a, b] = m[1].split(",").map(Number);
      return Math.round((Math.atan2(b, a) * 180) / Math.PI);
    }),
  );
}

test.describe("the shared table view", () => {
  test("faces each card at the player sitting there", async ({ page, browser, isMobile }) => {
    const { contexts } = await fourPlayerTable(page, browser);
    await keepScore(page, isMobile);

    // a table is people around an edge, not a list down a page: the seats down
    // each side are turned to face inwards
    const rots = await seatRotations(page);
    expect(rots.some((r) => r !== 0), `every seat was upright: [${rots}]`).toBe(true);
    expect(rots).toContain(90);
    expect(rots).toContain(-90);

    for (const c of contexts) await c.close();
  });

  test("a player keeping score can rearrange the table without being the host", async ({
    page,
    browser,
    isMobile,
  }) => {
    const { contexts, others } = await fourPlayerTable(page, browser);
    const bram = others["Bram"]; // seated, keeping score, and not the host
    await keepScore(bram, isMobile);

    const names = () => bram.locator(".seat-name").allInnerTexts();
    const before = await names();
    const a = (await bram.locator(".seat-card").nth(0).boundingBox())!;
    const b = (await bram.locator(".seat-card").nth(1).boundingBox())!;
    await bram.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
    await bram.mouse.down();
    await bram.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
    await bram.mouse.up();

    // it must stick rather than snap back — the seats are stored, not local
    await expect.poll(async () => (await names()).join(","), { timeout: 10_000 }).not.toBe(
      before.join(","),
    );
    // and it survives a reload, which is what proves the server took it rather
    // than the tiles having merely moved on this device
    const after = (await names()).join(",");
    await bram.reload();
    await expect(bram.locator(".tracker-bar")).toBeVisible({ timeout: 15_000 });
    await expect.poll(async () => (await names()).join(","), { timeout: 10_000 }).toBe(after);

    for (const c of contexts) await c.close();
  });
});

/**
 * Holding a side runs the total in tens.
 *
 * Going from 40 to 12 used to be twenty-eight taps. A tap still moves one; a
 * press that lasts a second starts repeating ten every half second until it is
 * released. The same gesture on both screens, so learning it once is enough.
 */
test.describe("holding to run in tens", () => {
  test("on your own life total", async ({ page }) => {
    await createRoom(page, "Ada");
    await page.getByRole("button", { name: /^start/i }).first().click();
    await expect(page.locator(".life-number")).toHaveText("20", { timeout: 15_000 });

    // a tap is still worth one
    await page.locator(".life-half.inc").click();
    await expect(page.locator(".life-number")).toHaveText("21", { timeout: 5_000 });

    // and a hold runs: two steps inside 1.7s
    await holdSide(page, ".life-half.dec", 1_700);
    await expect(page.locator(".life-number")).toHaveText("1", { timeout: 5_000 });

    // upwards too
    await holdSide(page, ".life-half.inc", 1_700);
    await expect(page.locator(".life-number")).toHaveText("21", { timeout: 5_000 });
  });

  test("a press shorter than a second is only a tap", async ({ page }) => {
    await createRoom(page, "Ada");
    await page.getByRole("button", { name: /^start/i }).first().click();
    await expect(page.locator(".life-number")).toHaveText("20", { timeout: 15_000 });

    await holdSide(page, ".life-half.dec", 600);
    // one, not ten — and not eleven either, which is what forgetting to
    // suppress the tap after a repeat would give
    await expect(page.locator(".life-number")).toHaveText("19", { timeout: 5_000 });
  });

  test("on someone else's seat, from the table view", async ({ page, browser, isMobile }) => {
    const { contexts } = await fourPlayerTable(page, browser);
    await keepScore(page, isMobile);

    const seatLife = () => page.locator(".seat-card").first().locator(".seat-life").innerText();
    await expect(page.locator(".seat-card").first().locator(".seat-life")).toHaveText("20", {
      timeout: 10_000,
    });

    // Target the half itself, not a screen-space guess: these cards are
    // rotated to face their players, so the "left" half of a card is not the
    // left of the screen. One step only — at zero the card shows a skull
    // instead of a number, which would tell us nothing about the arithmetic.
    await holdSide(page, ".seat-card >> nth=0 >> .seat-half.dec", 1_200);
    await expect.poll(async () => await seatLife(), { timeout: 10_000 }).toBe("10");

    await holdSide(page, ".seat-card >> nth=0 >> .seat-half.inc", 1_700);
    await expect.poll(async () => await seatLife(), { timeout: 10_000 }).toBe("30");

    for (const c of contexts) await c.close();
  });

  test("putting life back on a dead player brings them in again", async ({
    page,
    browser,
    isMobile,
  }) => {
    // this replaces the hold-for-a-menu that used to be the only way back
    const { contexts } = await fourPlayerTable(page, browser);
    await keepScore(page, isMobile);
    const first = page.locator(".seat-card").first();

    // run them to zero — the app eliminates them on its own
    await holdSide(page, ".seat-card >> nth=0 >> .seat-half.dec", 1_700);
    await expect(first).toHaveClass(/dead/, { timeout: 10_000 });

    // a tap on the giving side is enough to say they are not
    await page.locator(".seat-card").first().locator(".seat-half.inc").click();
    await expect(first).not.toHaveClass(/dead/, { timeout: 10_000 });

    for (const c of contexts) await c.close();
  });
});
