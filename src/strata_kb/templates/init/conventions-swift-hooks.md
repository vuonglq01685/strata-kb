> This file extends [common/hooks.md](../common/hooks.md) with Swift-specific content.

# Swift hooks

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/swift.local.md`.

## PostToolUse hooks

Configure in `.claude/settings.json` (this repo's, committed):

- **SwiftFormat**: auto-format `.swift` files after edit.
- **SwiftLint**: run lint checks after editing `.swift` files.
- **swift build**: type-check modified packages after edit.

## Warnings

Flag `print()` statements — use `os.Logger` or structured logging
instead for production code.
