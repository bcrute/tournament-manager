import { expect, test } from "@playwright/test";

test.describe("the public site", () => {
  test("front page presents the app and both ways in", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: /start a game/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /run a tournament/i })).toBeVisible();
  });

  test("navigation reaches the table", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /start a game/i }).click();
    await expect(page).toHaveURL(/\/table$/);
  });

  test("the entry point is never cached, so a deploy reaches the user", async ({ request }) => {
    // this project shipped a fortnight of invisible deploys because index.html
    // had no Cache-Control and browsers kept an old bundle
    const res = await request.get("/");
    expect(res.headers()["cache-control"]).toBe("no-cache");
  });

  test("a deep link is served the app, and is not cached either", async ({ request }) => {
    const res = await request.get("/table/r/ZZZZZ");
    expect(res.status()).toBe(200);
    expect(res.headers()["cache-control"]).toBe("no-cache");
  });

  test("hashed assets are cached hard", async ({ page, request }) => {
    await page.goto("/");
    const src = await page.locator("script[src*='/assets/']").first().getAttribute("src");
    const res = await request.get(src!);
    expect(res.headers()["cache-control"]).toContain("immutable");
  });

  test("the schema is not served in production mode", async ({ request }) => {
    const res = await request.get("/openapi.json");
    // the SPA fallback answers instead; what must not appear is a real schema
    expect(await res.text()).not.toContain('"paths"');
  });
});
