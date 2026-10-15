"""Express adapter for `routes.py`: `app/router.METHOD(path, ...)` on
identifiers bound to `express()` / `Router()`, `.route(path).get()` chains
and `.use(prefix, router)` mounts followed through relative imports
(ESM and CommonJS), re-exports included.

An unfollowable mount, a dynamic path or prefix, a verb call on a receiver
that cannot be tracked, and a router never mounted anywhere are sites (see
`_routes_js` for the shared default-to-site rule).
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_jsutil import (
    _EXTS,
    _SCRIPT_EXT_RE,
    _args,
    _error_line,
    _last_name,
    _lit,
    _parse,
    _read,
    _site,
    _source_files,
    _text,
    _walk,
)
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._scopes import Scope

if TYPE_CHECKING:
    from tree_sitter import Node, Tree


_EXPRESS_VERBS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "all": "ANY",
    "options": "OPTIONS",
    "head": "HEAD",
}
_EXPRESS_HINT = re.compile(
    rb"express|Router|\.(?:get|post|put|patch|delete|all|options|head|use|route)\s*\("
)
_FUNCTION_TYPES = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)
_ExportRef = str | tuple[str, str]  # local ident, or (file, export name) re-export
_NodeKey = tuple[str, str]  # (file, receiver key)


@dataclass
class _Mount:
    prefix: str | None  # None: dynamic prefix (already sited)
    kind: str  # "local" | "file"
    ident: str  # receiver key (local) or export name (file)
    target: str  # target file (file kind)
    site: str


@dataclass
class _FileInfo:
    rel: str
    kinds: dict[str, str] = field(default_factory=dict)  # key -> app | router
    decl: dict[str, int] = field(default_factory=dict)
    routes: dict[str, list[tuple[str, str, str, int]]] = field(default_factory=dict)
    mounts: dict[str, list[_Mount]] = field(default_factory=dict)
    exports: dict[str, _ExportRef] = field(default_factory=dict)
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    sites: list[str] = field(default_factory=list)


def _recv_key(node: Node | None) -> str | None:
    """`app`, `router`, or `this.app` -- a receiver we can track."""
    if node is None:
        return None
    if node.type == "identifier":
        return _text(node)
    if node.type == "member_expression":
        obj = node.child_by_field_name("object")
        if obj is not None and obj.type == "this":
            return _text(node)
    return None


def _require_spec(node: Node | None) -> str | None:
    """`x` of a `require('x')` call, else None."""
    if node is None or node.type != "call_expression":
        return None
    fn = node.child_by_field_name("function")
    args = _args(node)
    if fn is None or _text(fn) != "require" or len(args) != 1:
        return None
    return _lit(args[0])


def _classify(value: Node | None) -> str | None:
    """ "app" for `express()`, "router" for `Router()` / `express.Router()`."""
    if value is None or value.type != "call_expression":
        return None
    fn = value.child_by_field_name("function")
    if fn is None:
        return None
    if fn.type == "identifier":
        name = _text(fn)
        return "app" if name == "express" else "router" if name == "Router" else None
    if fn.type == "member_expression" and _last_name(fn) == "Router":
        return "router"
    if _require_spec(fn) == "express":
        return "app"
    return None


def _resolve_spec(rel: str, spec: str, file_set: set[str]) -> str | None:
    """Repo path of a relative import inside the scope, else None."""
    if not spec.startswith("."):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
    stem = (
        _SCRIPT_EXT_RE.sub("", base) if base.endswith((".js", ".mjs", ".cjs")) else None
    )
    options = [base]
    for root in (base, stem) if stem else (base,):
        options += [root + ext for ext in _EXTS]
        options += [f"{root}/index{ext}" for ext in _EXTS]
    return next((o for o in options if o in file_set), None)


def _collect_imports(info: _FileInfo, tree: Tree) -> None:
    for node in _walk(tree.root_node):
        if node.type == "import_statement":
            spec = _lit(node.child_by_field_name("source"))
            if spec is None:
                continue
            for part in _walk(node):
                if part.type == "import_clause":
                    for child in part.children:
                        if child.type == "identifier":
                            info.imports[_text(child)] = (spec, "default")
                        elif child.type == "namespace_import":
                            names = [
                                c
                                for c in child.named_children
                                if c.type == "identifier"
                            ]
                            if names:
                                info.imports[_text(names[0])] = (spec, "*")
                elif part.type == "import_specifier":
                    name = _text(part.child_by_field_name("name"))
                    alias = part.child_by_field_name("alias")
                    info.imports[_text(alias) or name] = (spec, name)
        elif node.type == "variable_declarator":
            _collect_declarator(info, node)
        elif node.type == "assignment_expression":
            key = _recv_key(node.child_by_field_name("left"))
            kind = _classify(node.child_by_field_name("right"))
            if key and kind:
                info.kinds[key] = kind
                info.decl.setdefault(key, _ts.line_of(node))
        elif node.type == "public_field_definition":
            name = _text(node.child_by_field_name("name"))
            kind = _classify(node.child_by_field_name("value"))
            if name and kind:
                info.kinds[f"this.{name}"] = kind
                info.decl.setdefault(f"this.{name}", _ts.line_of(node))


def _collect_declarator(info: _FileInfo, node: Node) -> None:
    name = node.child_by_field_name("name")
    value = node.child_by_field_name("value")
    if name is None or value is None:
        return
    spec = _require_spec(value)
    if name.type == "identifier":
        key = _text(name)
        if spec is not None:
            info.imports[key] = (spec, "")
        elif value.type == "member_expression" and (
            member_spec := _require_spec(value.child_by_field_name("object"))
        ):
            info.imports[key] = (member_spec, _last_name(value))
        kind = _classify(value)
        if kind:
            info.kinds[key] = kind
            info.decl.setdefault(key, _ts.line_of(node))
    elif name.type == "object_pattern" and spec is not None:
        for child in name.named_children:
            if child.type == "shorthand_property_identifier_pattern":
                info.imports[_text(child)] = (spec, _text(child))
            elif child.type == "pair_pattern":
                key = _text(child.child_by_field_name("key"))
                local = _text(child.child_by_field_name("value"))
                if key and local:
                    info.imports[local] = (spec, key)


def _collect_exports(info: _FileInfo, tree: Tree, file_set: set[str]) -> None:
    for stmt in tree.root_node.named_children:
        if stmt.type == "export_statement":
            _collect_esm_export(info, stmt, file_set)
        elif stmt.type == "expression_statement" and stmt.named_children:
            expr = stmt.named_children[0]
            if expr.type == "assignment_expression":
                _collect_cjs_export(info, expr, file_set)


def _collect_esm_export(info: _FileInfo, stmt: Node, file_set: set[str]) -> None:
    value = stmt.child_by_field_name("value")
    if value is not None and value.type == "identifier":
        info.exports["default"] = _text(value)
    declaration = stmt.child_by_field_name("declaration")
    if declaration is not None and declaration.type in (
        "lexical_declaration",
        "variable_declaration",
    ):
        for decl in declaration.named_children:
            name = decl.child_by_field_name("name")
            if (
                decl.type == "variable_declarator"
                and name is not None
                and name.type == "identifier"
            ):
                info.exports[_text(name)] = _text(name)
    source = _lit(stmt.child_by_field_name("source"))
    target = _resolve_spec(info.rel, source, file_set) if source is not None else None
    for clause in (c for c in stmt.children if c.type == "export_clause"):
        for spec in clause.named_children:
            name = _text(spec.child_by_field_name("name"))
            alias = _text(spec.child_by_field_name("alias")) or name
            if source is None:
                info.exports[alias] = name
            elif target is not None:
                info.exports[alias] = (target, name)


def _collect_cjs_export(info: _FileInfo, expr: Node, file_set: set[str]) -> None:
    left = _text(expr.child_by_field_name("left"))
    right = expr.child_by_field_name("right")
    if right is None:
        return
    if left == "module.exports":
        name = "default"
    elif left.startswith(("module.exports.", "exports.")):
        name = left.rsplit(".", 1)[1]
    else:
        return
    if right.type == "identifier":
        info.exports[name] = _text(right)
    elif right.type == "object" and name == "default":
        for part in right.named_children:
            if part.type == "shorthand_property_identifier":
                info.exports[_text(part)] = _text(part)
            elif part.type == "pair":
                value = part.child_by_field_name("value")
                if value is not None and value.type == "identifier":
                    info.exports[_text(part.child_by_field_name("key"))] = _text(value)
    elif (spec := _require_spec(right)) is not None:
        target = _resolve_spec(info.rel, spec, file_set)
        if target is not None:
            info.exports[name] = (target, "default")


def _handler(args: list[Node]) -> str:
    last = args[-1] if args else None
    if last is not None and last.type in ("identifier", "member_expression"):
        return _text(last)
    return "(inline)"


def _add_route(
    info: _FileInfo, key: str, call: Node, verb: str, args: list[Node]
) -> None:
    """One `<recv>.<verb>(path, ...handlers)` call -> a route, or a site."""
    path = _lit(args[0]) if args else None
    if path is None or len(args) < 2:
        info.sites.append(_site(info.rel, call))
        return
    info.routes.setdefault(key, []).append(
        (_EXPRESS_VERBS[verb], path, _handler(args), _ts.line_of(call))
    )


def _route_chain(info: _FileInfo, key: str, call: Node) -> None:
    """`router.route('/x').get(h).post(g)`."""
    args = _args(call)
    path = _lit(args[0]) if args else None
    current = call
    chained = False
    while True:
        member = current.parent
        outer = member.parent if member is not None else None
        if (
            member is None
            or outer is None
            or member.type != "member_expression"
            or outer.type != "call_expression"
            or member.child_by_field_name("object") != current
            or outer.child_by_field_name("function") != member
        ):
            break
        chained = True
        verb = _last_name(member)
        if path is not None and verb in _EXPRESS_VERBS:
            info.routes.setdefault(key, []).append(
                (_EXPRESS_VERBS[verb], path, _handler(_args(outer)), _ts.line_of(outer))
            )
        current = outer
    if path is None or not chained:
        info.sites.append(_site(info.rel, call))


def _root_ident(node: Node) -> str:
    while node.type in ("member_expression", "call_expression"):
        child = node.child_by_field_name(
            "object" if node.type == "member_expression" else "function"
        )
        if child is None:
            return ""
        node = child
    return _text(node) if node.type == "identifier" else ""


def _import_ref(
    info: _FileInfo, file_set: set[str], name: str
) -> tuple[str, str] | str:
    """For an imported identifier: ("file", rel, export) | "ignore" | "site"."""
    spec, imported = info.imports[name]
    if not spec.startswith("."):
        return "ignore"
    target = _resolve_spec(info.rel, spec, file_set)
    if target is None or imported == "*":
        return "site"
    return target, imported if imported not in ("", "default") else "default"


def _classify_target(
    info: _FileInfo, file_set: set[str], target: Node, has_path: bool
) -> tuple | str:
    """What a `.use(...)` argument is: ("local", key) | ("file", rel, export)
    | "ignore" (middleware) | "site" (looks like a router we cannot follow)."""
    unknown = "site" if has_path else "ignore"
    kind = target.type
    if kind in _FUNCTION_TYPES:
        return "ignore"
    if kind == "call_expression":
        fn = target.child_by_field_name("function")
        spec = _require_spec(target)
        if spec is not None:
            if not spec.startswith("."):
                return "ignore"
            rel = _resolve_spec(info.rel, spec, file_set)
            return ("file", rel, "default") if rel else "site"
        if fn is not None and fn.type == "call_expression" and _require_spec(fn):
            return "site"  # require('./factory')()
        base = _root_ident(fn) if fn is not None else ""
        if base in info.imports:
            return "site" if info.imports[base][0].startswith(".") else "ignore"
        return "ignore" if base == "express" else unknown
    if kind in ("identifier", "member_expression"):
        key = _recv_key(target)
        if key in info.kinds:
            return ("local", key)
        base = _root_ident(target)
        if kind == "identifier" and base in info.imports:
            ref = _import_ref(info, file_set, base)
            return ("file", *ref) if isinstance(ref, tuple) else ref
        if base in info.imports:
            return "site" if info.imports[base][0].startswith(".") else "ignore"
        return "site" if has_path or "route" in _text(target).lower() else "ignore"
    return unknown


def _looks_like_path(info: _FileInfo, args: list[Node]) -> bool:
    """First `.use()` argument is a mount path: a literal, or -- with more
    arguments behind it -- an expression that is not a router, an import or
    a call (`PREFIX`, `base + '/x'`), which is then a dynamic prefix."""
    if not args:
        return False
    first = args[0]
    if first.type in (
        "string",
        "template_string",
        "array",
        "regex",
        "binary_expression",
    ):
        return True
    if len(args) < 2 or first.type not in ("identifier", "member_expression"):
        return False
    return _recv_key(first) not in info.kinds and _root_ident(first) not in info.imports


def _add_mount(info: _FileInfo, file_set: set[str], key: str, call: Node) -> None:
    args = _args(call)
    has_path = _looks_like_path(info, args)
    prefix: str | None = ""
    targets = args
    if has_path:
        prefix = _lit(args[0])
        targets = args[1:]
    here = _site(info.rel, call)
    for target in targets:
        decision = _classify_target(info, file_set, target, has_path)
        if decision == "ignore":
            continue
        if decision == "site" or prefix is None:
            info.sites.append(here)
        if isinstance(decision, tuple):
            mount = (
                _Mount(prefix, "local", decision[1], "", here)
                if decision[0] == "local"
                else _Mount(prefix, "file", decision[2], decision[1], here)
            )
            info.mounts.setdefault(key, []).append(mount)


def _suspicious_unbound(
    info: _FileInfo, call: Node, verb: str, args: list[Node], imports_express: bool
) -> None:
    """`x.get('/p', handler)` on a receiver we cannot track (a parameter, a
    field, a factory result) is probably a route we cannot attribute."""
    if len(args) < 2 or args[1].type == "object":
        return
    first = _lit(args[0])
    if (first is not None and first.startswith("/")) or (
        first is None and imports_express
    ):
        info.sites.append(_site(info.rel, call))


def _is_route_call(node: Node | None, info: _FileInfo) -> bool:
    """`<tracked>.route('/x')` -- the receiver of a `.get()` in a chain that
    `_route_chain` already handled."""
    if node is None or node.type != "call_expression":
        return False
    fn = node.child_by_field_name("function")
    if fn is None or fn.type != "member_expression" or _last_name(fn) != "route":
        return False
    return _recv_key(fn.child_by_field_name("object")) in info.kinds


def _analyse_calls(
    info: _FileInfo, tree: Tree, file_set: set[str], imports_express: bool
) -> None:
    for node in _walk(tree.root_node):
        if node.type != "call_expression":
            continue
        fn = node.child_by_field_name("function")
        if fn is None or fn.type != "member_expression":
            continue
        verb = _last_name(fn)
        obj = fn.child_by_field_name("object")
        key = _recv_key(obj)
        args = _args(node)
        if key in info.kinds:
            if verb in _EXPRESS_VERBS:
                first = _lit(args[0]) if args else None
                is_setting = (
                    verb == "get"
                    and len(args) == 1
                    and not (first or "").startswith("/")
                )
                if not is_setting:
                    _add_route(info, key, node, verb, args)
            elif verb == "route":
                _route_chain(info, key, node)
            elif verb == "use":
                _add_mount(info, file_set, key, node)
        elif verb in _EXPRESS_VERBS and not _is_route_call(obj, info):
            _suspicious_unbound(info, node, verb, args, imports_express)


def _resolve_export(get_info, rel: str, name: str, depth: int = 0) -> _NodeKey | None:
    info = get_info(rel)
    ref = info.exports.get(name) if info is not None else None
    if isinstance(ref, str):
        return rel, ref
    if isinstance(ref, tuple) and depth < 5:
        return _resolve_export(get_info, ref[0], ref[1], depth + 1)
    return None


def express(root: Path, scope: Scope, files: list[str]) -> AdapterResult:
    result = AdapterResult()
    candidates = _source_files(files)
    file_set = set(candidates)
    infos: dict[str, _FileInfo | None] = {}

    def load(rel: str) -> _FileInfo | None:
        if rel in infos:
            return infos[rel]
        infos[rel] = None
        data = _read(root, rel)
        if data is None or rel not in file_set:
            if data is None and rel in file_set:
                result.dynamic_sites.append(f"{rel}:1")
            return None
        tree = _parse(rel, data)
        info = _FileInfo(rel)
        line = _error_line(tree)
        if line is not None:
            info.sites.append(f"{rel}:{line}")
        _collect_imports(info, tree)
        _collect_exports(info, tree, file_set)
        _analyse_calls(info, tree, file_set, b"express" in data)
        infos[rel] = info
        return info

    for rel in candidates:
        data = _read(root, rel)
        if data is not None and _EXPRESS_HINT.search(data):
            load(rel)

    edges: dict[_NodeKey, list[tuple[str, _NodeKey]]] = {}
    claimed: set[_NodeKey] = set()
    done: set[str] = set()
    while True:
        pending = sorted(r for r, i in infos.items() if i is not None and r not in done)
        if not pending:
            break
        for rel in pending:
            done.add(rel)
            info = infos[rel]
            if info is None:
                continue
            for key, mounts in info.mounts.items():
                for mount in mounts:
                    dest = _mount_target(rel, mount, load)
                    if dest == "ignore":
                        continue
                    if isinstance(dest, str):
                        info.sites.append(mount.site)
                        continue
                    claimed.add(dest)
                    if mount.prefix is not None:
                        edges.setdefault((rel, key), []).append((mount.prefix, dest))

    live = {r: i for r, i in infos.items() if i is not None}

    def emit(node: _NodeKey, prefix: str, stack: frozenset[_NodeKey]) -> None:
        rel, key = node
        for method, path, handler, line in live[rel].routes.get(key, []):
            result.routes.append(
                Route(method, join_path(prefix, path), handler, rel, line)
            )
        for sub, dest in edges.get(node, []):
            if dest not in stack and dest != node:
                emit(dest, join_path(prefix, sub), stack | {node})

    for rel in sorted(live):
        info = live[rel]
        for key in sorted(info.kinds):
            node = (rel, key)
            if info.routes.get(key) or info.mounts.get(key):
                if node in claimed:
                    continue
                if info.kinds[key] == "router":
                    # never mounted anywhere we can see: its real prefix is unknown
                    info.sites.append(f"{rel}:{info.decl[key]}")
                emit(node, "", frozenset())
    for info in live.values():
        result.dynamic_sites.extend(info.sites)
    return result


def _mount_target(rel: str, mount: _Mount, load) -> _NodeKey | str:
    """Node a mount points at, or "site" when it cannot be followed, or
    "ignore" when the target turns out to be plain middleware."""
    if mount.kind == "local":
        return rel, mount.ident
    target = load(mount.target)
    if target is None:
        return "site"
    dest = _resolve_export(load, mount.target, mount.ident)
    owner = load(dest[0]) if dest is not None else target
    if dest is not None and owner is not None and dest[1] in owner.kinds:
        return dest
    return "ignore" if owner is not None and not owner.kinds else "site"
