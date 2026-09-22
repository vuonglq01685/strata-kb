# C# / .NET coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/dotnet.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/dotnet.local.md` wins over both.

| Topic | C# / .NET | Shared |
|---|---|---|
| Coding style | [dotnet/coding-style.md](dotnet/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [dotnet/patterns.md](dotnet/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [dotnet/security.md](dotnet/security.md) | [common/security.md](common/security.md) |
| Testing | [dotnet/testing.md](dotnet/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [dotnet/hooks.md](dotnet/hooks.md) | [common/hooks.md](common/hooks.md) |

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```csharp
const int MaxAltitudeFt = 60_000; // per ATM-STD §5.3 @ v2.1
```

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
