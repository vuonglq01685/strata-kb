"""Minimal-API routes for the ASP.NET Core adapter: `MapGet` / `MapPost` /
`MapPut` / `MapDelete` / `MapPatch` / `MapMethods` / `MapHealthChecks` calls
and the `MapGroup(prefix)` chains they hang off.

**Prefix tracking.** Inside one method (or the file's top-level statements)
a variable assigned a `MapGroup` chain remembers its prefix, so
`var api = app.MapGroup("/api"); api.MapGet("/x", ...)` is `/api/x`. Calls
in between that return the builder (`RequireAuthorization()`, `WithTags()`,
...) change nothing. An identifier that was never assigned is the app itself
(prefix empty).

**Endpoint helpers.** A static method or extension taking an
`IEndpointRouteBuilder`, `RouteGroupBuilder` or `WebApplication`
(`public static void MapUsers(this IEndpointRouteBuilder app)`) is expanded
at each call site with the caller's prefix; its own routes are relative to
its builder parameter. A helper no code in the repo calls, one called with an
unreadable prefix, two helpers of one name, a recursive helper and a helper
whose return value is used as a group are sites.

**Default to a site.** Every other `Map...` call is a site (`Map`, `MapWhen`,
`MapFallback*`, `MapControllerRoute`, `MapHub`, `MapGrpcService`,
`MapIdentityApi`, an unknown library extension): it serves paths this scan
cannot list. Page / documentation mappings (`MapControllers`,
`MapRazorPages`, `MapOpenApi`, `MapSwagger`, ...) are not sites. A `Map...`
call the walk never reached (a field initializer, a property) is a site too.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _cs_ast as ast
from strata_kb.codeingest.extractors._jvm_ast import run_cached
from strata_kb.codeingest.extractors._routes_jsutil import _text
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)

if TYPE_CHECKING:
    from tree_sitter import Node

_VERBS = {
    "MapGet": "GET",
    "MapPost": "POST",
    "MapPut": "PUT",
    "MapDelete": "DELETE",
    "MapPatch": "PATCH",
}
_HTTP_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"}
)
# mappings that serve pages, documentation or the controllers read elsewhere
_BENIGN = frozenset(
    {
        "MapControllers",
        "MapRazorPages",
        "MapRazorComponents",
        "MapBlazorHub",
        "MapOpenApi",
        "MapSwagger",
        "MapScalarApiReference",
        "MapStaticAssets",
        "MapToApiVersion",
    }
)
_BUILT_IN = frozenset({*_VERBS, "MapMethods", "MapGroup", "MapHealthChecks", *_BENIGN})
_BUILDERS = frozenset({"IEndpointRouteBuilder", "RouteGroupBuilder", "WebApplication"})
_BUILDER_USE = re.compile(
    rb"\b(?:IEndpointRouteBuilder|RouteGroupBuilder|WebApplication)\b"
)
_MAP_CALL = re.compile(r"Map[A-Z]\w*")
# how a local becomes the app itself
_APP_INIT = re.compile(
    r"\.Build\s*\(\s*\)|WebApplication\s*\.\s*Create|\bCreateBuilder\b"
)
_UNITS = frozenset(
    {"method_declaration", "constructor_declaration", "operator_declaration"}
)
_WRAPPERS = ("parenthesized_expression", "await_expression", "postfix_unary_expression")
_Key = tuple[str, int]  # (file, start byte): one syntax node


@dataclass(frozen=True)
class _Helper:
    rel: str
    node: Node
    name: str
    cls: str
    param: str
    index: int  # position of the builder among the parameters
    extension: bool
    returns: str = ""  # simple name of the return type

    @property
    def key(self) -> _Key:
        return self.rel, self.node.start_byte


@dataclass
class _Acc:
    """What a walk found: routes, sites, the `Map...` nodes it consumed."""

    routes: list[Route] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)
    nodes: set[_Key] = field(default_factory=set)
    expanded: set[_Key] = field(default_factory=set)


@dataclass
class _Run:
    root: Path
    helpers: dict[str, list[_Helper]]
    summaries: dict[_Key, _Acc] = field(default_factory=dict)
    active: set[_Key] = field(default_factory=set)
    members: dict[str, dict[str, str | None]] = field(default_factory=dict)
    # helpers a walk of that file expanded (callers outside the scope's files)
    expanded_by: dict[str, set[_Key]] = field(default_factory=dict)

    def fields(self, rel: str, top: Node | None = None) -> dict[str, str | None]:
        """Fields and properties of a file typed as a builder: the app
        itself (`WebApplication`, prefix empty) or a builder / group whose
        prefix was set somewhere else (None)."""
        if rel not in self.members:
            found: dict[str, str | None] = {}
            if top is None:
                data = ast.source(self.root, rel)
                top = (
                    ast.tree(self.root, rel, data).root_node
                    if data is not None
                    else None
                )
            for decl in ast.type_decls(top) if top is not None else []:
                for member in ast.body_members(decl):
                    typed = member
                    if member.type == "field_declaration":
                        typed = next(
                            (
                                c
                                for c in member.children
                                if c.type == "variable_declaration"
                            ),
                            member,
                        )
                    kind = ast.simple_name(typed.child_by_field_name("type"))
                    if kind not in _BUILDERS:
                        continue
                    names = (
                        [
                            _text(d.child_by_field_name("name"))
                            for d in typed.children
                            if d.type == "variable_declarator"
                        ]
                        if member.type == "field_declaration"
                        else [_text(member.child_by_field_name("name"))]
                    )
                    for name in names:
                        found[name] = "" if kind == "WebApplication" else None
            self.members[rel] = found
        return self.members[rel]


def _callee(call: Node) -> tuple[str, Node | None, Node | None]:
    """(method name, receiver, name node) of `recv.Name<T>(...)` / `Name(...)`."""
    fn = call.child_by_field_name("function")
    recv: Node | None = None
    name = fn
    if fn is not None and fn.type == "member_access_expression":
        recv = fn.child_by_field_name("expression")
        name = fn.child_by_field_name("name")
    if name is not None and name.type == "generic_name" and name.named_children:
        name = name.named_children[0]
    return _text(name), recv, name


def _args(call: Node) -> list[tuple[str | None, Node]]:
    listing = call.child_by_field_name("arguments")
    out: list[tuple[str | None, Node]] = []
    for arg in listing.named_children if listing is not None else []:
        if arg.type != "argument":
            continue
        key = next((c for c in arg.named_children if c.type == "name_colon"), None)
        kids = [
            c for c in arg.named_children if c.type not in ("name_colon", "comment")
        ]
        if kids:
            out.append((_text(key).rstrip(": ") if key is not None else None, kids[-1]))
    return out


def _arg(args: list[tuple[str | None, Node]], position: int, name: str) -> Node | None:
    for key, node in args:
        if key == name:
            return node
    positional = [n for k, n in args if k is None]
    return positional[position] if position < len(positional) else None


def _walk_unit(node: Node, skip: frozenset[int]) -> Iterator[Node]:
    """Pre-order walk that leaves the helpers (by start byte) to their own scan."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(c for c in reversed(current.children) if c.start_byte not in skip)


_CONSTRAINT = re.compile(r"where\s+(\w+)\s*:\s*(.*)", re.DOTALL)


def _is_builder(type_name: str, constraints: dict[str, str]) -> bool:
    """A builder type, or a type parameter constrained to one."""
    name = ast.simple_name(type_name).rstrip("?").strip()
    bound = constraints.get(name, "")
    return name in _BUILDERS or any(
        ast.simple_name(b).rstrip("?") in _BUILDERS for b in bound.split(",")
    )


def _helper_of(rel: str, node: Node, cls: str) -> _Helper | None:
    constraints = {}
    for clause in node.children:
        found = (
            _CONSTRAINT.match(_text(clause)) if "constraint" in clause.type else None
        )
        if found:
            constraints[found.group(1)] = found.group(2)
    for index, param in enumerate(ast.params(node)):
        if _is_builder(param.type, constraints):
            kind = node.child_by_field_name("returns") or node.child_by_field_name(
                "type"
            )
            return _Helper(
                rel,
                node,
                ast.decl_name(node),
                cls,
                param.name,
                index,
                param.this,
                ast.simple_name(kind).rstrip("?"),
            )
    return None


def helper_names(root: Path, repo_files: list[str]) -> frozenset[str]:
    """Names of the repo's endpoint helpers: a file that calls one is read."""
    return frozenset(_helper_index(root, repo_files))


def _seed(node: Node) -> dict[str, str | None]:
    """Parameters of a method that is not a helper: not the app, so a route
    mapped on one is a site. A `WebApplication` is the app itself."""
    return {
        p.name: "" if ast.simple_name(p.type).rstrip("?") == "WebApplication" else None
        for p in ast.params(node)
    }


def _helper_index(root: Path, repo_files: list[str]) -> dict[str, list[_Helper]]:
    def scan() -> dict[str, list[_Helper]]:
        found: dict[str, list[_Helper]] = {}
        for rel in ast.cs_files(root, repo_files, repo_files):
            data = ast.source(root, rel)
            if data is None or not _BUILDER_USE.search(data):
                continue
            top = ast.tree(root, rel, data).root_node
            owners = [(d, ast.decl_name(d)) for d in ast.type_decls(top)]
            declared = [(m, name) for d, name in owners for m in ast.methods(d)]
            declared += [
                (n, "")
                for g in ast.members_of(top)
                if g.type == "global_statement"
                for n in g.named_children
                if n.type == "local_function_statement"
            ]
            for method, cls in declared:
                helper = _helper_of(rel, method, cls)
                if helper is not None:
                    found.setdefault(helper.name, []).append(helper)
        return found

    return run_cached(("cs-helpers", root), scan)


def _walk_file(run: _Run, rel: str, top: Node, acc: _Acc) -> None:
    """Walk one file: its top-level statements, its methods, and the bodies
    of the helpers it defines."""
    skip = _helper_starts(run, rel)
    scan_file = _Scan(run, rel, acc, skip)
    env: dict[str, str | None] = {}
    for statement in ast.members_of(top):
        if statement.type == "global_statement":
            scan_file.walk(statement, env)
    for node in _walk_unit(top, frozenset()):
        if node.type in _UNITS and node.start_byte not in skip:
            scan_file.walk(node, _seed(node))


def _called_elsewhere(run: _Run, repo_files: list[str], helper: _Helper) -> bool:
    """Whether a walk of any file that names the helper expands it (callers
    in other scopes, or in files this scope's hint never parsed)."""
    pattern = re.compile(
        rb"\b" + re.escape(helper.name.encode()) + rb"\s*(?:<[^>()]*>)?\s*\("
    )
    for rel in ast.cs_files(run.root, repo_files, repo_files):
        data = ast.source(run.root, rel)
        if data is None or not pattern.search(data):
            continue
        if rel not in run.expanded_by:
            acc = _Acc()
            _walk_file(run, rel, ast.tree(run.root, rel, data).root_node, acc)
            for other in run.helpers.values():
                for h in other:
                    if h.rel == rel and (summary := summarize(run, h)):
                        acc.expanded |= summary.expanded
            run.expanded_by[rel] = acc.expanded
        if helper.key in run.expanded_by[rel]:
            return True
    return False


class _Scan:
    """One walk (a method, the top-level statements, a helper's body)."""

    def __init__(self, run: _Run, rel: str, acc: _Acc, skip: frozenset[int]):
        self.run = run
        self.rel = rel
        self.acc = acc
        self.skip = skip

    def site(self, node: Node | None) -> None:
        line = node.start_point[0] + 1 if node is not None else 1
        self.acc.sites.append(f"{self.rel}:{line}")

    # -- prefix of a builder expression --------------------------------

    def builder_like(self, expr: Node, env: dict[str, str | None]) -> bool:
        while True:
            if expr.type == "identifier":
                return _text(expr) in env or _text(expr) in self.run.fields(self.rel)
            if expr.type == "member_access_expression":
                inner = expr.child_by_field_name("expression")
                if inner is None:
                    return False
                expr = inner
                continue
            if expr.type == "invocation_expression":
                name, recv, _n = _callee(expr)
                if name == "MapGroup" or name in self.run.helpers:
                    return True
                if recv is None:
                    return False
                expr = recv
                continue
            if expr.type in _WRAPPERS:
                if not expr.named_children:
                    return False
                expr = expr.named_children[-1]
                continue
            return False

    def prefix(self, expr: Node | None, env: dict[str, str | None]) -> str | None:
        """Prefix of the builder `expr` evaluates to; None when unreadable."""
        if expr is None:
            return ""
        if expr.type in _WRAPPERS:
            return (
                self.prefix(expr.named_children[-1], env) if expr.named_children else ""
            )
        if expr.type == "identifier":
            name = _text(expr)
            return env[name] if name in env else self.run.fields(self.rel).get(name, "")
        if expr.type == "member_access_expression":
            return self.prefix(expr.child_by_field_name("expression"), env)
        if expr.type != "invocation_expression":
            return ""
        name, recv, name_node = _callee(expr)
        if name == "MapGroup":
            base = self.prefix(recv, env)
            given = _arg(_args(expr), 0, "prefix") or _arg(_args(expr), 0, "pattern")
            text = ast.literal(given) if given is not None else None
            if base is None or text is None:
                self.site(name_node)
                return None
            self.acc.nodes.add((self.rel, expr.start_byte))
            return join_path(base, text)
        if name in self.run.helpers and name not in _BUILT_IN:
            found = self.run.helpers[name]
            if len(found) == 1 and found[0].returns == "WebApplication":
                return ""  # the app itself, handed back
            self.site(name_node)  # a group handed back by a helper
            return None
        return self.prefix(recv, env)

    # -- the walk ---------------------------------------------------------

    def walk(self, node: Node, env: dict[str, str | None]) -> None:
        """Visit `node` in source order. A lambda sees a copy of the scope
        plus its own parameters, so a parameter never outlives its body."""
        stack = [(node, env)]
        while stack:
            current, scope = stack.pop()
            if current is not node and current.start_byte in self.skip:
                continue
            inner = scope
            kind = current.type
            if kind in ("lambda_expression", "anonymous_method_expression"):
                inner = dict(scope)
                self.bind_lambda(current, inner)
            elif kind == "local_function_statement":
                inner = dict(scope)
                inner.update(_seed(current))  # a builder handed in: not the app
            elif kind == "variable_declarator":
                self.declare(current, scope)
            elif kind == "assignment_expression":
                left, right = (
                    current.child_by_field_name("left"),
                    current.child_by_field_name("right"),
                )
                if left is not None and right is not None and left.type == "identifier":
                    self.assign(_text(left), right, scope)
            elif kind in (
                "foreach_statement",
                "declaration_pattern",
                "declaration_expression",
            ):
                named = current.child_by_field_name(
                    "left" if kind == "foreach_statement" else "name"
                )
                if named is not None and named.type == "identifier":
                    scope[_text(named)] = None  # a variable this scan does not follow
            elif kind == "invocation_expression":
                self.call(current, scope)
            stack.extend((c, inner) for c in reversed(current.children))

    def declare(self, node: Node, env: dict[str, str | None]) -> None:
        if not node.named_children:
            return
        name = _text(node.named_children[0])
        init = node.named_children[-1] if len(node.named_children) >= 2 else None
        parent = node.parent
        declared = (
            ast.simple_name(parent.child_by_field_name("type"))
            if parent is not None and parent.type == "variable_declaration"
            else ""
        )
        if init is None:
            env[name] = None
        elif self.builder_like(init, env):
            env[name] = self.prefix(init, env)
        elif declared == "WebApplication" or _APP_INIT.search(_text(init)[:300]):
            env[name] = ""  # the app itself
        else:
            env[name] = None

    def assign(self, name: str, init: Node, env: dict[str, str | None]) -> None:
        if self.builder_like(init, env):
            env[name] = self.prefix(init, env)
        elif _text(init) and _APP_INIT.search(_text(init)[:300]):
            env[name] = ""
        else:
            env[name] = None

    def bind_lambda(self, node: Node, env: dict[str, str | None]) -> None:
        """Lambda parameters: the `endpoints` of `UseEndpoints(endpoints =>
        ...)` is the app; any other is a builder handed in by code this scan
        does not follow."""
        listing = node.child_by_field_name("parameters")
        names: list[tuple[str, str]] = []  # (name, declared type)
        if listing is not None and listing.type == "parameter_list":
            names = [(p.name, ast.simple_name(p.type)) for p in ast.params(node)]
        elif listing is not None:
            names = [(_text(listing), "")]
        call = node.parent.parent.parent if node.parent and node.parent.parent else None
        owner = (
            _callee(call)[0]
            if call is not None and call.type == "invocation_expression"
            else ""
        )
        for name, declared in names:
            env[name] = (
                "" if owner == "UseEndpoints" or declared == "WebApplication" else None
            )

    def call(self, node: Node, env: dict[str, str | None]) -> None:
        name, recv, name_node = _callee(node)
        key = (self.rel, node.start_byte)
        if name in _VERBS or name in ("MapMethods", "MapHealthChecks"):
            self.acc.nodes.add(key)
            self.route(node, name, recv, name_node, env)
        elif name == "MapGroup":
            self.acc.nodes.add(key)
            self.prefix(node, env)  # a prefix that is not a literal is a site
        elif name in _BENIGN:
            self.acc.nodes.add(key)
        elif name in self.run.helpers:
            self.acc.nodes.add(key)
            self.expand(node, name, recv, name_node, env)
        elif _MAP_CALL.fullmatch(name) or name == "Map":
            self.acc.nodes.add(key)
            self.site(name_node)

    def route(
        self,
        node: Node,
        name: str,
        recv: Node | None,
        name_node: Node | None,
        env: dict[str, str | None],
    ) -> None:
        base = self.prefix(recv, env)
        args = _args(node)
        path = ast.literal(_arg(args, 0, "pattern"))
        if base is None or path is None:
            self.site(name_node)
            return
        verbs = [_VERBS[name]] if name in _VERBS else ["ANY"]
        if name == "MapMethods":
            listed = ast.strings(_arg(args, 1, "httpMethods"))
            verbs = [v.upper() for v in listed or []]
            if not verbs or any(v not in _HTTP_METHODS for v in verbs):
                self.site(name_node)
                return
        handler, body = "(inline)", ""
        last = args[-1][1] if len(args) > 1 else None
        if name == "MapHealthChecks":
            handler = "MapHealthChecks"
        elif last is not None and last.type in (
            "identifier",
            "member_access_expression",
        ):
            handler = " ".join(_text(last).split())
        elif last is not None and last.type in (
            "lambda_expression",
            "anonymous_method_expression",
        ):
            body = next(
                (
                    p.type.rstrip("?").strip()
                    for p in ast.params(last)
                    if any(a.name == "FromBody" for a in p.attrs)
                ),
                "",
            )
        line = (name_node or node).start_point[0] + 1
        self.acc.routes += [
            Route(verb, join_path(base, path), handler, self.rel, line, body)
            for verb in verbs
        ]

    def expand(
        self,
        node: Node,
        name: str,
        recv: Node | None,
        name_node: Node | None,
        env: dict[str, str | None],
    ) -> None:
        found = self.run.helpers[name]
        if len(found) != 1:
            self.site(name_node)  # two helpers of one name
            return
        helper = found[0]
        args = _args(node)
        static_form = recv is None or ast.simple_name(recv) == helper.cls
        builder = (
            recv
            if helper.extension and not static_form
            else _arg(args, helper.index, helper.param)
        )
        base = self.prefix(builder, env) if builder is not None else None
        if base is None:
            self.site(name_node)
            return
        summary = summarize(self.run, helper)
        if summary is None:  # recursion
            self.site(name_node)
            return
        self.acc.routes += [
            replace(r, path=join_path(base, r.path)) for r in summary.routes
        ]
        self.acc.sites += summary.sites
        self.acc.nodes |= summary.nodes
        self.acc.expanded |= summary.expanded | {helper.key}


def summarize(run: _Run, helper: _Helper) -> _Acc | None:
    """Routes of a helper body relative to its builder parameter (None when
    the helper is being summarised already: a cycle)."""
    if helper.key in run.summaries:
        return run.summaries[helper.key]
    if helper.key in run.active:
        return None
    run.active.add(helper.key)
    acc = _Acc()
    body = helper.node.child_by_field_name("body")
    if body is not None:
        _Scan(run, helper.rel, acc, frozenset()).walk(
            body, {**_seed(helper.node), helper.param: ""}
        )
    run.active.discard(helper.key)
    run.summaries[helper.key] = acc
    return acc


def _helper_starts(run: _Run, rel: str) -> frozenset[int]:
    return frozenset(
        h.node.start_byte for hs in run.helpers.values() for h in hs if h.rel == rel
    )


def scan(
    root: Path, trees: dict[str, Node], repo_files: list[str], result: AdapterResult
) -> tuple[list[Route], bool]:
    """Minimal-API routes of a scope's parsed files; sites go to `result`.
    The flag says a helper defined here maps routes that a caller (maybe in
    another scope) lists: this scope serves them, so it is not empty."""
    delegated = False
    run = run_cached(
        ("cs-minimal", root), lambda: _Run(root, _helper_index(root, repo_files))
    )
    acc = _Acc()
    for rel in sorted(trees):
        _walk_file(run, rel, trees[rel], acc)
    # helpers defined here: their bodies are scanned even when nothing calls
    # them. One no walk expands serves nothing this scan can list, so each
    # route it maps is a site.
    for hs in run.helpers.values():
        for helper in hs:
            if helper.rel not in trees:
                continue
            summary = summarize(run, helper)
            if summary is None:
                continue
            acc.nodes |= summary.nodes
            acc.sites += summary.sites
            if helper.key in acc.expanded or _called_elsewhere(run, repo_files, helper):
                delegated = delegated or bool(summary.routes)
            else:
                acc.sites += [f"{r.file}:{r.line}" for r in summary.routes]
    # a `Map...` call nothing above consumed (a field initializer, a property)
    for rel in sorted(trees):
        for node in _walk_unit(trees[rel], frozenset()):
            if node.type != "invocation_expression":
                continue
            name, _recv, name_node = _callee(node)
            if (rel, node.start_byte) not in acc.nodes and (
                _MAP_CALL.fullmatch(name) or name == "Map"
            ):
                acc.sites.append(f"{rel}:{(name_node or node).start_point[0] + 1}")
    result.dynamic_sites += acc.sites
    return acc.routes, delegated
