# Go coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/go.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/go.local.md` wins over both.

| Topic | Go | Shared |
|---|---|---|
| Coding style | [go/coding-style.md](go/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [go/patterns.md](go/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [go/security.md](go/security.md) | [common/security.md](common/security.md) |
| Testing | [go/testing.md](go/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [go/hooks.md](go/hooks.md) | [common/hooks.md](common/hooks.md) |

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```go
const MaxAltitudeFt = 60000 // per ATM-STD §5.3 @ v2.1
```

## Linting (preset)

The preset below is the target strength. When this repo has no linter, the
first task of a dev plan creates these files and records the command as
`cmd.lint`. gofmt runs as a golangci-lint linter, so one command covers
both. Where `cmd.lint` fails on the untouched tree, narrow `select` /
rules / warning caps to what passes, and list each narrowed rule under
`## Findings` in the PR body as a tightening still owed.

`.golangci.yml`:

```yaml
run:
  timeout: 5m
linters:
  enable:
    - govet
    - staticcheck
    - errcheck
    - gofmt
```

`.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

[*.go]
indent_style = tab
```

Install and run:

```
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
golangci-lint run
```

Record as `cmd.lint`: `golangci-lint run`
