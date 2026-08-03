/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
// `?raw` rather than `readFileSync`: tsconfig covers `src/` with no
// @types/node, so a Node import here fails `tsc` and therefore the build.
// Vite inlines these at transform time, which is typed and works unchanged in
// the image.
import notice from "./FanContentNotice.tsx?raw";
import rulings from "./cards/Rulings.tsx?raw";
import manifestJson from "../package.json?raw";

/**
 * The two conditions that make this app's use of Magic content legitimate.
 *
 * Scryfall serves card data under the Wizards Fan Content Policy, and that
 * policy is **noncommercial**. In July 2026 a Scryfall integration was removed
 * from this repo precisely to drop that licence chain, with a regression test
 * asserting the proxy stayed gone. In August 2026 the decision that made the
 * chain a problem was itself reversed — this app is noncommercial permanently,
 * and the commercial vehicle is a separate project (`docs/commercial-position.md`).
 * So Scryfall came back, and `/rulings` uses it.
 *
 * The lesson from that sequence is the reason this file exists. The original
 * regression test was deleted during an unrelated refactor, so when the
 * integration was reintroduced there was nothing left to notice. A decision
 * with nothing enforcing it is a decision that quietly stops being true.
 *
 * What is enforced here:
 *
 *   1. **Attribution**, which the Fan Content Policy requires and whose
 *      wording it fixes — so it must not be paraphrased into something
 *      friendlier.
 *   2. **Noncommercial**, checked the only way a test can: no payment
 *      integration. If someone adds one, this fails, and the failure is the
 *      prompt to re-read the licensing analysis before shipping it.
 *
 * The second is a proxy, not a proof — you could sell something without a
 * payment SDK in the frontend. It catches the realistic case, which is
 * somebody wiring up Stripe without connecting it to a card-content question
 * three documents away.
 */

/** Every component, as source, so "is it still rendered" is answerable. */
const components = import.meta.glob("./**/*.tsx", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

describe("the Fan Content Policy conditions", () => {
  it("still renders the notice somewhere", () => {
    // The failure this catches is deletion rather than edit: every assertion
    // about the notice's wording passes just as happily when nothing puts the
    // component on a page.
    const users = Object.entries(components).filter(
      ([path, source]) =>
        !path.endsWith("FanContentNotice.tsx") && source.includes("FanContentNotice"),
    );
    expect(
      users.length,
      "FanContentNotice exists but nothing renders it, which is the same as not having it",
    ).toBeGreaterThan(0);
  });

  describe("attribution, in the wording the policy fixes", () => {
    it("names itself unofficial and unendorsed", () => {
      expect(notice).toContain("unofficial Fan Content permitted under the Fan Content Policy");
      expect(notice).toContain("Not");
      expect(notice).toMatch(/approved\/endorsed by Wizards/);
    });

    it("carries the copyright line", () => {
      expect(notice).toContain("Portions of the materials used are property of Wizards");
      expect(notice).toContain("©Wizards of the Coast LLC");
    });

    it("still credits the Treachery project and its illustrators", () => {
      // Separate from the Wizards obligation: that card set is a third party's
      // work and the art belongs to individual artists.
      expect(notice).toContain("mtgtreachery.net");
      expect(notice).toMatch(/artwork belongs to the individual illustrators/i);
    });
  });

  describe("attribution on the page that uses Scryfall", () => {
    it("credits Wizards for the rulings and Scryfall for serving them", () => {
      expect(rulings).toMatch(/written by Wizards of the Coast/i);
      expect(rulings).toContain("scryfall.com");
    });

    it("disclaims affiliation with both", () => {
      expect(rulings).toMatch(/unofficial and unaffiliated/i);
    });
  });

  describe("noncommercial", () => {
    //: Payment processors and billing SDKs. Adding one to this app is the
    //: event that invalidates the licence position, not a routine dependency
    //: bump — see docs/commercial-position.md §3.
    const PAYMENT_SDKS = [
      "stripe",
      "paddle",
      "lemonsqueezy",
      "paypal",
      "braintree",
      "chargebee",
      "recurly",
      "square",
    ];

    it("ships no payment integration", () => {
      const manifest = JSON.parse(manifestJson) as {
        dependencies?: Record<string, string>;
        devDependencies?: Record<string, string>;
      };
      const installed = [
        ...Object.keys(manifest.dependencies ?? {}),
        ...Object.keys(manifest.devDependencies ?? {}),
      ].map((d) => d.toLowerCase());

      const found = installed.filter((dep) => PAYMENT_SDKS.some((sdk) => dep.includes(sdk)));
      expect(
        found,
        "A payment dependency appeared. This app is noncommercial, and that is " +
          "what permits its use of Scryfall and Magic card content under the " +
          "Wizards Fan Content Policy. Read docs/commercial-position.md §3 " +
          "before going further — the commercial product is a separate project " +
          "and ships no Magic content at all.",
      ).toEqual([]);
    });

    // The other half — that the decision is still written down in
    // docs/commercial-position.md — is asserted in
    // backend/tests/test_licence_position.py. Vite refuses to read outside its
    // own root, and repo-shape checks already live on the Python side next to
    // the deployment guards.
  });
});
