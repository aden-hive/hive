import { readFileSync } from "node:fs";
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dashboard ships inside Hive, so it shows Hive's version: the one in core/pyproject.toml
// (aden-hive), not this package.json's, which is never released.
const HIVE_VERSION = (() => {
  const pyproject = readFileSync(path.resolve(__dirname, "../pyproject.toml"), "utf8");
  const table = pyproject.slice(pyproject.indexOf("[project]")).split(/\n\[/)[0]; // up to the next table
  const match = table.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) throw new Error("core/pyproject.toml has no [project] version");
  return match[1];
})();

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(HIVE_VERSION),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8787",
        changeOrigin: true,
      },
    },
  },
});
