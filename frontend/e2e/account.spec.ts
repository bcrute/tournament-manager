import { expect, Page, test } from "@playwright/test";
import { linkIn, waitForMail } from "./mailbox";

/**
 * The player account area.
 *
 * The endpoints behind this existed and were tested long before any of it was
 * reachable: the dashboard sat at an address nothing linked to, and the rename,
 * recovery-code and email endpoints had no user interface at all. So these
 * tests are deliberately about *reachability and wiring* — that a signed-out
 * visitor is offered a way in, that each section is its own address, and that
 * changing a name in one place changes it in the others.
 *
 * The server enforces every one of these rules itself; nothing here is a
 * security check. `backend/tests/test_account_profile.py` is where that lives.
 */

/** The site nav is a hamburger on a phone and inline links past 60rem. */
async function siteNav(page: Page) {
  const menu = page.getByRole("button", { name: /^menu$/i });
  if (await menu.isVisible().catch(() => false)) await menu.click();
  return page.getByRole("navigation", { name: "Site" });
}

/** A fresh account, made through the UI the way a visitor would. */
async function signUp(page: Page, username: string) {
  await page.goto("/account");
  await page.getByRole("button", { name: /^sign up$/i }).click();
  await page.getByPlaceholder(/^username$/i).fill(username);
  await page.getByPlaceholder(/^password$/i).fill("a good long password");
  await page.getByRole("button", { name: /create account/i }).click();
  // recovery codes are shown once, and the only way past them is acknowledging
  await expect(page.getByRole("heading", { name: /save your recovery codes/i })).toBeVisible();
  await page.getByRole("button", { name: /saved them/i }).click();
  await expect(page.getByRole("navigation", { name: "Account" })).toBeVisible();
}

const unique = (prefix: string) => `${prefix}-${Date.now().toString(36)}`;

test.describe("finding the account area at all", () => {
  test("a signed-out visitor is offered a way in from every page", async ({ page }) => {
    await page.goto("/");
    const nav = await siteNav(page);
    // "Account" would be a dead end for someone who has none, and "Sign in"
    // alone never advertised that making one was an option at all
    const entry = nav.getByRole("link", { name: /sign up/i });
    await expect(entry).toBeVisible();
    await expect(entry).toHaveText(/sign up/i);
    await expect(entry).toHaveText(/sign in/i);
    await entry.click();
    await expect(page).toHaveURL(/\/account$/);
    await expect(page.getByRole("heading", { name: /your account/i })).toBeVisible();
    // and creating one is reachable from there in one click
    await page.getByRole("button", { name: /^sign up$/i }).click();
    await expect(page.getByRole("button", { name: /create account/i })).toBeVisible();
  });

  test("the sign-up entry appears on the play and tournament surfaces too", async ({ page }) => {
    for (const path of ["/table", "/tournament"]) {
      await page.goto(path);
      const nav = await siteNav(page);
      await expect(nav.getByRole("link", { name: /sign up/i })).toBeVisible();
    }
  });

  test("the old dashboard address still lands somewhere", async ({ page }) => {
    // it was linked from the privacy page, and from anyone's history
    await page.goto("/table/me");
    await expect(page).toHaveURL(/\/account$/);
  });

  test("the nav shows who you are once you are signed in", async ({ page }) => {
    const name = unique("navname");
    await signUp(page, name);
    await page.goto("/");
    const nav = await siteNav(page);
    await expect(nav.getByRole("link", { name })).toBeVisible();
  });
});

test.describe("creating an account", () => {
  test("asks for a username and a password, and nothing else", async ({ page }) => {
    await page.goto("/account");
    await page.getByRole("button", { name: /^sign up$/i }).click();

    // A recovery email used to ride along here. It is account state a reset
    // would be sent to, and taking it before anyone can prove they own it had
    // an unverified string doing a credential's job.
    await expect(page.locator("input[type=email]")).toHaveCount(0);
    await expect(page.getByPlaceholder(/email/i)).toHaveCount(0);
    await expect(page.getByText(/email is optional/i)).toHaveCount(0);

    await expect(page.getByPlaceholder(/^username$/i)).toBeVisible();
    await expect(page.getByPlaceholder(/^password$/i)).toBeVisible();
  });

  test("opens blank even when this device remembers a table name", async ({ page }) => {
    // an account username and the name you play under are different things
    await page.goto("/table");
    await page.evaluate(() => localStorage.setItem("table.name", "Grumpy Platypus 42"));
    await page.goto("/account");
    await expect(page.getByPlaceholder(/^username$/i)).toHaveValue("");
    await page.getByRole("button", { name: /^sign up$/i }).click();
    await expect(page.getByPlaceholder(/^username$/i)).toHaveValue("");
  });

  test("warns about an email-shaped username only while signing up", async ({ page }) => {
    await page.goto("/account");
    const warning = /should not be treated as private recovery information/i;

    // signing in: they already chose it, so second-guessing is just noise
    await page.getByPlaceholder(/^username$/i).fill("someone@example.com");
    await expect(page.getByText(warning)).toHaveCount(0);

    await page.getByRole("button", { name: /^sign up$/i }).click();
    await page.getByPlaceholder(/^username$/i).fill("someone@example.com");
    await expect(page.getByText(warning)).toBeVisible();

    // it must not promise anything about a field that no longer exists
    await expect(page.getByText(/field below|copied your address/i)).toHaveCount(0);
    // it recommends, it does not block: with a password filled the account can
    // still be created under the email-shaped username
    await page.getByPlaceholder(/^password$/i).fill("a good long password");
    await expect(page.getByRole("button", { name: /create account/i })).toBeEnabled();
  });

  test("still issues recovery codes, which are the only way back in", async ({ page }) => {
    await signUp(page, unique("codes"));
    // signUp asserts the codes screen and acknowledges it; getting here proves
    // the codes still appear without an email in the picture
    await expect(page.getByRole("navigation", { name: "Account" })).toBeVisible();
  });
});

test.describe("the sections", () => {
  test("each one is its own address, so it survives a reload", async ({ page }) => {
    await signUp(page, unique("sections"));

    for (const [tab, path, marker] of [
      ["Games", "/account/games", /no games yet/i],
      ["Notes", "/account/notes", /no notes yet/i],
      ["Settings", "/account/settings", /default table name/i],
    ] as const) {
      await page.getByRole("navigation", { name: "Account" }).getByRole("link", { name: tab }).click();
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByText(marker).first()).toBeVisible();

      await page.reload();
      await expect(page.getByText(marker).first()).toBeVisible();
    }
  });

  test("the overview shows totals rather than an empty page", async ({ page }) => {
    await signUp(page, unique("overview"));
    await expect(page.getByRole("heading", { name: /your play/i })).toBeVisible();
    await expect(page.getByText(/times you sat down/i)).toBeVisible();
    // an account with no events is the normal case, not an error state
    await expect(page.getByRole("heading", { name: /events you run/i })).toBeVisible();
  });
});

test.describe("the two names", () => {
  test("renaming the account updates the nav, not just the form", async ({ page }) => {
    const before = unique("rename");
    const after = `${before}-new`;
    await signUp(page, before);
    await page.goto("/account/settings");

    await page.getByLabel("Username", { exact: true }).fill(after);
    await page.getByLabel(/current password/i).first().fill("a good long password");
    await page.getByRole("button", { name: /change username/i }).click();

    await expect(page.getByText(new RegExp(`you now sign in as ${after}`, "i"))).toBeVisible();
    const nav = await siteNav(page);
    await expect(nav.getByRole("link", { name: after })).toBeVisible();
  });

  test("a wrong password leaves the username alone", async ({ page }) => {
    const name = unique("badpass");
    await signUp(page, name);
    await page.goto("/account/settings");

    await page.getByLabel("Username", { exact: true }).fill(`${name}-nope`);
    await page.getByLabel(/current password/i).first().fill("not the password");
    await page.getByRole("button", { name: /change username/i }).click();

    await expect(page.getByText(/your password is wrong/i)).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("Username", { exact: true })).toHaveValue(name);
  });

  test("the default table name is filled in at the table", async ({ page }) => {
    await signUp(page, unique("tablename"));
    await page.goto("/account/settings");

    await page.getByLabel(/table name/i).fill("Grumpy Platypus 42");
    await page.getByRole("button", { name: /save table name/i }).click();
    await expect(page.getByText(/you'll sit down as grumpy platypus 42/i)).toBeVisible();

    // the point of storing it on the account rather than the device
    await page.goto("/table");
    await expect(page.getByPlaceholder(/your name/i)).toHaveValue("Grumpy Platypus 42");
  });

  test("the table name never has to be unique", async ({ page, browser }) => {
    await signUp(page, unique("dupe-a"));
    await page.goto("/account/settings");
    await page.getByLabel(/table name/i).fill("Same Name 7");
    await page.getByRole("button", { name: /save table name/i }).click();
    await expect(page.getByText(/you'll sit down as same name 7/i)).toBeVisible();

    const ctx = await browser.newContext();
    const other = await ctx.newPage();
    await signUp(other, unique("dupe-b"));
    await other.goto("/account/settings");
    await other.getByLabel(/table name/i).fill("Same Name 7");
    await other.getByRole("button", { name: /save table name/i }).click();
    await expect(other.getByText(/you'll sit down as same name 7/i)).toBeVisible();
    await ctx.close();
  });
});

test.describe("games and notes", () => {
  test("a game played while signed in shows up with its note", async ({ page }) => {
    await signUp(page, unique("player"));

    await page.goto("/table");
    await page.getByRole("button", { name: /^create$/i }).click();
    await page.getByPlaceholder(/your name/i).fill("Ada");
    await page.getByRole("button", { name: /create room/i }).click();
    await page.waitForURL(/\/table\/r\/.+/);
    const code = (await page.locator(".bar-code").first().textContent())!.trim();

    await page.goto("/account/games");
    await expect(page.getByText(code, { exact: false }).first()).toBeVisible();

    await page.getByRole("button", { name: /add note/i }).first().click();
    await page.getByLabel(/your private note/i).fill("Ada mulliganed to four.");
    await page.getByRole("button", { name: /save note/i }).click();
    await expect(page.getByText(/mulliganed to four/i)).toBeVisible();

    // the notes tab is the same rows read the other way round
    await page.goto("/account/notes");
    await expect(page.getByText(/mulliganed to four/i)).toBeVisible();

    await page.getByLabel(/search your notes/i).fill("mulligan");
    await expect(page.getByText(/mulliganed to four/i)).toBeVisible();
    await page.getByLabel(/search your notes/i).fill("something else entirely");
    await expect(page.getByText(/nothing matches/i)).toBeVisible();
  });
});

test.describe("signing out", () => {
  test("returns the nav to offering a way in", async ({ page }) => {
    await signUp(page, unique("signout"));
    await page.goto("/account/settings");
    await page.getByRole("button", { name: /^sign out$/i }).click();
    await expect(page).toHaveURL(/\/table$/);

    const nav = await siteNav(page);
    await expect(nav.getByRole("link", { name: /sign in/i })).toBeVisible();
  });
});

test.describe("the recovery address", () => {
  const pw = "a good long password";

  /** Enrol an address from the settings screen. Returns the address. */
  async function enrol(page: Page, username: string) {
    const address = `${username}@example.com`;
    await page.goto("/account/settings");
    await page.getByLabel(/^email address$/i).fill(address);
    await page.getByLabel(/^your password$/i).fill(pw);
    await page.getByRole("button", { name: /add email/i }).click();
    return address;
  }

  test("adding one does not make it count for anything yet", async ({ page }) => {
    const username = unique("mail");
    await signUp(page, username);
    await enrol(page, username);

    // The overview is where a player reads their own state, and it must not
    // say an unconfirmed address is a recovery address.
    await expect(page.getByText(/waiting for confirmation/i)).toBeVisible({ timeout: 15_000 });
    await page.goto("/account");
    await expect(page.getByText(/recovery codes are your only way back in/i)).toBeVisible();
  });

  test("hosting stays shut until the link is used, and opens after", async ({ page }) => {
    const username = unique("mail");
    await signUp(page, username);
    const address = await enrol(page, username);
    await expect(page.getByText(/waiting for confirmation/i)).toBeVisible({ timeout: 15_000 });

    await page.goto("/tournament");
    await expect(page.getByText(/check your inbox/i)).toBeVisible({ timeout: 15_000 });

    await page.goto(linkIn(await waitForMail(address)));
    await expect(page.getByRole("heading", { name: /address confirmed/i })).toBeVisible({
      timeout: 15_000,
    });

    await page.goto("/tournament");
    await expect(page.getByRole("heading", { name: /your tournaments/i })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("a used link does not work a second time", async ({ page }) => {
    const username = unique("mail");
    await signUp(page, username);
    const address = await enrol(page, username);
    const link = linkIn(await waitForMail(address));

    await page.goto(link);
    await expect(page.getByRole("heading", { name: /address confirmed/i })).toBeVisible({
      timeout: 15_000,
    });
    await page.goto(link);
    await expect(page.getByText(/no longer valid/i)).toBeVisible({ timeout: 15_000 });
  });

  test("the address never appears in the address bar", async ({ page }) => {
    const username = unique("mail");
    await signUp(page, username);
    const address = await enrol(page, username);
    await page.goto(linkIn(await waitForMail(address)));
    // the token was in a fragment and the page wipes it on arrival, so neither
    // the token nor anything else from the link survives in history
    expect(page.url()).not.toContain("#");
    expect(page.url()).toContain("/account/verify");
  });

  test("adding one costs the password", async ({ page }) => {
    const username = unique("mail");
    await signUp(page, username);
    await page.goto("/account/settings");
    await page.getByLabel(/^email address$/i).fill(`${username}@example.com`);
    // no password typed: the button stays out of reach
    const button = page.getByRole("button", { name: /add email/i });
    await expect(button).toBeDisabled();
    await page.getByLabel(/^your password$/i).fill("not the password");
    await button.click();
    await expect(page.getByText(/password is wrong/i)).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("forgetting a password", () => {
  const pw = "a good long password";

  test("a confirmed address gets a link that sets a new password", async ({ page }) => {
    const username = unique("mail");
    await signUp(page, username);

    const address = `${username}@example.com`;
    await page.goto("/account/settings");
    await page.getByLabel(/^email address$/i).fill(address);
    await page.getByLabel(/^your password$/i).fill(pw);
    await page.getByRole("button", { name: /add email/i }).click();
    await page.goto(linkIn(await waitForMail(address)));
    await expect(page.getByRole("heading", { name: /address confirmed/i })).toBeVisible({
      timeout: 15_000,
    });

    // sign out, and forget the password
    await page.goto("/account/settings");
    await page.getByRole("button", { name: /^sign out$/i }).click();
    await page.goto("/account");
    await expect(page.getByRole("button", { name: /forgotten your password/i })).toBeVisible({
      timeout: 15_000,
    });
    await page.getByRole("button", { name: /forgotten your password/i }).click();
    await page.getByPlaceholder(/^username$/i).fill(username);
    await page.getByRole("button", { name: /send a reset link/i }).click();
    await expect(page.getByText(/if that account exists/i)).toBeVisible({ timeout: 15_000 });

    await page.goto(linkIn(await waitForMail(address)));
    await page.getByLabel(/^new password$/i).fill("an entirely new password");
    await page.getByLabel(/^and again$/i).fill("an entirely new password");
    await page.getByRole("button", { name: /set new password/i }).click();

    // Signed straight in — they proved control of the address and chose a
    // password, so being made to type it again immediately proves nothing.
    // Assert on the account area itself rather than the nav, which is a
    // collapsed hamburger at this width.
    await expect(page).toHaveURL(/\/account$/, { timeout: 15_000 });
    await expect(page.getByRole("button", { name: /^sign up$/i })).toHaveCount(0);
    await page.goto("/account/settings");
    await expect(page.getByRole("button", { name: /^sign out$/i })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("a name nobody has is answered exactly the same way", async ({ page }) => {
    await page.goto("/account");
    await page.getByRole("button", { name: /forgotten your password/i }).click();
    await page.getByPlaceholder(/^username$/i).fill("nobody-has-this-name");
    await page.getByRole("button", { name: /send a reset link/i }).click();
    await expect(page.getByText(/if that account exists/i)).toBeVisible({ timeout: 15_000 });
  });
});
