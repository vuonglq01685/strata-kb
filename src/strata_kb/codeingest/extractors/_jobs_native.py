"""Go (robfig/cron `AddFunc` / `AddJob`) and Rust (tokio-cron-scheduler
`Job::new*`) scanners for `jobs.py`."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._jobs_model import (
    ANONYMOUS,
    DYNAMIC,
    Ctx,
    Scanner,
    cron_text,
    num,
)
from strata_kb.codeingest.extractors._routes_jsutil import _text, _walk

if TYPE_CHECKING:
    from tree_sitter import Node


def _named(node: Node | None) -> list[Node]:
    return [c for c in (node.named_children if node else []) if c.type != "comment"]


def _go_name(node: Node) -> str:
    if node.type == "identifier":
        return _text(node)
    if node.type == "selector_expression":
        return _text(node.child_by_field_name("field"))
    if node.type == "func_literal":
        return ANONYMOUS
    if node.type == "unary_expression":
        inner = node.child_by_field_name("operand")
        return _go_name(inner) if inner is not None else DYNAMIC
    if node.type == "composite_literal":
        return _text(node.child_by_field_name("type")).rsplit(".", 1)[-1]
    return DYNAMIC


def _robfig(ctx: Ctx) -> None:
    for call in _walk(ctx.root):
        if call.type != "call_expression":
            continue
        fn = call.child_by_field_name("function")
        if fn is None or fn.type != "selector_expression":
            continue
        if _text(fn.child_by_field_name("field")) not in ("AddFunc", "AddJob"):
            continue
        args = _named(call.child_by_field_name("arguments"))
        if len(args) < 2:
            continue
        name = _go_name(args[1])
        ctx.add(name, cron_text(args[0]) or ctx.dyn(call), name, call)


_DURATIONS = {"from_secs": "s", "from_millis": "ms"}
_DURATION_JOBS = {
    "new_repeated": "interval",
    "new_repeated_async": "interval",
    "new_one_shot": "once",
    "new_one_shot_async": "once",
}


def _duration(node: Node) -> str | None:
    if node.type != "call_expression":
        return None
    fn = node.child_by_field_name("function")
    unit = _DURATIONS.get(
        _text(fn.child_by_field_name("name")) if fn is not None else ""
    )
    args = _named(node.child_by_field_name("arguments"))
    value = num(args[0]) if len(args) == 1 else None
    return f"{value}{unit}" if value and unit else None


def _rust_handler(node: Node) -> str:
    if node.type == "identifier":
        return _text(node)
    if node.type == "scoped_identifier":
        return _text(node.child_by_field_name("name"))
    return ANONYMOUS


def _tokio(ctx: Ctx) -> None:
    for call in _walk(ctx.root):
        if call.type != "call_expression":
            continue
        fn = call.child_by_field_name("function")
        if fn is None or fn.type != "scoped_identifier":
            continue
        kind = _text(fn.child_by_field_name("name"))
        if _text(fn.child_by_field_name("path")) != "Job" or not kind.startswith("new"):
            continue
        args = _named(call.child_by_field_name("arguments"))
        if not args:
            continue
        if kind in _DURATION_JOBS:
            span = _duration(args[0])
            schedule = f"{_DURATION_JOBS[kind]} {span}" if span else ctx.dyn(call)
        else:
            schedule = cron_text(args[0]) or ctx.dyn(call)
        handler = _rust_handler(args[-1]) if len(args) > 1 else ANONYMOUS
        ctx.add(handler, schedule, handler, call)


GO = [Scanner(re.compile(rb"robfig/cron"), _robfig)]
RUST = [Scanner(re.compile(rb"tokio_cron_scheduler"), _tokio)]
