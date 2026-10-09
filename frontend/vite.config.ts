/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The PWA plugin (service worker, manifest, offline pack) is configured in Stage 9.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Polling makes hot reload work for files bind-mounted from Windows into Docker.
    watch: { usePolling: true },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
