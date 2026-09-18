# Dart / Flutter coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/dart.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Types, enums, extensions: `PascalCase`. Variables, functions,
  parameters: `camelCase`. Files: `snake_case.dart`.
- Booleans read as predicates (`isReady`, `hasPending`).
- Widgets are nouns naming what they render (`UserAvatar`, not
  `BuildUserAvatar`).

## Module structure

- Organise by feature/domain (`lib/<feature>/`), not by widget/model/
  service layering across the whole app.
- Keep widgets and classes small and cohesive; a file past ~400 lines
  is a signal to split.
- Prefer composition over deep widget-inheritance chains.

## Error handling

- Throw typed exceptions (a custom `Exception` subclass), never a bare
  `String`; never swallow a `Future` — every one is awaited, returned,
  or explicitly `.catchError`-handled.
- Fail fast at boundaries: validate external data (API responses, user
  input) before it crosses into typed models.
- `catch` only what the code can handle; rethrow otherwise, preserving
  the stack trace (`Error.throwWithStackTrace` or rethrow `on E`).

## Logging

- Use `dart:developer`'s `log()` (structured, named); never
  `print` for diagnostics in committed code.
- Log where the error is handled, with enough context to act on.

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```dart
const maxAltitudeFt = 60000; // per ATM-STD §5.3 @ v2.1
```

## Testing

- `package:test` for pure Dart, `package:flutter_test` for widgets;
  AAA shape, one behaviour per test.
- Names describe the behaviour: `test("rejects expired token", ...)`,
  not `test("token 2", ...)`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

The preset below is the target strength. When this repo has no linter, the
first task of a dev plan creates these files and records the command as
`cmd.lint`. `dart format --set-exit-if-changed` and `dart analyze`
together cover formatting and lint. Where `cmd.lint` fails on the
untouched tree, narrow the enabled lint set to what passes, and list
each narrowed rule under `## Findings` in the PR body as a tightening
still owed.

`analysis_options.yaml`:

```yaml
include: package:lints/recommended.yaml

linter:
  rules:
    - avoid_print
    - prefer_const_constructors
```

Install and run:

```
dart pub add --dev lints
dart format --set-exit-if-changed . && dart analyze
```

Record as `cmd.lint`: `dart format --set-exit-if-changed . && dart analyze`
