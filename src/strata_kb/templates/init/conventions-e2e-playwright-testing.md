> This file extends [common/testing.md](../common/testing.md) with Playwright e2e-specific content.

# Playwright e2e testing

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/e2e-playwright.local.md`.

## Ground rules

- Every bug fix that is user-flow-visible lands together with the e2e
  test that would have caught it.
- Never edit a test to make it pass — diagnose the cause (app bug vs.
  test bug) before touching either.

## Flakiness and timing

- Never `page.waitForTimeout()` as a synchronization mechanism — wait
  on a condition (`expect(locator).toBeVisible()`, a network response,
  a state change) instead.
- Rely on Playwright's built-in auto-waiting/retrying assertions rather
  than manual polling loops.
- A flaky test is a bug in the test or the app under test — fix the
  cause; do not silence it with a retry count or `test.skip`.

## E2E shape

```ts
import { test, expect } from '@playwright/test';

test('landing hero loads', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toBeVisible();
});
```

- Avoid flaky timeout-based assertions
- Prefer deterministic waits

## Cross-browser

- Minimum: Chrome, Firefox, Safari
- Test scrolling, motion, and fallback behavior

## Responsive

- Test 320, 375, 768, 1024, 1440, 1920
- Verify no overflow
- Verify touch interactions
