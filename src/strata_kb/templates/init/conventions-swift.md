# Swift coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/swift.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Types, protocols, enums: `PascalCase`. Variables, functions, enum
  cases: `camelCase`.
- Booleans read as predicates (`isReady`, `hasPending`).
- Protocols describing a capability end in `-able`/`-ing` (`Equatable`,
  `Cancelling`); protocols describing a role are nouns (`DataSource`).

## Module structure

- Organise by feature/domain; one `Sources/<Target>` per independently
  buildable unit in `Package.swift`.
- Keep types small and cohesive; a file past ~400 lines is a signal to
  split.
- Depend on protocols at boundaries, inject concrete types at the
  composition root.

## Error handling

- Model recoverable failure with `throws` + a typed `Error` enum;
  `Result<Success, Failure>` where the call is async-callback-based.
- Never `try!`/force-unwrap on external input; `try?` only when the
  caller genuinely has no use for the failure reason.
- Fail fast at boundaries: validate external data (API responses, user
  input) before it crosses into typed code.

## Logging

- Use `os.Logger` (structured, category-scoped); never `print` for
  diagnostics in committed code.
- Log where the error is handled, with enough context to act on
  (`logger.error("resolve failed: \(error, privacy: .public)")`).

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```swift
let maxAltitudeFt = 60_000 // per ATM-STD §5.3 @ v2.1
```

## Testing

- XCTest (or `swift-testing` where the repo has adopted it); AAA shape,
  one behaviour per test.
- Names describe the behaviour: `func test_rejectsExpiredToken()`, not
  `func test2()`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

The preset below is the target strength. When this repo has no linter, the
first task of a dev plan creates these files and records the command as
`cmd.lint`. SwiftLint and swift-format together cover lint and
formatting. Where `cmd.lint` fails on the untouched tree, narrow
`disabled_rules` / warning caps to what passes, and list each narrowed
rule under `## Findings` in the PR body as a tightening still owed.

`.swiftlint.yml`:

```yaml
opt_in_rules:
  - force_unwrapping
disabled_rules: []
```

`.swift-format`:

```json
{
  "indentation": { "spaces": 4 },
  "lineLength": 100
}
```

Install and run:

```
brew install swiftlint swift-format
swiftlint lint --strict && swift-format lint --recursive Sources
```

Record as `cmd.lint`: `swiftlint lint --strict && swift-format lint --recursive Sources`
