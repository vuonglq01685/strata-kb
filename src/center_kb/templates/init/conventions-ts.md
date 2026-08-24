# TypeScript / JavaScript coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/ts.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Variables and functions: `camelCase`, descriptive; booleans read as
  predicates (`isReady`, `hasPending`, `shouldRetry`).
- Types, interfaces, classes, enums, React components: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE` for true module-level constants.
- Files: follow the repo's dominant style; when there is none,
  `kebab-case.ts` for modules, `PascalCase.tsx` for components.

## Module structure

- Organise by feature/domain, not by technical layer.
- One clear responsibility per file; ~200–400 lines typical, 800 max —
  extract before crossing it.
- Prefer named exports; a default export only for the file's single main
  artifact (e.g. a component).
- No deep relative import chains (`../../../`) — use the repo's path
  aliases when it has them.

## Error handling

- Throw `Error` subclasses, never strings; never swallow a rejection —
  every promise is awaited, returned, or explicitly `.catch`-handled.
- Fail fast at boundaries: validate external data (API responses, user
  input, file content) before it crosses into typed code.
- `catch` only what the code can handle; rethrow with cause otherwise:
  `throw new AppError("...", { cause: err })`.

## Logging

- Use the repo's logging facility; never `console.log` in committed
  code (a structured logger, or nothing).
- Log where the error is handled, with enough context to act on.

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```ts
const MAX_ALTITUDE_FT = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Testing

- The repo's test runner (vitest/jest), AAA shape, one behaviour per
  test.
- Names describe the behaviour: `test("rejects expired token")`, not
  `test("token 2")`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

When this repo has no linter, the first task of a dev plan creates the
files below exactly as shown and records the command as `cmd.lint`.

`eslint.config.mjs`:

```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
);
```

`.prettierrc.json`:

```json
{
  "singleQuote": false,
  "trailingComma": "all"
}
```

`.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2
```

Install and run:

```
npm install --save-dev eslint @eslint/js typescript-eslint prettier
npx eslint . && npx prettier --check .
```

Record as `cmd.lint`: `npx eslint . && npx prettier --check .`
