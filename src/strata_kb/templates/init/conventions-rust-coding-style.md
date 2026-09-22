> This file extends [common/coding-style.md](../common/coding-style.md) with Rust-specific content.

# Rust coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/rust.local.md`.

## Naming

- Modules, functions, variables: `snake_case`. Types, traits, enums:
  `PascalCase`. Constants and statics: `UPPER_SNAKE_CASE`.
- Booleans read as predicates (`is_ready`, `has_pending`).
- Getters have no `get_` prefix (`user.name()`, not `user.get_name()`);
  keep `get_` only for a genuinely fallible or indexed lookup.
- Lifetimes: short lowercase (`'a`, `'de`); descriptive names for
  complex cases (`'input`).

## Module structure

- Organise by feature/domain, not by technical layer; one crate per
  independently-versioned/publishable unit.
- Keep modules cohesive; a file past ~400 lines is a signal to split.
- Accept `&dyn Trait` / generics at boundaries, return concrete types
  from constructors.

```text
src/
├── main.rs
├── lib.rs
├── auth/           # Domain module
│   ├── mod.rs
│   ├── token.rs
│   └── middleware.rs
├── orders/         # Domain module
│   ├── mod.rs
│   ├── model.rs
│   └── service.rs
└── db/             # Infrastructure
    ├── mod.rs
    └── pool.rs
```

## Immutability

Rust variables are immutable by default — embrace this:

- Use `let` by default; only use `let mut` when mutation is required
- Prefer returning new values over mutating in place
- Use `Cow<'_, T>` when a function may or may not need to allocate

```rust
use std::borrow::Cow;

// GOOD — immutable by default, new value returned
fn normalize(input: &str) -> Cow<'_, str> {
    if input.contains(' ') {
        Cow::Owned(input.replace(' ', "_"))
    } else {
        Cow::Borrowed(input)
    }
}

// BAD — unnecessary mutation
fn normalize_bad(input: &mut String) {
    *input = input.replace(' ', "_");
}
```

## Ownership and borrowing

- Borrow (`&T`) by default; take ownership only when you need to store or consume
- Never clone to satisfy the borrow checker without understanding the root cause
- Accept `&str` over `String`, `&[T]` over `Vec<T>` in function parameters
- Use `impl Into<String>` for constructors that need to own a `String`

```rust
// GOOD — borrows when ownership isn't needed
fn word_count(text: &str) -> usize {
    text.split_whitespace().count()
}

// GOOD — takes ownership in constructor via Into
fn new(name: impl Into<String>) -> Self {
    Self { name: name.into() }
}

// BAD — takes String when &str suffices
fn word_count_bad(text: String) -> usize {
    text.split_whitespace().count()
}
```

## Iterators over loops

Prefer iterator chains for transformations; use loops for complex control flow:

```rust
// GOOD — declarative and composable
let active_emails: Vec<&str> = users.iter()
    .filter(|u| u.is_active)
    .map(|u| u.email.as_str())
    .collect();

// GOOD — loop for complex logic with early returns
for user in &users {
    if let Some(verified) = verify_email(&user.email)? {
        send_welcome(&verified)?;
    }
}
```

## Visibility

- Default to private; use `pub(crate)` for internal sharing
- Only mark `pub` what is part of the crate's public API
- Re-export public API from `lib.rs`

## Error handling

- Library crates: define error enums with `thiserror`; never panic on
  reachable input. Binary crates: `anyhow::Result` at the top level.
- Wrap with context: `.context("resolving ref")`; match with pattern
  matching, not string comparison on the message.
- `unwrap`/`expect` only where the invariant is enforced by the type
  system or checked immediately above; never on external input.

```rust
// GOOD — library error with thiserror
#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("failed to read config: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid config format: {0}")]
    Parse(String),
}

// GOOD — application error with anyhow
use anyhow::Context;

fn load_config(path: &str) -> anyhow::Result<Config> {
    let content = std::fs::read_to_string(path)
        .with_context(|| format!("failed to read {path}"))?;
    toml::from_str(&content)
        .with_context(|| format!("failed to parse {path}"))
}
```

## Logging

- Use `tracing` (structured spans + fields); never `println!` for
  diagnostics in committed code.
- Log where the error is handled, with key-value context
  (`tracing::error!(ref = %ref, err = %err, "resolve failed")`).
