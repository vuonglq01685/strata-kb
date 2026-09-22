> This file extends [common/patterns.md](../common/patterns.md) with Python-specific content.

# Python patterns

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/python.local.md`.

## Protocol (duck typing)

```python
from typing import Protocol

class Repository(Protocol):
    def find_by_id(self, id: str) -> dict | None: ...
    def save(self, entity: dict) -> dict: ...
```

## Dataclasses as DTOs

```python
from dataclasses import dataclass

@dataclass
class CreateUserRequest:
    name: str
    email: str
    age: int | None = None
```

## Context managers and generators

- Use context managers (`with` statement) for resource management
- Use generators for lazy evaluation and memory-efficient iteration
