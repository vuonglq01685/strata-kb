"""C# scheduler scanners for `jobs.py`: Hangfire `RecurringJob.AddOrUpdate`,
Quartz `WithCronSchedule`, and classes deriving `BackgroundService`."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._jobs_model import (
    DYNAMIC,
    UNNAMED,
    Ctx,
    Scanner,
    cron_text,
    name_only,
    num,
)
from strata_kb.codeingest.extractors._routes_jsutil import _lit, _text, _walk

if TYPE_CHECKING:
    from tree_sitter import Node

_LAMBDAS = ("lambda_expression", "anonymous_method_expression")


def _args(call: Node) -> list[Node]:
    args = call.child_by_field_name("arguments")
    return [
        a.named_children[-1]
        for a in (args.named_children if args is not None else [])
        if a.type == "argument" and a.named_children
    ]


def _method(call: Node) -> tuple[Node | None, str, list[str]]:
    """(receiver, method name, generic type arguments) of `a.B<T>(...)`."""
    fn = call.child_by_field_name("function")
    if fn is None or fn.type != "member_access_expression":
        return None, "", []
    name = fn.child_by_field_name("name")
    types: list[str] = []
    if name is not None and name.type == "generic_name":
        types = [
            _text(t)
            for c in name.named_children
            if c.type == "type_argument_list"
            for t in c.named_children
        ]
        name = name.named_children[0]
    return fn.child_by_field_name("expression"), _text(name), types


def _lambda_target(lam: Node, types: list[str]) -> str:
    body = lam.child_by_field_name("body")
    if body is not None and body.type == "await_expression" and body.named_children:
        body = body.named_children[0]
    if body is None or body.type != "invocation_expression":
        return "-"
    recv, name, _ = _method(body)
    if recv is None:
        return "-"
    owner = _text(recv)
    if types and _text(lam.child_by_field_name("parameters")).strip("()") == owner:
        owner = types[0]
    # a receiver such as `new Mailer("smtp://...")` is not a name
    return f"{owner}.{name}" if name_only(owner) else name


def _is_cron(node: Node | None) -> bool:
    return (
        node is not None
        and node.type == "member_access_expression"
        and _text(node.child_by_field_name("expression")) == "Cron"
    )


def _hangfire_cron(ctx: Ctx, node: Node | None, at: Node) -> str:
    if node is None:
        return ctx.dyn(at)
    text = cron_text(node)
    if text:
        return text
    if _is_cron(node):
        return _text(node)
    if (
        node.type == "invocation_expression"
        and _is_cron(node.child_by_field_name("function"))
        and all(_lit(a) is not None or num(a) is not None for a in _args(node))
    ):
        return " ".join(_text(node).split())
    return ctx.dyn(at)


def _hangfire(ctx: Ctx) -> None:
    for call in _walk(ctx.root):
        if call.type != "invocation_expression":
            continue
        recv, name, types = _method(call)
        if recv is None or _text(recv) != "RecurringJob" or name != "AddOrUpdate":
            continue
        args = _args(call)
        idx = next((i for i, a in enumerate(args) if a.type in _LAMBDAS), None)
        if idx is None:
            ctx.add(DYNAMIC, ctx.dyn(call), "-", call)
            continue
        handler = _lambda_target(args[idx], types)
        given = _lit(args[0]) if idx > 0 else None
        fallback = handler.rsplit(".", 1)[-1] if handler != "-" else DYNAMIC
        schedule_node = args[idx + 1] if len(args) > idx + 1 else None
        ctx.add(
            given or fallback, _hangfire_cron(ctx, schedule_node, call), handler, call
        )


def _chain(call: Node) -> list[tuple[str, list[Node]]]:
    """Every `.Method(args)` of the fluent chain `call` sits in."""
    out: list[tuple[str, list[Node]]] = []
    cur: Node | None = call
    while cur is not None and cur.type == "invocation_expression":
        recv, name, _ = _method(cur)
        out.append((name, _args(cur)))
        cur = recv
    up = call.parent
    while up is not None and up.type == "member_access_expression":
        inv = up.parent
        if inv is None or inv.type != "invocation_expression":
            break
        out.append((_text(up.child_by_field_name("name")), _args(inv)))
        up = inv.parent
    return out


def _quartz(ctx: Ctx) -> None:
    for call in _walk(ctx.root):
        if (
            call.type != "invocation_expression"
            or _method(call)[1] != "WithCronSchedule"
        ):
            continue
        args = _args(call)
        schedule = (cron_text(args[0]) if args else None) or ctx.dyn(call)
        chain = {name: a for name, a in reversed(_chain(call)) if a}
        name = _lit(chain["WithIdentity"][0]) if "WithIdentity" in chain else None
        job = _lit(chain["ForJob"][0]) if "ForJob" in chain else None
        ctx.add(name or UNNAMED, schedule, job or "-", call)


def _hosted(ctx: Ctx) -> None:
    for cls in _walk(ctx.root):
        if cls.type != "class_declaration":
            continue
        if any(c.type == "modifier" and _text(c) == "abstract" for c in cls.children):
            continue
        bases = next((c for c in cls.named_children if c.type == "base_list"), None)
        if bases is None or not any(
            _text(b).rsplit(".", 1)[-1] == "BackgroundService"
            for b in bases.named_children
        ):
            continue
        ctx.add(_text(cls.child_by_field_name("name")), "hosted", "ExecuteAsync", cls)


SCANNERS = [
    Scanner(re.compile(rb"RecurringJob"), _hangfire),
    Scanner(re.compile(rb"WithCronSchedule"), _quartz),
    Scanner(re.compile(rb"BackgroundService"), _hosted),
]
