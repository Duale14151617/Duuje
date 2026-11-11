import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy API calls to the backend so no CORS setup is needed. In production serve /api behind the same reverse proxy.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: "http://localhost:8080", rewrite: (p) => p.replace(/^\/api/, "") } } },
});
