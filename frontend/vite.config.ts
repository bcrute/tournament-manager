import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // Playwright specs are driven by `npm run e2e`, not vitest — they import a
    // different test runner and fail at collection here
    exclude: ["node_modules/**", "dist/**", "e2e/**", "shots/**"],
    coverage: {
      // Gate the regression-prone logic modules; presentational components are
      // intentionally excluded (they change constantly and break loudly in
      // use, and the browser suite covers them).
      //
      // This list is hand-written and therefore drifts —
      // `src/coverageGate.test.ts` fails when a `.ts` module is in neither
      // this list nor its EXEMPT map. Adding a module here without tests will
      // pull the whole gate down, which is the intended pressure.
      include: [
        "src/table/api.ts",
        "src/table/session.ts",
        "src/table/useDebouncedDelta.ts",
        "src/table/backGuard.ts",
        "src/table/useWakeLock.ts",
        "src/table/carousel.ts",
        "src/table/useAutoHide.ts",
        "src/table/fetchPolicy.ts",
        "src/table/seats.ts",
        "src/table/emoji.ts",
        "src/table/useHoldRepeat.ts",
        "src/tournament/api.ts",
        "src/admin/api.ts",
        "src/account/api.ts",
        "src/account/useAccount.ts",
        "src/username.ts",
        "src/goBack.ts",
        "src/nav.ts",
        "src/table/qrPayload.ts",
        "src/storage.ts",
        // shared by all four API layers: a bad Retry-After parse shows every
        // rate-limited user "in NaN seconds"
        "src/retryAfter.ts",
        "src/cards/api.ts",
        "src/cards/useSuggest.ts",
        // 170 lines of user-facing strings with a lookup around them; it had
        // tests and no gate, so its coverage could rot unnoticed
        "src/i18n.ts",
      ],
      thresholds: {
        statements: 90,
        branches: 85,
        functions: 90,
        lines: 90,
      },
    },
  },
  server: {
    proxy: {
      "/api/table/ws": { target: "ws://localhost:8000", ws: true },
      "/api": "http://localhost:8000",
    },
  },
});
