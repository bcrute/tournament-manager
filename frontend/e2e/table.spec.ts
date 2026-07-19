import { expect, Page, test } from "@playwright/test";

/** Start a game and return its room code. */
async function createRoom(page: Page, name: string) {
  await page.goto("/table");
  await page.getByRole("button", { name: /create game/i }).click();
  await page.getByPlaceholder(/your name/i).fill(name);
  await page.getByRole("button", { name: /create room/i }).click();
  await expect(page).toHaveURL(/\/table\/r\/[A-Z0-9]{5}/);
  return page.url().split("/").pop()!;
}

test.describe("a game at the table", () => {
  test("a player creates a room and lands in it", async ({ page }) => {
    const code = await createRoom(page, "ada");
    expect(code).toMatch(/^[A-Z0-9]{5}$/);
    // the code shows in the bar and again in the lobby heading; either proves it
    await expect(page.getByText(code).first()).toBeVisible();
  });

  test("the menu offers the options a player actually has", async ({ page }) => {
    await createRoom(page, "ada");
    await page.getByRole("button", { name: /menu/i }).click();
    // scope to the menu: the lobby has its own Rename control, which now has a
    // real accessible name since it stopped being a bare glyph
    const menu = page.locator(".bar-menu");
    await expect(menu.getByRole("button", { name: /rename/i })).toBeVisible();
    await expect(menu.getByRole("button", { name: /show table view here/i })).toBeVisible();
    await expect(menu.getByRole("button", { name: /use as table display/i })).toBeVisible();
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
    await expect(p2).toHaveURL(new RegExp(`/table/r/${code}`), { timeout: 15_000 });

    // the first player sees them arrive, without reloading
    await expect(page.getByText(/joined/i).first()).toBeVisible({ timeout: 15_000 });
    await second.close();
  });

  test("switching to the table view keeps the seat and can be switched back", async ({ page }) => {
    await createRoom(page, "ada");
    await page.getByRole("button", { name: /menu/i }).click();
    await page.getByRole("button", { name: /show table view here/i }).click();

    const back = page.getByRole("button", { name: /back to my view/i });
    await expect(back).toBeVisible({ timeout: 10_000 });
    // scope to the bar: the event log also mentions it, which would be ambiguous
    await expect(page.locator(".tracker-bar")).toContainText(/keeping score/i);

    await back.click();
    await expect(page.getByRole("button", { name: /menu/i })).toBeVisible({ timeout: 10_000 });
  });
});
