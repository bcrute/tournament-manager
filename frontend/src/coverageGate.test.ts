/// <reference types="vite/client" />
// @vitest-environment node
//
// Node rather than the project default of jsdom, because this file imports
// `vite.config.ts` — which pulls in esbuild, and esbuild refuses to run where
// `new TextEncoder().encode("") instanceof Uint8Array` is false, which is
// exactly what jsdom's TextEncoder does. Nothing here touches the DOM.
import { describe, expect, it } from "vitest";
import viteConfig from "../vite.config";

/**
 * The coverage gate is a hand-written list, so it drifts. This is the thing
 * that notices.
 *
 * `vite.config.ts` names the modules coverage thresholds apply to, one path at
 * a time. Anything not on that list is invisible to the gate: it can have no
 * tests at all and the reported figure stays at 99%, because the figure is of
 * the *listed* files. Three modules had already slipped through when this was
 * written, two of them added the same week.
 *
 * That is the same failure as a CI check that silently skips — a control that
 * quietly stops applying is worse than no control, because the number keeps
 * saying everything is fine.
 *
 * So every `.ts` module under `src/` has to be in one of two places: the
 * coverage `include` list, or `EXEMPT` below with a reason someone wrote down.
 * Adding a module and forgetting both fails this test.
 *
 * `.tsx` is deliberately out of scope. Presentational components are excluded
 * from coverage on purpose (see `vite.config.ts`) — they change constantly,
 * break loudly in use, and the browser suite covers them.
 *
 * Implementation note: the module list comes from `import.meta.glob` and the
 * gated list from importing the config object, rather than from reading either
 * off disk. That keeps this file free of Node APIs — `tsconfig.json` covers
 * `src/` and has no `@types/node`, so `readFileSync` here would fail the type
 * check and therefore the build — and it means the config is *the* source
 * rather than a regex's guess at it.
 */

/**
 * Modules the gate does not apply to, and why. A reason is required: the point
 * is that a gap is a decision somebody took, not a thing nobody noticed.
 */
const EXEMPT: Record<string, string> = {
  "apps.ts":
    "Unreferenced — nothing imports APPS, and Home.tsx hardcodes its own list. " +
    "Delete it or wire it up; either way there is no behaviour here to cover.",
  "table/useRoom.ts":
    "No tests yet, and the largest such gap in the client: polling, socket and " +
    "reconnect for the live room. Covered on happy paths by the browser suite only.",
  "tournament/useTournament.ts":
    "No tests yet. Polling with hidden-tab backoff; same shape as useRoom and " +
    "should follow it in.",
};

/** Every `.ts` module under `src/`, as `src/`-relative names. */
function modules(): string[] {
  const found = import.meta.glob("./**/*.ts", { eager: false });
  return Object.keys(found)
    .map((p) => p.replace(/^\.\//, ""))
    .filter((p) => !p.endsWith(".test.ts") && !p.endsWith(".d.ts"));
}

/** The `include:` paths from the config, as `src/`-relative names. */
function gated(): string[] {
  // Vitest types `coverage` as a union across providers, and the "custom"
  // branch has no `include`. We know which provider this project uses; the
  // narrowing is here rather than a config change so the config stays about
  // configuration.
  const coverage = viteConfig.test?.coverage as { include?: string[] } | undefined;
  return (coverage?.include ?? [])
    .filter((p) => p.startsWith("src/"))
    .map((p) => p.slice("src/".length));
}

describe("the coverage gate covers what exists", () => {
  it("accounts for every logic module, by gating it or exempting it on purpose", () => {
    const covered = new Set(gated());
    const unaccounted = modules().filter((m) => !covered.has(m) && !(m in EXEMPT));
    expect(
      unaccounted,
      "these .ts modules are invisible to the coverage gate. Add them to " +
        "include: [] in vite.config.ts, or to EXEMPT here with a reason:\n  " +
        unaccounted.join("\n  "),
    ).toEqual([]);
  });

  it("does not exempt a module that no longer exists", () => {
    // An exemption outliving its module is a stale excuse, and the next
    // person reads it as a live one.
    const present = new Set(modules());
    const ghosts = Object.keys(EXEMPT).filter((m) => !present.has(m));
    expect(ghosts, `EXEMPT names modules that are gone: ${ghosts.join(", ")}`).toEqual([]);
  });

  it("does not both gate and exempt the same module", () => {
    const covered = new Set(gated());
    const both = Object.keys(EXEMPT).filter((m) => covered.has(m));
    expect(both, `listed twice, so the exemption is a lie: ${both.join(", ")}`).toEqual([]);
  });

  it("requires a real reason, not an empty string", () => {
    for (const [module, reason] of Object.entries(EXEMPT)) {
      expect(reason.trim().length, `${module} has no reason`).toBeGreaterThan(20);
    }
  });

  it("finds both lists at all", () => {
    // If either source stops resolving, every assertion above passes
    // vacuously — which is the exact failure mode this file exists to prevent.
    expect(gated().length).toBeGreaterThan(10);
    expect(gated()).toContain("storage.ts");
    expect(modules().length).toBeGreaterThan(10);
    expect(modules()).toContain("storage.ts");
  });
});
