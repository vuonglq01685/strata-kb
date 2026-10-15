"""Actix Web route adapter (Rust).

Routes come from two places and both are read the way the program registers
them:

- **attribute macros** -- `#[get("/p")]`, `#[route("/p", method = "GET")]` on
  a handler fn. A handler is a route only where `App::new().service(h)` /
  `scope.service(h)` / `cfg.service(h)` registers it, under the scopes it is
  registered in (twice -> two routes). An attributed handler nothing
  registers is **not** listed (a false route) and **is** a site at its
  attribute (it may be registered through code this adapter cannot follow);
  see `_routes_rust.py` for the shared reasoning.
- **builders** -- `web::scope(p)`, `web::resource(p).route(web::get().to(h))`
  / `.to(h)`, `.route(p, web::get().to(h))`, `.configure(f)` /
  `.configure(|cfg| ..)` with `cfg.service(..)` inside, `.service(scope_fn())`.

The evaluator (`_rs_interp`) runs every function body; every `App::new()`
is a root app whose routes are listed with the fully joined path. Not routes
and not sites: `actix_files::Files` (static files), `.wrap`, `.app_data`,
`.default_service`, `.guard` (they add no (method, path)). Sites: a
non-literal scope / resource / route path, a `.service(..)` argument that is
neither a known service nor a registered handler (`SwaggerUi`, an external
crate's scope), `.configure(f)` of a function that is not in the package, a
scope / resource / `ServiceConfig` function nothing calls, an attributed
handler nothing registers, a route-shaped call on an unresolved receiver.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from strata_kb.codeingest.extractors._routes_model import AdapterResult
from strata_kb.codeingest.extractors._rs_attrs import VERBS, route_attrs
from strata_kb.codeingest.extractors._rs_frag import Frag, emit, prefixed
from strata_kb.codeingest.extractors._rs_index import Fn
from strata_kb.codeingest.extractors._rs_interp import (
    Closure,
    Env,
    Frame,
    Interp,
    Other,
    Step,
    args_of,
)
from strata_kb.codeingest.extractors._rs_syntax import (
    crate_tail,
    line_of,
    plain_path,
    segments,
    text,
    walk,
)

if TYPE_CHECKING:
    from tree_sitter import Node

    from strata_kb.codeingest.extractors._rs_index import Index

__all__ = ["run"]

_FACTORY = re.compile(r"\b(?:Scope|Resource|HttpServiceFactory|App|ServiceConfig)\b")
_NOT_ROOT = re.compile(r"\b(?:Scope|Resource|HttpServiceFactory)\b")
_PASS = frozenset(
    {
        "wrap", "wrap_fn", "app_data", "data", "data_factory", "default_service",
        "guard", "name", "external_resource", "on_connect", "service_factory",
        "clone", "into", "unwrap", "expect", "ok",
    }
)  # fmt: skip


@dataclass
class Cont:
    """An App, Scope, Resource or ServiceConfig being filled."""

    kind: str
    prefixes: list[str] | None = field(default_factory=lambda: [""])
    routes: list[Frag] = field(default_factory=list)
    method: str = "ANY"  # a resource's `.guard(guard::Get())`


@dataclass
class Method:
    """`web::get()` / `web::route()` / `web::method(..)`, `.to(h)` pending."""

    method: str
    handler: str = ""


class Static:
    """`actix_files::Files`: serves files, no handler code."""


class ActixPlay(Interp):
    def __init__(self, idx: Index):
        super().__init__(idx)
        self.apps: list[Cont] = []
        self.registered: set[int] = set()
        self.claimed: dict[int, list] = {}
        self.configured: set[tuple[str, int]] = set()

    # -- hooks -----------------------------------------------------------

    def should_run(self, closure: Closure) -> bool:
        """A `|cfg: &mut ServiceConfig| ..` closure is run where `.configure`
        applies it, or at the end as a whole app (see `run`)."""
        return "ServiceConfig" not in text(
            closure.node.child_by_field_name("parameters")
        )

    def follow(self, fn: Fn, args: list[Any]) -> bool:
        return any(isinstance(a, Cont) for a in args) or bool(_FACTORY.search(fn.ret))

    def merge(self, vals: list[Any]) -> Any:
        conts = [v for v in vals if isinstance(v, Cont)]
        if len(conts) < 2:
            return vals[0]
        out = Cont(conts[0].kind)
        for c in conts:
            self.absorb(out, c)
        return out

    def ext_call(self, frame: Frame, segs: tuple[str, ...], call: Node) -> Any:
        framework = crate_tail(segs, ("actix_web",))
        if framework is not None:
            made = self.actix_call(frame, framework[1:], call)
            if made is not None:
                return made
        elif segs[:1] == ("actix_files",) and segs[-2:] == ("Files", "new"):
            self.eval_args(frame, call)
            return Static()
        self.eval_args(frame, call)
        return None

    def actix_call(self, frame: Frame, tail: tuple[str, ...], call: Node) -> Any:
        last = tail[-1]
        if tail[-2:] in (("App", "new"), ("App", "default")):
            app = Cont("app")
            self.apps.append(app)
            return app
        if tail[-2:] == ("web", "scope"):
            return self.container(frame, "scope", call)
        if tail[-2:] == ("web", "resource"):
            return self.container(frame, "resource", call)
        if tail[-2:] == ("web", "redirect"):  # answers every method at `from`
            made = self.container(frame, "resource", call, 2)
            made.routes.append(
                Frag("ANY", "", "(inline)", frame.mod.file, line_of(call))
            )
            return made
        if len(tail) >= 2 and tail[-2] == "web" and last in VERBS | {"route"}:
            return Method("ANY" if last == "route" else last.upper())
        if tail[-2:] == ("web", "method"):
            return self.method_call(frame, call)
        if tail[-2:] == ("web", "to"):
            made = Method("ANY")
            self.set_handler(frame, made, args_of(call))
            return made
        return None

    def method_call(self, frame: Frame, call: Node) -> Method:
        args = args_of(call)
        segs = segments(args[0]) if len(args) == 1 else None
        name = segs[-1] if segs else ""
        if name.isupper() and name.lower() in VERBS:
            return Method(name)
        self.site(frame, call)
        return Method("ANY")

    def container(self, frame: Frame, kind: str, call: Node, arity: int = 1) -> Cont:
        args = args_of(call)
        prefixes = self.prefixes(frame, args[0]) if len(args) == arity else None
        if prefixes is None:
            self.site(frame, call)
        return Cont(kind, prefixes)

    def prefixes(self, frame: Frame, node: Node) -> list[str] | None:
        """One literal, or an array of literals (`web::resource(["/a", "/b"])`)."""
        if node.type == "array_expression":
            parts = [self.string_of(frame, c) for c in node.named_children]
            return (
                None
                if not parts or None in parts
                else [p for p in parts if p is not None]
            )
        one = self.string_of(frame, node)
        return None if one is None else [one]

    # -- steps -----------------------------------------------------------

    def step(self, frame: Frame, val: Any, step: Step) -> Any:
        if isinstance(val, Other):
            self.eval_args(frame, step.node)
            return None
        if isinstance(val, Cont):
            return self.cont_step(frame, val, step)
        if isinstance(val, Method):
            return self.method_step(frame, val, step)
        if isinstance(val, Static):
            self.eval_args(frame, step.node)
            return val
        return self.unresolved_step(frame, step)

    def cont_step(self, frame: Frame, cont: Cont, step: Step) -> Any:
        name, args = step.name, args_of(step.node)
        if name == "service" and len(args) == 1:
            self.add_service(frame, cont, args[0])
        elif name == "route" and cont.kind == "resource" and len(args) == 1:
            self.add_method(frame, cont, "", self.eval(frame, args[0]), step.line)
        elif name == "route" and len(args) == 2:
            path = self.string_of(frame, args[0])
            if path is None:
                self.site_at(frame, step.line)
                self.eval(frame, args[1])
            else:
                self.add_method(frame, cont, path, self.eval(frame, args[1]), step.line)
        elif name == "guard" and cont.kind == "resource" and len(args) == 1:
            cont.method = self.guard_method(args[0]) or cont.method
            self.eval_args(frame, step.node)
        elif name == "to" and cont.kind == "resource" and len(args) == 1:
            made = Method(cont.method)
            self.set_handler(frame, made, args)
            self.add_method(frame, cont, "", made, step.line)
        elif name == "configure" and len(args) == 1:
            self.configure(frame, cont, args[0], step)
        elif name in _PASS:
            self.eval_args(frame, step.node)
        else:
            self.site_at(frame, step.line)
            self.eval_args(frame, step.node)
        return cont

    def method_step(self, frame: Frame, made: Method, step: Step) -> Method:
        args = args_of(step.node)
        if step.name == "to" and len(args) == 1:
            self.set_handler(frame, made, args)
        elif step.name == "guard" and len(args) == 1:
            if made.method == "ANY":
                made.method = self.guard_method(args[0]) or "ANY"
            self.eval_args(frame, step.node)
        elif step.name in _PASS or step.name in ("to", "guard"):
            self.eval_args(frame, step.node)
        else:
            self.site_at(frame, step.line)
            self.eval_args(frame, step.node)
        return made

    @staticmethod
    def guard_method(node: Node) -> str | None:
        """`guard::Get()` -> "GET"; any other guard does not pick a method."""
        fn = (
            node.child_by_field_name("function")
            if node.type == "call_expression"
            else None
        )
        segs = segments(fn) if fn is not None else None
        if segs and segs[-2:-1] == ("guard",) and segs[-1].lower() in VERBS:
            return segs[-1].upper()
        return None

    def unresolved_step(self, frame: Frame, step: Step) -> Any:
        """Ruling 12: a framework-shaped call on a receiver that is not a
        known container is a site; anything else is ordinary code."""
        args = args_of(step.node)
        shaped = False
        if step.name == "service" and len(args) == 1:
            val = self.eval(frame, args[0])
            # a container / attributed handler, or something nothing proves
            # is ordinary (`shared::svc()`): both are routing on an unknown
            shaped = (
                val is None
                or isinstance(val, Cont)
                or self.service_fn(frame, args[0]) is not None
            )
        elif step.name == "route" and len(args) == 2:
            lit = self.string_of(frame, args[0]) is not None
            shaped = isinstance(self.eval(frame, args[1]), Method) or lit
        elif step.name == "configure" and len(args) == 1:
            shaped = (
                self.takes_config(frame, args[0]) or self.eval(frame, args[0]) is None
            )
        else:
            self.eval_args(frame, step.node)
        if shaped:
            self.site_at(frame, step.line)
        return None

    def takes_config(self, frame: Frame, node: Node) -> bool:
        val = self.eval(frame, node)
        if isinstance(val, Closure):
            params = val.node.child_by_field_name("parameters")
            return "ServiceConfig" in text(params)
        return isinstance(val, Fn) and any("ServiceConfig" in t for _n, t in val.params)

    # -- registration ----------------------------------------------------

    def set_handler(self, frame: Frame, made: Method, args: list[Node]) -> None:
        made.handler = "(inline)"
        if len(args) != 1:
            return
        made.handler = plain_path(args[0]) or "(inline)"
        val = self.eval(frame, args[0])
        if isinstance(val, Fn):
            self.registered.add(id(val))

    def add_method(
        self, frame: Frame, cont: Cont, path: str, made: Any, line: int
    ) -> None:
        if not isinstance(made, Method) or not made.handler:
            self.site_at(frame, line)
            return
        cont.routes.append(Frag(made.method, path, made.handler, frame.mod.file, line))

    def service_fn(self, frame: Frame, node: Node) -> Fn | None:
        if node.type not in ("identifier", "scoped_identifier"):
            return None
        val = self.eval(frame, node)
        if isinstance(val, Fn) and self.attrs_of(val):
            return val
        return None

    def attrs_of(self, fn: Fn) -> list:
        if id(fn) not in self.claimed:
            self.claimed[id(fn)] = [
                a for a in route_attrs(self.idx, fn) if a.framework in ("actix", None)
            ]
        return self.claimed[id(fn)]

    def add_service(self, frame: Frame, cont: Cont, node: Node) -> None:
        kind = node.type
        if kind in ("parenthesized_expression", "reference_expression"):
            inner = next(iter(node.named_children), None)
            if inner is not None:
                self.add_service(frame, cont, inner)
            return
        if kind == "tuple_expression":
            for part in node.named_children:
                self.add_service(frame, cont, part)
            return
        if kind in ("identifier", "scoped_identifier"):
            val = self.eval(frame, node)
            if isinstance(val, Fn):
                self.register_handler(frame, cont, val, node)
                return
            self.absorb_value(frame, cont, val, node)
            return
        self.absorb_value(frame, cont, self.eval(frame, node), node)

    def absorb_value(self, frame: Frame, cont: Cont, val: Any, node: Node) -> None:
        if isinstance(val, Cont):
            self.absorb(cont, val)
        elif not isinstance(val, Static):
            self.site(frame, node)

    def register_handler(self, frame: Frame, cont: Cont, fn: Fn, node: Node) -> None:
        attrs = self.attrs_of(fn)
        if not attrs:
            self.site(frame, node)
            return
        self.registered.add(id(fn))
        text_ = plain_path(node) or "(inline)"
        for attr in attrs:
            if attr.path is None or attr.methods is None:
                self.sites.add(f"{fn.file}:{attr.line}")
                continue
            for method in attr.methods:
                cont.routes.append(Frag(method, attr.path, text_, fn.file, attr.line))

    def absorb(self, parent: Cont, child: Cont) -> None:
        for prefix in child.prefixes or []:
            parent.routes.extend(prefixed(child.routes, prefix))

    def configure(self, frame: Frame, cont: Cont, node: Node, step: Step) -> None:
        val = self.eval(frame, node)
        if isinstance(val, Closure):
            self.configured.add((frame.mod.file, val.node.start_byte))
            self.run_closure(val, [cont])
        elif isinstance(val, Fn):
            self.apply_fn(frame, val, [cont], step.node)
        else:
            self.site_at(frame, step.line)


def run_config_closures(play: ActixPlay, idx: Index) -> None:
    """A `|cfg: &mut ServiceConfig| ..` closure nothing here configures is
    handed to the runtime (shuttle's `Ok(config.into())`, a lambda adapter),
    which applies it to a fresh `App`: its routes are a whole app's."""
    for fn in idx.fns:
        body = fn.body
        for node in walk(body) if body is not None else []:
            if node.type != "closure_expression":
                continue
            if "ServiceConfig" not in text(node.child_by_field_name("parameters")):
                continue
            if (fn.file, node.start_byte) in play.configured:
                continue
            app = Cont("app")
            play.apps.append(app)
            play.run_closure(Closure(node, Frame(fn.mod, Env())), [app])


def run(idx: Index) -> AdapterResult:
    play = ActixPlay(idx)
    roots = [
        f
        for f in idx.fns
        if not _NOT_ROOT.search(f.ret)
        and not any("ServiceConfig" in t for _n, t in f.params)
    ]
    for fn in roots:
        play.run_fn(fn, [], None)
    run_config_closures(play, idx)
    rooted = {id(f) for f in roots}
    for fn in idx.fns:
        if id(fn) not in play.reached and id(fn) not in rooted:
            play.sites.add(f"{fn.file}:{fn.line}")
    for fn in [*idx.fns, *play.local_fns.values()]:
        for attr in route_attrs(idx, fn):
            if attr.framework == "other":  # a verb attribute of a crate we cannot read
                play.sites.add(f"{fn.file}:{attr.line}")
        attrs = play.attrs_of(fn)
        if attrs and id(fn) not in play.registered:
            play.sites.add(f"{fn.file}:{attrs[0].line}")
    routes = emit([r for app in play.apps for r in app.routes])
    return AdapterResult(
        routes, sorted(play.sites | set(idx.sites) | set(idx.macro_sites()))
    )
