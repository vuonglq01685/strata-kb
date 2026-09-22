# Hooks — shared

Language-agnostic rules, scaffolded into every dev repo. A file under
`docs/conventions/<lang>/` extends its counterpart here; where the two
disagree, the language file wins. Record repo-specific deviations in the
relevant `docs/conventions/<lang>.local.md`.

Hooks are configured per repo in `.claude/settings.json`, committed with the
code. Nothing here refers to a user-level configuration.

## Hook types

- **PreToolUse**: Before tool execution (validation, parameter modification)
- **PostToolUse**: After tool execution (auto-format, checks)
- **Stop**: When session ends (final verification)

## Auto-accept permissions

Use with caution:
- Enable for trusted, well-defined plans
- Disable for exploratory work
- Never use dangerously-skip-permissions flag
- Configure `permissions.allow` in this repo's `.claude/settings.json` instead
