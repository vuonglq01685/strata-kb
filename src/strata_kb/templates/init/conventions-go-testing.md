> This file extends [common/testing.md](../common/testing.md) with Go-specific content.

# Go testing

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/go.local.md`.

## Ground rules

- Standard `testing` package; table-driven tests for behaviour families;
  AAA shape inside each case.
- Names describe the behaviour: `TestRejectsExpiredToken`, subtests via
  `t.Run("expired token", ...)`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Framework

Use the standard `go test` with **table-driven tests**.

## Race detection

Always run with the `-race` flag:

```bash
go test -race ./...
```

## Coverage

```bash
go test -cover ./...
```
