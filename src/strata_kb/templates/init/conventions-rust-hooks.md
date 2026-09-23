> This file extends [common/hooks.md](../common/hooks.md) with Rust-specific content.

# Rust hooks

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/rust.local.md`.

## PostToolUse hooks

Configure in `.claude/settings.json` (this repo's, committed):

- **cargo fmt**: Auto-format `.rs` files after edit
- **cargo clippy**: Run lint checks after editing Rust files
- **cargo check**: Verify compilation after changes (faster than `cargo build`)
