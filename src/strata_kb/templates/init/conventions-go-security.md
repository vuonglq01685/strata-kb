> This file extends [common/security.md](../common/security.md) with Go-specific content.

# Go security

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/go.local.md`.

## Secret management

```go
apiKey := os.Getenv("OPENAI_API_KEY")
if apiKey == "" {
    log.Fatal("OPENAI_API_KEY not configured")
}
```

## Security scanning

- Use **gosec** for static security analysis:

  ```bash
  gosec ./...
  ```

## Context and timeouts

Always use `context.Context` for timeout control:

```go
ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
defer cancel()
```
