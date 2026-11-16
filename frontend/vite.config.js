import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5678,
    // Polling makes file watching reliable across Docker bind mounts.
    watch: { usePolling: process.env.VITE_USE_POLLING === "true" },
    // Allow pages on any port of localhost (and *.localhost), 127.0.0.1, 0.0.0.0 and [::1], plus HTML
    // files opened from disk (their origin is "null"), to call /api and /mcp. /mcp still needs an integration key.
    // Same rule as the backend's cors_origin_regex (backend/app/config.py).
    cors: {
      origin: [/^https?:\/\/(?:(?:[^/:]+\.)?localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::\d+)?$/, "null"],
      credentials: true,
    },
    proxy: {
      "/api": process.env.API_PROXY_TARGET || "http://localhost:8765",
      // MCP endpoint for AI agents, so it is reachable at http://localhost:5678/mcp too.
      "/mcp": process.env.API_PROXY_TARGET || "http://localhost:8765",
    },
  },
});
