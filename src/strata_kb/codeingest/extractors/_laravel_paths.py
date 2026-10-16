"""File expressions of Laravel route statements: which repo file a
`->group(base_path('routes/x.php'))`, `require __DIR__.'/x.php'` or
`module_path('Blog', '/Routes/web.php')` names.

`path_spec()` reads the expression into a (kind, fragment) pair without
evaluating anything; `resolve_path()` places it among the repo's PHP files.
Anything computed (a variable, a call this module does not know) has no
spec, which the builder turns into a site. Several files fitting a
`module_path` suffix equally well are ambiguous, which is a site too.
"""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING, Protocol

from strata_kb.codeingest.extractors import _php_ast as php
from strata_kb.codeingest.extractors._routes_jsutil import _text

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["Finder", "path_spec", "resolve_path"]

_MAX_PARTS = 64

_PATH_FUNCS = {
    "base_path": "",
    "app_path": "app/",
    "database_path": "database/",
    "resource_path": "resources/",
    "public_path": "public/",
    "config_path": "config/",
    "storage_path": "storage/",
}


class Finder(Protocol):
    def find(self, kind: str, fragment: str, source: str) -> list[str] | None:
        """Repo files an include expression can name, `[]` for none, None
        when several files fit equally well."""


def _leaf(node: Node | None) -> tuple[str, str] | None:
    node = php.unwrap(node)
    if node is None:
        return None
    text = php.literal(node)
    if text is not None:
        return ("lit", text)
    if node.type == "name" and _text(node) == "__DIR__":
        return ("dir", "")
    if node.type != "function_call_expression":
        return None
    fn = node.child_by_field_name("function")
    args = php.call_args(node.child_by_field_name("arguments"))
    name = _text(fn) if fn is not None else ""
    if name in _PATH_FUNCS:
        rel = php.literal(args[0].value) if args else ""
        return None if rel is None else ("root", _PATH_FUNCS[name] + rel.lstrip("/"))
    if name == "module_path" and len(args) >= 2:
        rel = php.literal(args[-1].value)
        return None if rel is None else ("suffix", rel)
    if name == "dirname" and len(args) == 1 and _text(args[0].value) == "__DIR__":
        return ("dir", "/..")
    return None


def path_spec(node: Node | None) -> tuple[str, str] | None:
    """(kind, fragment) of a file expression: `dir` is relative to the
    including file (`__DIR__`), `root` to the app root (`base_path`), `lit`
    is a plain string, `suffix` matches the end of a repo path."""
    operands: list[Node | None] = []
    current = php.unwrap(node)
    while current is not None and current.type == "binary_expression":
        op = current.child_by_field_name("operator")
        if op is None or _text(op) != "." or len(operands) >= _MAX_PARTS:
            return None
        operands.append(current.child_by_field_name("right"))
        current = php.unwrap(current.child_by_field_name("left"))
    operands.append(current)
    specs = [_leaf(n) for n in reversed(operands)]
    first = specs[0]
    if first is None:
        return None
    kind, fragment = first
    for nxt in specs[1:]:
        if nxt is None or nxt[0] != "lit" or kind not in ("dir", "root", "lit"):
            return None
        fragment += nxt[1]
    return (kind, fragment)


def resolve_path(
    kind: str, fragment: str, source: str, scope_root: str, files: frozenset[str]
) -> list[str] | None:
    """Repo files a (kind, fragment) file expression names; see `Finder`."""
    fragment = fragment.replace("\\", "/")

    def exists(path: str) -> list[str]:
        path = posixpath.normpath(path)
        return [path] if path in files and not path.startswith("..") else []

    here = posixpath.dirname(source)
    if kind == "dir":
        return exists(posixpath.join(here, fragment.lstrip("/")))
    if kind == "root":
        return exists(posixpath.join(scope_root, fragment.lstrip("/")))
    tail = fragment.strip("/")
    if kind == "lit":  # the app root, then the including file; no wider guess
        return exists(posixpath.join(scope_root, tail)) or exists(
            posixpath.join(here, tail)
        )
    hits = sorted(f for f in files if f == tail or f.endswith("/" + tail))
    if not hits:
        return []
    return hits if len(hits) == 1 else None
