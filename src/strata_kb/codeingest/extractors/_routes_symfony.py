"""Symfony route adapter for `routes.py`.

Reads `#[Route(path, methods:, name:)]` attributes (and the legacy
`@Route("...")` docblock annotation) of the scope's PHP classes: a class
`Route` is the prefix of its methods' routes, a method `Route` is a route
(`methods` absent means `ANY`), an invokable class with a class `Route` and
no method route is one route. `config/routes*.yaml` says which directories
are scanned and under which `prefix` (`_symfony_config`).

**Collect first, resolve after.** Every file is read into class records
before any route is placed, so inheritance (a base class or trait that
carries the `#[Route]` methods), repo-defined `Route` subclasses and the
YAML imports do not depend on file order.

**Default to a site, never drop.** A path, prefix or `methods` that is not a
string literal (a constant, a localised array), a positional argument this
scan does not read, a class-level `methods`, routes on an abstract class or
a trait, a class that inherits routes, a custom attribute extending
`Route`, a docblock this scan cannot read, YAML-declared routes, XML and
PHP route configurators, a controller no YAML import covers.

Shortcut: the legacy docblock form is read by a small Doctrine-annotation
parser (strings and `{...}` string lists only), not by a full one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _php_ast as php
from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_jsutil import (
    _error_line,
    _read,
    _text,
    _walk,
)
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._scopes import Scope
from strata_kb.codeingest.extractors._symfony_config import (
    configurator_sites,
    read_config,
)
from strata_kb.codeingest.extractors._symfony_doc import doc_routes

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["ADAPTERS"]

_HINT = re.compile(
    rb"\bRoute\b|RoutingConfigurator|RouteCollection|ApiPlatform|AdminDashboard"
)
_ACCEPTED = (
    "Symfony\\Component\\Routing\\",
    "Sensio\\Bundle\\FrameworkExtraBundle\\Configuration\\",
)
# attributes of other bundles that register routes this scan does not expand
_FOREIGN = (
    "ApiPlatform\\Metadata\\",
    "EasyCorp\\Bundle\\EasyAdminBundle\\Attribute\\AdminDashboard",
)
_VERBS = frozenset(
    {
        "GET",
        "HEAD",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
        "TRACE",
        "CONNECT",
        "PURGE",
    }
)
_CLASSES = ("class_declaration", "trait_declaration")


@dataclass(frozen=True)
class _Spec:
    path: str
    methods: tuple[str, ...]
    line: int


@dataclass
class _Method:
    name: str
    specs: list[_Spec] = field(default_factory=list)
    bad: list[int] = field(default_factory=list)  # lines of unreadable routes


@dataclass
class _Class:
    rel: str
    name: str
    line: int
    trait: bool
    abstract: bool
    parent: str
    traits: tuple[str, ...]
    specs: list[_Spec] = field(default_factory=list)
    bad: list[int] = field(default_factory=list)
    methods: list[_Method] = field(default_factory=list)
    invokable: bool = False

    @property
    def routed(self) -> bool:
        return any(m.specs or m.bad for m in self.methods)


@dataclass(frozen=True)
class _Found:
    rel: str
    handler: str
    method: str
    path: str
    line: int


def _route_class(fqcn: str) -> bool:
    return php.short(fqcn) == "Route" and (
        fqcn == "Route" or fqcn.startswith(_ACCEPTED)
    )


def _read_attr(attr: php.Attr) -> _Spec | None:
    path = ""
    methods: tuple[str, ...] = ()
    for a in attr.args:
        if a.name == "path" or (a.name is None and a.index == 0):
            literal = php.literal(a.value)
            if literal is None:
                return None
            path = literal
        elif a.name is None and a.index >= 2:
            return None  # positional requirements, options, defaults, ...
        elif a.name == "methods":
            given = php.literal_list(a.value)
            upper = tuple(v.upper() for v in given or [])
            if given is None or any(v not in _VERBS for v in upper):
                return None
            methods = upper
    return _Spec(path, methods, attr.line)


def _routes_of(
    node: Node, uses: dict[str, str], custom: frozenset[str]
) -> tuple[list[_Spec], list[int]]:
    """(routes, lines of unreadable routes) declared on a class or method."""
    specs: list[_Spec] = []
    bad: list[int] = []
    for attr in php.attributes(node, uses):
        if _route_class(attr.fqcn):
            spec = _read_attr(attr)
            if spec is None:
                bad.append(attr.line)
            else:
                specs.append(spec)
        elif php.short(attr.name) in custom or attr.fqcn.startswith(_FOREIGN):
            bad.append(attr.line)  # built on Route, or another bundle's routes
    # every docblock directly above the declaration, past line comments
    doc = node.prev_named_sibling
    while doc is not None and doc.type == "comment":
        if _text(doc).startswith("/**"):
            first = _ts.line_of(doc)
            for offset, found in doc_routes(_ts.node_text(doc)):
                if found is None:
                    bad.append(first + offset)
                else:
                    specs.append(_Spec(found.path, found.methods, first + offset))
        doc = doc.prev_named_sibling
    return specs, bad


def _extends(cls: Node) -> str:
    base = next((c for c in cls.children if c.type == "base_clause"), None)
    name = (
        next((c for c in base.named_children if c.type != "comment"), None)
        if base
        else None
    )
    return _text(name).replace(" ", "") if name is not None else ""


def _custom_routes(trees: dict[str, Tree]) -> frozenset[str]:
    """Short names of repo classes extending Symfony's `Route` attribute."""
    found: set[str] = set()
    for tree in trees.values():
        uses = php.use_map(tree.root_node)
        for node in _walk(tree.root_node):
            if node.type != "class_declaration":
                continue
            full = php.resolve(_extends(node), uses)
            if full and _route_class(full):
                name = node.child_by_field_name("name")
                found.add(_text(name))
    return frozenset(found)


def _classes(rel: str, tree: Tree, custom: frozenset[str]) -> list[_Class]:
    uses = php.use_map(tree.root_node)
    out: list[_Class] = []
    for node in _walk(tree.root_node):
        if node.type not in _CLASSES:
            continue
        name = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        members = list(body.named_children) if body is not None else []
        specs, bad = _routes_of(node, uses, custom)
        cls = _Class(
            rel,
            _text(name),
            _ts.line_of(name if name is not None else node),
            node.type == "trait_declaration",
            any(c.type == "abstract_modifier" for c in node.children),
            php.short(_extends(node)),
            tuple(
                php.short(_text(n))
                for m in members
                if m.type == "use_declaration"
                for n in m.named_children
                if n.type in ("name", "qualified_name")
            ),
            specs,
            bad,
        )
        for member in members:
            if member.type != "method_declaration":
                continue
            method_name = _text(member.child_by_field_name("name"))
            found, unreadable = _routes_of(member, uses, custom)
            cls.methods.append(_Method(method_name, found, unreadable))
            cls.invokable = cls.invokable or method_name.lower() == "__invoke"
        out.append(cls)
    return out


def _inherits(cls: _Class, by_name: dict[str, list[_Class]]) -> bool:
    """Whether a parent class or used trait (in the repo) carries routes."""
    todo = [cls.parent, *cls.traits]
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        if not name or name in seen:
            continue
        seen.add(name)
        for parent in by_name.get(name, []):
            if parent.routed:
                return True
            todo += [parent.parent, *parent.traits]
    return False


def _place(cls: _Class, sites: set[str], found: list[_Found]) -> None:
    if cls.trait or cls.abstract:
        # the subclasses that inherit these routes decide their paths
        for method in cls.methods:
            sites.update(
                f"{cls.rel}:{n}" for n in [*(s.line for s in method.specs), *method.bad]
            )
        return
    sites.update(f"{cls.rel}:{n}" for n in cls.bad)
    for method in cls.methods:
        sites.update(f"{cls.rel}:{n}" for n in method.bad)
    if any(m.specs for m in cls.methods):  # class-level verbs merge with the method's
        sites.update(f"{cls.rel}:{s.line}" for s in cls.specs if s.methods)
    prefixes = [s.path for s in cls.specs] or [""]
    for method in cls.methods:
        handler = f"{cls.name}.{method.name}"
        for spec in method.specs:
            for prefix in prefixes:
                found += _rows(
                    cls.rel,
                    handler,
                    spec.methods,
                    join_path(prefix, spec.path),
                    spec.line,
                )
    quiet = not any(m.specs or m.bad for m in cls.methods)
    if cls.specs and cls.invokable and quiet:
        for spec in cls.specs:
            found += _rows(
                cls.rel, cls.name, spec.methods, join_path(spec.path), spec.line
            )


def _rows(
    rel: str, handler: str, methods: tuple[str, ...], path: str, line: int
) -> list[_Found]:
    return [_Found(rel, handler, m, path, line) for m in methods or ("ANY",)]


def _heirs(sources: dict[str, bytes], trees: dict[str, Tree]) -> frozenset[str]:
    """Parse the files that never mention `Route` but extend or use a class
    that carries routes, or use an attribute built on `Route` (repeating for
    the next generation), so inheritance does not depend on which file holds
    the routes. Returns the names of the attributes built on `Route`."""
    while True:
        custom = _custom_routes(trees)
        classes = [
            c for rel in sorted(trees) for c in _classes(rel, trees[rel], custom)
        ]
        by_name: dict[str, list[_Class]] = {}
        for cls in classes:
            by_name.setdefault(cls.name, []).append(cls)
        names = {c.name for c in classes if c.routed or _inherits(c, by_name)} | custom
        if not names:
            return custom
        alternatives = b"|".join(re.escape(n.encode()) for n in sorted(names))
        pattern = re.compile(rb"\b(?:" + alternatives + rb")\b")
        more = [
            rel
            for rel, data in sources.items()
            if rel not in trees and pattern.search(data)
        ]
        if not more:
            return custom
        for rel in more:
            trees[rel] = _ts.parse("php", sources[rel])


def adapter(
    root: Path, scope: Scope, scope_files: list[str], repo_files: list[str]
) -> AdapterResult:
    result = AdapterResult()
    sites: set[str] = set()
    trees: dict[str, Tree] = {}
    sources: dict[str, bytes] = {}
    configurators = False
    for rel in php.source_files(scope_files):
        data = _read(root, rel)
        if data is None:
            sites.add(f"{rel}:1")
        elif _HINT.search(data):
            trees[rel] = _ts.parse("php", data)
            found_sites = configurator_sites(rel, data)
            sites.update(found_sites)
            configurators = configurators or bool(found_sites)
        else:
            sources[rel] = data
    custom = _heirs(sources, trees)
    for rel, tree in trees.items():
        line = _error_line(tree)
        if line is not None:
            sites.add(f"{rel}:{line}")
    classes = [c for rel in sorted(trees) for c in _classes(rel, trees[rel], custom)]
    by_name: dict[str, list[_Class]] = {}
    for cls in classes:
        by_name.setdefault(cls.name, []).append(cls)
    found: list[_Found] = []
    for cls in classes:
        if not (cls.trait or cls.abstract) and _inherits(cls, by_name):
            sites.add(f"{cls.rel}:{cls.line}")
        _place(cls, sites, found)
    config = read_config(root, scope.path, repo_files)
    sites.update(config.sites)
    configured = config.present or configurators
    routes: set[Route] = set()
    uncovered: dict[str, int] = {}
    for item in found:
        prefixes = config.prefixes(item.rel) if configured else [""]
        if not prefixes:
            prefixes = [""]
            uncovered[item.rel] = min(uncovered.get(item.rel, item.line), item.line)
        for prefix in prefixes:
            routes.add(
                Route(
                    item.method,
                    join_path(prefix, item.path),
                    item.handler,
                    item.rel,
                    item.line,
                )
            )
    sites.update(f"{rel}:{line}" for rel, line in uncovered.items())
    result.routes = sorted(routes, key=lambda r: (r.file, r.path, r.method, r.line))
    result.dynamic_sites = sorted(sites)
    return result


ADAPTERS: dict[str, Callable[[Path, Scope, list[str], list[str]], AdapterResult]] = {
    "Symfony": adapter
}
