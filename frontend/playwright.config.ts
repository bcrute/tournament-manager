import { defineConfig, devices } from "@playwright/test";

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
          "python -m uvicorn app.main:app --host 127.0.0.1 --port 8099",
        url: "http://127.0.0.1:8099/api/health",
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
});
