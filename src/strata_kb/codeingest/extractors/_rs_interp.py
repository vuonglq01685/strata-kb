"""A small tree-walking evaluator for Rust function bodies, the common base
of the Actix / Axum / Rocket adapters.

It does not run code: it follows how a program *wires* its router. `let`
bindings, assignments, blocks, `if` / `match` / loops (both branches, once),
closures, `return` and tail values are read in order; a method chain
(`a.b(x).c(y)`) is unrolled iteratively and each step is handed to the
framework subclass. In-repo function calls are followed with their arguments
bound to the parameters (depth, cycle and budget guarded).

A value the evaluator cannot prove is `None` (unknown): the subclass decides
what an unknown value means in router position (a site), never "not a
router". Nothing recurses on chain length; nesting of expressions is capped
(`MAX_NEST`) and a `RecursionError` anywhere is a site at the function.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._rs_index import Fn, Index, Mod, Res, scoped_mod
from strata_kb.codeingest.extractors._rs_syntax import (
    attrs_before,
    is_cfg_test,
    line_of,
    segments,
    string_of,
    text,
    walk,
)

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = [
    "Closure",
    "Env",
    "Frame",
    "Interp",
    "Other",
    "Step",
    "Str",
    "Tuple",
    "unroll",
]

MAX_NEST = 48
MAX_CALL_DEPTH = 8
BUDGET = 300_000
_MISSING = object()
_COMMENTS = ("line_comment", "block_comment", "attribute_item", "inner_attribute_item")
_TRANSPARENT = frozenset(
    {
        "parenthesized_expression",
        "reference_expression",
        "type_cast_expression",
        "unary_expression",
    }
)
_LOOPS = frozenset({"for_expression", "while_expression", "loop_expression"})
_STR_PASS = frozenset({"to_string", "to_owned", "into", "as_str"})
_MACRO_LIMIT = 20_000
_TYPE_TAIL = re.compile(r"([A-Za-z_]\w*)\s*(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?\s*$")
# macros whose arguments are data, not code that could build a router
_QUIET_MACROS = frozenset(
    {
        "println", "print", "eprintln", "eprint", "format", "write", "writeln", "panic",
        "todo", "unimplemented", "unreachable", "info", "debug", "warn", "error", "trace",
        "assert", "assert_eq", "assert_ne", "debug_assert", "debug_assert_eq",
        "debug_assert_ne", "format_args", "env", "include_str", "concat", "stringify",
        "json", "matches", "cfg", "line", "file", "vec", "relative", "uri", "table",
    }
)  # fmt: skip


class Env:
    __slots__ = ("parent", "vars")

    def __init__(self, parent: Env | None = None):
        self.vars: dict[str, Any] = {}
        self.parent = parent

    def get(self, name: str) -> Any:
        env: Env | None = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        return _MISSING

    def set(self, name: str, val: Any) -> None:
        self.vars[name] = val

    def assign(self, name: str, val: Any) -> None:
        env: Env | None = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = val
                return
            env = env.parent
        self.vars[name] = val


@dataclass
class Frame:
    mod: Mod
    env: Env
    depth: int = 0
    stack: frozenset[int] = frozenset()
    owner: str | None = None
    rets: list[Any] | None = None

    def child(self) -> Frame:
        return Frame(
            self.mod, Env(self.env), self.depth, self.stack, self.owner, self.rets
        )


@dataclass
class Closure:
    node: Node
    frame: Frame


class Other:
    """A value of a type declared in this package (or built by an in-repo
    function returning one): provably not a framework router, so a routing
    word called on it is ordinary code."""


@dataclass
class Str:
    value: str


@dataclass
class Tuple:
    items: list[Any]


@dataclass
class Step:
    name: str  # method name, or "" for a field access
    args: Node | None  # `arguments` node of a method call
    node: Node
    field: bool = False
    line: int = 0  # line of the method name (not of the chain's first token)


def unroll(node: Node) -> tuple[Node, list[Step]]:
    """Peel a method chain: (base expression, steps in call order)."""
    steps: list[Step] = []
    cur = node
    while True:
        kind = cur.type
        if kind == "call_expression":
            fn = cur.child_by_field_name("function")
            if fn is not None and fn.type == "generic_function":
                fn = fn.child_by_field_name("function")
            if fn is not None and fn.type == "field_expression":
                tag = fn.child_by_field_name("field")
                steps.append(
                    Step(
                        text(tag),
                        cur.child_by_field_name("arguments"),
                        cur,
                        False,
                        line_of(tag or cur),
                    )
                )
                value = fn.child_by_field_name("value")
                if value is None:
                    break
                cur = value
                continue
            break
        if kind in ("await_expression", "try_expression", "parenthesized_expression"):
            inner = next(iter(cur.named_children), None)
            if inner is None:
                break
            cur = inner
            continue
        if kind == "field_expression":
            steps.append(
                Step(
                    text(cur.child_by_field_name("field")),
                    None,
                    cur,
                    True,
                    line_of(cur),
                )
            )
            value = cur.child_by_field_name("value")
            if value is None:
                break
            cur = value
            continue
        break
    steps.reverse()
    return cur, steps


def args_of(call: Node | None) -> list[Node]:
    args = call.child_by_field_name("arguments") if call is not None else None
    if args is None:
        args = call
    return [
        c
        for c in (args.named_children if args is not None else [])
        if c.type not in _COMMENTS
    ]


class Interp:
    """Subclass hooks: `ext_call`, `step`, `macro`, `follow`, `merge`,
    `bind_param`, `path_value`."""

    def __init__(self, idx: Index):
        self.idx = idx
        self.sites: set[str] = set()
        self.reached: set[int] = set()
        self.budget = BUDGET
        self.nesting = 0
        self.local_fns: dict[tuple[str, int], Fn] = {}  # fns declared inside bodies

    # -- sites -----------------------------------------------------------

    def site(self, frame: Frame, node: Node) -> None:
        self.sites.add(f"{frame.mod.file}:{line_of(node)}")

    def site_at(self, frame: Frame, line: int) -> None:
        self.sites.add(f"{frame.mod.file}:{line}")

    # -- hooks -----------------------------------------------------------

    def ext_call(self, frame: Frame, segs: tuple[str, ...], call: Node) -> Any:
        """A call whose path resolved outside the package (or not at all
        for a bare name). Return a value, or `_MISSING`-like None."""
        self.eval_args(frame, call)
        return None

    def step(self, frame: Frame, val: Any, step: Step) -> Any:
        self.eval_args(frame, step.node)
        return None

    def macro(self, frame: Frame, node: Node) -> Any:
        self.macro_args(frame, node)
        return None

    def macro_args(self, frame: Frame, node: Node) -> None:
        """Evaluate the arguments of `join!(serve(a()), serve(b()))`-style
        macros: their token tree is re-parsed as an expression list (lines
        kept by padding) and each element evaluated. A body that does not
        parse as one (`select! { x = f => .. }`) is left alone."""
        name = (segments(node.child_by_field_name("macro")) or ("",))[-1]
        if (
            self.idx.macros.get(name) or name == "include"
        ):  # expands to code we do not read
            self.site(frame, node)
        tree = next((c for c in node.named_children if c.type == "token_tree"), None)
        if tree is None or name in _QUIET_MACROS:
            return
        inner = text(tree)[1:-1].rstrip().removesuffix(",")
        if "(" not in inner or len(inner) > _MACRO_LIMIT:
            return
        row = tree.start_point[0]
        parsed = _ts.parse(
            "rust", ("\n" * row + f"fn _(){{let _=({inner},);}}").encode()
        )
        if parsed.root_node.has_error:
            return
        tuple_ = next(
            (n for n in walk(parsed.root_node) if n.type == "tuple_expression"), None
        )
        for part in tuple_.named_children if tuple_ is not None else []:
            self.eval(frame, part)

    def on_let(self, frame: Frame, node: Node, val: Any) -> Any:
        return val

    def follow(self, fn: Fn, args: list[Any]) -> bool:
        return False

    def merge(self, vals: list[Any]) -> Any:
        return vals[0]

    def bind_param(self, fn: Fn, name: str, type_text: str, arg: Any) -> Any:
        return arg

    def path_value(self, frame: Frame, node: Node) -> Any:
        """A path used as a value: an in-repo function (or None)."""
        segs = segments(node)
        res = self.resolve(frame, segs) if segs else None
        if res is not None and res.kind == "type":
            return Other()  # a unit struct value
        return res.fn if res is not None and res.kind == "fn" else None

    # -- running ---------------------------------------------------------

    def run_fn(self, fn: Fn, args: list[Any], frame: Frame | None) -> Any:
        """Evaluate `fn`'s body with `args` bound to its parameters."""
        depth = frame.depth + 1 if frame is not None else 0
        stack = (frame.stack if frame is not None else frozenset()) | {id(fn)}
        body = fn.body
        self.reached.add(id(fn))
        if body is None:
            return None
        env = Env()
        for i, (name, type_text) in enumerate(fn.params):
            arg = args[i] if i < len(args) else None
            if name:
                env.set(name, self.bind_param(fn, name, type_text, arg))
        if frame is None:
            self.budget = BUDGET  # per root function
        sub = Frame(fn.mod, env, depth, stack, fn.owner, [])
        try:
            tail = self.block(sub, body)
        except RecursionError:  # also the budget: both end this function's run
            self.sites.add(f"{fn.file}:{fn.line}")
            return None
        vals = [v for v in [*(sub.rets or []), tail] if v is not None]
        return self.join(vals)

    def join(self, vals: list[Any]) -> Any:
        if not vals:
            return None
        return vals[0] if len(vals) == 1 else self.merge(vals)

    def run_closure(self, closure: Closure, args: list[Any]) -> Any:
        node = closure.node
        frame = closure.frame.child()
        params = node.child_by_field_name("parameters")
        for i, param in enumerate(params.named_children if params is not None else []):
            pat = (
                param.child_by_field_name("pattern")
                if param.type == "parameter"
                else param
            )
            if pat is not None:
                self.bind(frame.env, pat, args[i] if i < len(args) else None)
        body = node.child_by_field_name("body")
        frame.rets = []
        val = self.eval(frame, body) if body is not None else None
        return self.join([v for v in [*frame.rets, val] if v is not None])

    # -- statements ------------------------------------------------------

    def block(self, frame: Frame, node: Node) -> Any:
        frame = frame.child()
        pairs = list(attrs_before(node))
        kids = [item for _attrs, item in pairs]
        for attrs, kid in pairs:
            if kid.type == "function_item" and not is_cfg_test(attrs):
                key = (frame.mod.file, kid.start_byte)
                fn = self.local_fns.get(key)
                if fn is None:
                    fn = Fn(frame.mod, kid, attrs, None)
                    self.local_fns[key] = fn
                frame.env.set(fn.name, fn)
        tail: Any = None
        for kid in kids:
            if kid.type == "use_declaration":
                frame.mod = scoped_mod(frame.mod, kid)
        for i, kid in enumerate(kids):
            kind = kid.type
            if kind == "let_declaration":
                self.let(frame, kid)
            elif kind == "expression_statement":
                inner = next(iter(kid.named_children), None)
                if inner is not None:
                    self.eval(frame, inner)
            elif kind in (
                "function_item",
                "empty_statement",
                "use_declaration",
                "const_item",
                "static_item",
                "struct_item",
                "enum_item",
                "impl_item",
                "trait_item",
                "mod_item",
                "type_item",
                "macro_definition",
            ):
                continue
            elif i == len(kids) - 1:
                tail = self.eval(frame, kid)
            else:
                self.eval(frame, kid)
        return tail

    def let(self, frame: Frame, node: Node) -> None:
        pat = node.child_by_field_name("pattern")
        value = node.child_by_field_name("value")
        val = self.eval(frame, value) if value is not None else None
        val = self.on_let(frame, node, val)
        mutable = any(c.type == "mutable_specifier" for c in node.children)
        if (
            not mutable
            and val is None
            and value is not None
            and pat is not None
            and pat.type == "identifier"
        ):
            lit = self.string_of(frame, value)
            if lit is not None:
                val = Str(lit)
        if pat is not None:
            self.bind(frame.env, pat, val, value)
        other = node.child_by_field_name("alternative")
        if other is not None:
            self.eval(frame.child(), other)

    def bind(
        self, env: Env, pat: Node, val: Any, value_node: Node | None = None
    ) -> None:
        if pat.type == "identifier":
            env.set(text(pat), val)
            return
        if pat.type == "tuple_pattern" and isinstance(val, Tuple):
            parts = [c for c in pat.named_children if c.type not in _COMMENTS]
            if len(parts) == len(val.items):
                for part, item in zip(parts, val.items, strict=True):
                    self.bind(env, part, item)
                return
        for sub in walk(pat):
            if sub.type == "identifier":
                env.set(text(sub), None)

    # -- expressions -----------------------------------------------------

    def eval(self, frame: Frame, node: Node) -> Any:
        self.budget -= 1
        if self.budget < 0:
            raise RecursionError("evaluation budget")
        if self.nesting >= MAX_NEST:
            self.site(frame, node)
            return None
        self.nesting += 1
        try:
            return self._eval(frame, node)
        finally:
            self.nesting -= 1

    def _eval(self, frame: Frame, node: Node) -> Any:
        kind = node.type
        if kind in (
            "call_expression",
            "field_expression",
            "await_expression",
            "try_expression",
        ):
            return self.chain(frame, node)
        if kind == "identifier":
            val = frame.env.get(text(node))
            if val is _MISSING:
                return self.path_value(frame, node)
            return val
        if kind in _TRANSPARENT:
            inner = next(iter(node.named_children), None)
            return self.eval(frame, inner) if inner is not None else None
        if kind in ("block", "unsafe_block", "async_block", "const_block"):
            return self.eval_block(frame, node)
        if kind == "if_expression":
            return self.if_expr(frame, node)
        if kind == "match_expression":
            return self.match_expr(frame, node)
        if kind in _LOOPS:
            return self.loop(frame, node)
        if kind == "closure_expression":
            return Closure(node, frame)
        if kind == "assignment_expression":
            return self.assign(frame, node)
        if kind == "return_expression":
            inner = next(iter(node.named_children), None)
            val = self.eval(frame, inner) if inner is not None else None
            if frame.rets is not None:
                frame.rets.append(val)
            return None
        if kind == "macro_invocation":
            return self.macro(frame, node)
        if kind == "tuple_expression":
            return Tuple(
                [
                    self.eval(frame, c)
                    for c in node.named_children
                    if c.type not in _COMMENTS
                ]
            )
        if kind in ("scoped_identifier", "generic_function"):
            return self.path_value(frame, node)
        if kind in ("string_literal", "raw_string_literal"):
            lit = string_of(node)
            return Str(lit) if lit is not None else None
        if kind in (
            "integer_literal",
            "boolean_literal",
            "float_literal",
            "char_literal",
        ):
            return None
        for kid in node.named_children:
            if kid.type not in _COMMENTS:
                self.eval(frame, kid)
        return None

    def eval_block(self, frame: Frame, node: Node) -> Any:
        if node.type == "block":
            return self.block(frame, node)
        inner = next((c for c in node.named_children if c.type == "block"), None)
        return self.block(frame, inner) if inner is not None else None

    def if_expr(self, frame: Frame, node: Node) -> Any:
        cond = node.child_by_field_name("condition")
        sub = frame.child()
        if cond is not None:
            if cond.type == "let_condition":
                value = cond.child_by_field_name("value")
                val = self.eval(sub, value) if value is not None else None
                pat = cond.child_by_field_name("pattern")
                if pat is not None:
                    self.bind(sub.env, pat, val)
            else:
                self.eval(sub, cond)
        vals = []
        then = node.child_by_field_name("consequence")
        if then is not None:
            vals.append(self.eval(sub, then))
        other = node.child_by_field_name("alternative")
        if other is not None:
            inner = next(iter(other.named_children), None)
            if inner is not None:
                vals.append(self.eval(frame, inner))
        return self.join([v for v in vals if v is not None])

    def match_expr(self, frame: Frame, node: Node) -> Any:
        value = node.child_by_field_name("value")
        scrut = self.eval(frame, value) if value is not None else None
        body = node.child_by_field_name("body")
        vals = []
        for arm in body.named_children if body is not None else []:
            if arm.type != "match_arm":
                continue
            sub = frame.child()
            pat = arm.child_by_field_name("pattern")
            if pat is not None:
                self.bind(sub.env, pat, scrut)
            expr = arm.child_by_field_name("value")
            if expr is not None:
                vals.append(self.eval(sub, expr))
        return self.join([v for v in vals if v is not None])

    def loop(self, frame: Frame, node: Node) -> Any:
        sub = frame.child()
        value = node.child_by_field_name("value") or node.child_by_field_name(
            "condition"
        )
        if value is not None:
            self.eval(sub, value)
        pat = node.child_by_field_name("pattern")
        if pat is not None:
            self.bind(sub.env, pat, None)
        body = node.child_by_field_name("body")
        if body is not None:
            self.eval(sub, body)
        return None

    def assign(self, frame: Frame, node: Node) -> Any:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        val = self.eval(frame, right) if right is not None else None
        if left is not None and left.type == "identifier":
            frame.env.assign(text(left), val)
        return None

    # -- chains and calls -------------------------------------------------

    def chain(self, frame: Frame, node: Node) -> Any:
        base, steps = unroll(node)
        if base.type == "call_expression":
            val = self.call_path(frame, base)
        else:
            val = self.eval(frame, base)
        for step in steps:
            val = self.step(frame, val, step) if not step.field else None
        return val

    def eval_args(self, frame: Frame, call: Node | None) -> list[Any]:
        """Evaluate every argument; closures among them are run (unbound
        parameters), so a router built inside `HttpServer::new(|| ..)` or
        `spawn(async move { .. })` is found."""
        vals = [self.eval(frame, a) for a in args_of(call)]
        for val in vals:
            if isinstance(val, Closure) and self.should_run(val):
                self.run_closure(val, [])
        return vals

    def should_run(self, closure: Closure) -> bool:
        return True

    def call_path(self, frame: Frame, call: Node) -> Any:
        fn_node = call.child_by_field_name("function")
        if fn_node is None:
            return None
        if fn_node.type == "identifier":
            held = frame.env.get(text(fn_node))
            if isinstance(held, Fn):
                return self.call_fn(frame, held, call)
            if isinstance(held, Closure):
                return self.run_closure(held, self.eval_args(frame, call))
            if held is not _MISSING:
                self.eval_args(frame, call)
                return None
        segs = segments(fn_node)
        if segs is None:
            self.eval(frame, fn_node)
            self.eval_args(frame, call)
            return None
        res = self.resolve(frame, segs)
        if res is None:
            return self.ext_call(frame, segs, call)
        if res.kind == "fn" and res.fn is not None:
            return self.call_fn(frame, res.fn, call)
        if res.kind == "ext":
            return self.ext_call(frame, res.segs, call)
        if (
            res.kind == "amb"
        ):  # two candidates: a site only when either would be followed
            args = self.eval_args(frame, call)
            if any(self.follow(alt, args) for alt in res.alts):
                self.site(frame, call)
            return None
        return self.unknown_call(frame, call)

    def unknown_call(self, frame: Frame, call: Node) -> Any:
        self.eval_args(frame, call)
        return None

    def resolve(self, frame: Frame, segs: tuple[str, ...]) -> Res | None:
        if len(segs) == 1:
            held = frame.env.get(segs[0])
            if isinstance(held, Fn):  # a function declared in this body
                return Res("fn", fn=held)
        if segs[0] == "Self" and frame.owner is not None and len(segs) == 2:
            return self.idx.method(frame.owner, segs[1])
        return self.idx.resolve(frame.mod, segs)

    def call_fn(self, frame: Frame, fn: Fn, call: Node) -> Any:
        args = self.eval_args(frame, call)
        if fn.has_self:  # `Type::method(&value, x)`: the first argument is `self`
            args = args[1:]
        return self.apply_fn(frame, fn, args, call)

    def typed_value(self, mod: Mod, owner: str | None, type_text: str) -> Any:
        """`Other` when `type_text` names a type declared in the package."""
        name = type_text.replace("&", " ").replace("mut ", " ").strip()
        if name == "Self" and owner:
            return Other()
        match = _TYPE_TAIL.search(name)
        res = self.idx.resolve(mod, (match.group(1),)) if match else None
        return Other() if res is not None and res.kind == "type" else None

    def apply_fn(self, frame: Frame, fn: Fn, args: list[Any], at: Node) -> Any:
        if not self.follow(fn, args):
            return self.typed_value(fn.mod, fn.owner, fn.ret)
        if id(fn) in frame.stack or frame.depth >= MAX_CALL_DEPTH:
            self.site(frame, at)
            return None
        return self.run_fn(fn, args, frame)

    # -- literals ---------------------------------------------------------

    def string_of(self, frame: Frame, node: Node | None, hops: int = 0) -> str | None:
        """A path / prefix string: a literal, an immutable `let` of one, or a
        `const` of the package. Anything computed is None."""
        while node is not None and hops < 8:
            hops += 1
            kind = node.type
            if kind in ("string_literal", "raw_string_literal"):
                return string_of(node)
            if kind in _TRANSPARENT:
                node = next(iter(node.named_children), None)
            elif kind == "identifier":
                held = frame.env.get(text(node))
                if isinstance(held, Str):
                    return held.value
                if held is not _MISSING:
                    return None
                res = self.idx.resolve(frame.mod, (text(node),))
                return res.value if res is not None and res.kind == "const" else None
            elif kind == "scoped_identifier":
                segs = segments(node)
                res = self.resolve(frame, segs) if segs else None
                return res.value if res is not None and res.kind == "const" else None
            elif kind == "call_expression":
                node = self._str_wrapped(node)
            else:
                return None
        return None

    @staticmethod
    def _str_wrapped(call: Node) -> Node | None:
        """`"x".to_string()` / `String::from("x")` -> the literal."""
        fn = call.child_by_field_name("function")
        if fn is not None and fn.type == "field_expression":
            if text(fn.child_by_field_name("field")) in _STR_PASS:
                return fn.child_by_field_name("value")
            return None
        if fn is not None and segments(fn) == ("String", "from"):
            args = args_of(call)
            return args[0] if len(args) == 1 else None
        return None
