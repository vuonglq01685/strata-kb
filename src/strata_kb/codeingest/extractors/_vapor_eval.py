"""Evaluator core of the Vapor route adapter: scopes, bindings, statements
and call chains. `_routes_swift.Vapor` adds what a call means (routers,
groups, collections, helpers); this base class walks the syntax, keeps the
lexical environment and knows which names it must not trust."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import _lit, _text
from strata_kb.codeingest.extractors._routes_model import Route
from strata_kb.codeingest.extractors._swift_ast import (
    COMMENTS,
    Call,
    first_of,
    kids,
    pattern_names,
    type_name,
)
from strata_kb.codeingest.extractors._vapor_index import Fn, Index
from strata_kb.codeingest.extractors._vapor_shape import (
    is_middleware,
    pattern_names_of,
)
from strata_kb.codeingest.extractors._vapor_values import (
    KNOWN_SUPERTYPES,
    LITERALS,
    MADE,
    MIDDLEWARE_PROTOCOLS,
    MW,
    PLAIN_TYPES,
    ROUTER_TYPES,
    SELF,
    STRINGS,
    TRANSPARENT,
    Env,
    Frame,
    Items,
    Plain,
    Router,
    Step,
    Text,
    TypeRef,
    Value,
    line,
    unroll,
    unsafe_names,
    where,
)

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["BUDGET", "Evaluator"]

KNOWN = KNOWN_SUPERTYPES | MIDDLEWARE_PROTOCOLS
BUDGET = 5000  # follow steps one entry point may spend


class Evaluator:
    def __init__(self, idx: Index):
        self.idx = idx
        self.routes: set[Route] = set()
        self.sites: set[str] = set()
        self.registered: set[str] = set()
        self.reached: set[int] = set()
        self.budget = BUDGET
        self._unsafe: dict[int, frozenset[str]] = {}

    def unsafe_of(self, node: Node) -> frozenset[str]:
        if node.id not in self._unsafe:
            self._unsafe[node.id] = frozenset(unsafe_names(node))
        return self._unsafe[node.id]

    def guarded(self, file: str, node: Node, action) -> None:
        try:
            action()
        except RecursionError:
            self.sites.add(f"{file}:{line(node)}")

    def run_top(self, rel: str) -> None:
        nodes = self.idx.top_level[rel]
        unsafe = frozenset().union(*(self.unsafe_of(n) for n in nodes))
        frame = Frame(rel, "", Env(), unsafe, 0, frozenset())
        for node in nodes:
            self.budget = BUDGET
            self.guarded(rel, node, lambda n=node: self.eval(n, frame))

    def run_member(self, rel: str, owner: str, node: Node) -> None:
        frame = Frame(rel, owner, Env(), self.unsafe_of(node), 0, frozenset())
        self.budget = BUDGET
        self.guarded(rel, node, lambda: self.eval(node, frame))

    def run_fn(
        self,
        fn: Fn,
        binds: dict[str, Value],
        depth: int,
        stack: frozenset[int],
        owner: str,
        outer: Frame | None = None,
        me: Router | None = None,
    ) -> None:
        body = fn.body
        if body is None:
            return
        unsafe = self.unsafe_of(fn.node) | (outer.unsafe if outer else frozenset())
        bounds = fn.bounds()
        env = Env(outer.env if outer else None)
        for param in fn.params():
            if param.internal in binds:
                value = binds[param.internal]
            else:
                kind = type_name(param.type_node)
                value = self.of_type(bounds.get(kind, kind), None)
            env.vars[param.internal] = None if param.internal in unsafe else value
        me = me or self.router_self(owner)
        frame = Frame(fn.file, owner, env, unsafe, depth, stack, me)
        self.guarded(fn.file, fn.node, lambda: self.eval(body, frame))

    def router_self(self, owner: str) -> Router | None:
        """`self` of a method declared in an extension of Vapor's own router
        types (`extension Application { .. }`)."""
        if owner not in ROUTER_TYPES or self.idx.has_type(owner):
            return None
        return Router("") if owner == "Application" else Router(None)

    def of_type(self, name: str, router: Router | None) -> Value:
        """What a value declared with type `name` is."""
        name = self.idx.resolve_alias(name)
        if not name:
            return None
        if self.idx.has_type(name):
            # a supertype outside the repo may be a router builder: unknown
            if self.idx.conforms(name, "RoutesBuilder") or self.idx.has_unknown_super(
                name, KNOWN
            ):
                return None
            return Plain(name)
        if name in ROUTER_TYPES:
            if router is not None:
                return router
            return Router("") if name == "Application" else Router(None)
        return Plain(name) if name in PLAIN_TYPES else None

    def ident(self, node: Node, frame: Frame) -> Value:
        name = _text(node)
        if name == "Self":
            return SELF
        if name in frame.unsafe:
            return None
        found, value = frame.env.lookup(name)
        if found:
            return value
        if name[:1].isupper():
            return TypeRef(name)
        if frame.self_type:
            return self.of_type(self.idx.prop_type(frame.self_type, name), None)
        return None

    # -- statements and expressions ------------------------------------------

    def eval(self, node: Node, frame: Frame) -> Value:
        kind = node.type
        if kind in COMMENTS:
            return None
        if kind in ("call_expression", "navigation_expression"):
            return self.chain(node, frame)
        if kind in TRANSPARENT or kind == "postfix_expression":
            inner = node.child_by_field_name("expr") or node.child_by_field_name(
                "target"
            )
            return self.eval(inner, frame) if inner is not None else None
        if kind == "simple_identifier":
            return self.ident(node, frame)
        if kind == "self_expression":
            return frame.me or SELF
        if kind in STRINGS:
            text = _lit(node)
            for child in kids(node):
                if child.type == "interpolated_expression":
                    self.eval(child, frame)
            return Text(text) if text is not None else None
        if kind in LITERALS:
            return None
        if kind == "array_literal":
            return Items(tuple(self.eval(c, frame) for c in kids(node)))
        if kind == "lambda_literal":
            self.closure(node, frame, None)
            return None
        if kind == "as_expression":
            parts = kids(node)
            return self.eval(parts[0], frame) if parts else None
        if kind == "prefix_expression" and _text(node).startswith("."):
            return None  # implicit member: `.GET`, `.anything`
        self.statement(node, frame)
        return None

    def statement(self, node: Node, frame: Frame) -> None:
        """Statements and declarations; any other node just visits its children."""
        kind = node.type
        if kind == "statements":
            inner = replace(frame, env=Env(frame.env))
            for child in kids(node):
                # one statement nested past the stack limit must not take the
                # statements after it down
                self.guarded(frame.file, child, lambda c=child: self.eval(c, inner))
        elif kind == "property_declaration":
            self.bind_property(node, frame)
        elif kind == "assignment":
            result = node.child_by_field_name("result")
            if result is not None:
                self.eval(result, frame)
        elif kind == "for_statement":
            self.for_loop(node, frame)
        elif kind == "function_declaration":
            word = first_of(node, "simple_identifier")
            local = Fn(node, frame.file, frame.self_type, _text(word) if word else "")
            self.run_fn(local, {}, frame.depth, frame.stack, frame.self_type, frame)
        else:
            for child in kids(node):
                self.eval(child, frame)

    def bind_property(self, node: Node, frame: Frame) -> None:
        names = pattern_names(node)
        values = node.children_by_field_name("value")
        results = [self.eval(v, frame) for v in values]
        for child in kids(node):
            if child.type == "computed_property":
                self.eval(child, frame)
        value: Value = None
        if len(names) == 1 and len(values) == 1:
            value = results[0]
            annotation = next(
                (c for c in kids(node) if c.type == "type_annotation"), None
            )
            declared = (
                type_name(annotation.child_by_field_name("name")) if annotation else ""
            )
            if value is None and declared:
                value = self.of_type(declared, None)
            if value is None and values[0].type in (
                "call_expression",
                "navigation_expression",
            ):
                value = MW if is_middleware(self.idx, frame, values[0]) else MADE
            binder = next(
                (c for c in kids(node) if c.type == "value_binding_pattern"), None
            )
            if isinstance(value, Text | Items) and (
                binder is None or _text(binder) != "let"
            ):
                value = None
        for name in names:
            frame.env.bind(name, None if name in frame.unsafe else value)

    def for_loop(self, node: Node, frame: Frame) -> None:
        collection = node.child_by_field_name("collection")
        body = next((c for c in kids(node) if c.type == "statements"), None)
        items = self.eval(collection, frame) if collection is not None else None
        pattern = node.child_by_field_name("item")
        names = pattern_names_of(pattern)
        if body is None:
            return
        if (
            isinstance(items, Items)
            and len(names) == 1
            and 0 < len(items.values) <= 200
        ):
            for value in items.values:
                env = Env(frame.env)
                env.vars[names[0]] = None if names[0] in frame.unsafe else value
                self.eval(body, replace(frame, env=env))
            return
        env = Env(frame.env)
        for name in names:
            env.vars[name] = None
        self.eval(body, replace(frame, env=env))

    def closure(self, lam: Node, frame: Frame, values: list[Value] | Value) -> None:
        env = Env(frame.env)
        header = first_of(lam, "lambda_function_type")
        params: list[str] = []
        for group in kids(header) if header is not None else []:
            if group.type != "lambda_function_type_parameters":
                continue
            for param in kids(group):
                words = [c for c in kids(param) if c.type == "simple_identifier"]
                if words:
                    params.append(_text(words[-1]))
        names = params or ["$0", "$1", "$2"]
        given = values if isinstance(values, list) else [values] * len(names)
        for i, name in enumerate(names):
            env.vars[name] = given[i] if i < len(given) else None
        body = first_of(lam, "statements")
        if body is not None:
            self.eval(body, replace(frame, env=env))

    # -- calls ----------------------------------------------------------------

    def site(self, frame: Frame, node: Node) -> None:
        self.sites.add(f"{frame.file}:{where(node)}")

    def eval_args(self, frame: Frame, call: Call) -> list[Value]:
        return [
            None if a.value.type == "lambda_literal" else self.eval(a.value, frame)
            for a in call.args
        ]

    def rest(self, frame: Frame, call: Call, skip: Node | None = None) -> None:
        """Visit the closures of a call that nothing else consumed."""
        for arg in [
            *call.trailing,
            *(a for a in call.args if a.value.type == "lambda_literal"),
        ]:
            if skip is None or arg.value.id != skip.id:
                self.closure(arg.value, frame, None)

    def chain(self, node: Node, frame: Frame) -> Value:
        base, steps = unroll(node)
        index = 0
        if base.type == "simple_identifier" and steps and steps[0].kind == "c":
            value = self.free_call(frame, base, steps[0], steps[0].call)
            index = 1
        else:
            value = self.eval(base, frame)
        while index < len(steps):
            step = steps[index]
            nxt = steps[index + 1] if index + 1 < len(steps) else None
            if step.kind == "m" and nxt is not None and nxt.kind == "c":
                value = self.method_call(frame, value, step, nxt.call)
                index += 2
            elif step.kind == "m":
                value = self.member(frame, value, step)
                index += 1
            else:
                self.eval_args(frame, step.call)
                self.rest(frame, step.call)
                value = None
                index += 1
        return value

    # -- what a call means: `_routes_swift.Vapor` ------------------------------

    def member(self, frame: Frame, base: Value, step: Step) -> Value:
        raise NotImplementedError

    def free_call(self, frame: Frame, base: Node, step: Step, call: Call) -> Value:
        raise NotImplementedError

    def method_call(self, frame: Frame, recv: Value, step: Step, call: Call) -> Value:
        raise NotImplementedError
