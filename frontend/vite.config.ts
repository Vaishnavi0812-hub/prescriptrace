/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Where /api requests are forwarded: the backend container in Docker, or a local backend.
const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env;
// xfwd adds X-Forwarded-For, so the backend's per-IP rate limits see each real client.
const apiProxy = {
  "/api": { target: env?.API_PROXY_TARGET ?? "http://localhost:8000", changeOrigin: true, xfwd: true },
};

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Installable app; the service worker caches the app shell only. API answers are never
    // cached by it: offline checks use the offline pack the user chooses to save (ADR-018).
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "PrescripTrace: medicine safety check",
        short_name: "PrescripTrace",
        description:
          "Medicine interaction and recall check for pharmacies and clinics. Decision support only.",
        lang: "en",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "portrait",
        theme_color: "#1F5F4A",
        background_color: "#FBF7F0",
        icons: [
          { src: "pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "pwa-512.png", sizes: "512x512", type: "image/png" },
          { src: "pwa-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [],
      },
    }),
  ],
  server: {
    // Polling makes hot reload work for files bind-mounted from Windows into Docker.
    watch: { usePolling: true },
    proxy: apiProxy,
  },
  // `npm run serve` (what Docker runs): the optimised build, including the offline service worker.
  preview: { proxy: apiProxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
