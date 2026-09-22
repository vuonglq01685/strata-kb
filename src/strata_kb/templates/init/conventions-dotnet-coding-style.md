> This file extends [common/coding-style.md](../common/coding-style.md) with C# / .NET-specific content.

# C# / .NET coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/dotnet.local.md`.

## Naming

- Namespaces, classes, records, structs, enums, methods, properties:
  `PascalCase`; interfaces prefixed `I` (`IResolver`).
- Locals and parameters: `camelCase`; private fields `_camelCase`.
- Constants: `PascalCase` (`MaxAltitudeFt`).
- Async methods end in `Async`.

## Module structure

- Organise by feature/domain, not by technical layer alone.
- One top-level type per file, file named after it; extract before a
  class grows past ~400 lines.
- Depend on interfaces at boundaries; use the built-in DI container,
  no service-locator calls in business logic.

## Standards

- Follow current .NET conventions and enable nullable reference types.
- Prefer explicit access modifiers on public and internal APIs.
- Keep files aligned with the primary type they define.
- The formatter and linter are fixed by the `## Linting (preset)` section
  of `docs/conventions/dotnet.md`; that preset wins over any tool named
  here.
- Prefer expression-bodied members only when they stay readable.

## Types and models

- Prefer `record` or `record struct` for immutable value-like models.
- Use `class` for entities or types with identity and lifecycle.
- Use `interface` for service boundaries and abstractions.
- Avoid `dynamic` in application code; prefer generics or explicit
  models.

```csharp
public sealed record UserDto(Guid Id, string Email);

public interface IUserRepository
{
    Task<UserDto?> FindByIdAsync(Guid id, CancellationToken cancellationToken);
}
```

## Immutability

- Prefer `init` setters, constructor parameters, and immutable
  collections for shared state.
- Do not mutate input models in-place when producing updated state.

```csharp
public sealed record UserProfile(string Name, string Email);

public static UserProfile Rename(UserProfile profile, string name) =>
    profile with { Name = name };
```

## Async

- Prefer `async`/`await` over blocking calls like `.Result` or
  `.Wait()`.
- Pass `CancellationToken` through public async APIs.

## Error handling

- Throw specific exception types; never `catch (Exception) {}` — a
  swallowed exception is a bug.
- Fail fast at boundaries: validate arguments where data enters
  (`ArgumentNullException.ThrowIfNull`, explicit checks naming the
  offending value).
- Catch only what the code can handle; otherwise wrap and rethrow with
  the original as `InnerException`.

```csharp
public async Task<Order> LoadOrderAsync(
    Guid orderId,
    CancellationToken cancellationToken)
{
    try
    {
        return await repository.FindAsync(orderId, cancellationToken)
            ?? throw new InvalidOperationException($"Order {orderId} was not found.");
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "Failed to load order {OrderId}", orderId);
        throw;
    }
}
```

## Logging

- Use `Microsoft.Extensions.Logging` (`ILogger<T>`); never
  `Console.WriteLine` for diagnostics in committed code.
- Use structured message templates
  (`_logger.LogError("resolve failed for {Ref}", reference)`), not
  string interpolation.
