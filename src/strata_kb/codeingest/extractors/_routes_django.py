"""Django route adapter: `urlpatterns` of `path()`, `re_path()` / `url()` and
`include()`, plus Django REST framework routers and `@api_view`.

The URLconf graph starts at `ROOT_URLCONF` (a literal in any settings file);
with none, at every `urls.py` (or module with `urlpatterns`) no other URLconf
includes. `include("app.urls")`, `include(("app.urls", ns))`,
`include(patterns_list)`, an imported URLconf module and `include(router.urls)`
are followed; prefixes join like Django joins them. A `path()` route keeps
its converters (`<int:pk>`); a `re_path()` regex is kept verbatim (the path
then reads `prefix` + regex, `^`/`$` included). Methods are `ANY`, except a
function view decorated `@api_view([...])`, `@require_http_methods([...])`,
`@require_GET/POST/safe`.

DRF: `DefaultRouter()` / `SimpleRouter()` with `router.register("p", ViewSet)`
expands to the standard list/detail routes the ViewSet's bases and methods
provide (`ModelViewSet`, `ReadOnlyModelViewSet`, the `*Mixin`s, defined
`list/create/retrieve/update/partial_update/destroy`) and `@action` routes.
Not listed: the `.json` format-suffix variants of a `DefaultRouter`.

**Sites.** Non-literal route or prefix; a `urlpatterns` built any way this
reader cannot follow (a call, a comprehension, a function); `include()` of a
module outside the repo (except the admin) or of something unresolved;
`i18n_patterns`, `format_suffix_patterns`; a router class other than the DRF
ones; a ViewSet with a base this reader does not know; `ROOT_URLCONF` that
is not a literal or does not resolve; `set_urlconf` / `request.urlconf` /
django-hosts; a URLconf nothing includes while `ROOT_URLCONF` names another
(its routes are listed without the missing prefix); a `path()` call never
reached; django-ninja; a web module with 0 routes and 0 sites, at its
dependency line.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _py_ast as ast
from strata_kb.codeingest.extractors._routes_drf import Routers, Rt
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._routes_python import (
    dependency_site,
    import_site,
    pattern_sites,
)
from strata_kb.codeingest.extractors._scopes import Scope

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["ADAPTERS"]

_MAX_DEPTH = 60
_PATH_FUNCS = {"path": False, "re_path": True, "url": True}
_ADMIN = frozenset({"django.contrib.admin.urls", "django.contrib.admin.sites"})
_HINT = re.compile(
    rb"urlpatterns|\bre_path\b|\bpath\(|\binclude\(|\.register\(|ROOT_URLCONF"
)
_WEB_IMPORT = re.compile(
    rb"^[ \t]*(?:from|import)[ \t]+(?:django\.(?:urls|conf\.urls|views|http|shortcuts)"
    rb"|rest_framework)\b",
    re.MULTILINE,
)
_URLCONF_SWITCH = re.compile(
    rb"\bset_urlconf\b|\.urlconf\s*=(?!=)|\bROOT_HOSTCONF\b|\bhost_patterns\b"
    rb"|^[ \t]*(?:from|import)[ \t]+ninja\b",
    re.MULTILINE,
)
# First-party URLconfs with a fixed route list: (path, view).
_BUILTIN_INCLUDES: dict[str, tuple[tuple[str, str], ...]] = {
    "django.contrib.auth.urls": (
        ("login/", "LoginView"),
        ("logout/", "LogoutView"),
        ("password_change/", "PasswordChangeView"),
        ("password_change/done/", "PasswordChangeDoneView"),
        ("password_reset/", "PasswordResetView"),
        ("password_reset/done/", "PasswordResetDoneView"),
        ("reset/<uidb64>/<token>/", "PasswordResetConfirmView"),
        ("reset/done/", "PasswordResetCompleteView"),
    ),
    "rest_framework.urls": (("login/", "LoginView"), ("logout/", "LogoutView")),
}
_REQUIRE = {
    "require_GET": ["GET"],
    "require_POST": ["POST"],
    "require_safe": ["GET", "HEAD"],
}


@dataclass
class Inc:
    piece: str
    regex: bool
    file: str
    line: int
    entries: Sequence[Entry] | None = None  # inline patterns
    module: str | None = None  # a URLconf file


Entry = Rt | Inc


def _line(node: Node) -> int:
    return node.start_point[0] + 1


class _Urls:
    def __init__(
        self, root: Path, proj: ast.Project, mine: list[str], repo_files: list[str]
    ):
        self.root = root
        self.proj = proj
        self.mine = mine
        self.repo_files = repo_files
        self.sites: list[str] = []
        self.consumed: set[tuple[str, int]] = set()
        self.included: set[str] = set()
        self._modules: dict[str, list[Entry]] = {}
        self._busy: set[str] = set()
        self.routers = Routers(proj, mine, self.site)
        self._depth = 0

    # -- helpers
    def site(self, rel: str, node: Node | int) -> None:
        self.sites.append(f"{rel}:{node if isinstance(node, int) else _line(node)}")

    def _url_kind(self, rel: str, call: Node) -> str:
        """path | re_path | include | "" for a django.urls call."""
        fn = ast.callee(call)
        if fn is None:
            return ""
        if fn.type == "identifier":
            module = self.proj.import_module_of(rel, fn)
            name = self.proj.imported_name(rel, fn)
        elif fn.type == "attribute":
            base = self.proj.chain(rel, fn.child_by_field_name("object"))
            module = base.module if base.kind == "external" else ""
            name = ast.text(fn.child_by_field_name("attribute"))
        else:
            return ""
        if not module.startswith("django"):
            return ""
        if name in _PATH_FUNCS:
            return "re_path" if _PATH_FUNCS[name] else "path"
        return "include" if name == "include" else ""

    # -- patterns
    def module_entries(self, rel: str) -> list[Entry]:
        if rel in self._modules:
            return self._modules[rel]
        if rel in self._busy:
            return []
        self._busy.add(rel)
        try:
            self._modules[rel] = self._read_module(rel)
        finally:
            self._busy.discard(rel)
        return self._modules[rel]

    def _read_module(self, rel: str) -> list[Entry]:
        info = self.proj.info(rel)
        if info is None:
            self.site(rel, 1)
            return []
        if info.error_line is not None:
            self.site(rel, info.error_line)
        acc: list[Entry] = []
        found = False
        stack = [info.tree.root_node]
        statements: list[Node] = []
        while stack:
            node = stack.pop()
            for child in reversed(node.children):
                if child.type in ("function_definition", "class_definition", "lambda"):
                    continue
                if child.type in ("assignment", "augmented_assignment", "call"):
                    statements.append(child)
                    if child.type != "call":
                        continue
                stack.append(child)
        statements.sort(key=lambda n: n.start_byte)
        for stmt in statements:
            if self._statement(rel, stmt, acc):
                found = True
        if not found:
            self.site(rel, 1)  # no readable `urlpatterns`
        return acc

    def _statement(self, rel: str, stmt: Node, acc: list[Entry]) -> bool:
        if stmt.type in ("assignment", "augmented_assignment"):
            left = stmt.child_by_field_name("left")
            if left is None or ast.text(left) != "urlpatterns":
                return False
            value = stmt.child_by_field_name("right")
            entries = self.eval(rel, value, acc)
            if stmt.type == "assignment":
                acc[:] = entries
            else:
                acc += entries
            return True
        fn = ast.callee(stmt)
        if (
            fn is None
            or fn.type != "attribute"
            or ast.text(fn.child_by_field_name("object")) != "urlpatterns"
        ):
            return False
        attr = ast.text(fn.child_by_field_name("attribute"))
        args = ast.call_args(stmt).pos
        if attr == "append" and args:
            acc += self.eval_item(rel, args[0], acc)
        elif attr == "extend" and args:
            acc += self.eval(rel, args[0], acc)
        elif attr == "insert" and len(args) > 1:
            acc += self.eval_item(rel, args[1], acc)
        else:
            self.site(rel, stmt)
        return True

    def eval(
        self, rel: str, node: Node | None, acc: list[Entry], depth: int = 0
    ) -> list[Entry]:
        """Entries of a list-valued expression."""
        node = ast.unwrap(node)
        if node is None:
            return []
        if depth > _MAX_DEPTH:  # `a + b + c + ...` nested past what is followed
            self.site(rel, node)
            return []
        kind = node.type
        if kind in ("list", "tuple"):
            out: list[Entry] = []
            for item in node.named_children:
                if item.type == "comment":
                    continue
                if item.type == "list_splat":
                    out += self.eval(
                        rel,
                        item.named_children[0] if item.named_children else None,
                        acc,
                        depth + 1,
                    )
                else:
                    out += self.eval_item(rel, item, acc, depth)
            return out
        if (
            kind == "binary_operator"
            and ast.text(node.child_by_field_name("operator")) == "+"
        ):
            return [
                *self.eval(rel, node.child_by_field_name("left"), acc, depth + 1),
                *self.eval(rel, node.child_by_field_name("right"), acc, depth + 1),
            ]
        if kind == "identifier" and ast.text(node) == "urlpatterns":
            return list(acc)
        if kind in ("identifier", "attribute"):
            return self._ref_entries(rel, node, depth)
        if kind == "call":
            return self.eval_item(rel, node, acc, depth)
        self.site(rel, node)
        return []

    def _ref_entries(self, rel: str, node: Node, depth: int) -> list[Entry]:
        parts = ast.dotted(node) or []
        if (
            parts
            and parts[-1] in ("urls", "get_urls")
            or (parts[-2:] == ["site", "urls"])
        ):
            owner = (
                node.child_by_field_name("object") if node.type == "attribute" else None
            )
            router = self.routers.of(rel, owner)
            if router is not None:
                return [*self.routers.urls(router)]
            if parts[-2:] == ["site", "urls"]:
                return []  # the admin
        ref = self.proj.chain(rel, node)
        if ref.kind == "assign" and ref.node is not None:
            return self.eval(ref.file, ref.node, [], depth + 1)
        self.site(rel, node)
        return []

    def eval_item(
        self, rel: str, node: Node | None, acc: list[Entry], depth: int = 0
    ) -> list[Entry]:
        """One element of `urlpatterns`, or a call producing patterns."""
        node = ast.unwrap(node)
        if node is None:
            return []
        if node.type in ("identifier", "attribute"):
            return self._ref_entries(rel, node, depth)
        if node.type != "call":
            self.site(rel, node)
            return []
        kind = self._url_kind(rel, node)
        if kind in ("path", "re_path"):
            return self._path(rel, node, kind == "re_path", depth)
        parts = ast.dotted(ast.callee(node)) or []
        name = parts[-1] if parts else ""
        args = ast.call_args(node).pos
        if name in ("static", "staticfiles_urlpatterns"):
            return []
        if name in ("format_suffix_patterns", "i18n_patterns"):
            self.site(rel, node)
            out: list[Entry] = []
            for arg in args[:1] if name == "format_suffix_patterns" else args:
                out += self.eval(rel, arg, acc, depth + 1)
            return out
        fn = ast.callee(node)
        if name == "get_urls" and fn is not None:
            return self._ref_entries(rel, fn, depth)
        self.site(rel, node)
        return []

    def _path(self, rel: str, call: Node, regex: bool, depth: int) -> list[Entry]:
        self.consumed.add((rel, call.id))
        args = ast.call_args(call)
        route = (
            args.pos[0] if args.pos else args.kw.get("route") or args.kw.get("regex")
        )
        view = args.pos[1] if len(args.pos) > 1 else args.kw.get("view")
        piece = ast.lit(route)
        if piece is None or view is None or args.splat and not args.pos:
            self.site(rel, call)
            return []
        line = _line(call)
        inner = ast.unwrap(view)
        if (
            inner is not None
            and inner.type == "call"
            and self._url_kind(rel, inner) == "include"
        ):
            return self._include(rel, inner, piece, regex, line, depth)
        methods, name = self._view(rel, view)
        return [Rt(piece, regex, name, tuple(methods), rel, line)]

    def _include(
        self, rel: str, call: Node, piece: str, regex: bool, line: int, depth: int
    ) -> list[Entry]:
        self.consumed.add((rel, call.id))
        args = ast.call_args(call)
        target = ast.unwrap(
            args.pos[0]
            if args.pos
            else args.kw.get("arg") or args.kw.get("urlconf_module")
        )
        if target is None or args.splat:
            self.site(rel, call)
            return []
        if target.type == "tuple" and target.named_children:
            target = ast.unwrap(target.named_children[0])
        if target is None:
            self.site(rel, call)
            return []
        literal = ast.lit(target)
        if literal is not None:
            mod = self.proj.resolve_module(literal, rel)
            if mod is not None and mod.file is not None:
                self.included.add(mod.file)
                return [Inc(piece, regex, rel, line, module=mod.file)]
            if mod is None and literal in _ADMIN:
                return []
            builtin = _BUILTIN_INCLUDES.get(literal) if mod is None else None
            if builtin is not None:
                line = _line(call)
                inner = [Rt(p, False, v, ("ANY",), rel, line) for p, v in builtin]
                return [Inc(piece, regex, rel, line, entries=inner)]
            self.site(rel, call)
            return []
        if target.type == "list":
            return [
                Inc(
                    piece,
                    regex,
                    rel,
                    line,
                    entries=self.eval(rel, target, [], depth + 1),
                )
            ]
        if target.type in ("identifier", "attribute"):
            return self._include_ref(rel, call, target, piece, regex, line, depth)
        self.site(rel, call)
        return []

    def _include_ref(
        self,
        rel: str,
        call: Node,
        target: Node,
        piece: str,
        regex: bool,
        line: int,
        depth: int,
    ) -> list[Entry]:
        ref = self.proj.chain(rel, target)
        if ref.kind == "mod" and ref.mod is not None and ref.mod.file is not None:
            self.included.add(ref.mod.file)
            return [Inc(piece, regex, rel, line, module=ref.mod.file)]
        parts = ast.dotted(target) or []
        if parts[-2:] == ["site", "urls"]:
            return []  # the admin
        if parts and parts[-1] == "urls" and target.type == "attribute":
            router = self.routers.of(rel, target.child_by_field_name("object"))
            if router is not None:
                return [Inc(piece, regex, rel, line, entries=self.routers.urls(router))]
        if ref.kind == "assign" and ref.node is not None:
            return [
                Inc(
                    piece,
                    regex,
                    rel,
                    line,
                    entries=self.eval(ref.file, ref.node, [], depth + 1),
                )
            ]
        self.site(rel, call)
        return []

    # -- views
    def _view(self, rel: str, view: Node) -> tuple[list[str], str]:
        node: Node | None = ast.unwrap(view)
        for _ in range(6):
            if node is None or node.type != "call":
                break
            fn = ast.callee(node)
            if (
                fn is not None
                and fn.type == "attribute"
                and ast.text(fn.child_by_field_name("attribute")) == "as_view"
            ):
                return ["ANY"], ast.text(fn.child_by_field_name("object"))
            args = ast.call_args(node).pos
            if not args:
                return ["ANY"], ast.text(fn)
            node = ast.unwrap(args[0])
        if node is None:
            return ["ANY"], ast.text(view)
        name = "lambda" if node.type == "lambda" else ast.text(node)
        ref = self.proj.chain(rel, node)
        if ref.kind == "func" and ref.node is not None:
            return self._function_methods(ref.node) or ["ANY"], name
        return ["ANY"], name

    def _function_methods(self, func: Node) -> list[str] | None:
        for expr, _ in ast.decorator_calls(func):
            call = expr if expr.type == "call" else None
            parts = ast.dotted(ast.callee(call) if call is not None else expr) or []
            name = parts[-1] if parts else ""
            if name in _REQUIRE:
                return _REQUIRE[name]
            if name in ("api_view", "require_http_methods"):
                args = ast.call_args(call).pos if call is not None else []
                found = (
                    ast.literal_strings(args[0])
                    if args
                    else (["GET"] if name == "api_view" else None)
                )
                return [m.upper() for m in found] if found else None
        return None


def _root_urlconfs(
    root: Path, proj: ast.Project, mine: list[str], urls: _Urls
) -> tuple[list[str], bool]:
    """(URLconf files named by ROOT_URLCONF, whether any was named)."""
    out: list[str] = []
    named = False
    for rel in mine:
        info = proj.info(rel)
        if info is None or b"ROOT_URLCONF" not in info.data:
            continue
        literal_lines: set[int] = set()
        for stmt in [
            n for n in ast_walk(info.tree.root_node) if n.type == "assignment"
        ]:
            if ast.text(stmt.child_by_field_name("left")) != "ROOT_URLCONF":
                continue
            named = True
            literal_lines.add(_line(stmt))
            value = ast.lit(stmt.child_by_field_name("right"))
            mod = proj.resolve_module(value, rel) if value else None
            if mod is not None and mod.file is not None:
                out.append(mod.file)
            else:
                urls.site(rel, stmt)
        for number, text in enumerate(info.data.splitlines(), start=1):
            if (
                b"ROOT_URLCONF" in text
                and number not in literal_lines
                and not text.lstrip().startswith(b"#")
            ):
                urls.site(rel, number)
    return sorted(set(out)), named


def ast_walk(node: Node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _walk(
    urls: _Urls,
    entries: Sequence[Entry],
    acc: tuple[tuple[str, bool], ...],
    stack: tuple[str, ...],
    out: list[Route],
    visited: set[str],
) -> None:
    for entry in entries:
        pieces = (*acc, (entry.piece, entry.regex))
        if isinstance(entry, Rt):
            path = _compose(pieces)
            out += [
                Route(m, path, entry.view, entry.file, entry.line)
                for m in entry.methods
            ]
            continue
        if entry.entries is not None:
            _walk(urls, entry.entries, pieces, stack, out, visited)
        elif entry.module is not None:
            if entry.module in stack:
                urls.site(entry.file, entry.line)
                continue
            visited.add(entry.module)
            _walk(
                urls,
                urls.module_entries(entry.module),
                pieces,
                (*stack, entry.module),
                out,
                visited,
            )


def _compose(pieces: tuple[tuple[str, bool], ...]) -> str:
    if any(regex for _t, regex in pieces):
        return "/" + "".join(t for t, _r in pieces).lstrip("/")
    return join_path(*(t for t, _r in pieces))


def _adapter(
    root: Path, scope: Scope, scope_files: list[str], repo_files: list[str]
) -> AdapterResult:
    pyfiles = ast.product_files(repo_files)
    mine = ast.product_files(scope_files)
    proj = ast.Project(root, pyfiles)
    urls = _Urls(root, proj, mine, repo_files)
    result = AdapterResult()
    try:
        _scan(root, scope, mine, repo_files, proj, urls, result)
    except Exception:  # noqa: BLE001 -- degrade, never crash: one bad scope must not abort the run
        result.dynamic_sites.append(
            f"{scope.manifest if scope.path == '.' else scope.path + '/' + scope.manifest}:1"
        )
    return result


def _scan(
    root: Path,
    scope: Scope,
    mine: list[str],
    repo_files: list[str],
    proj: ast.Project,
    urls: _Urls,
    result: AdapterResult,
) -> None:
    urls.routers.index()
    candidates = []
    for rel in mine:
        info = proj.info(rel)
        if info is None:
            result.dynamic_sites.append(f"{rel}:1")
        elif rel.rsplit("/", 1)[-1] == "urls.py" or b"urlpatterns" in info.data:
            candidates.append(rel)
    for rel in candidates:
        urls.module_entries(rel)
    named_roots, named = _root_urlconfs(root, proj, mine, urls)
    roots = named_roots if named else [c for c in candidates if c not in urls.included]
    routes: list[Route] = []
    visited: set[str] = set(roots)
    for rel in roots:
        _walk(urls, urls.module_entries(rel), (), (rel,), routes, visited)
    for rel in candidates:
        if rel not in visited:
            urls.site(rel, 1)  # reachable from no URLconf: listed without its prefix
            visited.add(rel)
            _walk(urls, urls.module_entries(rel), (), (rel,), routes, visited)
    for router in urls.routers.unexpanded():
        urls.site(router.file, router.line)
    _strays(proj, urls, mine)
    result.routes = routes
    result.dynamic_sites += urls.sites
    result.dynamic_sites += pattern_sites(root, mine, _URLCONF_SWITCH)
    web = named or import_site(root, mine, _WEB_IMPORT) is not None
    if not routes and not result.dynamic_sites and web:
        result.dynamic_sites.append(dependency_site(root, scope, repo_files, "Django"))


def _strays(proj: ast.Project, urls: _Urls, mine: list[str]) -> None:
    """A `path()` / `include()` call no URLconf evaluated."""
    for rel in mine:
        info = proj.info(rel)
        if info is None or not _HINT.search(info.data):
            continue
        for call in ast.all_calls(info.tree):
            if (rel, call.id) not in urls.consumed and urls._url_kind(rel, call):
                urls.site(rel, call)


ADAPTERS = {"Django": _adapter}
