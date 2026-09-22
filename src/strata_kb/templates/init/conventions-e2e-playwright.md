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

## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/e2e-playwright.local.md` wins over both.

| Topic | Playwright e2e | Shared |
|---|---|---|
| Coding style | [e2e-playwright/coding-style.md](e2e-playwright/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [e2e-playwright/patterns.md](e2e-playwright/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [e2e-playwright/security.md](e2e-playwright/security.md) | [common/security.md](common/security.md) |
| Testing | [e2e-playwright/testing.md](e2e-playwright/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [e2e-playwright/hooks.md](e2e-playwright/hooks.md) | [common/hooks.md](common/hooks.md) |

## Citation comments

Every standard-derived value (code, format, enum, threshold) asserted
in a spec is verbatim from the resolved KB section at the pinned
version and carries a citation comment on the same line or the line
above:

```ts
await expect(page.getByTestId("max-altitude")).toHaveText("60000"); // per ATM-STD §5.3 @ v2.1
```

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
