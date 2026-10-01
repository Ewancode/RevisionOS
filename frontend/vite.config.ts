/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

// In Docker the API is reachable as `api`; on the host, as localhost.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
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
