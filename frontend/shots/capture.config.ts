import { defineConfig, devices } from "@playwright/test";

/**
 * Screenshot capture, kept apart from the test suite.
 *
 * These are marketing assets, not assertions — they write files into
 * `public/shots/` and are run deliberately (`npm run shots`), never in CI. A
 * CI run that regenerates images would either fail on trivial pixel drift or
 * commit binaries nobody reviewed.
 */
export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8099",
    ...devices["Pixel 7"],
    // a clean 2x phone screen, no device chrome
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command:
          "cd ../../backend && TABLE_STATIC_DIR=../frontend/dist " +
          "TREACHERY_DB=$(mktemp -d)/shots.db TABLE_RATELIMIT=off " +
          "python -m uvicorn app.main:app --host 127.0.0.1 --port 8099",
        url: "http://127.0.0.1:8099/api/health",
        reuseExistingServer: true,
        timeout: 60_000,
      },
});
