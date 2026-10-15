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
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._go_ast import (
    GIN,
    UNKNOWN,
    Func,
    GoFile,
    Index,
    Other,
    Pkg,
    Router,
    Str,
    Typed,
    Value,
    dotted,
    group_like,
    params,
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

_VERBS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_HTTP_METHODS = _VERBS | {"CONNECT", "TRACE"}
_METHOD_CONSTS = {
    f"Method{m.title()}": m for m in sorted(_HTTP_METHODS)
}  # http.MethodGet
_ROUTE_NAMES = _VERBS | {"Any"}
_STRINGS = frozenset({"interpreted_string_literal", "raw_string_literal"})
_SCOPES = frozenset(
    {
        "block", "if_statement", "for_statement", "expression_switch_statement",
        "type_switch_statement", "select_statement", "expression_case", "default_case",
        "type_case", "communication_case",
    }
)  # fmt: skip
_LEAVES = frozenset(
    {
        "comment", "interpreted_string_literal", "raw_string_literal",
        "import_declaration", "type_declaration", "package_clause",
    }
)  # fmt: skip
_GROUP_CALLS = frozenset({"Use", "Static", "StaticFS", "StaticFile", "StaticFileFS"})
_INLINE = "(inline)"
_MAX_DEPTH = 8
_MAX_KEY = 8  # longest dotted key looked up in the environment
_BUDGET = 5000
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
_OTHER_ROUTING = _VERBS | {
    "Get", "Post", "Put", "Patch", "Delete", "Head", "Options", "Any", "Handle",
    "HandleFunc", "Route", "Mount", "Group", "PathPrefix", "Subrouter", "Match",
    "Add",
}  # fmt: skip
_STRUCTURAL = frozenset({"Route", "Mount", "PathPrefix", "Subrouter", "Group"})
_UNSAFE_PATH = re.compile(r"[\s\x00-\x1f]")  # not a path a router could register
_SKIP_FILE = re.compile(r"(?:^|/)(?:testdata|_[^/]*|\.[^/]+)/|_test\.go$")


class Seg(NamedTuple):
    name: str | None  # method name; None for a direct call `f(...)`
    args: list[Node]
    node: Node
    fn: Node


class Frame(NamedTuple):
    file: GoFile
    env: Env
    depth: int
    stack: frozenset[int]


class Env:
    __slots__ = ("parent", "vars")

    def __init__(self, parent: Env | None = None) -> None:
        self.vars: dict[str, Value] = {}
        self.parent = parent

    def get(self, key: str) -> Value | None:
        env: Env | None = self
        while env is not None:
            if key in env.vars:
                return env.vars[key]
            env = env.parent
        return None

    def assign(self, key: str, value: Value) -> None:
        env: Env | None = self
        while env is not None:
            if key in env.vars:
                env.vars[key] = value
                return
            env = env.parent
        self.vars[key] = value


def _args(call: Node) -> list[Node]:
    lst = call.child_by_field_name("arguments")
    return [c for c in lst.named_children if c.type != "comment"] if lst else []


def unroll(call: Node) -> tuple[Node | None, list[Seg]]:
    """Base expression and the calls chained on it, innermost first:
    `a.b().c(x)` is base `a` with segments `b()`, `c(x)`."""
    segs: list[Seg] = []
    cur: Node | None = call
    while cur is not None:
        while cur.type == "parenthesized_expression" and cur.named_children:
            cur = cur.named_children[0]
        if cur.type != "call_expression":
            break
        fn = cur.child_by_field_name("function")
        if fn is None:
            return None, segs[::-1]
        while fn.type == "parenthesized_expression" and fn.named_children:
            fn = fn.named_children[0]
        if fn.type != "selector_expression":
            segs.append(Seg(None, _args(cur), cur, fn))
            return None, segs[::-1]
        segs.append(Seg(_text(fn.child_by_field_name("field")), _args(cur), cur, fn))
        cur = fn.child_by_field_name("operand")
    return cur, segs[::-1]


def _line(seg: Seg) -> int:
    field = seg.fn.child_by_field_name("field") if seg.name is not None else None
    return _ts.line_of(field if field is not None else seg.fn)


def _handler(node: Node) -> str:
    return (dotted(node) or _INLINE) if node.type != "identifier" else _text(node)


def _routing_names(path: str) -> frozenset[str]:
    return _HTTP_ROUTING if path == "net/http" else _OTHER_ROUTING


class Play:
    def __init__(self, idx: Index) -> None:
        self.idx = idx
        self.routes: set[Route] = set()
        self.sites: set[str] = set(idx.sites)
        self.budget = _BUDGET
        self.reached: set[int] = set()
        self._pkg_env: dict[str, Env] = {}
        self._group_params: dict[int, bool] = {}

    # --- entry --------------------------------------------------------------

    def run(self) -> None:
        funcs = self.idx.methods_and_funcs()
        for directory in sorted(self.idx.pkgs):
            env = self.pkg_env(directory)
            for gofile, decl in self.idx.pkgs[directory].decls:
                self._guard(gofile, decl, lambda g=gofile, d=decl, e=env: self.walk(
                    d, Frame(g, e, 0, frozenset())
                ))  # fmt: skip
        for func in funcs:
            if not self.has_group_param(func):
                self._guard(func.file, func.node, lambda f=func: self.run_func(
                    f, {}, 0, frozenset({id(f)})
                ))  # fmt: skip
        for func in funcs:
            if self.has_group_param(func) and id(func) not in self.reached:
                self._probe(func)

    def _guard(self, gofile: GoFile, node: Node, action: Callable[[], None]) -> None:
        """Run one root; whatever it cannot handle (a hostile nesting, an
        unforeseen node shape) is a site at the root, never a crash and
        never a silently missing function."""
        try:
            action()
        except Exception:  # noqa: BLE001 -- degrade, never crash: one bad function must not abort the scope
            self.sites.add(f"{gofile.rel}:{_ts.line_of(node)}")

    def _probe(self, func: Func) -> None:
        """An uncalled helper: run it into a scratch result; anything it
        would register or flag makes its declaration a site."""
        saved = self.routes, self.sites
        self.routes, self.sites = set(), set()
        self._guard(func.file, func.node, lambda: self.run_func(
            func, {}, 0, frozenset({id(func)}), probe=True
        ))  # fmt: skip
        produced = bool(self.routes or self.sites)
        self.routes, self.sites = saved
        if produced:
            self.sites.add(f"{func.file.rel}:{func.line}")

    def has_group_param(self, func: Func) -> bool:
        key = id(func)
        if key not in self._group_params:
            self._group_params[key] = any(
                group_like(self.idx.classify(func.file, p.type)) for p in func.params
            )
        return self._group_params[key]

    def bindings(self, func: Func, probe: bool) -> dict[str, Value]:
        out: dict[str, Value] = {}
        if func.recv_name and func.recv_type:
            out[func.recv_name] = Typed(func.file.dir, func.recv_type)
        for p in func.params:
            if p.name:
                v = self.idx.classify(func.file, p.type)
                out[p.name] = Router("") if probe and group_like(v) else v or UNKNOWN
        return out

    def run_func(
        self,
        func: Func,
        binds: dict[str, Value],
        depth: int,
        stack: frozenset[int],
        probe: bool = False,
    ) -> None:
        env = Env(self.pkg_env(func.file.dir))
        env.vars.update(self.bindings(func, probe))
        env.vars.update(binds)
        body = func.node.child_by_field_name("body")
        if body is not None:
            self.walk(body, Frame(func.file, env, depth, stack))

    def pkg_env(self, directory: str) -> Env:
        """Package-level `const` / `var` bindings of all files of a package,
        resolved in passes so a later file may define what an earlier uses."""
        env = self._pkg_env.get(directory)
        if env is not None:
            return env
        env = self._pkg_env[directory] = Env()
        pkg = self.idx.pkgs.get(directory)
        for _ in range(4 if pkg else 0):
            before = dict(env.vars)
            for gofile, decl in pkg.decls if pkg else ():
                frame = Frame(gofile, env, 0, frozenset())
                self._guard(
                    gofile,
                    decl,
                    lambda f=frame, d=decl: env.vars.update(self.declared(f, d)),
                )
            if env.vars == before:
                break
        return env

    # --- statements ---------------------------------------------------------

    def walk(self, start: Node, frame: Frame) -> None:
        stack: list = [(start, frame.env)]
        while stack:
            item = stack.pop()
            if callable(item):
                item()
                continue
            node, env = item
            self.visit(node, frame._replace(env=env), stack)

    def visit(self, node: Node, frame: Frame, stack: list) -> None:
        kind = node.type
        if kind in _LEAVES:
            return
        if kind in _SCOPES:
            frame = frame._replace(env=Env(frame.env))
        env = frame.env
        if kind == "func_literal":
            inner = Env(env)
            for p in params(node.child_by_field_name("parameters")):
                if p.name:
                    inner.vars[p.name] = (
                        self.idx.classify(frame.file, p.type) or UNKNOWN
                    )
            body = node.child_by_field_name("body")
            if body is not None:
                stack.append((body, inner))
        elif kind == "call_expression":
            self.chain(frame, node, True)
            base, segs = unroll(node)
            children = [base] if base is not None else []
            for seg in segs:
                if seg.name is None:
                    children.append(seg.fn)
                children += seg.args
            stack.extend((c, env) for c in reversed(children))
        elif kind in ("short_var_declaration", "assignment_statement"):
            self.assign(frame, node, stack)
        elif kind in ("var_declaration", "const_declaration"):
            pairs = self.declared(frame, node)
            stack.append(lambda: env.vars.update(pairs))
            stack.extend((c, env) for c in reversed(node.named_children))
        elif kind == "range_clause":
            left = node.child_by_field_name("left")
            names = [dotted(c) for c in (left.named_children if left else [])]
            stack.append(lambda: env.vars.update({n: UNKNOWN for n in names if n}))
            right = node.child_by_field_name("right")
            if right is not None:
                stack.append((right, env))
        else:
            stack.extend((c, env) for c in reversed(node.named_children))

    def assign(self, frame: Frame, node: Node, stack: list) -> None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        lhs = left.named_children if left is not None else []
        rhs = right.named_children if right is not None else []
        define = node.type == "short_var_declaration"
        operator = node.child_by_field_name("operator")
        plain = define or (operator is not None and _text(operator) == "=")
        if plain and len(lhs) == len(rhs):
            values = [self.value_of(frame, r) for r in rhs]
        elif plain and len(rhs) == 1:
            values = [self.value_of(frame, rhs[0])] + [None] * (len(lhs) - 1)
        else:
            values = [None] * len(lhs)
        # a local string is a variable, not a constant: a path built from it is dynamic
        values = [UNKNOWN if v is None or isinstance(v, Str) else v for v in values]
        env = frame.env

        def bind() -> None:
            for target, value in zip(lhs, values, strict=True):
                key = dotted(target)
                if key is None or key == "_":
                    continue
                if define:
                    env.vars[key] = value
                else:
                    env.assign(key, value)

        stack.append(bind)
        stack.extend((c, env) for c in reversed([*rhs, *lhs]))

    def declared(self, frame: Frame, node: Node) -> dict[str, Value]:
        """Bindings of a `var` / `const` declaration. Only a `const` keeps a
        string: a `var` can be reassigned."""
        keep = node.type == "const_declaration"
        out: dict[str, Value] = {}
        specs = [
            s
            for c in node.named_children
            for s in (c.named_children if c.type == "var_spec_list" else [c])
            if s.type in ("var_spec", "const_spec")
        ]
        for spec in specs:
            names = [_text(n) for n in spec.children_by_field_name("name")]
            value = spec.child_by_field_name("value")
            exprs = value.named_children if value is not None else []
            typed = self.idx.classify(frame.file, spec.child_by_field_name("type"))
            if len(exprs) == len(names):
                values = [self.value_of(frame, e) for e in exprs]
            elif len(exprs) == 1:
                values = [self.value_of(frame, exprs[0])] + [None] * (len(names) - 1)
            else:
                values = [None] * len(names)
            declared_type = spec.child_by_field_name("type") is not None
            for name, v in zip(names, values, strict=True):
                if not keep and isinstance(v, Str):
                    v = None
                if (
                    declared_type
                    and not isinstance(v, Str)
                    and not (isinstance(v, Router) and isinstance(typed, Router))
                ):
                    v = typed  # an explicit type wins (an interface hides the value)
                out[name] = v or typed or UNKNOWN
        return out

    # --- values -------------------------------------------------------------

    def value_of(self, frame: Frame, node: Node) -> Value | None:
        while node.type in ("parenthesized_expression", "unary_expression"):
            inner = (
                node.named_children[0]
                if node.type == "parenthesized_expression" and node.named_children
                else node.child_by_field_name("operand")
            )
            if inner is None:
                return None
            node = inner
        kind = node.type
        if kind == "identifier":
            name = _text(node)
            value = frame.env.get(name)
            if value is not None:
                return value
            path = frame.file.imports.get(name)
            return Pkg(path) if path else None
        if kind in _STRINGS:
            text = _ts.string_literal(node)
            return Str(text) if text is not None else None
        if kind == "selector_expression":
            return self.selector_value(frame, node)
        if kind == "call_expression":
            return self.chain(frame, node, False)
        if kind == "composite_literal":
            return self.idx.classify(frame.file, node.child_by_field_name("type"))
        if kind == "binary_expression":
            return self.concat(frame, node)
        return None

    def concat(self, frame: Frame, node: Node) -> Str | None:
        """`a + b + ...` of constant strings, flattened without recursion."""
        leaves: list[Node] = []
        todo = [node]
        while todo:
            cur = todo.pop()
            op = cur.child_by_field_name("operator")
            if cur.type == "binary_expression" and op is not None and _text(op) == "+":
                todo += [
                    x
                    for x in (
                        cur.child_by_field_name("right"),
                        cur.child_by_field_name("left"),
                    )
                    if x
                ]
            elif cur.type == "parenthesized_expression" and cur.named_children:
                todo.append(cur.named_children[0])
            else:
                leaves.append(cur)
        # a leaf that is another operator (`8 << 20`, `a - b`) is not a string
        parts = [
            None if leaf.type == "binary_expression" else self.value_of(frame, leaf)
            for leaf in leaves
        ]
        if any(not isinstance(p, Str) for p in parts):
            return None
        return Str("".join(p.text for p in parts if isinstance(p, Str)))

    def selector_value(self, frame: Frame, node: Node) -> Value | None:
        """`a.b.c`: the longest bound prefix (`s.router`), else the leftmost
        operand, then one field step at a time."""
        fields: list[str] = []
        cur: Node | None = node
        while cur is not None and cur.type == "selector_expression":
            fields.append(_text(cur.child_by_field_name("field")))
            cur = cur.child_by_field_name("operand")
        fields.reverse()
        key = dotted(node) if len(fields) <= _MAX_KEY else None
        parts = key.split(".") if key else []
        value: Value | None = None
        for i in range(len(parts), 1, -1):
            value = frame.env.get(".".join(parts[:i]))
            if value is not None:
                fields = fields[i - 1 :]
                break
        else:
            value = self.value_of(frame, cur) if cur is not None else None
        for name in fields:
            value = self.member(value, name)
            if value is None:
                break
        return value

    def member(self, base: Value | None, name: str) -> Value | None:
        if isinstance(base, Router) and name == "RouterGroup":
            return base  # the engine embeds its root group
        if isinstance(base, Pkg) and base.path == "net/http" and name in _METHOD_CONSTS:
            return Str(_METHOD_CONSTS[name])
        if isinstance(base, Pkg):
            target = self.idx.import_dir(base.path)
            return self.pkg_env(target).get(name) if target is not None else None
        info = self.idx.info(base) if isinstance(base, Typed) else None
        if info is not None and name in info.fields:
            return self.idx.classify(info.file, info.fields[name])
        return None

    def string(self, frame: Frame, node: Node) -> str | None:
        value = self.value_of(frame, node)
        return value.text if isinstance(value, Str) else None

    def result_value(self, func: Func) -> Value | None:
        result = func.result
        if result is not None and result.type == "parameter_list":
            first = params(result)
            result = first[0].type if first else None
        return self.idx.classify(func.file, result)

    # --- calls --------------------------------------------------------------

    def site(self, frame: Frame, seg: Seg) -> None:
        self.sites.add(f"{frame.file.rel}:{_line(seg)}")

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
        if name in _ROUTE_NAMES or name in ("Handle", "Match"):
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
        if name in _VERBS:
            return [name]
        if not args:
            return None
        if name == "Handle":
            first = self.string(frame, args[0])
            return [first] if first in _HTTP_METHODS else None
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
        ok = bool(found) and all(m in _HTTP_METHODS for m in found)
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
                Route(method, full, _handler(handlers[-1]), frame.file.rel, _line(seg))
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
        return Other(pkg.path)

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
        name, args = seg.name or "", seg.args
        first = self.string(frame, args[0]) if args else None
        rooted = first is not None and first.startswith("/")
        if name in _ROUTE_NAMES:
            return len(args) >= 2 and (rooted or (first is None and frame.file.gin))
        if name == "Group":
            return rooted
        if name in _HTTP_ROUTING:
            return len(args) >= 2
        if frame.file.other_router and name in _OTHER_ROUTING:
            return rooted or name in _STRUCTURAL
        return False

    def apply(
        self, frame: Frame, func: Func, seg: Seg, recv: Typed | None, emit: bool
    ) -> Value | None:
        """Call of an in-repo function: follow it when it takes a group."""
        result = self.result_value(func)
        if not emit or not self.has_group_param(func):
            return result
        self.reached.add(id(func))
        args = [self.value_of(frame, a) for a in seg.args]
        binds: dict[str, Value] = {}
        if recv is not None and func.recv_name:
            binds[func.recv_name] = recv
        unknown_group = False
        for i, p in enumerate(func.params):
            arg = args[i] if i < len(args) and not p.variadic else None
            if group_like(self.idx.classify(func.file, p.type)):
                if isinstance(arg, Router) and p.name:
                    binds[p.name] = arg
                else:
                    unknown_group = True
            elif isinstance(arg, Router) and p.name:
                binds[p.name] = arg
        key = id(func)
        if (
            unknown_group
            or key in frame.stack
            or frame.depth >= _MAX_DEPTH
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
