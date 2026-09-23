> This file extends [common/coding-style.md](../common/coding-style.md) with Python-specific content.

# Python coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/python.local.md`.

## Standards

- Follow **PEP 8**.
- Use **type annotations** on every function signature.
- The formatter and linter are fixed by the `## Linting (preset)` section of
  `docs/conventions/python.md`; that preset wins over any tool named here.

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

## Immutability

Prefer immutable data structures — a new object, never a mutated one:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    name: str
    email: str
```

```python
from typing import NamedTuple


class Point(NamedTuple):
    x: float
    y: float
```

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
