"""FastAPI and Flask route adapters (Python).

Both frameworks hang routes on *holder* objects: an app (`FastAPI()`,
`Flask()`) or a router (`APIRouter()`, `Blueprint()`), joined by
`include_router` / `register_blueprint` / `mount`. The adapter builds that
graph across the scope's modules -- following relative and absolute imports,
`from pkg import module`, re-exports and function-local imports -- and walks
it from every app, joining prefixes the way each framework does:

- FastAPI: `include prefix + router prefix + route path`.
- Flask: `register_blueprint(url_prefix=)` replaces the blueprint's own
  `url_prefix`; a nested blueprint appends to its parent's.

Routes: `@x.get/post/put/patch/delete/head/options/trace(path)`,
`@x.route(path, methods=[...])` (Flask default `GET`), `@x.api_route`,
`add_api_route`, `add_url_rule`, and class views (`MethodView` lists the
methods the class defines; `View` its `methods`). A FastAPI handler's request
type is its Pydantic body parameter (see `_py_fields`).

**Sites (never silently dropped).** A non-literal path, prefix or method list;
an object a route is declared on that is not a holder this module can see
(parameter, call result, loop variable, a library `Api`); an include or
register of an unresolvable child; `mount` of anything but a sub app or
`StaticFiles`; websockets; `root_path`, `APPLICATION_ROOT`, werkzeug `Rule`,
starlette `Route`/`Mount`; Flask extensions that add routes; a holder no
include reaches (its routes are listed with their own prefix only); a
syntax error; and a web module (the framework is imported) with 0 routes and 0
sites, at its dependency line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _py_ast as ast
from strata_kb.codeingest.extractors import _py_fields
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._scopes import Scope

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["ADAPTERS"]

_CTORS = {
    "FastAPI": ("FastAPI", "app"),
    "APIRouter": ("FastAPI", "router"),
    "Flask": ("Flask", "app"),
    "Blueprint": ("Flask", "router"),
}
_VERBS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
)
_DECORATORS = _VERBS | {"route", "api_route", "websocket", "websocket_route"}
_IMPERATIVE = frozenset(
    {
        "include_router", "register_blueprint", "add_url_rule", "add_api_route",
        "add_route", "mount", "add_resource", "add_namespace", "add_api",
        "add_websocket_route", "add_api_websocket_route",
    }
)  # fmt: skip
# Unknown receiver: these names only mean routing (`mount`/`add_route` also
# occur in HTTP clients and servers that are not this framework).
_UNKNOWN_SITES = _IMPERATIVE - {"mount", "add_route"}
_VIEW_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
_HINT = re.compile(
    rb"FastAPI|APIRouter|Flask|Blueprint|MethodView"
    rb"|@\s*[\w.]+\.(?:get|post|put|patch|delete|head|options|trace|route|api_route|websocket|websocket_route)\s*\("
    rb"|\.(?:include_router|register_blueprint|add_url_rule|add_api_route|add_route|mount"
    rb"|add_resource|add_namespace|add_api|add_websocket_route|add_api_websocket_route)\s*\("
    rb"|\b(?:Rule|Route|Mount|APIRoute|WebSocketRoute)\s*\("
)
_ROUTING_CLASSES = {
    "werkzeug.routing": {"Rule"},
    "starlette.routing": {"Route", "Mount", "WebSocketRoute", "Host"},
    "fastapi.routing": {"APIRoute", "APIWebSocketRoute"},
}
_FLASK_LIBS = re.compile(
    rb"^[ \t]*(?:from|import)[ \t]+(?:flask_restx|flask_restful|flask_restplus"
    rb"|flask_smorest|flask_classful|flask_admin|flask_appbuilder|connexion"
    rb"|apiflask|flask_openapi3|flask_security\w*|flask_apispec|flask_restless|eve)\b",
    re.MULTILINE,
)
_APP_ROOT = re.compile(rb"\bAPPLICATION_ROOT\b|\bDispatcherMiddleware\b")
_ROOT_PATH = re.compile(rb"\b(?:root_path|openapi_prefix)\s*=")
_URL_PREFIX_SET = re.compile(rb"\.url_prefix\s*=(?!=)")
_IMPORT = {
    "FastAPI": re.compile(
        rb"^[ \t]*(?:from|import)[ \t]+(?:fastapi|starlette)\b", re.MULTILINE
    ),
    "Flask": re.compile(rb"^[ \t]*(?:from|import)[ \t]+flask\b", re.MULTILINE),
}
_DEP = {
    "FastAPI": re.compile(r"(?<![\w.-])fastapi(?!\w)", re.IGNORECASE),
    "Flask": re.compile(r"(?<![\w.-])flask(?!\w)", re.IGNORECASE),
    "Django": re.compile(r"(?<![\w.-])django(?!\w)", re.IGNORECASE),
}
_PY_MANIFESTS = ("pyproject.toml", "setup.cfg", "setup.py", "Pipfile")


@dataclass
class Decl:
    method: str
    path: str
    handler: str
    file: str
    line: int
    request_type: str = ""


@dataclass(eq=False)
class Holder:
    fw: str
    kind: str  # app | router
    file: str
    line: int
    prefix: str | None = ""  # None: written, but not a literal
    decls: list[Decl] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)
    incoming: int = 0


@dataclass
class Edge:
    child: Holder
    prefix: str | None  # None: not given (Flask: the child's own applies)


def dependency_site(root: Path, scope: Scope, repo_files: list[str], fw: str) -> str:
    """`file:line` of the first manifest line naming the framework."""
    names = [
        f
        for f in sorted(repo_files)
        if (f.rsplit("/", 1)[0] if "/" in f else ".") == scope.path
        and (
            f.rsplit("/", 1)[-1] in _PY_MANIFESTS
            or re.fullmatch(r"requirements[^/]*\.txt", f.rsplit("/", 1)[-1])
        )
    ]
    for rel in names:
        try:
            lines = (
                (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
            )
        except OSError:
            continue
        for number, line in enumerate(lines, start=1):
            if not line.lstrip().startswith("#") and _DEP[fw].search(line):
                return f"{rel}:{number}"
    return f"{scope.manifest if scope.path == '.' else scope.path + '/' + scope.manifest}:1"


def _line_at(data: bytes, pos: int) -> int:
    return data.count(b"\n", 0, pos) + 1


def import_site(root: Path, files: list[str], pattern: re.Pattern[bytes]) -> str | None:
    """`file:line` of the first scope file matching `pattern`."""
    for rel in files:
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        found = pattern.search(data)
        if found:
            return f"{rel}:{_line_at(data, found.start())}"
    return None


def pattern_sites(
    root: Path, files: list[str], pattern: re.Pattern[bytes]
) -> list[str]:
    out = []
    for rel in files:
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        out += [f"{rel}:{_line_at(data, m.start())}" for m in pattern.finditer(data)]
    return out


class _Engine:
    def __init__(self, root: Path, repo_files: list[str], proj: ast.Project, fw: str):
        self.root = root
        self.repo_files = repo_files
        self.proj = proj
        self.fw = fw
        self.holders: dict[tuple[str, int], Holder] = {}
        self.order: list[Holder] = []
        self.analyzed: set[str] = set()
        self.file_sites: dict[str, list[str]] = {}

    # -- bookkeeping
    def _stray(self, rel: str, node: Node) -> None:
        self.file_sites.setdefault(rel, []).append(f"{rel}:{ast_line(node)}")

    # -- per file
    def analyze(self, rel: str) -> None:
        if rel in self.analyzed:
            return
        self.analyzed.add(rel)
        info = self.proj.info(rel)
        if info is None:
            self.file_sites.setdefault(rel, []).append(f"{rel}:1")
            return
        if not _HINT.search(info.data):
            return
        if info.error_line is not None:
            self.file_sites.setdefault(rel, []).append(f"{rel}:{info.error_line}")
        calls = ast.all_calls(info.tree)
        for call in calls:
            self._ctor(rel, call)
        for call in calls:
            self._call(rel, call)

    def _name(self, rel: str, call: Node) -> str:
        fn = ast.callee(call)
        if fn is None:
            return ""
        if fn.type == "identifier":
            return self.proj.imported_name(rel, fn)
        parts = ast.dotted(fn)
        return parts[-1] if parts else ""

    def _ctor(self, rel: str, call: Node) -> None:
        name = self._name(rel, call)
        if name not in _CTORS:
            return
        fw, kind = _CTORS[name]
        parent = call.parent
        bound = (
            parent is not None
            and parent.type == "assignment"
            and parent.child_by_field_name("right") == call
        )
        holder = Holder(fw, kind, rel, ast_line(call))
        args = ast.call_args(call)
        here = f"{rel}:{holder.line}"
        if args.splat:
            holder.sites.append(here)  # `**options` may carry a prefix
        if fw == "FastAPI":
            if {"root_path", "openapi_prefix", "routes"} & args.kw.keys():
                holder.sites.append(here)
            if kind == "router" and "prefix" in args.kw:
                holder.prefix = ast.lit(args.kw["prefix"])
        else:
            if "subdomain" in args.kw or len(args.pos) > 2:
                holder.sites.append(here)
            if kind == "router" and "url_prefix" in args.kw:
                holder.prefix = ast.lit(args.kw["url_prefix"])
        if holder.prefix is None:
            holder.sites.append(here)
        if not bound:
            # `return Blueprint(..)`, `register(APIRouter())`: no name to follow
            holder.sites.append(here)
        self.holders[(rel, call.id)] = holder
        self.order.append(holder)

    # -- receivers
    def holder_of(self, rel: str, node: Node | None, depth: int = 0) -> Holder | None:
        if node is None or depth > 6:
            return None
        ref = self.proj.chain(rel, node)
        return self._holder_ref(ref, depth)

    def _holder_ref(self, ref: ast.Ref, depth: int) -> Holder | None:
        if depth > 6:
            return None
        if ref.kind == "assign" and ref.node is not None:
            self.analyze(ref.file)
            held = self.holders.get((ref.file, ref.node.id))
            if held is not None:
                return held
            value = ast.unwrap(ref.node)
            if value is not None and value.type in ("identifier", "attribute"):
                return self.holder_of(ref.file, value, depth + 1)
            return None
        if ref.kind == "attr" and ref.base is not None and ref.name == "router":
            base = self._holder_ref(ref.base, depth + 1)
            return base if base is not None and base.kind == "app" else None
        return None

    # -- calls
    def _call(self, rel: str, call: Node) -> None:
        fn = ast.callee(call)
        if fn is None:
            return
        if fn.type == "identifier":
            module = self.proj.import_module_of(rel, fn)
            if self._name(rel, call) in _ROUTING_CLASSES.get(module, ()):
                self._stray(rel, call)
            return
        if fn.type != "attribute":
            return
        attr = ast.text(fn.child_by_field_name("attribute"))
        if attr in ("append", "extend", "insert"):
            self._route_list_edit(rel, call, fn)
            return
        if attr not in _DECORATORS and attr not in _IMPERATIVE:
            return
        holder = self.holder_of(rel, fn.child_by_field_name("object"))
        deco = call.parent is not None and call.parent.type == "decorator"
        if holder is None:
            if (
                attr in _DECORATORS
                and deco
                and (ast.call_args(call).pos or ast.call_args(call).kw)
            ) or attr in _UNKNOWN_SITES:
                self._stray(rel, call)
            return
        if holder.fw != self.fw:
            return
        if attr in _DECORATORS:
            self._decorated(rel, call, holder, attr, deco)
        else:
            self._imperative(rel, call, holder, attr)

    def _route_list_edit(self, rel: str, call: Node, fn: Node) -> None:
        """`app.routes.append(...)`: routes added behind the graph's back."""
        target = fn.child_by_field_name("object")
        if target is None or target.type != "attribute":
            return
        if ast.text(target.child_by_field_name("attribute")) != "routes":
            return
        holder = self.holder_of(rel, target.child_by_field_name("object"))
        if holder is not None and holder.fw == self.fw:
            holder.sites.append(f"{rel}:{ast_line(call)}")

    def _methods(self, attr: str, args: ast.Args) -> list[str] | None:
        if attr in _VERBS:
            return [attr.upper()]
        node = args.kw.get("methods")
        if node is None:
            return ["GET"]
        found = ast.literal_strings(node)
        if not found:
            return None
        return list(dict.fromkeys(m.upper() for m in found))

    def _decorated(
        self, rel: str, call: Node, holder: Holder, attr: str, deco: bool
    ) -> None:
        here = f"{rel}:{ast_line(call)}"
        args = ast.call_args(call)
        target = ast.decorated(call) if deco else None
        if target is None or attr in ("websocket", "websocket_route") or args.splat:
            holder.sites.append(here)
            return
        node = args.pos[0] if args.pos else args.kw.get("path") or args.kw.get("rule")
        path = ast.lit(node)
        methods = self._methods(attr, args)
        if path is None or methods is None:
            holder.sites.append(here)
            return
        line = ast_line(call)
        if target.type == "class_definition":
            self._class_view(rel, target, holder, path, here, line, args)
            return
        owner = ast.enclosing_class(target)
        handler = ast.func_name(target)
        if owner is not None:
            handler = f"{ast.text(owner.child_by_field_name('name'))}.{handler}"
        request = self._request(rel, target)
        holder.decls += [Decl(m, path, handler, rel, line, request) for m in methods]

    def _request(self, rel: str, func: Node) -> str:
        if self.fw != "FastAPI":
            return ""
        return _py_fields.body_type(self.root, self.repo_files, func, rel)

    def _class_view(
        self,
        rel: str,
        cls: Node,
        holder: Holder,
        path: str,
        here: str,
        line: int,
        args: ast.Args,
        explicit: list[str] | None = None,
    ) -> None:
        methods = explicit or self._view_methods(rel, cls)
        if methods is None:
            holder.sites.append(here)
            return
        name = ast.text(cls.child_by_field_name("name"))
        holder.decls += [
            Decl(
                m,
                path,
                f"{name}.{m.lower()}" if m.lower() in _VIEW_METHODS else name,
                rel,
                line,
            )
            for m in methods
        ]

    def _view_methods(self, rel: str, cls: Node) -> list[str] | None:
        """HTTP methods of a Flask class view, None when not readable."""
        defined: list[str] = []
        attr: list[str] | None = None
        kind = ""
        stack = [(rel, cls)]
        seen: set[int] = set()
        while stack:
            file, node = stack.pop(0)
            if node.id in seen or len(seen) > 12:
                return None
            seen.add(node.id)
            body = node.child_by_field_name("body")
            for stmt in body.named_children if body is not None else []:
                inner = stmt
                if stmt.type == "decorated_definition":
                    inner = stmt.child_by_field_name("definition") or stmt
                if inner.type == "function_definition":
                    name = ast.func_name(inner)
                    if name in _VIEW_METHODS:
                        defined.append(name.upper())
                elif (
                    inner.type == "assignment"
                    and ast.text(inner.child_by_field_name("left")) == "methods"
                    and attr is None
                ):
                    attr = ast.literal_strings(inner.child_by_field_name("right"))
                    if attr is None:
                        return None
            bases = node.child_by_field_name("superclasses")
            for base in bases.named_children if bases is not None else []:
                if base.type == "keyword_argument":
                    continue
                parts = ast.dotted(base)
                if not parts:
                    return None
                if parts[-1] in ("MethodView", "View"):
                    kind = kind or parts[-1]
                    continue
                ref = self.proj.chain(file, base)
                if ref.kind != "class" or ref.node is None:
                    return None
                stack.append((ref.file, ref.node))
        if kind == "MethodView":
            return list(dict.fromkeys(defined)) or None
        if kind == "View":
            return list(dict.fromkeys(m.upper() for m in attr)) if attr else ["GET"]
        return None

    def _imperative(self, rel: str, call: Node, holder: Holder, attr: str) -> None:
        here = f"{rel}:{ast_line(call)}"
        args = ast.call_args(call)
        pos = args.pos
        if args.splat:
            holder.sites.append(here)
            return
        if attr == "include_router" and self.fw == "FastAPI":
            self._link(
                rel,
                holder,
                pos[0] if pos else args.kw.get("router"),
                args.kw.get("prefix"),
                here,
            )
        elif attr == "register_blueprint" and self.fw == "Flask":
            if "subdomain" in args.kw:
                holder.sites.append(here)
            child = pos[0] if pos else args.kw.get("blueprint")
            self._link(rel, holder, child, args.kw.get("url_prefix"), here, flask=True)
        elif attr == "mount" and self.fw == "FastAPI":
            self._mount(rel, holder, args, here)
        elif attr in ("add_api_route", "add_route") and self.fw == "FastAPI":
            self._add_api_route(rel, call, holder, args, here)
        elif attr == "add_url_rule" and self.fw == "Flask":
            self._add_url_rule(rel, call, holder, args, here)
        else:
            holder.sites.append(here)

    def _link(
        self,
        rel: str,
        holder: Holder,
        child_node: Node | None,
        prefix_node: Node | None,
        here: str,
        flask: bool = False,
    ) -> None:
        child = self.holder_of(rel, child_node)
        if child is None or child.fw != self.fw or child.kind != "router" and flask:
            holder.sites.append(here)
            return
        prefix: str | None = None if flask else ""
        if prefix_node is not None:
            prefix = ast.lit(prefix_node)
            if prefix is None:
                holder.sites.append(here)
                prefix = None if flask else ""
        holder.edges.append(Edge(child, prefix))
        child.incoming += 1

    def _mount(self, rel: str, holder: Holder, args: ast.Args, here: str) -> None:
        path = ast.lit(args.pos[0] if args.pos else args.kw.get("path"))
        target = args.pos[1] if len(args.pos) > 1 else args.kw.get("app")
        inner = ast.unwrap(target)
        if inner is not None and inner.type == "call":
            parts = ast.dotted(ast.callee(inner)) or []
            if parts and parts[-1] == "StaticFiles":
                return  # static files are not routes
        child = self.holder_of(rel, target)
        if path is None or child is None or child.fw != "FastAPI":
            holder.sites.append(here)
            return
        holder.edges.append(Edge(child, path))
        child.incoming += 1

    def _endpoint(self, rel: str, node: Node | None) -> tuple[str, str]:
        """(handler text, request type) of an endpoint expression."""
        handler = ast.text(node) or "?"
        ref = self.proj.chain(rel, node)
        if ref.kind == "func" and ref.node is not None:
            return handler, self._request(ref.file, ref.node)
        return handler, ""

    def _add_api_route(
        self, rel: str, call: Node, holder: Holder, args: ast.Args, here: str
    ) -> None:
        path = ast.lit(args.pos[0] if args.pos else args.kw.get("path"))
        endpoint = args.pos[1] if len(args.pos) > 1 else args.kw.get("endpoint")
        methods = self._methods("add_api_route", args)
        if path is None or methods is None or endpoint is None:
            holder.sites.append(here)
            return
        handler, request = self._endpoint(rel, endpoint)
        holder.decls += [
            Decl(m, path, handler, rel, ast_line(call), request) for m in methods
        ]

    def _add_url_rule(
        self, rel: str, call: Node, holder: Holder, args: ast.Args, here: str
    ) -> None:
        path = ast.lit(args.pos[0] if args.pos else args.kw.get("rule"))
        view = args.kw.get("view_func") or (args.pos[2] if len(args.pos) > 2 else None)
        if path is None or view is None:
            holder.sites.append(here)
            return
        explicit: list[str] | None = None
        if "methods" in args.kw:
            explicit = ast.literal_strings(args.kw["methods"])
            if not explicit:
                holder.sites.append(here)
                return
            explicit = list(dict.fromkeys(m.upper() for m in explicit))
        line = ast_line(call)
        inner = ast.unwrap(view)
        if inner is not None and inner.type == "call":
            fn = ast.callee(inner)
            if (
                fn is not None
                and fn.type == "attribute"
                and ast.text(fn.child_by_field_name("attribute")) == "as_view"
            ):
                ref = self.proj.chain(rel, fn.child_by_field_name("object"))
                if ref.kind == "class" and ref.node is not None:
                    self._class_view(
                        ref.file, ref.node, holder, path, here, line, args, explicit
                    )
                    return
            holder.sites.append(here)
            return
        ref = self.proj.chain(rel, view)
        if ref.kind == "class" and ref.node is not None:
            holder.sites.append(here)  # a class passed as the view, not `as_view()`
            return
        handler = ast.text(view) or "?"
        holder.decls += [Decl(m, path, handler, rel, line) for m in explicit or ["GET"]]


def ast_line(node: Node) -> int:
    return node.start_point[0] + 1


def _walk(
    holder: Holder,
    base: str,
    override: str | None,
    stack: tuple[Holder, ...],
    out: list[Route],
    sites: list[str],
    seen: set[Holder],
) -> None:
    if holder in stack:
        sites.append(f"{holder.file}:{holder.line}")
        return
    seen.add(holder)
    sites += holder.sites
    own = join_path(base, override if override is not None else holder.prefix or "")
    out += [
        Route(
            d.method, join_path(own, d.path), d.handler, d.file, d.line, d.request_type
        )
        for d in holder.decls
    ]
    for edge in holder.edges:
        if holder.fw == "Flask":
            _walk(edge.child, own, edge.prefix, (*stack, holder), out, sites, seen)
        else:
            _walk(
                edge.child,
                join_path(own, edge.prefix or ""),
                None,
                (*stack, holder),
                out,
                sites,
                seen,
            )


def _run(
    fw: str, root: Path, scope: Scope, scope_files: list[str], repo_files: list[str]
) -> AdapterResult:
    pyfiles = ast.product_files(repo_files)
    mine = [f for f in ast.product_files(scope_files)]
    proj = ast.Project(root, pyfiles)
    engine = _Engine(root, repo_files, proj, fw)
    result = AdapterResult()
    scoped = frozenset(mine)
    for rel in mine:
        try:
            engine.analyze(rel)
        except Exception:  # noqa: BLE001 -- degrade, never crash: one bad file must not abort the scope
            result.dynamic_sites.append(f"{rel}:1")
    routes: list[Route] = []
    seen: set[Holder] = set()
    mine_holders = [h for h in engine.order if h.file in scoped and h.fw == fw]
    for h in mine_holders:
        if h.kind == "app" and h.incoming == 0:
            _walk(h, "", None, (), routes, result.dynamic_sites, seen)
    # Not reached from an app: list what is known, and say it is incomplete.
    leftovers = [
        h for h in mine_holders if h not in seen and (h.decls or h.edges or h.sites)
    ]
    for h in sorted(leftovers, key=lambda x: (x.incoming > 0, x.file, x.line)):
        if h in seen:
            continue
        result.dynamic_sites.append(f"{h.file}:{h.line}")
        _walk(h, "", None, (), routes, result.dynamic_sites, seen)
    for rel in mine:
        result.dynamic_sites += engine.file_sites.get(rel, [])
    result.dynamic_sites += _framework_sites(fw, root, mine)
    result.routes = routes
    if not routes and not result.dynamic_sites:
        net = _web_net(fw, root, scope, mine, repo_files)
        if net:
            result.dynamic_sites.append(net)
    return result


def _framework_sites(fw: str, root: Path, files: list[str]) -> list[str]:
    if fw == "FastAPI":
        return pattern_sites(root, files, _ROOT_PATH)
    return [
        *pattern_sites(root, files, _APP_ROOT),
        *pattern_sites(root, files, _FLASK_LIBS),
        *pattern_sites(root, files, _URL_PREFIX_SET),
    ]


def _web_net(
    fw: str, root: Path, scope: Scope, files: list[str], repo_files: list[str]
) -> str | None:
    """A module that imports the framework yet yielded nothing: say so."""
    if import_site(root, files, _IMPORT[fw]) is None:
        return None
    return dependency_site(root, scope, repo_files, fw)


def _adapter(fw: str):
    def adapter(
        root: Path, scope: Scope, scope_files: list[str], repo_files: list[str]
    ) -> AdapterResult:
        return _run(fw, root, scope, scope_files, repo_files)

    return adapter


ADAPTERS = {"FastAPI": _adapter("FastAPI"), "Flask": _adapter("Flask")}
