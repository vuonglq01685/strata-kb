> This file extends [common/hooks.md](../common/hooks.md) with Playwright e2e-specific content.

# Playwright e2e hooks

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/e2e-playwright.local.md`.

Hooks are configured per repo in `.claude/settings.json`, committed with
the code. Nothing here refers to a user-level configuration.

## PostToolUse hooks

- Lint the edited spec with the Playwright ESLint config the
  `## Linting (preset)` section of `docs/conventions/e2e-playwright.md`
  sets up — match on `Write|Edit` and run it on the edited file only.
- Never run the whole suite from a hook: a full Playwright run is minutes
  long, and a hook that slow gets disabled rather than fixed. Run one spec
  or nothing.

## Stop hooks

- A Stop hook may run the suite once, at the end of a session, and only
  when the repo's own `cmd.test.e2e` command is cheap enough to finish
  unattended. Otherwise leave it to CI.
