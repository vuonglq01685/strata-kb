// Login smoke: every account in .kb/test-env.yaml must log in. Run by
// /tester-env-setup with `npx playwright test tests/fixtures/login.smoke.spec.ts`.
// Credentials are read from env vars only; nothing is typed through MCP.
import { test, expect } from "./login";

for (const role of ["buyer", "admin"] as const) {
  test(`login as ${role}`, async ({ page, loginAs }) => {
    await loginAs(role);
    await expect(page).not.toHaveURL(/\/login/);
  });
}
