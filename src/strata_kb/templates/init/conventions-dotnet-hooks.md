> This file extends [common/hooks.md](../common/hooks.md) with C# / .NET-specific content.

# C# / .NET hooks

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/dotnet.local.md`.

## PostToolUse hooks

Configure in `.claude/settings.json` (this repo's, committed):

- **dotnet format**: Auto-format edited C# files and apply analyzer
  fixes.
- **dotnet build**: Verify the solution or project still compiles
  after edits.
- **dotnet test --no-build**: Re-run the nearest relevant test project
  after behavior changes.

## Stop hooks

- Run a final `dotnet build` before ending a session with broad C#
  changes.
- Warn on modified `appsettings*.json` files so secrets do not get
  committed.
