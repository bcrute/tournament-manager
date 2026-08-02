import { expect, Page, test } from "@playwright/test";

/**
 * Hidden roles, and the one gesture the whole mode rests on.
 *
 * Hold your card to look at it. That shipped broken for two weeks: the carousel
 * read the caller's own card out of `state.players`, where the server masks
 * every unrevealed identity — including yours, deliberately, since that array
 * is the same shape for everyone. Your card is served once, on `state.me.card`.
 * Holding flipped a card back over to reveal a card back.
 *
 * Every unit test stayed green the whole time, because their fixtures put a
 * card on the caller's own row where the real server never does. Only a browser
 * with a real pointer, against the real server, can see this one.
 *
 * **The Leader is public from the deal** (they start face up in the command
 * zone), so exactly one of the five players legitimately has a face-up card and
 * nothing to peek at. These tests find a hidden player rather than assuming the
 * host is one — an earlier version assumed it and passed or failed on the roll.
 */

/** Every player's page in a dealt five-handed game. */
async function dealtGame(page: Page, browser: import("@playwright/test").Browser) {
  await page.goto("/table");
  await page.getByRole("button", { name: /^create$/i }).click();
  await page.getByPlaceholder(/your name/i).fill("Ada");
  await page.getByRole("button", { name: /treachery/i }).click();
  await page.getByRole("button", { name: /create room/i }).click();
  await page.waitForURL(/\/table\/r\/.+/);
  const code = (await page.locator(".bar-code").first().textContent())!.trim();

  const contexts = [];
  const pages: Page[] = [page];
  for (const name of ["Bram", "Cleo", "Dev", "Esme"]) {
    const ctx = await browser.newContext();
    const p = await ctx.newPage();
    await p.goto("/table");
    await p.evaluate((x) => localStorage.setItem("table.name", x), name);
    await p.goto(`/table?join=${code}`);
    await expect(p).toHaveURL(/\/table\/r\/.+/, { timeout: 15_000 });
    contexts.push(ctx);
    pages.push(p);
  }

  await expect(page.locator(".tr-players li")).toHaveCount(5, { timeout: 20_000 });
  await page.getByRole("button", { name: /deal & start/i }).click();
  for (const p of pages) {
    await expect(p.locator(".role-screen")).toBeVisible({ timeout: 20_000 });
  }
  return { contexts, pages };
}

/** A player whose identity is still secret — anyone but the Leader. */
async function hiddenPlayer(pages: Page[]): Promise<Page> {
  for (const p of pages) {
    if ((await p.locator("img.role-card").count()) === 0) return p;
  }
  throw new Error("every player's card was face up — the Leader should be the only one");
}

async function holdCard(page: Page) {
  const box = (await page.locator(".role-screen").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
}

test.describe("looking at your own hidden role", () => {
  test("holding the card shows it, releasing hides it again", async ({ page, browser }) => {
    const { contexts, pages } = await dealtGame(page, browser);
    const me = await hiddenPlayer(pages);

    await expect(me.getByText(/hold/i).first()).toBeVisible();

    await holdCard(me);
    // the entire point of the mode: your identity, while you hold it
    await expect(me.locator("img.role-card")).toHaveCount(1, { timeout: 5_000 });

    await me.mouse.up();
    await expect(me.locator("img.role-card")).toHaveCount(0, { timeout: 5_000 });

    for (const c of contexts) await c.close();
  });

  test("the card stays face down when nobody is touching it", async ({ page, browser }) => {
    const { contexts, pages } = await dealtGame(page, browser);
    const me = await hiddenPlayer(pages);
    // someone glancing over your shoulder must not find it face up
    await me.waitForTimeout(1_500);
    await expect(me.locator("img.role-card")).toHaveCount(0);
    for (const c of contexts) await c.close();
  });

  test("peeking shows your own card, not the public Leader's", async ({ page, browser }) => {
    const { contexts, pages } = await dealtGame(page, browser);
    const me = await hiddenPlayer(pages);

    // Reading the card out of `players` didn't just yield null — it is also the
    // array that carries the Leader. Pin that the card under your thumb is the
    // one labelled yours.
    await expect(me.locator(".carousel-label")).toContainText(/your card/i);
    await holdCard(me);
    await expect(me.locator("img.role-card")).toHaveCount(1, { timeout: 5_000 });
    await expect(me.locator(".carousel-label")).toContainText(/your card/i);
    await me.mouse.up();

    for (const c of contexts) await c.close();
  });

  test("nothing sits on top of the card you are reading", async ({ page, browser }) => {
    // Pressing the card used to wake the thumbnail strip, which then covered
    // the thing you pressed it to see. The strip belongs to sideways movement.
    const { contexts, pages } = await dealtGame(page, browser);
    const me = await hiddenPlayer(pages);

    await holdCard(me);
    await expect(me.locator("img.role-card")).toHaveCount(1, { timeout: 5_000 });
    await expect(me.locator(".carousel-strip:not(.hidden)")).toHaveCount(0);
    await me.mouse.up();

    for (const c of contexts) await c.close();
  });

  test("your win condition is readable alongside your card", async ({ page, browser }) => {
    const { contexts, pages } = await dealtGame(page, browser);
    const me = await hiddenPlayer(pages);

    await holdCard(me);
    const tip = me.locator(".win-condition");
    await expect(tip).toBeVisible({ timeout: 5_000 });
    // one of the four roles, with the rule number it came from
    await expect(tip).toContainText(/leader|guardian|assassin|traitor/i);
    await expect(tip).toContainText(/907\.8[bcd]/);

    // and it must not be sitting on the card, or on the way out
    const card = (await me.locator("img.role-card").boundingBox())!;
    const box = (await tip.boundingBox())!;
    expect(box.y, "the tip overlaps the card").toBeGreaterThanOrEqual(card.y + card.height - 2);
    const slider = await me.locator(".unveil, .role-footer").first().boundingBox();
    if (slider) {
      expect(box.y + box.height, "the tip runs under the unveil slider").toBeLessThanOrEqual(
        slider.y + 2,
      );
    }
    await me.mouse.up();

    for (const c of contexts) await c.close();
  });

  test("the label clears the room bar and the card, and there is no art credit", async ({
    page,
    browser,
  }) => {
    // Both offsets on this screen used to be flat guesses against a bar that is
    // a different height, so the label's top sat under it. And the "art by"
    // line above the card duplicated a credit already printed on the card.
    const { contexts, pages } = await dealtGame(page, browser);
    const me = await hiddenPlayer(pages);

    await expect(me.getByText(/art by/i)).toHaveCount(0);

    const bar = (await me.locator(".room-bar").boundingBox())!;
    const label = (await me.locator(".carousel-label").boundingBox())!;
    expect(label.y, "the label is tucked under the room bar").toBeGreaterThanOrEqual(
      bar.y + bar.height,
    );

    await holdCard(me);
    await expect(me.locator("img.role-card")).toHaveCount(1, { timeout: 5_000 });
    const card = (await me.locator("img.role-card").boundingBox())!;
    expect(label.y + label.height, "the label is sitting on the card").toBeLessThanOrEqual(
      card.y + 1,
    );
    await me.mouse.up();

    for (const c of contexts) await c.close();
  });

  test("someone else's card is laid out like your own", async ({ page, browser }) => {
    // The clearance for the strip and the banner used to live on the win-tip's
    // rule, and the tip only shows on your own card. So another player's card
    // — no tip — grew a hundred pixels into the footer and had the thumbnails
    // drawn on top of it. The footer is the same size either way.
    const { contexts, pages } = await dealtGame(page, browser);
    const me = await hiddenPlayer(pages);

    // swipe sideways to the public Leader's card
    const box = (await me.locator(".role-screen").boundingBox())!;
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    await me.mouse.move(cx, cy);
    await me.mouse.down();
    await me.mouse.move(cx - 120, cy, { steps: 10 });
    await me.mouse.up();

    await expect(me.locator(".carousel-label")).not.toContainText(/your card/i, {
      timeout: 5_000,
    });
    await expect(me.locator("img.role-card")).toHaveCount(1);

    const card = (await me.locator("img.role-card").boundingBox())!;
    const footer = (await me.locator(".role-footer").boundingBox())!;
    expect(card.y + card.height, "the card runs under the strip and banner").toBeLessThanOrEqual(
      footer.y + 1,
    );
    const label = (await me.locator(".carousel-label").boundingBox())!;
    expect(label.y + label.height, "the label sits on the card").toBeLessThanOrEqual(card.y + 1);

    for (const c of contexts) await c.close();
  });

  test("the Leader is face up from the deal, with nothing to hold for", async ({
    page,
    browser,
  }) => {
    const { contexts, pages } = await dealtGame(page, browser);
    let leaders = 0;
    for (const p of pages) {
      if ((await p.locator("img.role-card").count()) > 0) leaders += 1;
    }
    // exactly one, by the rules — and it is why the other tests hunt for a
    // hidden player instead of assuming the host is one
    expect(leaders).toBe(1);
    for (const c of contexts) await c.close();
  });
});
