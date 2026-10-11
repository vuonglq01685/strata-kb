"""Import layering between the serving packages (1.15.1, review §4.2):
`serving` is transport-neutral; `web` never imports `mcp`; `intake` never
imports `web`. `mcp.main()` composing the http app from `web.app` is the one
allowed edge from mcp to web, and it is a lazy import inside a function.

Two whole-package rules sit on top: no import cycle among `strata_kb`
modules, even through function-level imports (a lazy import hides a cycle
from the interpreter, not from the design), and `prlint`/`mdmask` import
only the standard library, so the PR-lint CI job needs no installed extras."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import strata_kb

SRC = Path(strata_kb.__file__).parent


def _runtime_nodes(nodes: list[ast.stmt]) -> Iterator[ast.AST]:
    """Every node under `nodes`, minus `if TYPE_CHECKING:` subtrees, which
    never run."""
    for node in nodes:
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            yield from _runtime_nodes(node.orelse)
            continue
        yield from ast.walk(node)


def _imports(
    path: Path, *, top_level_only: bool = False, runtime_only: bool = False
) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if top_level_only:
        nodes: list[ast.AST] = list(tree.body)
    elif runtime_only:
        nodes = list(_runtime_nodes(tree.body))
    else:
        nodes = list(ast.walk(tree))
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


def _module_name(path: Path) -> str:
    parts = ("strata_kb", *path.relative_to(SRC).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _import_graph() -> dict[str, set[str]]:
    """Module -> the strata_kb modules importing it runs, function-level
    imports included, `if TYPE_CHECKING:` excluded. An import of `a.b.c`
    also runs `a/__init__` and `a/b/__init__`, so it is an edge to those
    packages too -- except the importer's own parent packages, or every
    package that re-exports its submodules would read as a cycle."""
    paths = {_module_name(p): p for p in SRC.rglob("*.py")}
    graph: dict[str, set[str]] = {}
    for mod, path in paths.items():
        own_parents = {mod.rsplit(".", i)[0] for i in range(1, mod.count(".") + 1)}
        targets: set[str] = set()
        for name in _imports(path, runtime_only=True):
            while name and name not in paths:
                name = name.rpartition(".")[0]
            if not name:
                continue
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                prefix = ".".join(parts[:i])
                if prefix in paths and prefix not in own_parents:
                    targets.add(prefix)
        targets.discard(mod)
        graph[mod] = targets
    return graph


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """One cycle in `graph` as [a, b, ..., a], or None for a DAG."""
    done: set[str] = set()
    stack: list[str] = []
    on_stack: set[str] = set()

    def visit(node: str) -> list[str] | None:
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(graph.get(node, ())):
            if nxt in on_stack:
                return [*stack[stack.index(nxt) :], nxt]
            if nxt not in done:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        on_stack.discard(node)
        done.add(node)
        return None

    for start in sorted(graph):
        if start not in done:
            found = visit(start)
            if found:
                return found
    return None


def test_find_cycle_reports_a_cycle_and_none_for_a_dag():
    cycle = _find_cycle({"a": {"b"}, "b": {"a"}})
    assert cycle is not None and {"a", "b"} <= set(cycle)
    assert _find_cycle({"a": {"b"}, "b": set()}) is None


def test_no_import_cycle_even_through_function_level_imports():
    cycle = _find_cycle(_import_graph())
    assert cycle is None, "import cycle: " + " → ".join(cycle or [])


def test_prlint_and_mdmask_import_only_the_standard_library():
    allowed = {"prlint.py": {"strata_kb.mdmask"}, "mdmask.py": set()}
    for name, extra in allowed.items():
        for mod in _imports(SRC / name):
            if mod.split(".")[0] in sys.stdlib_module_names:
                continue
            assert mod in extra or mod.rpartition(".")[0] in extra, (name, mod)


# Optional extras T0 does not install; a module that needs one at import
# time is skipped, not failed.
_OPTIONAL = ("docling", "fastembed", "boto3", "rapidocr", "pypdfium2")

_FRESH_IMPORT = f"""
import importlib, sys
failed = []
for name in sys.argv[1:]:
    for key in [k for k in sys.modules if k == "strata_kb" or k.startswith("strata_kb.")]:
        del sys.modules[key]
    try:
        importlib.import_module(name)
    except ImportError as exc:
        if not any(opt in str(exc) for opt in {_OPTIONAL!r}):
            failed.append(f"{{name}}: {{exc!r}}")
    except Exception as exc:
        failed.append(f"{{name}}: {{exc!r}}")
print("\\n".join(failed))
"""


def test_every_module_imports_first_in_a_fresh_interpreter():
    """A lazy import made module-level can break import order only when a
    module is the FIRST one imported; the suite never sees that, because by
    then everything is loaded."""
    names = sorted(_module_name(p) for p in SRC.rglob("*.py"))
    proc = subprocess.run(
        [sys.executable, "-c", _FRESH_IMPORT, *names],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", proc.stdout
