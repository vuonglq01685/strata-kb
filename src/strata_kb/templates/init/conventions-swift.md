# Swift coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/swift.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/swift.local.md` wins over both.

| Topic | Swift | Shared |
|---|---|---|
| Coding style | [swift/coding-style.md](swift/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [swift/patterns.md](swift/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [swift/security.md](swift/security.md) | [common/security.md](common/security.md) |
| Testing | [swift/testing.md](swift/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [swift/hooks.md](swift/hooks.md) | [common/hooks.md](common/hooks.md) |

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```swift
let maxAltitudeFt = 60_000 // per ATM-STD §5.3 @ v2.1
```

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
