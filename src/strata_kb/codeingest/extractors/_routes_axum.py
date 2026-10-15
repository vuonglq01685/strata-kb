"""Axum route adapter (Rust).

`Router::new().route("/p", get(h).post(h2)).nest("/api", api::routes())
.merge(other)` is read by evaluating the function bodies that build routers
(`_rs_interp`): a `Router` value holds the routes registered on it, `nest`
joins the nested router's routes under its prefix, `merge` unions them, and
a function that returns a `Router` is evaluated where it is called (across
modules: `mod users; users::routes()`), with `with_state`, `layer`,
`route_layer` and friends passing the router through. Both path-parameter
syntaxes (`/:id` up to axum 0.7, `/{id}` from 0.8) are kept as written.

What is emitted: every router no other router absorbed -- the one built in
`main`, returned to `axum::serve`, or returned by a function the app calls.
A function that returns a router is *only* evaluated where something calls
it: listing it bare would drop the prefix it is nested under. One that
nothing calls (or that only an unreachable function calls) is a site.

Not routes and not sites: `ServeDir` / `ServeFile` (files, no handler code;
same precedent as Gin `Static`), `fallback` / `fallback_service` (no
(method, path)), `layer` and `with_state`.

Sites: a non-literal path or prefix (`format!`, `concat!`, a variable), a
router that is not provably an axum router in `nest` / `merge` /
`serve` (a sibling workspace crate's `build_router()`, another crate's
`routes()`), a method this adapter does not know on a router
(`typed_get`, `api_route`, utoipa's `routes(..)`), a router handed to a
function it cannot follow, an unreachable router function, a route-shaped
call on a receiver that is not provably something else.

**Same-named APIs.** `get(h)` is axum's only when `get` resolves through a
`use` to `axum::routing`: `reqwest::get(url)`, `client.get(url)`,
`map.get(&k)`, an in-repo `fn get` are nothing. `.route(a, b)` on a value of
an in-repo type, or whose arguments are not route-shaped (a `"/"` literal in
an axum-importing file, or a method router), is ordinary code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from strata_kb.codeingest.extractors._routes_model import AdapterResult
from strata_kb.codeingest.extractors._rs_attrs import VERBS
from strata_kb.codeingest.extractors._rs_frag import Frag, emit, prefixed
from strata_kb.codeingest.extractors._rs_index import Fn, Mod
from strata_kb.codeingest.extractors._rs_interp import (
    Closure,
    Frame,
    Interp,
    Other,
    Step,
    args_of,
)
from strata_kb.codeingest.extractors._rs_syntax import (
    crate_tail,
    plain_path,
    text,
    walk,
)

if TYPE_CHECKING:
    from tree_sitter import Node

    from strata_kb.codeingest.extractors._rs_index import Index

__all__ = ["run"]

_ROUTER = re.compile(r"\b\w*Router\b")
# a parameter that *is* a router, by value (not `State<Router>`, not `&Router`:
# `Router::route` takes `self`): `Router<S>`, `axum::Router`
_ROUTER_PARAM = re.compile(r"^(?:\w+::)*\w*Router\b")
_PASS_ROUTER = frozenset(
    {
        "layer", "route_layer", "with_state", "into_make_service", "fallback",
        "into_make_service_with_connect_info", "into_service", "boxed", "into",
        "method_not_allowed_fallback", "reset_fallback", "into_inner",
        "unwrap", "expect", "ok", "unwrap_or_else", "unwrap_or_default", "map_err",
    }
)  # fmt: skip
# tower `Service` calls: they consume the router and give a response / future
_SERVICE_CALLS = frozenset({"call", "oneshot", "ready", "poll_ready", "ready_oneshot"})
_MAKE_SERVICE = frozenset(
    {"into_make_service", "into_make_service_with_connect_info", "into_service"}
)
_PASS_METHOD = frozenset(
    {
        "layer", "route_layer", "with_state", "handle_error", "fallback", "boxed",
        "into", "unwrap", "expect", "ok", "unwrap_or_else", "unwrap_or_default", "map_err",
    }
)  # fmt: skip
_WRAPPERS = frozenset({"Ok", "Some", "Err"})
_BOXES = frozenset({"Box", "Arc", "Rc", "Pin"})
_STATIC_TYPES = frozenset({"ServeDir", "ServeFile"})


@dataclass(eq=False)
class Rtr:
    routes: list[Frag] = field(default_factory=list)
    absorbed: bool = False


@dataclass
class MRtr:
    methods: list[tuple[str, str]] = field(default_factory=list)


class Static:
    """`ServeDir` / `ServeFile`: serves files, no handler code."""


def _handler(node: Node) -> str:
    return plain_path(node) or "(inline)"


class AxumPlay(Interp):
    def __init__(self, idx: Index):
        super().__init__(idx)
        self.routers: list[Rtr] = []

    # -- values ----------------------------------------------------------

    def new_router(self) -> Rtr:
        made = Rtr()
        self.routers.append(made)
        return made

    def absorb(self, parent: Rtr, child: Rtr, prefix: str | None) -> None:
        child.absorbed = True
        if prefix is not None and child is not parent:
            parent.routes.extend(prefixed(child.routes, prefix))

    def merge(self, vals: list[Any]) -> Any:
        routers = [v for v in vals if isinstance(v, Rtr)]
        if len(routers) < 2 or len(routers) != len(vals):
            return super().merge(vals)
        out = self.new_router()
        for r in routers:
            self.absorb(out, r, "")
        return out

    def router_ty(self, mod: Mod, type_text: str, *, param: bool = False) -> bool:
        """Does the type text name a router, also through an in-repo alias
        (`type Api = Router<S>;`)? `param`: the type is the whole parameter
        type (by value), not something mentioning a router."""
        direct = _ROUTER_PARAM.match(type_text) if param else _ROUTER.search(type_text)
        if direct:
            return True
        names = re.findall(r"[A-Za-z_]\w*", type_text)
        for name in names[:1] if param else names:
            res = self.idx.resolve(mod, (name,))
            if res is not None and res.kind == "ext" and _ROUTER.search(res.segs[-1]):
                return True
        return False

    def follow(self, fn: Fn, args: list[Any]) -> bool:
        return self.router_ty(fn.mod, fn.ret) or any(
            isinstance(a, Rtr | MRtr) for a in args
        )

    def apply_fn(self, frame: Frame, fn: Fn, args: list[Any], at: Node) -> Any:
        val = super().apply_fn(frame, fn, args, at)
        if val is None and self.router_ty(fn.mod, fn.ret):
            self.site(frame, at)  # a router we could not build
        return val

    def bind_param(self, fn: Fn, name: str, type_text: str, arg: Any) -> Any:
        if arg is not None or self.router_ty(fn.mod, type_text):
            return arg
        return self.typed_value(fn.mod, None, type_text)

    def on_let(self, frame: Frame, node: Node, val: Any) -> Any:
        declared = node.child_by_field_name("type")
        if (
            val is None
            and declared is not None
            and self.router_ty(frame.mod, text(declared))
        ):
            self.site(frame, node)
        return val

    # -- calls -----------------------------------------------------------

    def ext_call(self, frame: Frame, segs: tuple[str, ...], call: Node) -> Any:
        name = segs[-1]
        framework = crate_tail(segs, ("axum", "axum_extra"))
        if framework is not None:
            segs = framework
            if name == "serve":
                return self.serve(frame, args_of(call)[1:2])
            made = self.axum_call(frame, segs, call)
            if made is not None:
                return made
        elif len(segs) >= 2 and segs[-2] in _STATIC_TYPES:
            self.eval_args(frame, call)
            return Static()
        return self.generic(frame, segs, call)

    def axum_call(self, frame: Frame, segs: tuple[str, ...], call: Node) -> Any:
        tail, name = segs[-2:], segs[-1]
        args = args_of(call)
        if tail in (("Router", "new"), ("Router", "default")):
            return self.new_router()
        if tail in (("MethodRouter", "new"), ("MethodRouter", "default")):
            return MRtr()
        if "routing" not in segs:
            return None
        verb = name.removesuffix("_service")
        if name == "any" or name == "any_service":
            return self.method_router(
                frame, ["ANY"], args[:1], name.endswith("_service")
            )
        if name in ("on", "on_service") and len(args) == 2:
            names = self.filter_names(args[0])
            if not names:
                self.site(frame, call)
                return MRtr()
            return self.method_router(frame, names, args[1:], name == "on_service")
        if verb in VERBS:
            return self.method_router(frame, [verb.upper()], args[:1], name != verb)
        return None

    @staticmethod
    def filter_names(node: Node) -> list[str]:
        """`MethodFilter::GET.or(MethodFilter::POST)` -> ["GET", "POST"]."""
        return sorted(
            {
                text(n).upper()
                for n in walk(node)
                if n.type == "identifier" and text(n).lower() in VERBS
            }
        )

    def method_router(
        self, frame: Frame, methods: list[str], args: list[Node], service: bool
    ) -> Any:
        handler = "(inline)"
        if args:
            val = self.eval(frame, args[0])
            if service and isinstance(val, Static):
                return val
            handler = _handler(args[0])
        return MRtr([(m, handler) for m in methods])

    def serve(self, frame: Frame, args: list[Node]) -> Any:
        """The app handed to `serve`: an unknown router is a site."""
        for arg in args:
            val = self.eval(frame, arg)
            if val is None:
                self.site(frame, arg)
        return None

    def generic(self, frame: Frame, segs: tuple[str, ...], call: Node) -> Any:
        vals = self.eval_args(frame, call)
        name = segs[-1]
        if (
            name in _WRAPPERS
            or (len(segs) >= 2 and segs[-2] in _BOXES and name == "new")
        ) and vals:
            return vals[0]
        self.consume(frame, vals, args_of(call), call)
        return None

    def consume(
        self, frame: Frame, vals: list[Any], nodes: list[Node], at: Node, line: int = 0
    ) -> None:
        """A router given by value to a function nothing here follows: the
        routes it carries may be mounted anywhere, so they are dropped and it
        is a site. (`&router` cannot add routes: not a hand-over.)"""
        given = [
            v
            for v, n in zip(vals, nodes, strict=False)
            if n.type != "reference_expression"
        ]
        taken = [v for v in given if isinstance(v, Rtr)]
        for router in taken:
            router.absorbed = True
        if taken or any(isinstance(v, MRtr) for v in given):
            if line:
                self.site_at(frame, line)
            else:
                self.site(frame, at)

    # -- steps -----------------------------------------------------------

    def step(self, frame: Frame, val: Any, step: Step) -> Any:
        if isinstance(val, Rtr):
            return self.router_step(frame, val, step)
        if isinstance(val, MRtr):
            return self.method_step(frame, val, step)
        if isinstance(val, Static):
            self.eval_args(frame, step.node)
            return val
        if isinstance(val, Other):
            self.eval_args(frame, step.node)
            return None
        if isinstance(val, Closure | Fn) and step.name in _MAKE_SERVICE:
            return Static()  # a handler served as a service: no routes
        return self.unresolved_step(frame, step)

    def router_step(self, frame: Frame, rtr: Rtr, step: Step) -> Any:
        name, args = step.name, args_of(step.node)
        if name in ("route", "route_with_tsr") and len(args) == 2:
            self.route(frame, rtr, step, args)
        elif name == "route_service" and len(args) == 2:
            path = self.string_of(frame, args[0])
            target = self.eval(frame, args[1])
            if path is None:
                self.site_at(frame, step.line)
            elif not isinstance(target, Static):
                rtr.routes.append(
                    Frag("ANY", path, _handler(args[1]), frame.mod.file, step.line)
                )
        elif name in ("nest", "nest_service") and len(args) == 2:
            self.nest(frame, rtr, step, args)
        elif name == "merge" and len(args) == 1:
            child = self.eval(frame, args[0])
            if isinstance(child, Rtr):
                self.absorb(rtr, child, "")
            else:
                self.site_at(frame, step.line)
        elif name in _SERVICE_CALLS:
            self.eval_args(frame, step.node)
            return None
        elif name == "clone" and not args:
            copy = self.new_router()
            copy.routes = list(rtr.routes)
            return copy
        elif name == "fallback_service" and len(args) == 1:
            if isinstance(self.eval(frame, args[0]), Rtr):
                self.site_at(frame, step.line)
        elif name in _PASS_ROUTER:
            self.eval_args(frame, step.node)
        else:
            self.site_at(frame, step.line)
            self.eval_args(frame, step.node)
        return rtr

    def route(self, frame: Frame, rtr: Rtr, step: Step, args: list[Node]) -> None:
        path = self.string_of(frame, args[0])
        target = self.eval(frame, args[1])
        if path is None or not isinstance(target, MRtr | Static):
            self.site_at(frame, step.line)
        elif isinstance(target, MRtr):
            for method, handler in target.methods:
                rtr.routes.append(
                    Frag(method, path, handler, frame.mod.file, step.line)
                )

    def nest(self, frame: Frame, rtr: Rtr, step: Step, args: list[Node]) -> None:
        prefix = self.string_of(frame, args[0])
        child = self.eval(frame, args[1])
        if step.name == "nest_service" and isinstance(child, MRtr):
            if prefix is None:
                self.site_at(frame, step.line)
                return
            for method, handler in child.methods:
                rtr.routes.append(
                    Frag(method, prefix, handler, frame.mod.file, step.line)
                )
            return
        if isinstance(child, Static) and step.name == "nest_service":
            return
        if isinstance(child, Rtr):
            self.absorb(rtr, child, prefix)
        if prefix is None or not isinstance(child, Rtr):
            self.site_at(frame, step.line)

    def method_step(self, frame: Frame, made: MRtr, step: Step) -> Any:
        name, args = step.name, args_of(step.node)
        service = name.endswith("_service")
        verb = name.removesuffix("_service")
        if verb in VERBS and len(args) == 1:
            val = self.eval(frame, args[0])
            if not (service and isinstance(val, Static)):
                made.methods.append((verb.upper(), _handler(args[0])))
        elif name in ("on", "on_service") and len(args) == 2:
            names = self.filter_names(args[0]) or ["ANY"]
            self.eval(frame, args[1])
            made.methods.extend((m, _handler(args[1])) for m in names)
        elif name == "clone" and not args:
            return MRtr(list(made.methods))
        elif name == "merge" and len(args) == 1:
            other = self.eval(frame, args[0])
            if isinstance(other, MRtr):
                made.methods.extend(other.methods)
            else:
                self.site_at(frame, step.line)
        elif name in _PASS_METHOD:
            self.eval_args(frame, step.node)
        else:
            self.site_at(frame, step.line)
            self.eval_args(frame, step.node)
        return made

    def unresolved_step(self, frame: Frame, step: Step) -> Any:
        """Ruling 12: a routing call on a receiver nothing proves is a router
        is a site only when its arguments are routing-shaped."""
        name, args = step.name, args_of(step.node)
        vals = [self.eval(frame, a) for a in args]
        # an axum package: `.route(<any path>, x)` on a value nothing
        # proves is something else is routing, whatever `x` turns out to be
        literal = bool(args) and self.routing_shaped(args[0])
        shaped = False
        if name in ("route", "route_with_tsr") and len(args) == 2:
            shaped = isinstance(vals[1], MRtr) or literal
        elif name in ("nest", "nest_service", "route_service") and len(args) == 2:
            shaped = isinstance(vals[1], Rtr) or literal
        elif name == "merge" and len(args) == 1:
            shaped = isinstance(vals[0], Rtr)
        elif name == "serve" and len(args) == 1:
            if vals[0] is None:
                self.site_at(frame, step.line)
            return None
        if shaped:
            self.site_at(frame, step.line)
        else:
            self.consume(frame, vals, args, step.node, step.line)
        for val in vals:
            if isinstance(val, Rtr):
                val.absorbed = True
            elif isinstance(val, Closure):
                self.run_closure(val, [])
        return None


def run(idx: Index) -> AdapterResult:
    play = AxumPlay(idx)
    roots = [
        f
        for f in idx.fns
        if not play.router_ty(f.mod, f.ret)
        and not any(play.router_ty(f.mod, t, param=True) for _n, t in f.params)
    ]
    for fn in roots:
        play.run_fn(fn, [], None)
    rooted = {id(f) for f in roots}
    for fn in idx.fns:
        if id(fn) not in play.reached and id(fn) not in rooted:
            play.sites.add(f"{fn.file}:{fn.line}")
    routes = emit([r for rtr in play.routers if not rtr.absorbed for r in rtr.routes])
    return AdapterResult(
        routes,
        sorted(
            play.sites | set(idx.sites) | set(idx.router_items) | set(idx.macro_sites())
        ),
    )
