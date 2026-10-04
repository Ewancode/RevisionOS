/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

// In Docker the API is reachable as `api`; on the host, as localhost.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The Python worker loads Pyodide with a dynamic import(), so it must be
  // an ES module worker.
  worker: { format: "es" },
  build: {
    rollupOptions: {
      // RUNTIME_CHECK=1 adds the runtime check page (runtime-check.html) to a
      // build, to test the production bundle's Python and R runtimes.
      input: process.env.RUNTIME_CHECK
        ? { main: "index.html", check: "runtime-check.html" }
        : { main: "index.html" },
    },
  },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    // In Docker on Windows, file events don't cross the bind mount: poll.
    watch: process.env.VITE_POLL ? { usePolling: true, interval: 500 } : undefined,
    // Same-origin /api in development: no CORS, and cookies behave as in production.
    proxy: { "/api": { target: apiTarget, changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    // https, like the real app: Secure / __Host- cookies only work there.
    environmentOptions: { jsdom: { url: "https://localhost/" } },
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
  },
});
