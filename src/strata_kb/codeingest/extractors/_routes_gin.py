"""Gin route adapter (Go).

The adapter interprets Go function bodies the way the program would wire its
router, instead of matching `.GET(` text: `r := gin.Default()` /
`gin.New()` makes an engine, `g := r.Group(p)` (also chained, `Use`d, in
`{ ... }` blocks, and held in struct fields or package variables) makes a
group, and `<router>.GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS/Any/Handle/Match`
registers routes. Every definition of every file of the scope is indexed
first (`_go_ast.Index`), so file order never matters.

**Helpers.** A group passed into a function (`registerUser(api.Group("/u"))`,
`handlers.Register(g)`, `h.Register(g)`) is followed into that function's
body with the argument as the parameter, once per call, to a depth of 8 and
a fixed evaluation budget. The callee must resolve unambiguously (one
function of that name in the package, the method of a known receiver type);
any doubt (a loop variable, a func value, two candidates, a recursion cycle,
a library function that takes the router, e.g. pprof) is a site. A helper
with a group parameter that nothing calls is a site at its declaration.

**Not routes, not sites.** `Static`, `StaticFS`, `StaticFile`: they serve
files, no handler code; `NoRoute` / `NoMethod`: fallbacks without a path;
`Use`: middleware. (Python's `StaticFiles` mount is treated the same.) A
route-shaped call that is none of these and does not resolve to a gin router
is a site.

**Sites.** A non-constant path or prefix (anything but a literal, a
package/local `const`, or `+` of those); a method list that is not literal; a
route-shaped call on a receiver that is not a known gin router or known
non-gin type; a call on another router inside the scope (`http.HandleFunc`,
`mux.Handle`, chi, echo, gorilla/mux, fiber, ...); a syntax error.

**Same-named APIs (`http.Get`, resty `.Get`, `c.GET` helpers).** Gin verbs
are upper-case; a receiver that resolves to a gin router is a route, one that
resolves to any other type (an HTTP client, a plain struct, `*gin.Context`)
is ignored, one that does not resolve is a site only when the call has the
route shape (path-like first argument and a handler). `net/http` client
methods (`Get`, `Post`) never are.

Column rules: the handler is the last handler argument as identifier or
dotted-name text, else `(inline)`; test files (`_test.go`), `testdata/` and
`_`/`.`-prefixed directories (ignored by the go tool) are not scanned.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._gin_env import (
    Frame,
    Seg,
    handler_text,
    line_of_seg,
    unroll,
)
from strata_kb.codeingest.extractors._gin_eval import (
    HTTP_METHODS,
    MAX_DEPTH,
    ROUTE_NAMES,
    VERBS,
    Evaluator,
)
from strata_kb.codeingest.extractors._go_ast import (
    GIN,
    Func,
    Index,
    Other,
    Pkg,
    Router,
    Typed,
    Value,
    group_like,
)
from strata_kb.codeingest.extractors._routes_jsutil import _text
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._scopes import Scope

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["ADAPTERS"]

_GROUP_CALLS = frozenset({"Use", "Static", "StaticFS", "StaticFile", "StaticFileFS"})
# A call that takes a router and does not register routes with it.
_BENIGN = frozenset(
    {
        "ListenAndServe", "ListenAndServeTLS", "Serve", "ServeTLS", "Run", "RunTLS",
        "RunUnix", "RunFd", "RunListener", "Shutdown", "append", "len", "cap", "make",
        "new", "print", "println", "panic", "copy", "delete", "Printf", "Println",
        "Sprintf", "Errorf", "Fatal", "Fatalf", "Info", "Debug", "Error", "Warn",
    }
)  # fmt: skip
_BENIGN_PREFIXES = ("Run", "Serve", "ListenAndServe", "Start", "Shutdown")
_HTTP_ROUTING = frozenset({"Handle", "HandleFunc"})
_OTHER_ROUTING = VERBS | {
    "Get", "Post", "Put", "Patch", "Delete", "Head", "Options", "Any", "Handle",
    "HandleFunc", "Route", "Mount", "Group", "PathPrefix", "Subrouter", "Match",
    "Add",
}  # fmt: skip
_STRUCTURAL = frozenset({"Route", "Mount", "PathPrefix", "Subrouter", "Group"})
_UNSAFE_PATH = re.compile(r"[\s\x00-\x1f]")  # not a path a router could register
_SKIP_FILE = re.compile(r"(?:^|/)(?:testdata|_[^/]*|\.[^/]+)/|_test\.go$")


def _routing_names(path: str) -> frozenset[str]:
    return _HTTP_ROUTING if path == "net/http" else _OTHER_ROUTING


class Play(Evaluator):
    def chain(self, frame: Frame, call: Node, emit: bool) -> Value | None:
        base, segs = unroll(call)
        value = self.value_of(frame, base) if base is not None else None
        for seg in segs:
            if seg.name is None:
                value = self.direct(frame, seg, emit)
            elif isinstance(value, Router):
                value = self.router_step(frame, value, seg, emit)
            elif isinstance(value, Pkg):
                value = self.pkg_call(frame, value, seg, emit)
            elif isinstance(value, Typed):
                value = self.typed_call(frame, value, seg, emit)
            elif isinstance(value, Other):
                value = self.other_call(frame, value, seg, emit)
            else:
                value = self.unresolved(frame, seg, emit)
        return value

    def router_step(
        self, frame: Frame, router: Router, seg: Seg, emit: bool
    ) -> Router | None:
        name = seg.name
        if name in ROUTE_NAMES or name in ("Handle", "Match"):
            if emit:
                self.register(frame, router, seg)
            return router
        if name == "Group":
            prefix = self.string(frame, seg.args[0]) if seg.args else None
            if prefix is None:
                if emit:
                    self.site(frame, seg)
                return Router(None)
            return Router(
                None if router.prefix is None else join_path(router.prefix, prefix)
            )
        # Static*, NoRoute, NoMethod and Use are not routes (module docstring)
        return router if name in _GROUP_CALLS else None

    def methods_of(
        self, frame: Frame, name: str | None, args: list[Node]
    ) -> list[str] | None:
        if name == "Any":
            return ["ANY"]
        if name in VERBS:
            return [name]
        if not args:
            return None
        if name == "Handle":
            first = self.string(frame, args[0])
            return [first] if first in HTTP_METHODS else None
        listed = args[0]  # Match([]string{...}, path, handlers...)
        body = (
            listed.child_by_field_name("body")
            if listed.type == "composite_literal"
            else None
        )
        found = [
            self.string(frame, e.named_children[0])
            for e in (body.named_children if body is not None else [])
            if e.type == "literal_element" and e.named_children
        ]
        ok = bool(found) and all(m in HTTP_METHODS for m in found)
        return [m for m in found if m] if ok else None

    def register(self, frame: Frame, router: Router, seg: Seg) -> None:
        offset = 1 if seg.name in ("Handle", "Match") else 0
        methods = self.methods_of(frame, seg.name, seg.args)
        rest = seg.args[offset:]
        path = self.string(frame, rest[0]) if rest else None
        handlers = rest[1:]
        if (
            router.prefix is None
            or not methods
            or path is None
            or not handlers
            or _UNSAFE_PATH.search(path)
        ):
            self.site(frame, seg)
            return
        full = join_path(router.prefix, path)
        for method in methods:
            self.routes.add(
                Route(
                    method,
                    full,
                    handler_text(handlers[-1]),
                    frame.file.rel,
                    line_of_seg(seg),
                )
            )

    def leaks_router(self, frame: Frame, seg: Seg) -> bool:
        return any(isinstance(self.value_of(frame, a), Router) for a in seg.args)

    def leak(self, frame: Frame, seg: Seg, emit: bool) -> None:
        """A call this adapter cannot follow that receives a router."""
        name = seg.name or ""
        benign = name in _BENIGN or name.startswith(_BENIGN_PREFIXES)
        if emit and not benign and self.leaks_router(frame, seg):
            self.site(frame, seg)

    def direct(self, frame: Frame, seg: Seg, emit: bool) -> Value | None:
        fn = seg.fn
        if fn.type == "func_literal":
            return None  # visited as a child; its body is walked there
        name = _text(fn) if fn.type == "identifier" else ""
        if name and frame.env.get(name) is None:
            func = self.idx.func(frame.file.dir, name)
            if func is not None:
                return self.apply(frame, func, seg, None, emit)
        self.leak(frame, seg, emit)
        return None

    def pkg_call(self, frame: Frame, pkg: Pkg, seg: Seg, emit: bool) -> Value | None:
        if pkg.path == GIN:
            return Router("") if seg.name in ("Default", "New") else None
        target = self.idx.import_dir(pkg.path)
        if target is not None:
            func = self.idx.func(target, seg.name or "")
            if func is not None:
                return self.apply(frame, func, seg, None, emit)
            self.leak(frame, seg, emit)
            return None
        if (
            emit
            and self.idx.is_router_pkg(pkg.path)
            and seg.args
            and seg.name in _routing_names(pkg.path)
        ):
            self.site(frame, seg)
        else:
            self.leak(frame, seg, emit)
        # a value from a package we cannot read is unknown, not "not gin"
        return Other(pkg.path) if self.idx.non_gin(pkg.path) else None

    def other_call(self, frame: Frame, other: Other, seg: Seg, emit: bool) -> Value:
        routing = (
            self.idx.is_router_pkg(other.path)
            and seg.args
            and seg.name in _routing_names(other.path)
        )
        if emit and routing:
            self.site(frame, seg)
        else:
            self.leak(frame, seg, emit)
        return other

    def typed_call(
        self, frame: Frame, typed: Typed, seg: Seg, emit: bool
    ) -> Value | None:
        func = self.idx.method(typed.dir, typed.name, seg.name or "")
        if func is not None:
            return self.apply(frame, func, seg, typed, emit)
        info = self.idx.info(typed)
        for embedded in info.embeds if info is not None else []:
            promoted = self.idx.classify(info.file, embedded) if info else None
            if isinstance(promoted, Router):  # `type S struct{ *gin.Engine }`
                return self.router_step(frame, promoted, seg, emit)
        if info is not None and info.kind == "struct" and not info.embeds:
            return None  # a plain struct cannot be a gin router
        return self.unresolved(frame, seg, emit)

    def unresolved(self, frame: Frame, seg: Seg, emit: bool) -> None:
        if emit:
            if self.route_shaped(frame, seg):
                self.site(frame, seg)
            else:
                self.leak(frame, seg, emit)

    def route_shaped(self, frame: Frame, seg: Seg) -> bool:
        """A gin-verb-shaped call on a receiver that is not a known router.
        The path argument does not matter (`""` is idiomatic, `"users"` is
        legal): two arguments are a path and a handler. A 1-argument
        `e.GET("/x")` is an HTTP test client."""
        name, args = seg.name or "", seg.args
        if name in ROUTE_NAMES or name in _HTTP_ROUTING:
            return len(args) >= 2
        first = self.string(frame, args[0]) if args else None
        if name == "Group" and first is not None:
            return True
        if frame.file.other_router and name in _OTHER_ROUTING:
            return (first or "").startswith("/") or name in _STRUCTURAL
        return False

    def apply(
        self, frame: Frame, func: Func, seg: Seg, recv: Typed | None, emit: bool
    ) -> Value | None:
        """Call of an in-repo function: follow it when it takes a group. A
        router handed to a parameter of a type this adapter cannot read as a
        router (alias of unknown shape, custom interface, `any`) is a site."""
        result = self.result_value(func)
        if not emit:
            return result
        args = [self.value_of(frame, a) for a in seg.args]
        binds: dict[str, Value] = {}
        if recv is not None and func.recv_name:
            binds[func.recv_name] = recv
        unknown = False
        bound = set()
        for i, arg in enumerate(args):
            if not isinstance(arg, Router):
                continue
            last = func.params[-1] if func.params else None
            p = func.params[i] if i < len(func.params) else last
            kind = self.idx.classify(func.file, p.type) if p is not None else None
            if p is not None and isinstance(kind, Router):
                bound.add(i)
                if p.name and not p.variadic:
                    binds[p.name] = arg
            elif not isinstance(kind, Other):
                unknown = True
        groups = [
            i
            for i, p in enumerate(func.params)
            if group_like(self.idx.classify(func.file, p.type))
        ]
        unknown = unknown or any(i not in bound for i in groups)
        if not groups and not unknown:
            return result
        if groups:
            self.reached.add(id(func))
        key = id(func)
        if (
            unknown
            or key in frame.stack
            or frame.depth >= MAX_DEPTH
            or self.budget <= 0
        ):
            self.site(frame, seg)
            return result
        self.budget -= 1
        self.run_func(func, binds, frame.depth + 1, frame.stack | {key})
        return result


def _adapter(
    root: Path, scope: Scope, scope_files: list[str], _repo_files: list[str]
) -> AdapterResult:
    files = sorted(
        f for f in scope_files if f.endswith(".go") and not _SKIP_FILE.search(f)
    )
    play = Play(Index(root, scope, files))
    play.run()
    return AdapterResult(
        sorted(play.routes, key=lambda r: (r.file, r.path, r.method, r.line)),
        sorted(play.sites),
    )


ADAPTERS = {"Gin": _adapter}
