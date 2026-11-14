// Created once by `kb init`; yours to edit. The front-end URL comes from
// TEST_FE_URL in .env (written by /tester-env-setup), never a literal.
import { defineConfig, devices } from "@playwright/test";

// Node 20.12+; a missing .env is fine (CI passes real env vars).
try {
  process.loadEnvFile(".env");
} catch {}

export default defineConfig({
  use: {
    baseURL: process.env.TEST_FE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
