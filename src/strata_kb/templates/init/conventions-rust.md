# Rust coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/rust.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Modules, functions, variables: `snake_case`. Types, traits, enums:
  `PascalCase`. Constants and statics: `UPPER_SNAKE_CASE`.
- Booleans read as predicates (`is_ready`, `has_pending`).
- Getters have no `get_` prefix (`user.name()`, not `user.get_name()`);
  keep `get_` only for a genuinely fallible or indexed lookup.

## Module structure

- Organise by feature/domain, not by technical layer; one crate per
  independently-versioned/publishable unit.
- Keep modules cohesive; a file past ~400 lines is a signal to split.
- Accept `&dyn Trait` / generics at boundaries, return concrete types
  from constructors.

## Error handling

- Library crates: define error enums with `thiserror`; never panic on
  reachable input. Binary crates: `anyhow::Result` at the top level.
- Wrap with context: `.context("resolving ref")`; match with pattern
  matching, not string comparison on the message.
- `unwrap`/`expect` only where the invariant is enforced by the type
  system or checked immediately above; never on external input.

## Logging

- Use `tracing` (structured spans + fields); never `println!` for
  diagnostics in committed code.
- Log where the error is handled, with key-value context
  (`tracing::error!(ref = %ref, err = %err, "resolve failed")`).

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```rust
const MAX_ALTITUDE_FT: u32 = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Testing

- `#[cfg(test)]` module per file for units; `tests/` directory for
  integration tests. AAA shape inside each test.
- Names describe the behaviour: `fn rejects_expired_token()`, not
  `fn test_token_2()`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

The preset below is the target strength. When this repo has no linter, the
first task of a dev plan creates these files and records the command as
`cmd.lint`. `cargo fmt --check` and `cargo clippy` together cover both
formatting and lint. Where `cmd.lint` fails on the untouched tree, narrow
`select` / rules / warning caps to what passes, and list each narrowed
rule under `## Findings` in the PR body as a tightening still owed.

`.rustfmt.toml`:

```toml
edition = "2021"
max_width = 100
```

`clippy.toml`:

```toml
# repo-specific clippy thresholds go here; empty file is a valid default
```

Install and run:

```
rustup component add rustfmt clippy
cargo fmt --check && cargo clippy --all-targets -- -D warnings
```

Record as `cmd.lint`: `cargo fmt --check && cargo clippy --all-targets -- -D warnings`
