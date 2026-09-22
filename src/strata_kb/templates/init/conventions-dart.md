# Dart / Flutter coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/dart.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/dart.local.md` wins over both.

| Topic | Dart / Flutter | Shared |
|---|---|---|
| Coding style | [dart/coding-style.md](dart/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [dart/patterns.md](dart/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [dart/security.md](dart/security.md) | [common/security.md](common/security.md) |
| Testing | [dart/testing.md](dart/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [dart/hooks.md](dart/hooks.md) | [common/hooks.md](common/hooks.md) |

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```dart
const maxAltitudeFt = 60000; // per ATM-STD §5.3 @ v2.1
```

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
