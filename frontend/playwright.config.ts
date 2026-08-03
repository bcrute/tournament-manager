import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** Where the app under test drops the mail it "sends". Handed to the tests
 *  through the environment so both halves agree on one path. */
const MAILBOX = process.env.E2E_MAILBOX ?? join(mkdtempSync(join(tmpdir(), "e2e-mail-")), "mail.jsonl");
process.env.E2E_MAILBOX = MAILBOX;

/**
 * Browser tests against the **real production artifact**: the built frontend
 * served by the actual FastAPI app, not the Vite dev server. That matters —
 * several bugs this project shipped only exist in the built path (the SPA
 * fallback's cache headers, the hashed-bundle split), and a dev server would
 * have hidden all of them.
 *
 * The API tests already cover behaviour thoroughly. These exist for what only a
 * browser can see: that a control is actually rendered, reachable, and wired.
 */
export default defineConfig({
  testDir: "./e2e",
  // a real event has real latency; keep tests deterministic instead of fast
  timeout: 30_000,
  expect: { timeout: 7_000 },
  fullyParallel: false, // one shared SQLite database
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "list" : "line",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8099",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "mobile", use: { ...devices["Pixel 7"] } },
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command:
          "cd ../backend && TABLE_STATIC_DIR=../frontend/dist " +
          "TREACHERY_DB=$(mktemp -d)/e2e.db TABLE_RATELIMIT=off " +
          // The file transport, so a browser test can read the link out of a
          // confirmation email and click it. The alternative was a test-only
          // way to skip confirming — which would leave the one flow that most
          // needs end-to-end coverage covered only by unit tests.
          `TABLE_MAIL_FILE=${MAILBOX} TABLE_PUBLIC_URL=http://127.0.0.1:8099 ` +
          // Card data from a fixture rather than Scryfall. The suite runs with
          // no internet and must not depend on somebody else's uptime to pass;
          // the fixture is read through the same seam the real client
          // implements, so the routes take the production path.
          "TABLE_SCRYFALL_FIXTURE=../frontend/e2e/scryfall-fixture.json " +
          "python -m uvicorn app.main:app --host 127.0.0.1 --port 8099",
        url: "http://127.0.0.1:8099/api/health",
        // Never reuse: a server left running from an earlier session keeps the
        // code it started with, while the database on disk has since been
        // migrated. That mismatch produced a backend TypeError I could not
        // reproduce afterwards, because the next run started a fresh process.
        // Testing against a stale process is the same class of mistake as
        // testing against a stale bundle.
        reuseExistingServer: false,
        timeout: 60_000,
      },
});
