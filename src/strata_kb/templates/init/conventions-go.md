# Go coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/go.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Packages: short, all-lowercase, no underscores; the package name is
  part of the caller's vocabulary (`bytes.Buffer`, not
  `bytesutil.BytesBuffer`).
- Exported identifiers: `PascalCase`; unexported: `camelCase`.
- No `Get` prefix on getters (`user.Name()`, not `user.GetName()`).
- Interfaces with one method end in `-er` (`Reader`, `Resolver`).

## Module structure

- Organise packages by feature/domain; avoid catch-all `util` packages.
- Keep packages small and cohesive; a file past ~400 lines is a signal
  to split.
- Accept interfaces, return concrete types.

## Error handling

- Errors are values: return `error` as the last result, check it at
  every call site; never `_ =` an error away.
- Wrap with context: `fmt.Errorf("resolving ref: %w", err)`; match with
  `errors.Is` / `errors.As`, not string comparison.
- Fail fast at boundaries: validate input where data enters and return
  an error naming the offending value. `panic` only for programmer
  errors.

## Logging

- Use `log/slog` (structured); never `fmt.Println` for diagnostics in
  committed code.
- Log where the error is handled, with key-value context
  (`slog.Error("resolve failed", "ref", ref, "err", err)`).

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```go
const MaxAltitudeFt = 60000 // per ATM-STD §5.3 @ v2.1
```

## Testing

- Standard `testing` package; table-driven tests for behaviour families;
  AAA shape inside each case.
- Names describe the behaviour: `TestRejectsExpiredToken`, subtests via
  `t.Run("expired token", ...)`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

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
