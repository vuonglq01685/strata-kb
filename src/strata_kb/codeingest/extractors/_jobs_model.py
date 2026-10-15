"""Shapes and literal helpers shared by `jobs.py` and the per-language
scanners (`_jobs_adapters.py`, `_jobs_dotnet.py`, `_jobs_native.py`).

A scanner receives a `Ctx` (the parsed file) and calls `add()` once per
scheduled job it recognises. A schedule it cannot read as a literal is
reported through `dyn()`: the job is still listed, as `(dynamic)`, and the
`file:line` becomes a `partial` coverage site -- never dropped. Names only:
a constant, env var or config key is never emitted, only literals written
in the source.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_jsutil import _site, _text

if TYPE_CHECKING:
    from tree_sitter import Node

DYNAMIC = "(dynamic)"
ANONYMOUS = "(anonymous)"
UNNAMED = "(unnamed)"

_NUMBER_TYPES = frozenset(
    {
        "number",  # js/ts
        "integer",  # python
        "float",  # python
        "decimal_integer_literal",  # java
        "decimal_floating_point_literal",  # java
        "integer_literal",  # kotlin/csharp/rust
        "long_literal",  # kotlin
        "real_literal",  # csharp
        "int_literal",  # go
        "float_literal",  # go
    }
)
_NUMBER_RE = re.compile(r"(\d[\d_]*(?:\.\d+)?)[lLfFdDuU]*")
# `${app.cron}`, `{my.cron}`, `#{...}`: a config reference, not a schedule
_PLACEHOLDER_RE = re.compile(r"[${]")


@dataclass(frozen=True)
class Job:
    name: str
    schedule: str
    handler: str
    file: str  # repo-relative posix path of the declaring file or manifest
    line: int


@dataclass
class Ctx:
    """One parsed file and what its scanners found."""

    rel: str
    root: Node
    jobs: list[Job] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)

    def dyn(self, node: Node) -> str:
        self.sites.append(_site(self.rel, node))
        return DYNAMIC

    def add(self, name: str, schedule: str, handler: str, node: Node) -> None:
        self.jobs.append(
            Job(
                " ".join(name.split()) or DYNAMIC,
                " ".join(schedule.split()),
                " ".join(handler.split()) or "-",
                self.rel,
                _ts.line_of(node),
            )
        )


class Scanner(NamedTuple):
    gate: re.Pattern[bytes]  # a file without a match is not even parsed
    run: Callable[[Ctx], None]


def num(node: Node | None) -> str | None:
    """A plain numeric literal as written (`5_000L` -> `5000`), else None."""
    if node is None or node.type not in _NUMBER_TYPES:
        return None
    found = _NUMBER_RE.fullmatch(_text(node))
    return found.group(1).replace("_", "") if found else None


def plain(text: str | None) -> str | None:
    """`text` unless it is missing or a config placeholder (`${x}`, `{{ x }}`)."""
    return None if text is None or _PLACEHOLDER_RE.search(text) else text


def cron_text(node: Node | None) -> str | None:
    """A string literal that is not a config placeholder, else None."""
    return plain(_ts.string_literal(node)) if node is not None else None


def enclosing(node: Node, types: frozenset[str]) -> str:
    """Name of the closest ancestor of one of `types` ("" when none)."""
    current = node.parent
    while current is not None:
        if current.type in types:
            named = current.child_by_field_name("name")
            if named is None:
                named = next(
                    (
                        c
                        for c in current.named_children
                        if c.type in ("type_identifier", "identifier", "name")
                    ),
                    None,
                )
            return _text(named)
        current = current.parent
    return ""


def qualified(owner: str, method: str) -> str:
    return f"{owner}.{method}" if owner else method
