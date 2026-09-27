import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** The `hx serve` the dev server forwards `/api` to. */
const API = process.env.HX_API ?? "http://127.0.0.1:7777";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../src/hypothex/ui_dist", import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API, ws: true },
      "/.well-known": { target: API },
    },
  },
});
