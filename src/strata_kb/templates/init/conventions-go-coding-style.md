> This file extends [common/coding-style.md](../common/coding-style.md) with Go-specific content.

# Go coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/go.local.md`.

## Standards

- The formatter and linter are fixed by the `## Linting (preset)` section of
  `docs/conventions/go.md`; that preset wins over any tool named here.

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

## Design principles

- Accept interfaces, return structs — call sites depend on behaviour, not
  concrete types.
- Keep interfaces small (1-3 methods); a large interface is a design
  smell.

## Error handling

- Errors are values: return `error` as the last result, check it at
  every call site; never `_ =` an error away.
- Wrap with context: `fmt.Errorf("resolving ref: %w", err)`; match with
  `errors.Is` / `errors.As`, not string comparison.
- Fail fast at boundaries: validate input where data enters and return
  an error naming the offending value. `panic` only for programmer
  errors.

```go
if err != nil {
    return fmt.Errorf("failed to create user: %w", err)
}
```

## Logging

- Use `log/slog` (structured); never `fmt.Println` for diagnostics in
  committed code.
- Log where the error is handled, with key-value context
  (`slog.Error("resolve failed", "ref", ref, "err", err)`).
