import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    sourcemap: false,
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
      // main.tsx only mounts <App /> into the DOM; everything it renders is tested.
      exclude: ["src/main.tsx", "src/test/**", "src/**/*.test.{ts,tsx}"],
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
