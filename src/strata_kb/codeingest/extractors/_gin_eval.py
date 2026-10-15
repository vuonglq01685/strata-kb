"""Statement walking and value evaluation for the Gin adapter.

`Evaluator` indexes nothing itself (see `_go_ast.Index`): it runs function
bodies and package-level declarations over scoped environments (`_gin_env`),
binds names to values (routers, constants, packages, types) and evaluates
expressions without side effects. The call semantics (`chain`: what a call
on a router, package, type or unknown value means) live in
`_routes_gin.Play`, which subclasses it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._gin_env import (
    Env,
    Frame,
    Seg,
    line_of_seg,
    scan_assignments,
    unroll,
)
from strata_kb.codeingest.extractors._go_ast import (
    UNKNOWN,
    Func,
    GoFile,
    Index,
    Pkg,
    PkgInfo,
    Router,
    Str,
    Typed,
    Unknown,
    Value,
    dotted,
    group_like,
    params,
)
from strata_kb.codeingest.extractors._routes_jsutil import _text
from strata_kb.codeingest.extractors._routes_model import Route

if TYPE_CHECKING:
    from tree_sitter import Node

VERBS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
HTTP_METHODS = VERBS | {"CONNECT", "TRACE"}
ROUTE_NAMES = VERBS | {"Any"}
MAX_DEPTH = 8
_METHOD_CONSTS = {f"Method{m.title()}": m for m in sorted(HTTP_METHODS)}
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
_METHOD_VALUES = ROUTE_NAMES | {"Handle", "Match", "Group"}
_MAX_KEY = 8  # longest dotted key looked up in the environment
_BUDGET = 5000


class Evaluator:
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
                # a scratch scope: the walk binds names, the package scope is read-only
                self._guard(gofile, decl, lambda g=gofile, d=decl, e=env: self.walk(
                    d, Frame(g, Env(e), 0, frozenset())
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
        env = Env(self.pkg_env(func.file.dir), "func")
        env.vars.update(self.bindings(func, probe))
        env.vars.update(binds)
        body = func.node.child_by_field_name("body")
        if body is not None:
            self.walk(body, Frame(func.file, env, depth, stack))

    def pkg_env(self, directory: str) -> Env:
        """Package-level `const` / `var` bindings of all files of a package,
        resolved to a fixpoint so a later file may define what an earlier one
        uses. A `var` written inside function bodies takes the value all its
        writes agree on, else it is unknown (a site where it is used); a body
        never writes the shared environment."""
        env = self._pkg_env.get(directory)
        if env is not None:
            return env
        env = self._pkg_env[directory] = Env(kind="pkg")
        pkg = self.idx.pkgs.get(directory)
        if pkg is None:
            return env
        for _ in range(len(pkg.decls) + 2):
            before = dict(env.vars)
            for gofile, decl in pkg.decls:
                frame = Frame(gofile, env, 0, frozenset())
                self._guard(
                    gofile,
                    decl,
                    lambda f=frame, d=decl: env.vars.update(self.declared(f, d)),
                )
            self._apply_writes(pkg, env)
            if env.vars == before:
                break
        return env

    def _apply_writes(self, pkg: PkgInfo, env: Env) -> None:
        initialized = {
            n
            for _gofile, decl in pkg.decls
            if decl.type == "var_declaration"
            for n in self.initialized(decl)
        }
        writes = self.package_writes(pkg, env, initialized)
        engines = self.engine_vars(pkg, env)
        for name, values in writes.items():
            same = len(set(values)) == 1 and not isinstance(values[0], Unknown)
            if same:
                env.vars[name] = values[0]
            elif name not in engines:
                env.vars[name] = UNKNOWN
            # else: a var whose static type is *gin.Engine keeps the root
            # prefix whatever is written (Go typing forbids a group there)

    def engine_vars(self, pkg: PkgInfo, env: Env) -> set[str]:
        """Package vars whose static type is `*gin.Engine`: declared so, or
        untyped and initialised from `gin.Default()` / `gin.New()`. An
        interface-typed var (`gin.IRouter`) is not one, whatever it holds."""
        out: set[str] = set()
        for gofile, decl in pkg.decls:
            if decl.type != "var_declaration":
                continue
            frame = Frame(gofile, env, 0, frozenset())
            for spec in self.specs(decl):
                names = [_text(n) for n in spec.children_by_field_name("name")]
                type_node = spec.child_by_field_name("type")
                if type_node is not None:
                    engine = [self.idx.classify(gofile, type_node) == Router("")] * len(
                        names
                    )
                else:
                    value = spec.child_by_field_name("value")
                    exprs = value.named_children if value is not None else []
                    paired = len(exprs) == len(names)
                    engine = [
                        paired and self.value_of(frame, e) == Router("") for e in exprs
                    ] or [False] * len(names)
                out |= {n for n, e in zip(names, engine, strict=True) if e}
        return out

    def initialized(self, decl: Node) -> list[str]:
        out: list[str] = []
        for spec in self.specs(decl):
            if spec.child_by_field_name("value") is not None:
                out += [_text(n) for n in spec.children_by_field_name("name")]
        return out

    def package_writes(
        self, pkg: PkgInfo, env: Env, initialized: set[str]
    ) -> dict[str, list[Value]]:
        """Every value assigned to a package-level `var` from function bodies
        (plus its initializer), by name. A body that declares the same name
        itself assigns its own variable and is not a write."""
        names = {
            _text(n)
            for _gofile, decl in pkg.decls
            if decl.type == "var_declaration"
            for spec in self.specs(decl)
            for n in spec.children_by_field_name("name")
        }
        out: dict[str, list[Value]] = {}
        if not names:
            return out
        funcs = [f for g in (pkg.funcs, pkg.methods) for fs in g.values() for f in fs]
        for func in funcs:
            body = func.node.child_by_field_name("body")
            if body is None:
                continue
            assigned, local = scan_assignments(body, names)
            local |= {p.name for p in func.params if p.name}
            if not assigned:
                continue
            fenv = Env(env, "func")
            fenv.vars.update(self.bindings(func, False))
            frame = Frame(func.file, fenv, 0, frozenset())
            for name, rhs in assigned:
                if name in local:
                    continue
                value = self.value_of(frame, rhs) if rhs is not None else None
                if isinstance(value, Str) or value is None:
                    value = UNKNOWN
                out.setdefault(name, []).append(value)
        for name in out:
            if name in initialized and name in env.vars:
                out[name].append(env.vars[name])
        return out

    @staticmethod
    def specs(decl: Node) -> list[Node]:
        return [
            s
            for c in decl.named_children
            for s in (c.named_children if c.type == "var_spec_list" else [c])
            if s.type in ("var_spec", "const_spec")
        ]

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
        elif kind == "selector_expression":
            self.method_value(frame, node)
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

    def method_value(self, frame: Frame, node: Node) -> None:
        """A verb method taken as a value (`get := r.GET`, `add(r.POST, ...)`)
        hides the registration from this reading: a site. Selectors in call
        position are never visited here."""
        field = node.child_by_field_name("field")
        name = _text(field)
        if field is None or name not in _METHOD_VALUES:
            return
        operand = node.child_by_field_name("operand")
        value = self.value_of(frame, operand) if operand is not None else None
        if isinstance(value, Router) or (
            name in VERBS and (value is None or isinstance(value, Unknown))
        ):
            self.sites.add(f"{frame.file.rel}:{_ts.line_of(field)}")

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
        specs = self.specs(node)
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

    def site(self, frame: Frame, seg: Seg) -> None:
        self.sites.add(f"{frame.file.rel}:{line_of_seg(seg)}")

    def chain(self, frame: Frame, call: Node, emit: bool) -> Value | None:
        raise NotImplementedError  # implemented by `Play`
