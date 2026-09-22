> This file extends [common/testing.md](../common/testing.md) with C# / .NET-specific content.

# C# / .NET testing

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/dotnet.local.md`.

## Ground rules

- xUnit, AAA shape (Arrange–Act–Assert), one behaviour per test.
- Names describe the behaviour: `RejectsExpiredToken()`, not `Test2()`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Test framework

- Prefer **xUnit** for unit and integration tests.
- Use **FluentAssertions** for readable assertions.
- Use **Moq** or **NSubstitute** for mocking dependencies.
- Use **Testcontainers** when integration tests need real
  infrastructure.

## Test organization

- Mirror `src/` structure under `tests/`.
- Separate unit, integration, and end-to-end coverage clearly.
- Name tests by behavior, not implementation details.

```csharp
public sealed class OrderServiceTests
{
    [Fact]
    public async Task FindByIdAsync_ReturnsOrder_WhenOrderExists()
    {
        // Arrange
        // Act
        // Assert
    }
}
```

## ASP.NET Core integration tests

- Use `WebApplicationFactory<TEntryPoint>` for API integration
  coverage.
- Test auth, validation, and serialization through HTTP, not by
  bypassing middleware.

## Coverage

- Focus coverage on domain logic, validation, auth, and failure paths.
- Run `dotnet test` in CI with coverage collection enabled where
  available.
