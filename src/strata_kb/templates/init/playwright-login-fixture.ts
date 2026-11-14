// Login fixture for a user/password form. /tester-env-setup fills the
// selectors below by exploring the login page through Playwright MCP.
// Credentials come from env vars named TEST_<ROLE>_USER / TEST_<ROLE>_PASSWORD
// (the names .kb/test-env.yaml declares), never literals.
import { test as base, expect, type Page } from "@playwright/test";

export const LOGIN = {
  path: "/login", // TODO: set by /tester-env-setup
  user: 'input[name="username"]', // TODO: set by /tester-env-setup
  password: 'input[name="password"]', // TODO: set by /tester-env-setup
  submit: 'button[type="submit"]', // TODO: set by /tester-env-setup
};

export async function login(page: Page, userEnv: string, passwordEnv: string) {
  const user = process.env[userEnv];
  const password = process.env[passwordEnv];
  if (!user || !password) {
    throw new Error(`set ${userEnv} and ${passwordEnv} in .env`);
  }
  await page.goto(LOGIN.path);
  await page.fill(LOGIN.user, user);
  await page.fill(LOGIN.password, password);
  await page.click(LOGIN.submit);
}

export const test = base.extend<{ loginAs: (role: "buyer" | "admin") => Promise<void> }>({
  loginAs: async ({ page }, use) => {
    await use(async (role) => {
      const prefix = `TEST_${role.toUpperCase()}`;
      await login(page, `${prefix}_USER`, `${prefix}_PASSWORD`);
    });
  },
});

export { expect };
