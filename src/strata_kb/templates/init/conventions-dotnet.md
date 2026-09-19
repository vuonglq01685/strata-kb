# C# / .NET coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/dotnet.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

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

## Error handling

- Throw specific exception types; never `catch (Exception) {}` — a
  swallowed exception is a bug.
- Fail fast at boundaries: validate arguments where data enters
  (`ArgumentNullException.ThrowIfNull`, explicit checks naming the
  offending value).
- Catch only what the code can handle; otherwise wrap and rethrow with
  the original as `InnerException`.

## Logging

- Use `Microsoft.Extensions.Logging` (`ILogger<T>`); never
  `Console.WriteLine` for diagnostics in committed code.
- Use structured message templates
  (`_logger.LogError("resolve failed for {Ref}", reference)`), not
  string interpolation.

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```csharp
const int MaxAltitudeFt = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Testing

- xUnit, AAA shape (Arrange–Act–Assert), one behaviour per test.
- Names describe the behaviour: `RejectsExpiredToken()`, not `Test2()`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

The preset below is the target strength. When this repo has no linter, the
first task of a dev plan creates the `.editorconfig` below (format AND
analyzer severities live there), enables analyzers in the project file,
and records the command as `cmd.lint`. Where `cmd.lint` fails on the
untouched tree, narrow `select` / rules / warning caps to what passes,
and list each narrowed rule under `## Findings` in the PR body as a
tightening still owed.

`.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.cs]
indent_size = 4
dotnet_analyzer_diagnostic.category-Style.severity = warning
dotnet_diagnostic.IDE0005.severity = warning
```

Project file (inside `<PropertyGroup>`):

```xml
<EnableNETAnalyzers>true</EnableNETAnalyzers>
<EnforceCodeStyleInBuild>true</EnforceCodeStyleInBuild>
```

Run:

```
dotnet format --verify-no-changes
```

Record as `cmd.lint`: `dotnet format --verify-no-changes`
