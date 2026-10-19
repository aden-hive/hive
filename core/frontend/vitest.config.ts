import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Vitest config for the frontend. jsdom gives us a DOM for the
// component/hook tests; the layout simulation those tests need
// (scrollHeight / clientHeight / ResizeObserver) is installed per-test
// from ./src/test/layout.ts — jsdom itself has no layout engine.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  define: {
    // ChatPanel's import graph references the build-time version constant.
    __APP_VERSION__: JSON.stringify("test"),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
