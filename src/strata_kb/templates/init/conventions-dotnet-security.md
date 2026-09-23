> This file extends [common/security.md](../common/security.md) with C# / .NET-specific content.

# C# / .NET security

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/dotnet.local.md`.

## Secret management

- Never hardcode API keys, tokens, or connection strings in source
  code.
- Use environment variables, user secrets for local development, and a
  secret manager in production.
- Keep `appsettings.*.json` free of real credentials.

```csharp
// BAD
const string ApiKey = "sk-live-123";

// GOOD
var apiKey = builder.Configuration["OpenAI:ApiKey"]
    ?? throw new InvalidOperationException("OpenAI:ApiKey is not configured.");
```

## SQL injection prevention

- Always use parameterized queries with ADO.NET, Dapper, or EF Core.
- Never concatenate user input into SQL strings.
- Validate sort fields and filter operators before using dynamic query
  composition.

```csharp
const string sql = "SELECT * FROM Orders WHERE CustomerId = @customerId";
await connection.QueryAsync<Order>(sql, new { customerId });
```

## Input validation

- Validate DTOs at the application boundary.
- Use data annotations, FluentValidation, or explicit guard clauses.
- Reject invalid model state before running business logic.

## Authentication and authorization

- Prefer framework auth handlers instead of custom token parsing.
- Enforce authorization policies at endpoint or handler boundaries.
- Never log raw tokens, passwords, or PII.

## Error handling

- Return safe client-facing messages.
- Log detailed exceptions with structured context server-side.
- Do not expose stack traces, SQL text, or filesystem paths in API
  responses.
