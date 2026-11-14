// Created once by `kb init`; yours to edit. The front-end URL comes from
// TEST_FE_URL in .env (written by /tester-env-setup), never a literal.
import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

// .env sits next to this file. Needs Node 20.12+ (process.loadEnvFile); a
// missing .env is fine (CI passes real env vars), anything else is an error.
// `__dirname` exists when Playwright loads this file as CommonJS; in an ESM
// repo (package.json "type": "module") fall back to the working directory.
const here = typeof __dirname !== "undefined" ? __dirname : process.cwd();
try {
  process.loadEnvFile(path.resolve(here, ".env"));
} catch (e) {
  if ((e as NodeJS.ErrnoException)?.code !== "ENOENT") throw e;
}

export default defineConfig({
  use: {
    baseURL: process.env.TEST_FE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
