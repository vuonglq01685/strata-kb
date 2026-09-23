# TypeScript / JavaScript coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/ts.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/ts.local.md` wins over both.

| Topic | TypeScript / JavaScript | Shared |
|---|---|---|
| Coding style | [ts/coding-style.md](ts/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [ts/patterns.md](ts/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [ts/security.md](ts/security.md) | [common/security.md](common/security.md) |
| Testing | [ts/testing.md](ts/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [ts/hooks.md](ts/hooks.md) | [common/hooks.md](common/hooks.md) |

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```ts
const MAX_ALTITUDE_FT = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Linting (preset)

The preset below is the target strength. When this repo has no linter, the
first task of a dev plan creates these files and records the command as
`cmd.lint`. Where `cmd.lint` fails on the untouched tree, narrow `select` /
rules / warning caps to what passes, and list each narrowed rule under
`## Findings` in the PR body as a tightening still owed.

`eslint.config.mjs`:

```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { rules: { "no-console": "error" } },
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
