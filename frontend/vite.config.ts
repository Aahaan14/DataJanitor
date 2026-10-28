/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backend = process.env.VITE_DEV_BACKEND ?? "http://127.0.0.1:8000";
const testPort = process.env.DJ_TEST_PORT ?? "8791";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // In development the browser talks to Vite, which forwards API calls to the
    // backend — same origin, so no CORS needed.
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/docs": { target: backend, changeOrigin: true },
      "/openapi.json": { target: backend, changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    globalSetup: ["./tests/globalSetup.ts"],
    // The tests talk to a REAL backend started by globalSetup (no mocked data).
    env: { VITE_API_BASE_URL: `http://127.0.0.1:${testPort}` },
    testTimeout: 30_000,
    hookTimeout: 60_000,
    fileParallelism: false,
  },
});
