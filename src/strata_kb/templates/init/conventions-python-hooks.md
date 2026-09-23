> This file extends [common/hooks.md](../common/hooks.md) with Python-specific content.

# Python hooks

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/python.local.md`.

## PostToolUse hooks

Configure in `.claude/settings.json` (this repo's, committed):

- **ruff**: `ruff format` then `ruff check --fix` on the edited `.py` file.
- **mypy** or **pyright**: type-check after editing a `.py` file, if the
  repo has either configured.

## Warnings

- Warn about `print()` statements in edited files (use `logging` module instead)
