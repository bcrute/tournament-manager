import { describe, expect, it } from "vitest";
import { catalogs, en, FALLBACK, pickLocale, translate } from "./i18n";

const registry = {
  en,
  fr: { "nav.life": "Vie", "card.yours": "Votre carte" },
  "pt-BR": { "nav.life": "Vida" },
};

describe("translate", () => {
  it("returns the string for the locale", () => {
    expect(translate("fr", "nav.life", undefined, registry)).toBe("Vie");
  });

  it("falls back to English for a missing key", () => {
    expect(translate("fr", "nav.table", undefined, registry)).toBe(en["nav.table"]);
  });

  it("falls back from a regional locale to its base language", () => {
    expect(translate("fr-CA", "nav.life", undefined, registry)).toBe("Vie");
  });

  it("prefers an exact regional catalog over the base", () => {
    expect(translate("pt-BR", "nav.life", undefined, registry)).toBe("Vida");
  });

  it("returns the key itself when nothing has it, so it's diagnosable", () => {
    expect(translate("fr", "totally.missing", undefined, registry)).toBe("totally.missing");
  });

  it("interpolates variables", () => {
    expect(translate("en", "card.theirs", { name: "alice" }, registry)).toBe("alice's card");
  });

  it("leaves unknown placeholders intact rather than printing undefined", () => {
    expect(translate("en", "life.minus", { name: "bob" }, registry)).toBe("bob minus {n}");
  });

  it("handles numbers", () => {
    expect(translate("en", "status.gameOver", { n: 3 }, registry)).toContain("3");
  });
});

describe("pickLocale", () => {
  it("picks an exact match", () => {
    expect(pickLocale(["fr", "en"], ["en", "fr"])).toBe("fr");
  });

  it("matches a regional preference to a base catalog", () => {
    expect(pickLocale(["fr-CA"], ["en", "fr"])).toBe("fr");
  });

  it("matches a base preference to a regional catalog", () => {
    expect(pickLocale(["pt"], ["en", "pt-BR"])).toBe("pt-BR");
  });

  it("falls back to English when nothing matches", () => {
    expect(pickLocale(["ja", "ko"], ["en", "fr"])).toBe(FALLBACK);
  });

  it("handles an empty preference list", () => {
    expect(pickLocale([], ["en"])).toBe(FALLBACK);
  });
});

describe("catalog hygiene", () => {
  it("every shipped locale has exactly the English keys", () => {
    const expected = Object.keys(en).sort();
    for (const [locale, catalog] of Object.entries(catalogs)) {
      const keys = Object.keys(catalog).sort();
      const missing = expected.filter((k) => !keys.includes(k));
      const extra = keys.filter((k) => !expected.includes(k));
      expect({ locale, missing, extra }).toEqual({ locale, missing: [], extra: [] });
    }
  });

  it("no string is left empty", () => {
    for (const [locale, catalog] of Object.entries(catalogs)) {
      for (const [key, value] of Object.entries(catalog)) {
        expect(value.trim(), `${locale}:${key}`).not.toBe("");
      }
    }
  });

  it("placeholders in a translation exist in the English source", () => {
    const placeholders = (s: string) => (s.match(/\{(\w+)\}/g) ?? []).sort();
    for (const [locale, catalog] of Object.entries(catalogs)) {
      if (locale === "en") continue;
      for (const [key, value] of Object.entries(catalog)) {
        expect(placeholders(value), `${locale}:${key}`).toEqual(placeholders(en[key] ?? ""));
      }
    }
  });
});
