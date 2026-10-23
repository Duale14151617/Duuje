import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the SPA and API share an origin through this proxy, so session
// cookies and CSRF behave exactly as they do behind the production reverse proxy.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "node", exclude: ["e2e/**", "node_modules/**"] },
});
