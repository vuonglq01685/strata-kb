"""Syntax-only judgements of the Vapor route adapter: is an unresolved call
shaped like a routing call, is an argument path-like, what do a pattern's
names bind. No evaluation state."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import _lit, _text
from strata_kb.codeingest.extractors._swift_ast import Arg, Call, kids
from strata_kb.codeingest.extractors._vapor_index import Index
from strata_kb.codeingest.extractors._vapor_values import (
    HANDLER,
    LITERALS,
    MADE,
    METHOD,
    STRINGS,
    VERBS,
    Frame,
    Items,
    Plain,
    Text,
    unroll,
)

if TYPE_CHECKING:
    from tree_sitter import Node


def route_shaped(name: str, call: Call) -> bool:
    """A call on a receiver nothing is known about that looks like Vapor's
    routing API: a handler (`use:` or a closure) and path-like arguments."""
    args = call.args
    handler = bool(call.trailing) or any(
        a.label in ("use", "onUpgrade") or a.value.type == "lambda_literal"
        for a in args
    )
    plain = [a for a in args if a.label is None and a.value.type != "lambda_literal"]
    if name in VERBS:
        return (
            handler
            and all(a.label in (None, "use", "body") for a in args)
            and not any(not_a_path(a.value) for a in plain)
        )
    if name == "on":
        return (
            handler
            and bool(plain)
            and bool(METHOD.match("".join(_text(plain[0].value).split())))
        )
    if name == "webSocket":
        return handler
    if name in ("group", "grouped"):
        closure = bool(call.trailing) or any(a.label == "configure" for a in args)
        return any(pathy(a.value) for a in plain) and (name == "grouped" or closure)
    if name == "register":
        return any(a.label == "collection" for a in args)
    return False


def not_a_path(node: Node) -> bool:
    if node.type in LITERALS or node.type == "tuple_expression":
        return True
    return node.type == "navigation_expression" and "".join(
        _text(node).split()
    ).endswith(".self")


def pathy(node: Node) -> bool:
    if node.type in STRINGS | {"array_literal", "simple_identifier"}:
        return True
    if node.type == "call_expression":
        head = "".join(_text(kids(node)[0]).split())
        return head.endswith((".constant", ".parameter"))
    return "".join(_text(node).split()) in (".anything", ".catchall")


def pattern_names_of(pattern: Node | None) -> list[str]:
    names: list[str] = []
    stack = [pattern] if pattern is not None else []
    while stack:
        node = stack.pop()
        if node.type == "simple_identifier":
            names.append(_text(node))
        else:
            stack.extend(reversed(kids(node)))
    return names


_CONSTRUCTORS = {"constant": False, "parameter": True}  # name -> is a parameter


def path_constructor(node: Node) -> list[str] | None:
    """Segment of `.constant("x")`, `.parameter("id")` and the spelled-out
    `PathComponent.constant("x")`; None for any other call."""
    base, steps = unroll(node)
    head = "".join(_text(base).split())
    if base.type == "prefix_expression" and len(steps) == 1 and steps[0].kind == "c":
        word, call = head.removeprefix("."), steps[0].call
    elif head == "PathComponent" and [s.kind for s in steps] == ["m", "c"]:
        word, call = steps[0].name, steps[1].call
    else:
        return None
    if word not in _CONSTRUCTORS or len(call.args) != 1 or call.args[0].label:
        return None
    text = _lit(call.args[0].value)
    if text is None:
        return None
    return [":" + text] if _CONSTRUCTORS[word] else [text]


def path_or_middleware(frame: Frame, arg: Arg) -> tuple[str, list[str]]:
    node = arg.value
    if arg.label is not None:
        return "unknown", []
    segs = segments(frame, node)
    if segs is not None:
        return "path", segs
    if node.type == "call_expression":
        return "mw", []
    if node.type == "array_literal":
        parts = kids(node)
        if all(p.type == "call_expression" for p in parts):
            return "mw", []
    if node.type == "simple_identifier":
        found, value = frame.env.lookup(_text(node))
        if (
            found
            and _text(node) not in frame.unsafe
            and (value is MADE or isinstance(value, Plain))
        ):
            return "mw", []
    return "unknown", []


def segments(frame: Frame, node: Node) -> list[str] | None:
    """Path segments one argument contributes, or None when not literal."""
    kind = node.type
    if kind in STRINGS:
        text = _lit(node)
        return None if text is None else [text]
    if kind == "array_literal":
        out: list[str] = []
        for part in kids(node):
            more = segments(frame, part)
            if more is None:
                return None
            out += more
        return out
    spelled = "".join(_text(node).split())
    if kind == "simple_identifier":
        found, value = frame.env.lookup(spelled)
        if not found or spelled in frame.unsafe:
            return None
        if isinstance(value, Text):
            return [value.value]
        if isinstance(value, Items) and all(isinstance(v, Text) for v in value.values):
            return [v.value for v in value.values]
        return None
    if kind in ("prefix_expression", "navigation_expression"):
        return {".anything": ["*"], ".catchall": ["**"]}.get(
            spelled.removeprefix("PathComponent")
        )
    if kind == "call_expression":
        return path_constructor(node)
    return None


def handler_text(idx: Index, frame: Frame, node: Node) -> str:
    """The Handler column: `Type.method` / a dotted name, else `(inline)`."""
    if node.type not in (
        "navigation_expression",
        "simple_identifier",
        "call_expression",
    ):
        return "(inline)"
    spelled = "".join(_text(node).split())
    # `self.index(_:)` names a method with its argument labels
    spelled = re.sub(r"\((?:[A-Za-z_]\w*:)+\)$", "", spelled)
    for lead in ("self.", "Self."):
        if spelled.startswith(lead):
            spelled = (frame.self_type + "." if frame.self_type else "?.") + spelled[
                len(lead) :
            ]
    if (
        node.type == "simple_identifier"
        and frame.self_type
        and idx.find_methods(frame.self_type, spelled)
    ):
        spelled = f"{frame.self_type}.{spelled}"
    return spelled if HANDLER.match(spelled) and "?." not in spelled else "(inline)"
