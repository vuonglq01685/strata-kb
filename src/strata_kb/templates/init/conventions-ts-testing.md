> This file extends [common/testing.md](../common/testing.md) with TypeScript / JavaScript-specific content.

# TypeScript / JavaScript testing

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/ts.local.md`.

## Ground rules

- The repo's test runner (vitest/jest), AAA shape, one behaviour per
  test.
- Names describe the behaviour: `test("rejects expired token")`, not
  `test("token 2")`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## E2E testing

Use **Playwright** as the E2E testing framework for critical user flows.
A repo with a Playwright suite also scaffolds
`docs/conventions/e2e-playwright.md` and its pack — the e2e conventions
live there.
