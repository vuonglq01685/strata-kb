"""Import layering between the serving packages (1.15.1, review §4.2):
`serving` is transport-neutral; `web` never imports `mcp`; `intake` never
imports `web`. `mcp.main()` composing the http app from `web.app` is the one
allowed edge from mcp to web, and it is a lazy import inside a function."""

from __future__ import annotations

import ast
from pathlib import Path

import strata_kb

SRC = Path(strata_kb.__file__).parent


def _imports(path: Path, *, top_level_only: bool = False) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = tree.body if top_level_only else list(ast.walk(tree))
    found: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def _hits(path: Path, prefix: str, **kw) -> list[str]:
    return sorted(
        m for m in _imports(path, **kw) if m == prefix or m.startswith(prefix + ".")
    )


def test_web_never_imports_mcp():
    for path in (SRC / "web").glob("*.py"):
        assert _hits(path, "strata_kb.mcp") == [], path.name


def test_serving_imports_neither_transport():
    for path in (SRC / "serving").glob("*.py"):
        assert _hits(path, "strata_kb.mcp") == [], path.name
        assert _hits(path, "strata_kb.web") == [], path.name


def test_intake_never_imports_web():
    assert _hits(SRC / "intake.py", "strata_kb.web") == []


def test_mcp_imports_web_only_lazily():
    assert _hits(SRC / "mcp.py", "strata_kb.web", top_level_only=True) == []
