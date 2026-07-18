import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    coverage: {
      // gate the regression-prone logic modules; presentational components are
      // intentionally excluded (they change constantly and break loudly in use)
      include: [
        "src/table/api.ts",
        "src/table/session.ts",
        "src/table/useDebouncedDelta.ts",
        "src/table/backGuard.ts",
        "src/table/useWakeLock.ts",
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
