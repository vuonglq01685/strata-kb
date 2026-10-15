"""JS/TS route adapters for `routes.py`: NestJS, Next.js, Nuxt (Express lives in `_routes_express.py`).

Each adapter takes `(repo root, Scope, that scope's tracked files)` and
returns an `AdapterResult`: the `Route`s it could resolve statically, plus
`dynamic_sites` -- a `file:line` for every recognised routing form that did
NOT become a route.

**Default to a site, never drop.** A false `complete` is the worst failure,
so anything an adapter recognises as routing but cannot turn into a `Route`
is a site: a path or prefix that is not a string literal, a mount it cannot
follow, a decorator outside a controller, a syntax error in a file that
holds routing, a config option (`basePath`, `setGlobalPrefix` options,
versioning) that changes the served paths. The suspicious-sign rule (spec
5.8) is the same everywhere: a call or decorator named like an HTTP verb
(`Get`, `get`, ...) that did not become a route is a site. Over-partial is
acceptable; a silently missing route is not.

Test files (`*.test.*`, `*.spec.*`, `__tests__/`, `test/`) are not product
routes and are skipped.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_express import express
from strata_kb.codeingest.extractors._routes_jsutil import (
    _CLASS_TYPES,
    _SCRIPT_EXT_RE,
    _args,
    _config_sites,
    _error_line,
    _last_name,
    _lit,
    _local,
    _parse,
    _read,
    _scan,
    _site,
    _source_files,
    _text,
    _walk,
    declared_fields,
)
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._scopes import Scope

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["ADAPTERS", "declared_fields"]

# --- NestJS -----------------------------------------------------------------

_NEST_VERBS = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Patch": "PATCH",
    "Delete": "DELETE",
    "Options": "OPTIONS",
    "Head": "HEAD",
    "All": "ANY",
    "Sse": "GET",
}
_NEST_HINT = re.compile(
    rb"@(?:Controller|Version|"
    + "|".join(_NEST_VERBS).encode()
    + rb")\b|setGlobalPrefix|enableVersioning|RouterModule"
)


def _decorator(dec: Node) -> tuple[str, Node | None]:
    """(name, call node or None for a bare `@Name`)."""
    inner = dec.named_children[0] if dec.named_children else None
    if inner is not None and inner.type == "call_expression":
        return _last_name(inner.child_by_field_name("function")), inner
    return _last_name(inner), None


def _class_decorators(cls: Node) -> list[Node]:
    decs = [c for c in cls.children if c.type == "decorator"]
    if cls.parent is not None and cls.parent.type == "export_statement":
        decs += [c for c in cls.parent.children if c.type == "decorator"]
    return decs


def _members(cls: Node) -> list[tuple[Node, list[Node]]]:
    """(method, its decorators). In class bodies decorators are siblings
    that precede the member they decorate."""
    body = cls.child_by_field_name("body")
    out: list[tuple[Node, list[Node]]] = []
    pending: list[Node] = []
    for child in body.children if body is not None else []:
        if child.type == "decorator":
            pending.append(child)
        elif child.type == "method_definition":
            own = [c for c in child.children if c.type == "decorator"]
            out.append((child, pending + own))
            pending = []
        elif child.is_named and child.type != "comment":
            pending = []
    return out


def _controller_path(dec: Node) -> str | None:
    """Class prefix; None when it is not a plain literal (or the object form
    sets a `version`, which changes the served path)."""
    _name, call = _decorator(dec)
    args = _args(call)
    if not args:
        return ""
    first = args[0]
    if first.type != "object":
        return _lit(first)
    path = ""
    for pair in first.named_children:
        if pair.type != "pair":
            continue
        key = _lit(pair.child_by_field_name("key")) or _text(
            pair.child_by_field_name("key")
        )
        if key == "version":
            return None
        if key == "path":
            value = _lit(pair.child_by_field_name("value"))
            if value is None:
                return None
            path = value
    return path


def _verb_path(call: Node | None) -> str | None:
    if call is None:
        return None
    args = _args(call)
    return "" if not args else _lit(args[0])


def _body_type(method: Node) -> str:
    params = method.child_by_field_name("parameters")
    for param in params.named_children if params is not None else []:
        if param.type not in ("required_parameter", "optional_parameter"):
            continue
        is_body = False
        for dec in (c for c in param.children if c.type == "decorator"):
            name, call = _decorator(dec)
            is_body = is_body or (name == "Body" and not _args(call))
        annotation = param.child_by_field_name("type")
        if not is_body or annotation is None or not annotation.named_children:
            continue
        inner = annotation.named_children[0]
        if inner.type in (
            "type_identifier",
            "nested_type_identifier",
            "generic_type",
            "array_type",
        ):
            return _text(inner)
    return ""


def _global_prefix(loaded: list[tuple[str, Tree]], sites: list[str]) -> str | None:
    """The one `setGlobalPrefix('x')` literal of the scope ("" when there is
    none); None when it is dynamic or ambiguous. Options on the call
    (`exclude`), versioning and `RouterModule` also change served paths, so
    they are sites even though the prefix stays usable."""
    literals: list[tuple[str, Node, str | None]] = []
    for rel, tree in loaded:
        for node in _walk(tree.root_node):
            if node.type != "call_expression":
                continue
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "member_expression":
                continue
            name = _last_name(fn)
            owner = _text(fn.child_by_field_name("object"))
            if name == "setGlobalPrefix":
                args = _args(node)
                literals.append((rel, node, _lit(args[0]) if args else None))
                if len(args) > 1:
                    sites.append(_site(rel, node))
            elif name == "enableVersioning" or (
                owner == "RouterModule" and name == "register"
            ):
                sites.append(_site(rel, node))
    distinct = {lit for _rel, _node, lit in literals}
    only = next(iter(distinct), "")
    if only is None or len(distinct) > 1:
        sites.extend(_site(rel, node) for rel, node, _lit_ in literals)
        return None
    return only


def nest(root: Path, scope: Scope, files: list[str]) -> AdapterResult:
    result = AdapterResult()
    loaded = _scan(root, files, _NEST_HINT, result)
    prefix = _global_prefix(loaded, result.dynamic_sites)
    consumed: set[tuple[str, int]] = set()
    found: list[Route] = []
    for rel, tree in loaded:
        for cls in (n for n in _walk(tree.root_node) if n.type in _CLASS_TYPES):
            ctrl = next(
                (d for d in _class_decorators(cls) if _decorator(d)[0] == "Controller"),
                None,
            )
            if ctrl is None:
                continue
            base = _controller_path(ctrl)
            if base is None:
                result.dynamic_sites.append(_site(rel, ctrl))
            if any(c.type == "class_heritage" for c in cls.children):
                # inherited handlers are invisible from here
                result.dynamic_sites.append(_site(rel, cls))
            cname = _text(cls.child_by_field_name("name")) or "(anonymous)"
            for method, decs in _members(cls):
                mname = _text(method.child_by_field_name("name"))
                for dec in decs:
                    verb, call = _decorator(dec)
                    if verb not in _NEST_VERBS:
                        continue
                    consumed.add((rel, dec.start_byte))
                    path = _verb_path(call)
                    if path is None:
                        result.dynamic_sites.append(_site(rel, dec))
                    elif base is not None:
                        found.append(
                            Route(
                                _NEST_VERBS[verb],
                                join_path(base, path),
                                f"{cname}.{mname}",
                                rel,
                                _ts.line_of(dec),
                                _body_type(method),
                            )
                        )
        for node in _walk(tree.root_node):
            if node.type != "decorator":
                continue
            name, _call = _decorator(node)
            if name == "Version" or (
                name in _NEST_VERBS and (rel, node.start_byte) not in consumed
            ):
                result.dynamic_sites.append(_site(rel, node))
    if prefix is not None:  # an unknown global prefix makes every path unknown
        result.routes = [replace(r, path=join_path(prefix, r.path)) for r in found]
    return result


# --- Next.js ----------------------------------------------------------------

_NEXT_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_NEXT_ROUTE_RE = re.compile(r"^route\.[cm]?[jt]sx?$")
_GROUP_RE = re.compile(r"^\(.*\)$")


def _next_exports(tree: Tree) -> tuple[list[tuple[str, int]], bool]:
    """(exported names with line, whether an `export *` hides more)."""
    names: list[tuple[str, int]] = []
    star = False
    for stmt in tree.root_node.named_children:
        if stmt.type != "export_statement":
            continue
        line = _ts.line_of(stmt)
        declaration = stmt.child_by_field_name("declaration")
        if declaration is not None:
            if declaration.type in (
                "function_declaration",
                "generator_function_declaration",
            ):
                names.append((_text(declaration.child_by_field_name("name")), line))
            for decl in declaration.named_children:
                if decl.type == "variable_declarator":
                    names.append((_text(decl.child_by_field_name("name")), line))
        clauses = [c for c in stmt.children if c.type == "export_clause"]
        for clause in clauses:
            for spec in clause.named_children:
                alias = spec.child_by_field_name("alias")
                names.append((_text(alias or spec.child_by_field_name("name")), line))
        if (
            not clauses
            and declaration is None
            and stmt.child_by_field_name("value") is None
        ):
            star = star or any(c.type == "*" for c in stmt.children)
    return names, star


def next_js(root: Path, scope: Scope, files: list[str]) -> AdapterResult:
    result = AdapterResult()
    for rel in _source_files(files):
        local = _local(rel, scope)
        local = local[4:] if local.startswith("src/") else local
        parts = local.split("/")
        if parts[0] == "app" and _NEXT_ROUTE_RE.match(parts[-1]):
            segments = [p for p in parts[1:-1] if not _GROUP_RE.match(p)]
            if any(p.startswith("@") for p in segments):
                result.dynamic_sites.append(f"{rel}:1")  # parallel slot
                continue
            _next_route_file(root, rel, join_path(*segments), result)
        elif parts[0] == "pages" and len(parts) > 2 and parts[1] == "api":
            segments = [*parts[1:-1], _SCRIPT_EXT_RE.sub("", parts[-1])]
            if segments[-1] == "index":
                segments.pop()
            result.routes.append(Route("ANY", join_path(*segments), "default", rel, 1))
    result.dynamic_sites.extend(
        _config_sites(
            root,
            scope,
            files,
            frozenset(f"next.config.{e}" for e in ("js", "mjs", "cjs", "ts")),
            b"basePath",
        )
    )
    return result


def _next_route_file(root: Path, rel: str, path: str, result: AdapterResult) -> None:
    data = _read(root, rel)
    if data is None:
        result.dynamic_sites.append(f"{rel}:1")
        return
    tree = _parse(rel, data)
    line = _error_line(tree)
    if line is not None:
        result.dynamic_sites.append(f"{rel}:{line}")
    names, star = _next_exports(tree)
    methods = [(n, ln) for n, ln in names if n in _NEXT_METHODS]
    result.routes.extend(Route(n, path, n, rel, ln) for n, ln in methods)
    if star or not methods:
        result.dynamic_sites.append(f"{rel}:1")


# --- Nuxt -------------------------------------------------------------------

_NUXT_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "connect", "trace"}
)
_NUXT_ROOTS = {"server/api/": "api", "server/routes/": ""}


def nuxt(root: Path, scope: Scope, files: list[str]) -> AdapterResult:
    result = AdapterResult()
    for rel in _source_files(files):
        local = _local(rel, scope)
        for base, prefix in _NUXT_ROOTS.items():
            if not local.startswith(base):
                continue
            *dirs, filename = local[len(base) :].split("/")
            name = _SCRIPT_EXT_RE.sub("", filename)
            method = "ANY"
            stem, _dot, suffix = name.rpartition(".")
            if stem and suffix.lower() in _NUXT_METHODS:
                name, method = stem, suffix.upper()
            segments = [prefix, *dirs, "" if name == "index" else name]
            result.routes.append(Route(method, join_path(*segments), "default", rel, 1))
    result.dynamic_sites.extend(
        _config_sites(
            root,
            scope,
            files,
            frozenset(f"nuxt.config.{e}" for e in ("js", "mjs", "cjs", "ts")),
            b"baseURL",
        )
    )
    return result


ADAPTERS = {"NestJS": nest, "Express": express, "Next.js": next_js, "Nuxt": nuxt}
