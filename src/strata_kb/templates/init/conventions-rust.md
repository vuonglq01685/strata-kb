# Rust coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/rust.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/rust.local.md` wins over both.

| Topic | Rust | Shared |
|---|---|---|
| Coding style | [rust/coding-style.md](rust/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [rust/patterns.md](rust/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [rust/security.md](rust/security.md) | [common/security.md](common/security.md) |
| Testing | [rust/testing.md](rust/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [rust/hooks.md](rust/hooks.md) | [common/hooks.md](common/hooks.md) |

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```rust
const MAX_ALTITUDE_FT: u32 = 60_000; // per ATM-STD §5.3 @ v2.1
```

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
