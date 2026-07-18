import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
  },
  server: {
    proxy: {
      "/api/table/ws": { target: "ws://localhost:8000", ws: true },
      "/api": "http://localhost:8000",
    },
  },
});
