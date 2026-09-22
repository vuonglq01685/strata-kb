> This file extends [common/coding-style.md](../common/coding-style.md) with Playwright e2e-specific content.

# Playwright e2e coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/e2e-playwright.local.md`.

## Naming

- Spec files: `<feature>.spec.ts` (or `.js`), colocated under `e2e/` or
  next to the feature they cover — follow the repo's existing layout.
- `test.describe("<feature>")` groups by feature/page, not by test type.
- Test names describe user-visible behaviour: `test("rejects expired
  session and redirects to login")`, not `test("case 2")`.

## Diagnostics

- On CI, capture trace + screenshot + video on failure
  (`trace: "on-first-retry"`, `screenshot: "only-on-failure"`) so a
  failure is debuggable without reproducing it locally.
- Never leave `page.pause()` or a debug-only `console.log` in committed
  specs — that is a style rule.
