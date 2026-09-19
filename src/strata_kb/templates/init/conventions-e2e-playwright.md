# Playwright e2e conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/e2e-playwright.local.md`; that file is never touched by
`kb init` and OVERRIDES this one where they conflict. Where either file
conflicts with the repo's existing dominant style, the repo wins locally —
record the conflict as a finding in the PR.

This file covers end-to-end test conventions on top of whatever language
convention already governs the app under test (`ts.md`, `python.md`, ...);
it does not replace them.

## Naming

- Spec files: `<feature>.spec.ts` (or `.js`), colocated under `e2e/` or
  next to the feature they cover — follow the repo's existing layout.
- `test.describe("<feature>")` groups by feature/page, not by test type.
- Test names describe user-visible behaviour: `test("rejects expired
  session and redirects to login")`, not `test("case 2")`.

## Test structure

- Page objects / fixtures for anything reused across specs (login,
  seeded data) — no copy-pasted setup across files.
- One user flow per test; AAA shape (arrange via fixture/`beforeEach`,
  act via a handful of Playwright actions, assert via `expect`).
- Prefer role/text/testid locators (`getByRole`, `getByTestId`) over
  CSS selectors tied to styling, which break on unrelated UI changes.

## Flakiness and timing

- Never `page.waitForTimeout()` as a synchronization mechanism — wait
  on a condition (`expect(locator).toBeVisible()`, a network response,
  a state change) instead.
- Rely on Playwright's built-in auto-waiting/retrying assertions rather
  than manual polling loops.
- A flaky test is a bug in the test or the app under test — fix the
  cause; do not silence it with a retry count or `test.skip`.

## Diagnostics

- On CI, capture trace + screenshot + video on failure
  (`trace: "on-first-retry"`, `screenshot: "only-on-failure"`) so a
  failure is debuggable without reproducing it locally.
- Never leave `page.pause()` or a debug-only `console.log` in committed
  specs.

## Citation comments

Every standard-derived value (code, format, enum, threshold) asserted
in a spec is verbatim from the resolved KB section at the pinned
version and carries a citation comment on the same line or the line
above:

```ts
await expect(page.getByTestId("max-altitude")).toHaveText("60000"); // per ATM-STD §5.3 @ v2.1
```

## Testing

- Every bug fix that is user-flow-visible lands together with the e2e
  test that would have caught it.
- Never edit a test to make it pass — diagnose the cause (app bug vs.
  test bug) before touching either.

## Linting (preset)

The preset below is the target strength. When this repo has no
Playwright-aware lint config, the first task of a dev plan creates
these files and records the command as `cmd.lint`. Where `cmd.lint`
fails on the untouched tree, narrow `rules` to what passes, and list
each narrowed rule under `## Findings` in the PR body as a tightening
still owed.

`eslint.config.mjs` (added alongside the repo's existing config):

```js
import playwright from "eslint-plugin-playwright";

export default [
  {
    files: ["e2e/**/*.ts", "**/*.spec.ts"],
    ...playwright.configs["flat/recommended"],
  },
];
```

Install and run:

```
npm install --save-dev eslint-plugin-playwright
npx eslint e2e
```

Record as `cmd.lint`: `npx eslint e2e`

Record the e2e run itself as `cmd.test.e2e`: `npx playwright test`
