"""Java / Kotlin scheduler scanner for `jobs.py`: Spring, Quarkus and
Micronaut `@Scheduled(cron= | fixedRate= | fixedDelay= | every=)`."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._jobs_model import (
    Ctx,
    Scanner,
    cron_text,
    enclosing,
    num,
    qualified,
)
from strata_kb.codeingest.extractors._routes_jsutil import _lit, _text, _walk

if TYPE_CHECKING:
    from tree_sitter import Node

_CLASSES = frozenset({"class_declaration", "object_declaration"})
_METHODS = frozenset({"method_declaration", "function_declaration"})
_ANNOTATIONS = ("annotation", "marker_annotation")
# java.util.concurrent.TimeUnit -> the suffix `every 5m` already uses
_UNITS = {
    "NANOSECONDS": "ns",
    "MICROSECONDS": "us",
    "MILLISECONDS": "ms",
    "SECONDS": "s",
    "MINUTES": "m",
    "HOURS": "h",
    "DAYS": "d",
}


def _java_annotation(node: Node) -> tuple[str, dict[str, Node]]:
    pairs: dict[str, Node] = {}
    args = node.child_by_field_name("arguments")
    for arg in args.named_children if args is not None else []:
        if arg.type == "element_value_pair":
            key, value = (
                arg.child_by_field_name("key"),
                arg.child_by_field_name("value"),
            )
            if key is not None and value is not None:
                pairs[_text(key)] = value
    return _text(node.child_by_field_name("name")), pairs


def _kotlin_annotation(node: Node) -> tuple[str, dict[str, Node]]:
    invocation = next(
        (c for c in node.named_children if c.type == "constructor_invocation"), None
    )
    head = invocation if invocation is not None else node
    label = next((c for c in head.named_children if c.type == "user_type"), None)
    pairs: dict[str, Node] = {}
    for arg in head.named_children:
        if arg.type != "value_arguments":
            continue
        for item in arg.named_children:
            parts = item.named_children
            if len(parts) == 2 and parts[0].type == "simple_identifier":
                pairs[_text(parts[0])] = parts[1]
    return _text(label), pairs


def _schedule(ctx: Ctx, pairs: dict[str, Node], at: Node) -> str:
    if "cron" in pairs:
        text = cron_text(pairs["cron"])
        return "disabled" if text == "-" else text or ctx.dyn(at)
    for key in ("every", "fixedRate", "fixedDelay"):
        if key not in pairs:
            continue
        amount = num(pairs[key])
        if amount and "timeUnit" in pairs:
            unit = _UNITS.get(_text(pairs["timeUnit"]).rsplit(".", 1)[-1])
            return f"interval {amount}{unit}" if unit else ctx.dyn(at)
        if amount:
            return f"interval {amount}ms"
        text = cron_text(pairs[key])
        return f"every {text}" if text else ctx.dyn(at)
    for key in ("fixedRateString", "fixedDelayString"):
        text = cron_text(pairs[key]) if key in pairs else None
        if text and text.isdigit():
            return f"interval {text}ms"
    return ctx.dyn(at)


def _label(node: Node, kotlin: bool) -> tuple[str, dict[str, Node]]:
    label, pairs = _kotlin_annotation(node) if kotlin else _java_annotation(node)
    return label.rsplit(".", 1)[-1], pairs  # `@org.x.Scheduled` too


def _owner_method(node: Node) -> Node | None:
    """The method an annotation belongs to, also when nested in
    `@Schedules({...})`; None when a class comes first."""
    cur = node.parent
    while cur is not None and cur.type not in _CLASSES:
        if cur.type in _METHODS:
            return cur
        cur = cur.parent
    return None


def _scheduled(ctx: Ctx) -> None:
    kotlin = ctx.rel.endswith((".kt", ".kts"))
    for node in _walk(ctx.root):
        if node.type not in _ANNOTATIONS:
            continue
        label, pairs = _label(node, kotlin)
        target = _owner_method(node)
        if label == "Schedules":
            # the nested @Scheduled annotations are read on their own; a
            # container without any (a constant, a computed array) is a miss
            if not any(
                c is not node
                and c.type in _ANNOTATIONS
                and _label(c, kotlin)[0] == "Scheduled"
                for c in _walk(node)
            ):
                ctx.dyn(node)
            continue
        if label != "Scheduled" or target is None:
            continue
        method = _text(
            target.child_by_field_name("name")
            or next(
                (c for c in target.named_children if c.type == "simple_identifier"),
                None,
            )
        )
        given = _lit(pairs.get("name")) or _lit(pairs.get("identity"))
        ctx.add(
            given or method,
            _schedule(ctx, pairs, node),
            qualified(enclosing(target, _CLASSES), method),
            node,
        )


SCANNERS = [Scanner(re.compile(rb"\bSchedule[ds]\b"), _scheduled)]
