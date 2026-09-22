> This file extends [common/coding-style.md](../common/coding-style.md) with Swift-specific content.

# Swift coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/swift.local.md`.

## Standards

- The formatter and linter are fixed by the `## Linting (preset)` section of
  `docs/conventions/swift.md`; that preset wins over any tool named here.

## Naming

- Types, protocols, enums: `PascalCase`. Variables, functions, enum
  cases: `camelCase`.
- Booleans read as predicates (`isReady`, `hasPending`).
- Protocols describing a capability end in `-able`/`-ing` (`Equatable`,
  `Cancelling`); protocols describing a role are nouns (`DataSource`).
- Follow the Swift API Design Guidelines: clarity at the point of use —
  omit needless words — and name methods and properties for their roles,
  not their types.
- Use `static let` for constants over global constants.

## Module structure

- Organise by feature/domain; one `Sources/<Target>` per independently
  buildable unit in `Package.swift`.
- Keep types small and cohesive; a file past ~400 lines is a signal to
  split.
- Depend on protocols at boundaries, inject concrete types at the
  composition root.

## Immutability

- Prefer `let` over `var` — define everything as `let` and only change to
  `var` if the compiler requires it.
- Use `struct` with value semantics by default; use `class` only when
  identity or reference semantics are needed.

## Concurrency

Enable Swift 6 strict concurrency checking. Prefer:

- `Sendable` value types for data crossing isolation boundaries.
- Actors for shared mutable state.
- Structured concurrency (`async let`, `TaskGroup`) over unstructured
  `Task {}`.

## Error handling

- Model recoverable failure with `throws` + a typed `Error` enum;
  `Result<Success, Failure>` where the call is async-callback-based.
- Never `try!`/force-unwrap on external input; `try?` only when the
  caller genuinely has no use for the failure reason.
- Fail fast at boundaries: validate external data (API responses, user
  input) before it crosses into typed code.

```swift
func load(id: String) throws(LoadError) -> Item {
    guard let data = try? read(from: path) else {
        throw .fileNotFound(id)
    }
    return try decode(data)
}
```

## Logging

- Use `os.Logger` (structured, category-scoped); never `print` for
  diagnostics in committed code.
- Log where the error is handled, with enough context to act on
  (`logger.error("resolve failed: \(error, privacy: .public)")`).
