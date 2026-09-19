# Python coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/python.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Modules and packages: `snake_case`, short, no hyphens.
- Functions, methods, variables: `snake_case`, descriptive; booleans read
  as predicates (`is_ready`, `has_pending`, `should_retry`).
- Classes and exceptions: `PascalCase`; exception names end in `Error`.
- Constants: `UPPER_SNAKE_CASE` at module level.
- No abbreviations the codebase does not already use.

## Module structure

- Organise by feature/domain, not by technical layer.
- One clear responsibility per module; ~200–400 lines typical, 800 max —
  extract helpers before crossing it.
- Public surface first: module docstring, constants, then the functions
  and classes callers import; `_`-prefixed helpers below them.
- Imports at the top, grouped stdlib → third-party → local; no wildcard
  imports.

## Error handling

- Raise specific exceptions; never bare `except:` and never
  `except Exception: pass` — a silently swallowed error is a bug.
- Fail fast at boundaries: validate input where data enters the system
  and raise with a message naming the offending value.
- Catch only what the code can actually handle; otherwise re-raise with
  context: `raise NewError(...) from err`.

## Logging

- Use the `logging` module; never `print()` in committed code.
- One logger per module: `logger = logging.getLogger(__name__)`.
- Log where the error is handled, with enough context to act on. DEBUG
  for flow detail, INFO for state changes, WARNING for recoverable
  oddities, ERROR for failures.

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```python
MAX_ALTITUDE_FT = 60_000  # per ATM-STD §5.3 @ v2.1
```

## Testing

- pytest, AAA shape (Arrange–Act–Assert), one behaviour per test.
- Names describe the behaviour: `test_rejects_expired_token`, not
  `test_token_2`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

The preset below is the target strength. When this repo has no linter, the
first task of a dev plan creates these files and records the command as
`cmd.lint`. Where `cmd.lint` fails on the untouched tree, narrow `select` /
rules / warning caps to what passes, and list each narrowed rule under
`## Findings` in the PR body as a tightening still owed.

`ruff.toml`:

```toml
target-version = "py311"
line-length = 88

[lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "T20", "N"]

[format]
quote-style = "double"
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

[*.py]
indent_size = 4
```

Install and run:

```
pip install ruff
ruff check . && ruff format --check .
```

Record as `cmd.lint`: `ruff check . && ruff format --check .`
