import { defineConfig, devices } from "@playwright/test";

// Run against a running stack (backend + `npm run dev`): E2E_BASE_URL defaults to the Vite dev server.
export default defineConfig({
  testDir: "e2e",
  retries: 1,
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "android-phone", use: { ...devices["Pixel 5"] } },
    { name: "android-small", use: { ...devices["Galaxy S9+"], viewport: { width: 360, height: 640 } } },
  ],
});
