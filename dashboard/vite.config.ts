import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite configuration for the QuantBot dashboard.
// During development the dev server proxies API/WebSocket calls to the backend
// so the frontend can use same-origin relative URLs.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
