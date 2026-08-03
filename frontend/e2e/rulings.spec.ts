import { expect, test } from "@playwright/test";

/**
 * Looking up a ruling, in a browser, against the real server.
 *
 * Card data comes from a fixture through the same seam the live Scryfall
 * client implements (`TABLE_SCRYFALL_FIXTURE`, wired in playwright.config.ts),
 * so these exercise the production request path without depending on somebody
 * else's uptime for our suite to pass.
 *
 * The premise of the feature is three letters and a tap while four people
 * wait, so that is what these measure.
 */

test.describe("card rulings", () => {
  test("three letters and a tap gets you the ruling", async ({ page }) => {
    await page.goto("/rulings");

    // no sign-in, no room, no tournament — it is a play aid
    await expect(page.getByRole("heading", { name: /card rulings/i })).toBeVisible();

    const box = page.getByPlaceholder(/start typing a card name/i);
    await box.fill("lightn");
    await page.getByRole("option", { name: "Lightning Bolt" }).click();

    await expect(page.getByRole("heading", { name: "Lightning Bolt" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/any target means any creature/i)).toBeVisible();
  });

  test("the search box has focus on arrival", async ({ page }) => {
    // Someone opening this page is mid-argument. Making them tap the box first
    // is a tap that buys nothing.
    await page.goto("/rulings");
    await expect(page.getByPlaceholder(/start typing a card name/i)).toBeFocused();
  });

  test("a word from the middle of the name finds it", async ({ page }) => {
    await page.goto("/rulings");
    await page.getByPlaceholder(/start typing a card name/i).fill("feast");
    await expect(
      page.getByRole("option", { name: "Sword of Feast and Famine" }),
    ).toBeVisible();
  });

  test("one letter suggests nothing, because everything matches it", async ({ page }) => {
    await page.goto("/rulings");
    await page.getByPlaceholder(/start typing a card name/i).fill("l");
    await expect(page.getByRole("listbox")).toHaveCount(0);
  });

  test("the keyboard works end to end", async ({ page }) => {
    await page.goto("/rulings");
    const box = page.getByPlaceholder(/start typing a card name/i);
    await box.fill("lightn");
    await expect(page.getByRole("option").first()).toBeVisible();

    await box.press("ArrowDown"); // to the second suggestion
    await box.press("Enter");
    await expect(page.getByRole("heading", { name: "Lightning Helix" })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("a card with no rulings says so rather than showing an empty box", async ({ page }) => {
    await page.goto("/rulings");
    await page.getByPlaceholder(/start typing a card name/i).fill("counters");
    await page.getByRole("option", { name: "Counterspell" }).click();
    await expect(page.getByText(/no official rulings/i)).toBeVisible({ timeout: 15_000 });
    // and still somewhere to go and check for themselves
    await expect(page.getByRole("link", { name: /full card on scryfall/i })).toBeVisible();
  });

  test("the way out to Scryfall is always there", async ({ page }) => {
    await page.goto("/rulings");
    await page.getByPlaceholder(/start typing a card name/i).fill("lightn");
    await page.getByRole("option", { name: "Lightning Bolt" }).click();

    const out = page.getByRole("link", { name: /full card on scryfall/i });
    await expect(out).toBeVisible({ timeout: 15_000 });
    await expect(out).toHaveAttribute("href", /^https:\/\/scryfall\.com\//);
    // opening a third-party site must not carry our page along with it
    await expect(out).toHaveAttribute("rel", /noreferrer/);
    await expect(out).toHaveAttribute("target", "_blank");
  });

  test("nothing is loaded from Scryfall by the page itself", async ({ page }) => {
    // The whole reason this proxies. A link the player chooses to follow is
    // fine; an image the page fetches is a third-party request and would fail
    // the CSP — see privacy.spec.ts for the site-wide version of this.
    const foreign: string[] = [];
    const ownHost = new URL(test.info().project.use.baseURL!).host;
    page.on("request", (r) => {
      const url = r.url();
      if (url.startsWith("data:") || url.startsWith("blob:")) return;
      if (new URL(url).host !== ownHost) foreign.push(url);
    });

    await page.goto("/rulings");
    await page.getByPlaceholder(/start typing a card name/i).fill("lightn");
    await page.getByRole("option", { name: "Lightning Bolt" }).click();
    await expect(page.getByRole("heading", { name: "Lightning Bolt" })).toBeVisible({
      timeout: 15_000,
    });

    expect(foreign, `third-party requests: ${foreign.join(", ")}`).toEqual([]);
  });

  test("it is reachable from the site nav", async ({ page, isMobile }) => {
    await page.goto("/");
    if (isMobile) await page.getByRole("button", { name: /^menu$/i }).click();
    await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: /rulings/i }).click();
    await expect(page).toHaveURL(/\/rulings$/);
  });

  test("credits the people whose work this is", async ({ page }) => {
    await page.goto("/rulings");
    // Scoped to this page's own credit: the site footer carries the general
    // Fan Content notice, and an unscoped match hits both.
    const credit = page.locator(".ruling-credit");
    await expect(credit).toContainText(/wizards of the coast/i);
    await expect(credit).toContainText(/scryfall/i);
    await expect(credit).toContainText(/unofficial and unaffiliated/i);
  });
});
