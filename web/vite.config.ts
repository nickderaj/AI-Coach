import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    sourcemap: false,
    rolldownOptions: {
      input: { app: "index.html", sw: "src/sw/worker.ts" },
      output: {
        // The service worker must keep a fixed name at the root, for its scope and
        // so the browser can find new versions of it.
        entryFileNames: (chunk) => (chunk.name === "sw" ? "sw.js" : "assets/[name]-[hash].js"),
      },
    },
  },
  server: {
    // `pnpm dev` against a local API (python -m trainer.api --port 8000).
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    // A non-UTC zone, so date formatting that leaks the host's zone fails everywhere.
    env: { TZ: "Pacific/Auckland" },
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    unstubGlobals: true,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      // main.tsx only mounts <App /> and worker.ts only wires worker events to
      // strategy.ts; everything they call is tested.
      exclude: ["src/main.tsx", "src/sw/worker.ts", "src/test/**", "src/**/*.test.{ts,tsx}"],
      reporter: ["text", "json-summary", "lcov"],
      thresholds: {
        lines: 90,
        branches: 90,
        functions: 90,
        statements: 90,
      },
    },
  },
});
