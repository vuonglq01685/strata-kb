"""Flutter page adapter for `pages.py`: go_router `GoRoute(path: ...)` trees
(nested `routes:` join paths; `ShellRoute` / `StatefulShellBranch` pass the
prefix through) and the `routes:` map of `MaterialApp` / `CupertinoApp`.

Needs tree-sitter (Dart grammar); `pages.py` reports `not scanned` without it.

**Default to a site, never drop.** A non-literal `path:` or map key, a
`routes:` value or spread it cannot follow in the same file,
`onGenerateRoute`, imperative `MaterialPageRoute` / `PageRouteBuilder`,
go_router_builder's `@TypedGoRoute`, a syntax error: each
is a `file:line` site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._pages_model import Page, PageResult
from strata_kb.codeingest.extractors._routes_jsutil import (
    _error_line,
    _lit,
    _parse,
    _read,
    _site,
    _text,
    _walk,
)
from strata_kb.codeingest.extractors._routes_model import join_path
from strata_kb.codeingest.extractors._scopes import Scope
from strata_kb.codeingest.extractors._ts import language_for, line_of

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["flutter_pages"]

_HINT = re.compile(
    rb"GoRoute|ShellRoute|StatefulShell|MaterialApp|CupertinoApp|onGenerateRoute"
    rb"|TypedGoRoute|TypedShellRoute|TypedStatefulShellRoute"
    rb"|MaterialPageRoute|CupertinoPageRoute|PageRouteBuilder"
)
_SKIP = re.compile(r"(?:^|/)(?:test|integration_test)/|\.(?:g|freezed)\.dart$")
_SHELLS = frozenset({"ShellRoute", "StatefulShellRoute", "StatefulShellBranch"})
_ROUTE_KINDS = _SHELLS | {"GoRoute"}
_APPS = frozenset({"MaterialApp", "CupertinoApp"})
# pages pushed by hand (`Navigator.push(MaterialPageRoute(...))`) have no path
_IMPERATIVE = frozenset({"MaterialPageRoute", "CupertinoPageRoute", "PageRouteBuilder"})
_TYPED = re.compile(r"^Typed(?:GoRoute|ShellRoute|StatefulShellRoute)$")
_DECLARATIONS = frozenset(
    {
        "static_final_declaration",
        "initialized_identifier",
        "initialized_variable_definition",
    }
)


@dataclass(frozen=True)
class _Call:
    name: str  # constructor name without `.named`
    args: Node
    node: Node  # the identifier / const_object_expression


def _calls(tree: Tree) -> list[_Call]:
    out: list[_Call] = []
    for node in _walk(tree.root_node):
        if node.type in ("const_object_expression", "new_expression"):
            args = next((c for c in node.named_children if c.type == "arguments"), None)
            name = next(
                (c for c in node.named_children if c.type == "type_identifier"), None
            )
            if args is not None and name is not None:
                out.append(_Call(_text(name), args, node))
        elif node.type == "identifier":
            call = _selector_call(node)
            if call is not None:
                out.append(call)
    return out


def _selector_call(ident: Node) -> _Call | None:
    """`Name(...)` / `Name.named(...)` -- the grammar spells a call as an
    identifier followed by selector siblings."""
    nxt = ident.next_named_sibling
    if nxt is None or nxt.type != "selector":
        return None
    if nxt.named_children and nxt.named_children[0].type == "argument_part":
        part = nxt.named_children[0]
    else:  # `.named` then the arguments
        after = nxt.next_named_sibling
        if after is None or after.type != "selector" or not after.named_children:
            return None
        part = after.named_children[0]
        if part.type != "argument_part":
            return None
    args = next((c for c in part.named_children if c.type == "arguments"), None)
    return _Call(_text(ident), args, ident) if args is not None else None


def _named(args: Node) -> dict[str, Node]:
    out: dict[str, Node] = {}
    for arg in args.named_children:
        if arg.type != "named_argument":
            continue
        label = next((c for c in arg.named_children if c.type == "label"), None)
        value = [c for c in arg.named_children if c.type != "label"]
        if label is not None and value:
            out[_text(label).rstrip(":").strip()] = value[-1]
    return out


def _lists(tree: Tree) -> dict[str, Node]:
    """name -> list literal, for `final x = [...]` declarations."""
    out: dict[str, Node] = {}
    for node in _walk(tree.root_node):
        if node.type not in _DECLARATIONS:
            continue
        name = next((c for c in node.named_children if c.type == "identifier"), None)
        value = next((c for c in node.named_children if c.type == "list_literal"), None)
        if name is not None and value is not None:
            out.setdefault(_text(name), value)
    return out


def _ancestors(node: Node) -> list[Node]:
    out = []
    parent = node.parent
    while parent is not None:
        out.append(parent)
        parent = parent.parent
    return out


class _FileRoutes:
    def __init__(self, rel: str, tree: Tree, result: PageResult):
        self.rel = rel
        self.result = result
        self.lists = _lists(tree)
        self.calls = [c for c in _calls(tree) if c.name.split(".")[0] in _ROUTE_KINDS]
        self.by_args = {c.args.id: c for c in self.calls}
        self.parent: dict[int, _Call | None] = {
            c.node.id: self._nearest(c) for c in self.calls
        }
        self._memo: dict[int, str | None] = {}

    def site(self, node: Node) -> None:
        self.result.dynamic_sites.append(_site(self.rel, node))

    def _nearest(self, call: _Call) -> _Call | None:
        return next(
            (
                self.by_args[a.id]
                for a in _ancestors(call.node)
                if a.type == "arguments" and a.id in self.by_args
            ),
            None,
        )

    def _adopt(self, parent: _Call, group: Node) -> None:
        """Calls under `group` (a list declared elsewhere in the file) are
        `parent`'s children, not roots."""
        for call in self.calls:
            if self.parent[call.node.id] is None and any(
                a.id == group.id for a in _ancestors(call.node)
            ):
                self.parent[call.node.id] = parent

    def link(self) -> None:
        for call in list(self.calls):
            routes = _named(call.args).get("routes")
            if routes is not None:
                self._link(call, routes)

    def _link(self, call: _Call, routes: Node) -> None:
        if routes.type == "identifier":
            self._reference(call, routes)
        elif routes.type == "list_literal":
            for child in routes.named_children:
                if child.type == "spread_element" and child.named_children:
                    self._reference(call, child.named_children[0])
                elif child.type == "identifier" and not (
                    child.next_named_sibling is not None
                    and child.next_named_sibling.type == "selector"
                ):
                    self.site(child)  # a route held in a variable
        else:
            self.site(routes)

    def _reference(self, call: _Call, ref: Node) -> None:
        target = self.lists.get(_text(ref)) if ref.type == "identifier" else None
        if target is None:
            self.site(ref)
        else:
            self._adopt(call, target)

    def full(self, call: _Call, depth: int = 0) -> str | None:
        key = call.node.id
        if key not in self._memo:
            self._memo[key] = None  # a cycle reads as unknown
            parent = self.parent[key]
            base = self.full(parent, depth + 1) if parent is not None else ""
            kind = call.name.split(".")[0]
            path = _lit(_named(call.args).get("path")) if kind == "GoRoute" else ""
            if base is None or path is None:
                if kind == "GoRoute" and path is None:
                    self.site(call.node)
                self._memo[key] = None
            else:
                self._memo[key] = (
                    join_path(path) if path.startswith("/") else join_path(base, path)
                )
        return self._memo[key]

    def group(self, call: _Call) -> str:
        seen = 0
        parent = self.parent[call.node.id]
        while parent is not None and seen < len(self.calls):
            kind = parent.name.split(".")[0]
            if kind in _SHELLS:
                return kind
            parent = self.parent[parent.node.id]
            seen += 1
        return ""

    def pages(self) -> None:
        for call in self.calls:
            if call.name.split(".")[0] != "GoRoute":
                continue
            path = self.full(call)
            if path is not None:
                self.result.pages.append(
                    Page(path, self.rel, line_of(call.node), self.group(call))
                )


def _material_apps(rel: str, tree: Tree, result: PageResult) -> None:
    for call in _calls(tree):
        if call.name in _IMPERATIVE:
            result.dynamic_sites.append(_site(rel, call.node))
        if call.name not in _APPS:
            continue
        named = _named(call.args)
        if "home" in named:  # the page shown at "/"
            result.pages.append(Page("/", rel, line_of(call.node)))
        for key in ("onGenerateRoute", "onGenerateInitialRoutes"):
            if key in named:
                result.dynamic_sites.append(_site(rel, call.node))
        routes = named.get("routes")
        if routes is None:
            continue
        if routes.type != "set_or_map_literal":
            result.dynamic_sites.append(_site(rel, routes))
            continue
        for pair in routes.named_children:
            key_node = pair.child_by_field_name("key") if pair.type == "pair" else None
            path = _lit(key_node)
            if path is None:
                result.dynamic_sites.append(_site(rel, pair))
            else:
                result.pages.append(Page(join_path(path), rel, line_of(pair)))


def flutter_pages(
    root: Path, scope: Scope, files: list[str], repo_files: list[str]
) -> PageResult:
    result = PageResult()
    for rel in sorted(files):
        if language_for(rel) != "dart" or _SKIP.search(rel):
            continue
        data = _read(root, rel)
        if data is None:
            result.dynamic_sites.append(f"{rel}:1")
            continue
        if not _HINT.search(data):
            continue
        tree = _parse(rel, data)
        line = _error_line(tree)
        if line is not None:
            result.dynamic_sites.append(f"{rel}:{line}")
        routes = _FileRoutes(rel, tree, result)
        routes.link()
        routes.pages()
        _material_apps(rel, tree, result)
        for node in _walk(tree.root_node):
            if node.type == "annotation" and _TYPED.match(
                _text(node.child_by_field_name("name"))
            ):
                result.dynamic_sites.append(_site(rel, node))
    return result
