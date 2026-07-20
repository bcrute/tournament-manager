import { expect, Page, test } from "@playwright/test";

const pw = "a good long password";
const uniq = () => `org${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;

async function signUpOrganizer(page: Page, username: string) {
  await page.goto("/tournament");
  await page.getByRole("button", { name: /^sign up$/i }).click();
  await page.getByPlaceholder(/username/i).fill(username);
  await page.getByPlaceholder(/^password$/i).fill(pw);
  await page.getByRole("button", { name: /create account/i }).click();
  // recovery codes are shown once and must be acknowledged
  await expect(page.getByText(/save your recovery codes/i)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /saved them/i }).click();
}

test.describe("hosting a tournament", () => {
  test("an organizer signs up, is asked for an email, and creates an event", async ({ page }) => {
    await signUpOrganizer(page, uniq());

    // hosting is the one place an email is required, and it says why
    await expect(page.getByText(/needs an email address/i)).toBeVisible({ timeout: 15_000 });
    await page.getByPlaceholder(/you@example/i).fill("org@example.com");
    await page.getByRole("button", { name: /save and continue/i }).click();

    await expect(page.getByRole("heading", { name: /your tournaments/i })).toBeVisible({
      timeout: 15_000,
    });
    await page.getByRole("button", { name: /new tournament/i }).click();
    await page.getByPlaceholder(/friday night/i).fill("E2E Open");
    await page.getByRole("button", { name: /^create tournament$/i }).click();

    await expect(page).toHaveURL(/\/tournament\/[A-Z0-9]{5}\/organize\/pods/, {
      timeout: 15_000,
    });
    await expect(page.getByRole("heading", { name: "E2E Open" })).toBeVisible();
  });

  test("the console has real sections that survive a reload", async ({ page }) => {
    await signUpOrganizer(page, uniq());
    await page.getByPlaceholder(/you@example/i).fill("org@example.com");
    await page.getByRole("button", { name: /save and continue/i }).click();
    await page.getByRole("button", { name: /new tournament/i }).click();
    await page.getByPlaceholder(/friday night/i).fill("Sections");
    await page.getByRole("button", { name: /^create tournament$/i }).click();
    await expect(page).toHaveURL(/organize\/pods/, { timeout: 15_000 });

    await page.getByRole("link", { name: /standings/i }).click();
    await expect(page).toHaveURL(/organize\/standings/);

    // a section is a route: reloading keeps the organizer where they were
    await page.reload();
    await expect(page).toHaveURL(/organize\/standings/);
    await expect(page.getByRole("heading", { name: /standings/i })).toBeVisible();
  });

  test("a roster is added and the round plan appears with its provenance", async ({ page }) => {
    await signUpOrganizer(page, uniq());
    await page.getByPlaceholder(/you@example/i).fill("org@example.com");
    await page.getByRole("button", { name: /save and continue/i }).click();
    await page.getByRole("button", { name: /new tournament/i }).click();
    await page.getByPlaceholder(/friday night/i).fill("Planned");
    await page.getByRole("button", { name: /^create tournament$/i }).click();
    await expect(page).toHaveURL(/organize\/pods/, { timeout: 15_000 });

    await page.getByRole("link", { name: /roster/i }).click();
    await page.getByPlaceholder(/one name per line/i).fill(
      ["ada", "bram", "cleo", "dev", "esme", "finn", "gus", "hana"].join("\n"),
    );
    await page.getByRole("button", { name: /add players/i }).click();
    await expect(page.getByText("ada")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("link", { name: /pods/i }).click();
    const plan = page.locator(".tq-plan");
    await expect(plan).toBeVisible({ timeout: 15_000 });
    await expect(plan).toContainText("8");
    // provenance must always be stated: either sourced to a document, or
    // labelled a convention. Never a bare number.
    await expect(plan).toContainText(/per .+|convention/i);
    // and a pods event must be advised from a pods structure, not the 1v1 table
    await expect(plan).toContainText(/swiss round/i);
  });

  test("opening a round seats everyone, and a player is carried to their table", async ({
    page,
    browser,
  }) => {
    await signUpOrganizer(page, uniq());
    await page.getByPlaceholder(/you@example/i).fill("org@example.com");
    await page.getByRole("button", { name: /save and continue/i }).click();
    await page.getByRole("button", { name: /new tournament/i }).click();
    await page.getByPlaceholder(/friday night/i).fill("Live");
    await page.getByRole("button", { name: /^create tournament$/i }).click();
    await expect(page).toHaveURL(/organize\/pods/, { timeout: 15_000 });
    const code = page.url().split("/tournament/")[1].split("/")[0];

    await page.getByRole("link", { name: /roster/i }).click();
    await page.getByPlaceholder(/one name per line/i).fill("ada\nbram\ncleo\ndev");
    await page.getByRole("button", { name: /add players/i }).click();
    await expect(page.getByText("ada")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("link", { name: /pods/i }).click();
    await page.getByRole("button", { name: /start round 1/i }).click();
    await expect(page.getByText(/table 1/i)).toBeVisible({ timeout: 15_000 });

    // a player, on their own phone, with no account at all
    const ctx = await browser.newContext();
    const player = await ctx.newPage();
    await player.goto(`/tournament/${code}`);
    await player.getByRole("button", { name: "ada", exact: false }).first().click();
    // checking in routes them into their pod's room without typing a code
    await expect(player).toHaveURL(/\/table\/r\/.+/, { timeout: 20_000 });

    // and the round clock reaches them there
    await expect(player.locator(".round-clock")).toBeVisible({ timeout: 15_000 });

    // standings live behind the menu, not in their way
    const menuBtn = player.getByRole("button", { name: /menu/i });
    if (await menuBtn.isVisible().catch(() => false)) await menuBtn.click();
    await player.getByRole("button", { name: /tournament standings/i }).click();
    await expect(player.getByText(/won–drew–lost/i)).toBeVisible({ timeout: 15_000 });
    await ctx.close();
  });
});
