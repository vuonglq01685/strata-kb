> This file extends [common/patterns.md](../common/patterns.md) with Playwright e2e-specific content.

# Playwright e2e patterns

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/e2e-playwright.local.md`.

## Test structure

- Page objects / fixtures for anything reused across specs (login,
  seeded data) — no copy-pasted setup across files.
- One user flow per test; AAA shape (arrange via fixture/`beforeEach`,
  act via a handful of Playwright actions, assert via `expect`).
- Prefer role/text/testid locators (`getByRole`, `getByTestId`) over
  CSS selectors tied to styling, which break on unrelated UI changes.
