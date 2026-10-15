"""Vapor route adapter (Swift).

The adapter reads a Swift scope the way Vapor would wire it, instead of
matching `.get(` text. `Application` (also `Application.make(..)`) is the
root router; `grouped(...)` / `group(...){ g in .. }` chains narrow it by
their path components (string literals, `":id"`, `"*"`, `"**"`,
`.constant(..)`, `.parameter(..)`, `.anything`, `.catchall`, arrays of those,
`let` string constants); middleware arguments (`grouped(User.authenticator())`)
add no path. `get/post/put/patch/delete(<path>..., use:)`, a trailing closure,
`on(.GET, <path>..., use:)` and `webSocket(<path>...)` register routes, the
path segments joined with `/`.

**Collections.** `try app.register(collection: X())` (also on a group, or
inside another `boot`) resolves `X` by type name across ALL files, then reads
`boot(routes:)` with the registering router as its argument; `grouped("todos")`
inside `boot` applies its prefix. A helper that takes the router
(`func routes(_ app: Application)`, `func addApi(_ r: RoutesBuilder)`) is
followed with the caller's prefix, to a depth of 8 and a fixed budget.

**Layout.** Every definition of every file is indexed first
(`_vapor_index.Index`), so file order never matters. Entry points are the
top-level statements of each file and every function that can hold a concrete
router (it mentions `Application`); everything else is read afterwards with
an unknown router, so a route registered there is a site. A `var` assigned
again, a name bound twice in one scope (also across `#if` branches) and a
pattern-bound name resolve to nothing.

**Not routes.** `req.client.get(..)`, `req.parameters.get(..)`,
`Environment.get(..)`, `URLSession`, Fluent's `group(.or) { .. }`: a route
needs a handler (`use:` or a closure) and path-shaped arguments; a receiver
that provably is not a router (a `Request`, a `Client`, a standard or
in-repo type, `app.client`) is ignored whatever it is called with.

**Sites** (every one makes the scope `partial`): a path or prefix that is not
a literal; a receiver that is not provably a router or provably not one and
is called with the route shape (a handler and path arguments, or
`register(collection:)`); a router passed to a function that cannot be
followed; a collection that cannot be resolved or is never registered; a
route method used as a value; `routes.add(Route(..))`; an in-repo helper
added to the router types; a syntax error.

Column rules: the handler is `Type.method` / a dotted name, else `(inline)`;
the request type is left empty. `Tests/` and `Package.swift` are not read.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import _text
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._swift_ast import (
    Call,
    kids,
    type_name,
)
from strata_kb.codeingest.extractors._vapor_eval import BUDGET, Evaluator
from strata_kb.codeingest.extractors._vapor_index import Fn, Index
from strata_kb.codeingest.extractors._vapor_shape import (
    handler_text,
    path_or_middleware,
    route_shaped,
    segments,
)
from strata_kb.codeingest.extractors._vapor_values import (
    BENIGN_CALLS,
    HTTP_METHODS,
    LABELS,
    METHOD,
    PLAIN_MEMBERS,
    PLAIN_TYPES,
    ROUTER_TYPES,
    SELF,
    UNSAFE_PATH,
    VERBS,
    Coll,
    Frame,
    Items,
    Plain,
    Router,
    Step,
    Text,
    TypeRef,
    Value,
    line,
    where,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tree_sitter import Node

    from strata_kb.codeingest.extractors._scopes import Scope

__all__ = ["ADAPTERS"]

_SKIP_FILE = re.compile(
    r"(?:^|/)(?:Tests|\.build|Pods|Carthage)/|(?:^|/)Package(?:@[^/]*)?\.swift$"
)
_MAX_DEPTH = 8
_APP_MAKER = re.compile(rb"\bApplication\s*(?:\(|\.(?:make|init|new)\b)")


class Vapor(Evaluator):
    def run(self) -> None:
        idx = self.idx
        for rel in sorted(idx.top_level):
            self.run_top(rel)
        roots = [f for f in idx.all_fns if self.is_root(f)]
        for fn in roots:
            self.budget = BUDGET
            self.run_fn(fn, {}, 0, frozenset({fn.key}), fn.owner)
        owned = [m for m in idx.members if self.concrete(m[1], m[2])]
        for rel, owner, node in owned:
            self.run_member(rel, owner, node)
        reached = frozenset(self.reached) | {f.key for f in roots}
        for fn in idx.all_fns:
            if fn.key not in reached:
                self.budget = BUDGET
                self.run_fn(fn, {}, 0, frozenset({fn.key}), fn.owner)
        for rel, owner, node in idx.members:
            if (rel, owner, node) not in owned:
                self.run_member(rel, owner, node)
        self.unregistered()

    def app_owners(self) -> set[str]:
        idx = self.idx
        return {
            owner
            for (owner, _n), declared in idx.props.items()
            if any(idx.resolve_alias(t) == "Application" for t in declared)
        }

    def makes_application(self, node: Node) -> bool:
        return bool(_APP_MAKER.search(node.text or b""))

    def concrete(self, owner: str, node: Node) -> bool:
        """Can this code hold an `Application` without being handed one?"""
        return (
            owner in self.app_owners()
            or self.router_self(owner) == Router("")
            or self.makes_application(node)
        )

    def is_root(self, fn: Fn) -> bool:
        """A function that starts from an `Application` (a parameter, `self`
        of an extension, a stored property, one it makes). A function handed a
        `RoutesBuilder` is reached through its callers instead, so running it
        alone would only add sites."""
        bounds = fn.bounds()
        kinds = [
            self.idx.resolve_alias(bounds.get(k, k))
            for p in fn.params()
            for k in [type_name(p.type_node)]
        ]
        if "Application" in kinds and not self.idx.has_type("Application"):
            return True
        if any(k in ROUTER_TYPES for k in kinds):
            return False
        return self.concrete(fn.owner, fn.node)

    def unregistered(self) -> None:
        covered = set(self.registered)
        for name in self.registered:
            covered.update(self.idx.supertypes(name))
        for name, decls in self.idx.types.items():
            for decl in decls:
                if (
                    decl.kind != "protocol"
                    and name not in covered
                    and self.idx.conforms(name, "RouteCollection")
                ):
                    self.sites.add(f"{decl.file}:{line(decl.node)}")

    def member(self, frame: Frame, base: Value, step: Step) -> Value:
        name = step.name
        if isinstance(base, Router):
            if name == "routes":
                return base
            if name in VERBS | {"on", "grouped", "group", "webSocket", "register"}:
                self.site(frame, step.node)  # a route method used as a value
                return None
            return Plain() if name in PLAIN_MEMBERS else None
        if base is SELF:
            return self.of_type(self.idx.prop_type(frame.self_type, name), None)
        if isinstance(base, Plain):
            if self.idx.has_type(base.type):
                return self.of_type(self.idx.prop_type(base.type, name), None)
            return Router("") if name == "application" else Plain()
        if isinstance(base, TypeRef):
            if self.idx.has_type(base.name):
                return self.of_type(self.idx.prop_type(base.name, name), None)
            return Plain() if base.name in PLAIN_TYPES else None
        return None

    def free_call(self, frame: Frame, base: Node, step: Step, call: Call) -> Value:
        name = _text(base)
        vals = self.eval_args(frame, call)
        if frame.env.lookup(name)[0] or name in frame.unsafe:
            self.rest(frame, call)  # a closure held in a variable
            return None
        if name[:1].isupper():
            return self.construct(frame, name, call, vals, step.node)
        owner = frame.self_type
        fns = self.idx.find_methods(owner, name) if owner else []
        if not fns:
            owner, fns = "", self.idx.funcs.get(name, [])
        if not fns and frame.me is not None:
            return self.router_call(
                frame, frame.me, replace(step, name=name), call, vals
            )
        if not fns:
            return self.unknown(frame, name, call, vals, step.node)
        self.rest(frame, call)
        self.apply(frame, fns, call, vals, step.node, name, owner)
        return None

    def construct(
        self, frame: Frame, name: str, call: Call, vals: list[Value], node: Node
    ) -> Value:
        """`Application(env)`, `TodoController()`, `URLSession(..)`, any type."""
        self.rest(frame, call)
        idx = self.idx
        if name == "Application" and not idx.has_type(name):
            return Router("")
        if idx.has_type(name):
            if idx.conforms(name, "RoutesBuilder"):
                return None
            if idx.conforms(name, "RouteCollection"):
                return Coll(name)
            inits = idx.methods.get((name, "init"), [])
            if inits and any(isinstance(v, Router) for v in vals):
                picked = self.pick(inits, call, vals)
                if picked is not None:
                    self.enter(frame, picked[0], picked[1], node, name)
            return self.of_type(name, None)
        return Plain(name) if name in PLAIN_TYPES else None

    def method_call(self, frame: Frame, recv: Value, step: Step, call: Call) -> Value:
        name = step.name
        vals = self.eval_args(frame, call)
        if isinstance(recv, Router):
            return self.router_call(frame, recv, step, call, vals)
        owner = ""
        if recv is SELF:
            owner = frame.self_type
        elif isinstance(recv, Coll | TypeRef):
            owner = recv.name
        elif isinstance(recv, Plain):
            owner = recv.type
        if owner and self.idx.has_type(owner):
            fns = self.idx.find_methods(owner, name)
            if fns:
                self.rest(frame, call)
                self.apply(frame, fns, call, vals, step.node, name, owner)
                return None
        if isinstance(recv, TypeRef) and recv.name == "Application":
            self.rest(frame, call)
            return Router("") if name in ("make", "new", "init") else None
        if isinstance(recv, Plain) or (
            isinstance(recv, TypeRef) and recv.name in PLAIN_TYPES
        ):
            self.rest(frame, call)
            return Plain()
        if isinstance(recv, Coll):
            self.rest(frame, call)
            return None
        return self.unknown(frame, name, call, vals, step.node)

    def unknown(
        self, frame: Frame, name: str, call: Call, vals: list[Value], node: Node
    ) -> None:
        """A call on a receiver that is not provably a router and not provably
        anything else: a site when it has the route shape or takes a router."""
        if (
            route_shaped(name, call)
            or any(isinstance(v, Router) for v in vals)
            and name not in BENIGN_CALLS
        ):
            self.site(frame, node)
        self.rest(frame, call)

    # -- routers -----------------------------------------------------------------

    def router_call(
        self, frame: Frame, router: Router, step: Step, call: Call, vals: list[Value]
    ) -> Value:
        name = step.name
        if name in VERBS or name in ("on", "webSocket"):
            return self.register(frame, router, step, call)
        if name in ("grouped", "group"):
            return self.group(frame, router, step, call)
        if name == "register" and any(a.label == "collection" for a in call.args):
            self.collections(frame, router, step, call, vals)
            return Plain()
        if name == "add" and any(
            a.value.type == "call_expression"
            and _text(kids(a.value)[0]).split(".")[-1] == "Route"
            for a in call.args
        ):
            self.site(frame, step.node)
            return None
        helpers = [f for t in ROUTER_TYPES for f in self.idx.methods.get((t, name), [])]
        if helpers:  # an in-repo routing helper on the router types
            picked = self.pick(helpers, call, vals)
            self.rest(frame, call)
            if picked is None:
                self.site(frame, step.node)
            else:
                self.enter(
                    frame, picked[0], picked[1], step.node, picked[0].owner, router
                )
            return None
        self.unknown(frame, name, call, vals, step.node)
        return None

    def register(self, frame: Frame, router: Router, step: Step, call: Call) -> Value:
        name = step.name
        args = call.args
        handler = next((a.value for a in args if a.label in ("use", "onUpgrade")), None)
        trailing = [a.value for a in call.trailing]
        upgrade = [a.value for a in call.trailing if a.label == "onUpgrade"]
        if handler is None and (upgrade or trailing):
            handler = (upgrade or trailing)[0]
        paths = [
            a for a in args if a.label is None and a.value.type != "lambda_literal"
        ]
        methods: list[str] | None
        if name == "on":
            first = (
                METHOD.match("".join(_text(paths[0].value).split())) if paths else None
            )
            methods = (
                [first.group(1)] if first and first.group(1) in HTTP_METHODS else None
            )
            paths = paths[1:]
        else:
            methods = ["GET"] if name == "webSocket" else [name.upper()]
        parts: list[str] | None = []
        for arg in paths:
            more = segments(frame, arg.value)
            parts = None if more is None or parts is None else parts + more
        path = join_path(router.prefix or "", *parts) if parts is not None else ""
        if (
            handler is None
            or methods is None
            or parts is None
            or router.prefix is None
            or any(a.label is not None and a.label not in LABELS for a in args)
            or UNSAFE_PATH.search(path)
        ):
            self.site(frame, step.node)
        else:
            text = handler_text(self.idx, frame, handler)
            for method in methods:
                self.routes.add(Route(method, path, text, frame.file, where(step.node)))
        if handler is not None and handler.type == "lambda_literal":
            self.closure(handler, frame, Plain("Request"))
        elif handler is not None:
            self.eval(handler, frame)
        self.rest(frame, call, skip=handler)
        return Plain("Route")

    def group(self, frame: Frame, router: Router, step: Step, call: Call) -> Value:
        closure = call.trailing[0].value if call.trailing else None
        closure = closure or next(
            (a.value for a in call.args if a.label == "configure"), None
        )
        prefix, ok = router.prefix, True
        for arg in call.args:
            if arg.label == "configure":
                continue
            kind, segs = path_or_middleware(self.idx, frame, arg)
            if kind == "path" and prefix is not None:
                prefix = join_path(prefix, *segs)
            elif kind == "unknown":
                prefix, ok = None, False
        if step.name == "group" and (
            closure is None or closure.type != "lambda_literal"
        ):
            ok = False
        if not ok:
            self.site(frame, step.node)
        child = Router(prefix)
        if step.name == "grouped":
            self.rest(frame, call)
            return child
        if closure is not None and closure.type == "lambda_literal":
            self.closure(closure, frame, child)
        self.rest(frame, call, skip=closure)
        return Plain()

    # -- collections and helpers ----------------------------------------------------

    def collections(
        self, frame: Frame, router: Router, step: Step, call: Call, vals: list[Value]
    ) -> None:
        index = next(i for i, a in enumerate(call.args) if a.label == "collection")
        value = vals[index]
        if isinstance(value, Coll):
            names: list[str] | None = [value.name]
        elif (
            isinstance(value, Items)
            and value.values
            and all(isinstance(v, Coll) for v in value.values)
        ):
            names = [v.name for v in value.values if isinstance(v, Coll)]
        else:
            names = None
        if names is None:
            self.site(frame, step.node)
            return
        for name in names:
            self.follow(frame, router, name, step.node)

    def follow(self, frame: Frame, router: Router, name: str, node: Node) -> None:
        if len(self.idx.types.get(name, [])) != 1:
            self.site(frame, node)  # outside the repo, or two types of that name
            return
        self.registered.add(name)
        boots = [f for f in self.idx.find_methods(name, "boot") if len(f.params()) == 1]
        if len(boots) != 1:
            self.site(frame, node)
            return
        self.enter(frame, boots[0], {boots[0].params()[0].internal: router}, node, name)

    def enter(
        self,
        frame: Frame,
        fn: Fn,
        binds: dict[str, Value],
        node: Node,
        owner: str,
        me: Router | None = None,
    ) -> None:
        if fn.key in frame.stack or frame.depth >= _MAX_DEPTH or self.budget <= 0:
            self.site(frame, node)
            return
        self.budget -= 1
        self.reached.add(fn.key)
        self.run_fn(fn, binds, frame.depth + 1, frame.stack | {fn.key}, owner, None, me)

    def pick(
        self, fns: list[Fn], call: Call, vals: list[Value]
    ) -> tuple[Fn, dict[str, Value]] | None:
        """The one function the call's labels fit, with its parameter binds."""
        fits = []
        for fn in fns:
            binds = self.bind_args(fn, call, vals)
            if binds is not None:
                fits.append((fn, binds))
        return fits[0] if len(fits) == 1 else None

    def bind_args(
        self, fn: Fn, call: Call, vals: list[Value]
    ) -> dict[str, Value] | None:
        params = fn.params()
        used: set[str] = set()
        binds: dict[str, Value] = {}
        bounds = fn.bounds()
        for arg, value in zip(call.args, vals, strict=True):
            label = arg.label or "_"
            param = next(
                (p for p in params if p.external == label and p.internal not in used),
                None,
            )
            if param is None:
                return None
            used.add(param.internal)
            if isinstance(value, Router):
                kind = self.idx.resolve_alias(type_name(param.type_node))
                kind = bounds.get(kind, kind)
                if kind not in ROUTER_TYPES or self.idx.has_type(kind):
                    return None
                binds[param.internal] = value
            elif isinstance(value, Text):
                binds[param.internal] = value
        return binds

    def apply(
        self,
        frame: Frame,
        fns: list[Fn],
        call: Call,
        vals: list[Value],
        node: Node,
        name: str,
        owner: str,
    ) -> None:
        """Follow an in-repo call that hands a router over; any doubt (no
        candidate, two candidates, a parameter that is not a router) is a site."""
        if not any(isinstance(v, Router) for v in vals):
            return
        picked = self.pick(fns, call, vals)
        if picked is None:
            if name not in BENIGN_CALLS:
                self.site(frame, node)
            return
        self.enter(frame, picked[0], picked[1], node, owner)


def _adapter(
    root: Path, scope: Scope, scope_files: list[str], _repo_files: list[str]
) -> AdapterResult:
    files = sorted(
        f for f in scope_files if f.endswith(".swift") and not _SKIP_FILE.search(f)
    )
    idx = Index(root)
    for rel in files:
        idx.add_file(rel)
    idx.finish()
    play = Vapor(idx)
    play.run()
    sites = (
        play.sites
        | {f"{rel}:{line}" for rel, line in idx.errors.items()}
        | set(idx.unreadable)
    )
    return AdapterResult(
        sorted(play.routes, key=lambda r: (r.file, r.path, r.method, r.line)),
        sorted(sites),
    )


ADAPTERS = {"Vapor": _adapter}
