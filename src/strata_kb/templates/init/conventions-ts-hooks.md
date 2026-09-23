> This file extends [common/hooks.md](../common/hooks.md) with TypeScript / JavaScript-specific content.

# TypeScript / JavaScript hooks

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/ts.local.md`.

## PostToolUse hooks

Configure in `.claude/settings.json` (this repo's, committed):

- **Prettier**: auto-format JS/TS files after edit.
- **TypeScript check**: run `tsc` after editing `.ts`/`.tsx` files.
- **console.log warning**: warn about `console.log` in edited files.

## Stop hooks

- **console.log audit**: check all modified files for `console.log`
  before session ends.
