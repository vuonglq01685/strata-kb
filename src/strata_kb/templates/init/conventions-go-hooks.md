> This file extends [common/hooks.md](../common/hooks.md) with Go-specific content.

# Go hooks

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/go.local.md`.

## PostToolUse hooks

Configure in `.claude/settings.json` (this repo's, committed):

- **gofmt/goimports**: auto-format `.go` files after edit.
- **go vet**: run static analysis after editing `.go` files.
- **staticcheck**: run extended static checks on modified packages.
