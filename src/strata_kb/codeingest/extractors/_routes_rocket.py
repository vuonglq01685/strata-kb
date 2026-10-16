"""Rocket route adapter (Rust).

`#[get("/p/<id>")]`, `#[post("/", data = "<form>")]`,
`#[route(GET, uri = "/p")]` on a handler are routes where
`rocket::build().mount("/base", routes![a, b])` mounts them (also
`rocket::ignite()`, `rocket::custom(..)`, `#[launch]` and `#[rocket::main]`
functions, a function returning `Vec<Route>` built with `routes![..]`, a
fairing `AdHoc::on_ignite("x", |rocket| async { rocket.mount(..) })` that is
`.attach`ed, a helper that takes the `Rocket<Build>`). A mount prefix is
absolute (no nesting), so every function that takes no `Rocket` parameter is
evaluated on its own. The query part of a path (`/hello?<name>`) is not part
of the route and is dropped; `<id>` / `<rest..>` stay as written.

An attributed handler that no `routes![..]` mounts is not listed and is a
site (see `_routes_rust.py`). Not routes and not sites: `FileServer`,
`catchers![..]` / `register`, `manage`, `attach` of an ordinary fairing.
Sites: a non-literal mount prefix or attribute path, a `mount` of anything
but `routes![..]` / a function returning one / `FileServer`
(`make_swagger_ui`, another crate's `routes()`), a `Rocket` handed to a
function this adapter cannot follow, a `mount(..)` on a receiver that is not
provably something else, a `Rocket`-taking function nothing calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from strata_kb.codeingest.extractors._routes_model import AdapterResult, join_path
from strata_kb.codeingest.extractors._rs_attrs import route_attrs
from strata_kb.codeingest.extractors._rs_frag import Frag, emit
from strata_kb.codeingest.extractors._rs_index import Fn
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
    elements,
    segments,
    text,
)

if TYPE_CHECKING:
    from tree_sitter import Node

    from strata_kb.codeingest.extractors._rs_index import Index

__all__ = ["run"]

# by value only: `&Rocket` cannot mount (`Rocket::mount` takes `self`)
_ROCKET_TYPE = re.compile(r"^(?:\w+::)*Rocket\b")
_ROUTE_LIST_RET = re.compile(r"\b(?:Vec|Route|Rocket|AdHoc|Build)\b|^_$")
_PASS = frozenset(
    {
        "manage", "register", "configure", "reconfigure", "launch", "ignite", "into",
        "clone", "unwrap", "expect", "ok", "unwrap_or_else", "unwrap_or_default",
        "map_err", "try_launch", "try_launch_on", "launch_on", "launch_with",
    }
)  # fmt: skip
# read accessors: they give a figment / config / state, not the `Rocket`
_READS = frozenset(
    {"figment", "config", "state", "shutdown", "endpoints", "catchers", "routes"}
)
_WRAPPERS = frozenset({"Ok", "Some", "Err"})
_BOXES = frozenset({"Box", "Arc", "Rc", "Pin"})


@dataclass(eq=False)
class Rkt:
    routes: list[Frag] = field(default_factory=list)


@dataclass
class RouteList:
    items: list[tuple[Fn, str]]


@dataclass
class Static:
    """`FileServer`: serves files, no handler code."""


@dataclass
class AdHoc:
    runner: Any  # a Closure or an in-repo Fn taking the rocket


class RocketPlay(Interp):
    def __init__(self, idx: Index):
        super().__init__(idx)
        self.rockets: list[Rkt] = []
        self.registered: set[int] = set()
        self._claimed: dict[int, list] = {}

    def claimed(self, fn: Fn) -> list:
        if id(fn) not in self._claimed:
            self._claimed[id(fn)] = [
                a for a in route_attrs(self.idx, fn) if a.framework in ("rocket", None)
            ]
        return self._claimed[id(fn)]

    def new_rocket(self) -> Rkt:
        made = Rkt()
        self.rockets.append(made)
        return made

    def follow(self, fn: Fn, args: list[Any]) -> bool:
        return bool(_ROUTE_LIST_RET.search(fn.ret)) or any(
            isinstance(a, Rkt) for a in args
        )

    def merge(self, vals: list[Any]) -> Any:
        rockets = [v for v in vals if isinstance(v, Rkt)]
        if len(rockets) > 1 and len(rockets) == len(vals):
            out = self.new_rocket()  # a builder from either branch
            for rkt in rockets:
                out.routes.extend(rkt.routes)
            return out
        items = [i for v in vals if isinstance(v, RouteList) for i in v.items]
        if items and all(isinstance(v, RouteList) for v in vals):
            return RouteList(items)
        return super().merge(vals)

    # -- macros and calls ------------------------------------------------

    def macro(self, frame: Frame, node: Node) -> Any:
        segs = segments(node.child_by_field_name("macro")) or ("",)
        if not segs[-1].endswith("routes"):
            return super().macro(frame, node)
        tree = next((c for c in node.named_children if c.type == "token_tree"), None)
        items: list[tuple[Fn, str]] = []
        for elem in elements(tree):
            written = "".join(text(n) for n in elem)
            parts = tuple(written.split("::"))
            res = (
                self.resolve(frame, parts)
                if all(p.isidentifier() for p in parts)
                else None
            )
            if (
                res is None
                or res.kind != "fn"
                or res.fn is None
                or not self.claimed(res.fn)
            ):
                self.site(frame, node)
                continue
            items.append((res.fn, written))
        return RouteList(items)

    def ext_call(self, frame: Frame, segs: tuple[str, ...], call: Node) -> Any:
        name = segs[-1]
        framework = crate_tail(segs, ("rocket",))
        if framework is not None:
            segs = framework
            if segs[-2:] == ("Rocket", "build") or segs in (
                ("rocket", "build"),
                ("rocket", "ignite"),
                ("rocket", "custom"),
            ):
                self.eval_args(frame, call)
                return self.new_rocket()
            if (
                len(segs) >= 2
                and segs[-2] == "AdHoc"
                and name in ("on_ignite", "try_on_ignite")
            ):
                args = args_of(call)
                return AdHoc(self.eval(frame, args[1])) if len(args) == 2 else None
            if len(segs) >= 2 and segs[-2] == "FileServer":
                self.eval_args(frame, call)
                return Static()
        vals = self.eval_args(frame, call)
        if (
            name in _WRAPPERS
            or (len(segs) >= 2 and segs[-2] in _BOXES and name in ("new", "pin"))
        ) and vals:
            return vals[0]
        self.consume(frame, vals, args_of(call), call, 0)
        return None

    def consume(
        self,
        frame: Frame,
        vals: list[Any],
        nodes: list[Node],
        at: Node | None,
        line: int,
    ) -> None:
        """A `Rocket` handed by value to a function nothing here follows
        (`&rocket` only reads it: `Rocket::mount` takes `self`)."""
        given = [
            v
            for v, n in zip(vals, nodes, strict=False)
            if n.type != "reference_expression"
        ]
        if any(isinstance(v, Rkt) for v in given):
            if line:
                self.site_at(frame, line)
            elif at is not None:
                self.site(frame, at)

    # -- steps -----------------------------------------------------------

    def step(self, frame: Frame, val: Any, step: Step) -> Any:
        if isinstance(val, Other):
            self.eval_args(frame, step.node)
            return None
        if isinstance(val, Rkt):
            return self.rocket_step(frame, val, step)
        if isinstance(val, Static):
            self.eval_args(frame, step.node)
            return val
        return self.unresolved_step(frame, step)

    def rocket_step(self, frame: Frame, rkt: Rkt, step: Step) -> Any:
        name, args = step.name, args_of(step.node)
        if name == "mount" and len(args) == 2:
            self.mount(frame, rkt, step, args)
        elif name == "attach" and len(args) == 1:
            self.attach(frame, rkt, args[0], step)
        elif name in _PASS:
            self.eval_args(frame, step.node)
        elif name in _READS:
            self.eval_args(frame, step.node)
            return None
        else:
            self.site_at(frame, step.line)
            self.eval_args(frame, step.node)
        return rkt

    def mount(self, frame: Frame, rkt: Rkt, step: Step, args: list[Node]) -> None:
        base = self.string_of(frame, args[0])
        mounted = self.eval(frame, args[1])
        if isinstance(mounted, Static):
            return
        if isinstance(mounted, RouteList):  # a dropped mount still registers them
            self.registered.update(id(fn) for fn, _w in mounted.items)
        if base is None or not isinstance(mounted, RouteList):
            self.site_at(frame, step.line)
            return
        for fn, written in mounted.items:
            for attr in self.claimed(fn):
                if attr.path is None or attr.methods is None:
                    self.sites.add(f"{fn.file}:{attr.line}")
                    continue
                for method in attr.methods:
                    rkt.routes.append(
                        Frag(
                            method,
                            join_path(base, attr.path),
                            written,
                            fn.file,
                            attr.line,
                        )
                    )

    def attach(self, frame: Frame, rkt: Rkt, node: Node, step: Step) -> None:
        fairing = self.eval(frame, node)
        if not isinstance(fairing, AdHoc):
            self.attach_type(frame, rkt, node, step)
            return
        runner = fairing.runner
        if isinstance(runner, Closure):
            self.run_closure(runner, [rkt])
        elif isinstance(runner, Fn):
            self.apply_fn(frame, runner, [rkt], step.node)
        else:
            self.site_at(frame, step.line)

    def attach_type(self, frame: Frame, rkt: Rkt, node: Node, step: Step) -> None:
        """`.attach(Counter::default())`: a fairing struct of this package
        whose `on_ignite` hook may mount routes."""
        head = (
            node.child_by_field_name("function")
            if node.type == "call_expression"
            else node
        )
        if head is not None and head.type == "struct_expression":
            head = head.child_by_field_name("name")
        segs = segments(head)
        res = self.resolve(frame, segs[:1]) if segs else None
        if res is None or res.kind != "type":
            return
        hook = self.idx.method(res.segs[0], "on_ignite")
        if hook is not None and hook.kind == "fn" and hook.fn is not None:
            self.apply_fn(frame, hook.fn, [rkt], step.node)

    def unresolved_step(self, frame: Frame, step: Step) -> Any:
        """Ruling 12: `mount(base, routes![..])` on a receiver nothing proves
        is something else is a site; any other `.mount` / `.get` is code."""
        args = args_of(step.node)
        vals = [self.eval(frame, a) for a in args]
        if step.name == "mount" and len(args) == 2:
            if isinstance(vals[1], RouteList) or self.routing_shaped(args[0]):
                self.site_at(frame, step.line)
        else:
            self.consume(frame, vals, args, None, step.line)
        for val in vals:
            if isinstance(val, Closure):
                self.run_closure(val, [])
        return None


def run(idx: Index) -> AdapterResult:
    play = RocketPlay(idx)
    roots = [f for f in idx.fns if not any(_ROCKET_TYPE.match(t) for _n, t in f.params)]
    for fn in roots:
        play.run_fn(fn, [], None)
    rooted = {id(f) for f in roots}
    for fn in idx.fns:
        if id(fn) not in play.reached and id(fn) not in rooted:
            play.sites.add(f"{fn.file}:{fn.line}")
    for fn in [*idx.fns, *play.local_fns.values()]:
        for attr in route_attrs(idx, fn):
            if attr.framework == "other":  # a verb attribute of a crate we cannot read
                play.sites.add(f"{fn.file}:{attr.line}")
        attrs = play.claimed(fn)
        if attrs and id(fn) not in play.registered:
            play.sites.add(f"{fn.file}:{attrs[0].line}")
    routes = emit([r for rkt in play.rockets for r in rkt.routes])
    return AdapterResult(
        routes, sorted(play.sites | set(idx.sites) | set(idx.macro_sites()))
    )
