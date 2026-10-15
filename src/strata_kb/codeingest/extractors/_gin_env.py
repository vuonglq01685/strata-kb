"""Environment, frame and call-chain helpers of the Gin interpreter
(`_routes_gin.Play`): scoped variable bindings, the unrolled shape of a call
chain, and the column text of a handler argument."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._go_ast import GoFile, Value, dotted
from strata_kb.codeingest.extractors._routes_jsutil import _text

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = [
    "INLINE",
    "Env",
    "Frame",
    "Seg",
    "handler_text",
    "line_of_seg",
    "scan_assignments",
    "unroll",
]

INLINE = "(inline)"


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
    """Scoped bindings. `kind` is "pkg" for a package's environment (shared,
    read-only while function bodies run) and "func" for a function's own."""

    __slots__ = ("kind", "parent", "vars")

    def __init__(self, parent: Env | None = None, kind: str = "") -> None:
        self.vars: dict[str, Value] = {}
        self.parent = parent
        self.kind = kind

    def get(self, key: str) -> Value | None:
        env: Env | None = self
        while env is not None:
            if key in env.vars:
                return env.vars[key]
            env = env.parent
        return None

    def assign(self, key: str, value: Value) -> None:
        """Rebind `key` in the nearest local scope that has it. A package
        variable is never written from a body: the write shadows it in the
        function's own scope."""
        env: Env | None = self
        local = self
        while env is not None:
            if env.kind == "func":
                local = env
            if env.kind != "pkg" and key in env.vars:
                env.vars[key] = value
                return
            env = env.parent
        local.vars[key] = value


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


def line_of_seg(seg: Seg) -> int:
    field = seg.fn.child_by_field_name("field") if seg.name is not None else None
    return _ts.line_of(field if field is not None else seg.fn)


def handler_text(node: Node) -> str:
    return (dotted(node) or INLINE) if node.type != "identifier" else _text(node)


def scan_assignments(
    body: Node, names: set[str]
) -> tuple[list[tuple[str, Node | None]], set[str]]:
    """Assignments in a function body to any of `names` as (name, right-hand
    expression or None), and the names the body declares itself (`:=`, `var`,
    range variables, closure parameters), which shadow them."""
    assigned: list[tuple[str, Node | None]] = []
    local: set[str] = set()
    stack = [body]
    while stack:
        node = stack.pop()
        kind = node.type
        if kind in ("short_var_declaration", "range_clause"):
            left = node.child_by_field_name("left")
            local |= {_text(c) for c in (left.named_children if left else [])}
        elif kind in ("var_spec", "parameter_declaration"):
            local |= {_text(c) for c in node.children_by_field_name("name")}
        elif kind == "assignment_statement":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            lhs = left.named_children if left is not None else []
            rhs = right.named_children if right is not None else []
            op = node.child_by_field_name("operator")
            plain = op is not None and _text(op) == "="
            for i, target in enumerate(lhs):
                if target.type == "identifier" and _text(target) in names:
                    ok = plain and (len(lhs) == len(rhs) or (i == 0 and len(rhs) == 1))
                    assigned.append(
                        (
                            _text(target),
                            rhs[i if len(lhs) == len(rhs) else 0] if ok else None,
                        )
                    )
        stack.extend(node.named_children)
    return assigned, local
