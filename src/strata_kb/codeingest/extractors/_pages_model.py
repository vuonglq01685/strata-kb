"""Shapes shared by `pages.py` and the `_pages_*.py` adapters (leaf module,
so adapters never import `pages.py`)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Page:
    path: str  # full joined path, starts with "/"; params kept as written
    file: str  # repo-relative posix path of the declaring file
    line: int
    group: str = ""  # route group / slot / enclosing layout, as written


@dataclass
class PageResult:
    pages: list[Page] = field(default_factory=list)
    # "file:line" of every recognised routing form that did not become a
    # Page; `pages.py` turns each into a `partial` coverage detail.
    dynamic_sites: list[str] = field(default_factory=list)
    # Next.js `config.matcher` literals as (file, patterns); None = no matcher
    matcher: tuple[str, list[str]] | None = None
    # a parse-based step was skipped because tree-sitter is missing
    not_installed: bool = False


def line_at(data: bytes, offset: int) -> int:
    """1-based line of byte `offset`."""
    return data[:offset].count(b"\n") + 1
