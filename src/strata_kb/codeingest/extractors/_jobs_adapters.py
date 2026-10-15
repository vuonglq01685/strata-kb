"""Per-file scheduler scanners for `jobs.py`: the JS/TS (NestJS, node-cron,
BullMQ), Python (Celery) and PHP (Laravel, Symfony) sources, plus the
registry that maps every supported language to its scanners (the JVM,
.NET, Go and Rust ones live in their own modules).

Each scanner is gated on a byte pattern so a file that cannot hold its
scheduler is never parsed. Names are the method or function name (or the
decorator's own `name`), schedules are literals as written; anything else is
`(dynamic)` with a `file:line` site.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._jobs_dotnet import SCANNERS as _DOTNET
from strata_kb.codeingest.extractors._jobs_jvm import SCANNERS as _JVM
from strata_kb.codeingest.extractors._jobs_model import (
    ANONYMOUS,
    DYNAMIC,
    EXEC,
    UNNAMED,
    Ctx,
    Scanner,
    cron_text,
    enclosing,
    first_token,
    name_only,
    num,
    qualified,
)
from strata_kb.codeingest.extractors._jobs_native import GO, RUST
from strata_kb.codeingest.extractors._routes_jsutil import _args, _lit, _text, _walk

if TYPE_CHECKING:
    from tree_sitter import Node

_JS_CLASSES = frozenset({"class_declaration", "abstract_class_declaration", "class"})

# --- JS / TS -------------------------------------------------------------------


def _key(pair: Node) -> str:
    key = pair.child_by_field_name("key")
    if key is None:
        return ""
    return (_lit(key) or "") if key.type == "string" else _text(key)


def _object_value(obj: Node | None, key: str) -> Node | None:
    for pair in obj.named_children if obj is not None else []:
        if pair.type == "pair" and _key(pair) == key:
            return pair.child_by_field_name("value")
    return None


def _nest(ctx: Ctx) -> None:
    for dec in _walk(ctx.root):
        if dec.type != "decorator":
            continue
        call = next(
            (c for c in dec.named_children if c.type == "call_expression"), None
        )
        kind = _text(call.child_by_field_name("function")) if call else ""
        if call is None or kind not in ("Cron", "Interval", "Timeout"):
            continue
        method = dec.next_named_sibling
        while method is not None and method.type in ("decorator", "comment"):
            method = method.next_named_sibling
        if method is None or method.type != "method_definition":
            continue
        mname = _text(method.child_by_field_name("name"))
        args = _args(call)
        given: str | None = None
        if kind == "Cron":
            schedule = (cron_text(args[0]) if args else None) or ctx.dyn(dec)
            options = args[1] if len(args) > 1 and args[1].type == "object" else None
            given = _lit(_object_value(options, "name"))
        else:
            ms = num(args[-1]) if args else None
            schedule = f"{kind.lower()} {ms}ms" if ms else ctx.dyn(dec)
            given = _lit(args[0]) if len(args) == 2 else None
        owner = enclosing(method, _JS_CLASSES)
        ctx.add(given or mname, schedule, qualified(owner, mname), dec)


def _fn_name(node: Node | None) -> str:
    if node is None:
        return ANONYMOUS
    if node.type == "identifier":
        return _text(node)
    if node.type == "member_expression":
        return _text(node.child_by_field_name("property"))
    if node.type in ("function_expression", "function"):
        return _text(node.child_by_field_name("name")) or ANONYMOUS
    return ANONYMOUS


def _last_name(fn: Node) -> str:
    if fn.type == "member_expression":
        return _text(fn.child_by_field_name("property"))
    return _text(fn) if fn.type == "identifier" else ""


def _import_names(clause: Node) -> tuple[set[str], set[str]]:
    receivers: set[str] = set()
    funcs: set[str] = set()
    for part in clause.named_children:
        if part.type == "identifier":
            receivers.add(_text(part))
        elif part.type == "namespace_import":
            receivers.update(_text(c) for c in part.named_children)
        elif part.type == "named_imports":
            for spec in part.named_children:
                name = _text(spec.child_by_field_name("name"))
                alias = _text(spec.child_by_field_name("alias")) or name
                (
                    receivers
                    if name == "default"
                    else funcs
                    if name == "schedule"
                    else set()
                ).add(alias)
    return receivers, funcs


def _pattern_names(pattern: Node) -> set[str]:
    out: set[str] = set()
    for part in pattern.named_children:
        if (
            part.type == "shorthand_property_identifier_pattern"
            and _text(part) == "schedule"
        ):
            out.add("schedule")
        elif (
            part.type == "pair_pattern"
            and _text(part.child_by_field_name("key")) == "schedule"
        ):
            out.add(_text(part.child_by_field_name("value")))
    return out


def _node_cron_bindings(root: Node) -> tuple[set[str], set[str]]:
    """Local names bound to the `node-cron` module and to its `schedule`."""
    receivers: set[str] = set()
    funcs: set[str] = set()
    for node in _walk(root):
        if node.type == "import_statement":
            clause = next(
                (
                    c
                    for c in node.named_children
                    if c.type in ("import_clause", "import_require_clause")
                ),
                None,
            )
            if clause is None:
                continue
            source = _lit(node.child_by_field_name("source")) or _lit(
                clause.child_by_field_name("source")
            )
            if source != "node-cron":
                continue
            if clause.type == "import_require_clause":
                receivers |= {
                    _text(c) for c in clause.named_children if c.type == "identifier"
                }
            else:
                got = _import_names(clause)
                receivers |= got[0]
                funcs |= got[1]
        elif node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            args = (
                _args(value)
                if value is not None and value.type == "call_expression"
                else []
            )
            if (
                value is None
                or _text(value.child_by_field_name("function")) != "require"
            ):
                continue
            if not args or _lit(args[0]) != "node-cron":
                continue
            target = node.child_by_field_name("name")
            if target is None:
                continue
            if target.type == "identifier":
                receivers.add(_text(target))
            elif target.type == "object_pattern":
                funcs |= _pattern_names(target)
    return receivers, funcs


def _is_require_node_cron(node: Node) -> bool:
    if node.type != "call_expression":
        return False
    args = _args(node)
    return (
        _text(node.child_by_field_name("function")) == "require"
        and bool(args)
        and _lit(args[0]) == "node-cron"
    )


def _node_cron(ctx: Ctx) -> None:
    receivers, funcs = _node_cron_bindings(ctx.root)
    for call in _walk(ctx.root):
        if call.type != "call_expression":
            continue
        fn = call.child_by_field_name("function")
        if fn is None:
            continue
        if fn.type == "member_expression":
            owner = fn.child_by_field_name("object")
            direct = owner is not None and _is_require_node_cron(owner)
            bound = (direct or _text(owner) in receivers) and _text(
                fn.child_by_field_name("property")
            ) == "schedule"
        else:
            bound = fn.type == "identifier" and _text(fn) in funcs
        args = _args(call)
        if not bound or len(args) < 2:
            continue
        schedule = cron_text(args[0]) or ctx.dyn(call)
        handler = _fn_name(args[1])
        options = args[2] if len(args) > 2 and args[2].type == "object" else None
        ctx.add(
            _lit(_object_value(options, "name")) or handler, schedule, handler, call
        )


def _bull_name(pair: Node) -> str:
    obj = pair.parent
    args = obj.parent if obj is not None else None
    call = args.parent if args is not None and args.type == "arguments" else None
    fn = call.child_by_field_name("function") if call is not None else None
    if fn is None or _last_name(fn) not in ("add", "upsertJobScheduler"):
        return UNNAMED
    first = (_args(call) or [None])[0]
    if first is None:
        return UNNAMED
    return _lit(first) or (_text(first) if first.type == "identifier" else UNNAMED)


def _bullmq(ctx: Ctx) -> None:
    for pair in _walk(ctx.root):
        if pair.type != "pair" or _key(pair) != "repeat":
            continue
        value = pair.child_by_field_name("value")
        if value is None:
            continue
        if value.type != "object":
            if value.type in ("identifier", "member_expression", "call_expression"):
                ctx.add(_bull_name(pair), ctx.dyn(pair), "-", pair)
            continue
        if any(c.type == "spread_element" for c in value.named_children):
            ctx.add(_bull_name(pair), ctx.dyn(pair), "-", pair)
            continue
        pattern = _object_value(value, "pattern") or _object_value(value, "cron")
        every = _object_value(value, "every")
        if pattern is None and every is None:
            continue  # `repeat: { count: 3 }` is some other library's option
        if pattern is not None:
            schedule = cron_text(pattern) or ctx.dyn(pair)
        elif num(every):
            schedule = f"interval {num(every)}ms"
        else:
            schedule = ctx.dyn(pair)
        ctx.add(_bull_name(pair), schedule, "-", pair)


_JS = [
    Scanner(re.compile(rb"@nestjs/schedule"), _nest),
    Scanner(re.compile(rb"node-cron"), _node_cron),
    Scanner(re.compile(rb"bullmq|@nestjs/bull|['\"]bull['\"]"), _bullmq),
]

# --- Python (Celery) --------------------------------------------------------------

_BEAT_KEYS = frozenset({"beat_schedule", "CELERY_BEAT_SCHEDULE", "BEAT_SCHEDULE"})
_PY_SCHEDULES = frozenset({"crontab", "timedelta", "solar", "schedule"})
_SIGNATURE_METHODS = frozenset({"s", "si", "signature", "subtask"})
_PY_CLASSES = frozenset({"class_definition"})


def _last(node: Node | None) -> str:
    if node is None:
        return ""
    if node.type == "attribute":
        return _text(node.child_by_field_name("attribute"))
    return _text(node) if node.type == "identifier" else ""


def _py_call_args(call: Node) -> tuple[list[Node], dict[str, Node]]:
    args = call.child_by_field_name("arguments")
    positional: list[Node] = []
    keywords: dict[str, Node] = {}
    for arg in args.named_children if args is not None else []:
        if arg.type == "keyword_argument":
            value = arg.child_by_field_name("value")
            if value is not None:
                keywords[_text(arg.child_by_field_name("name"))] = value
        elif arg.type != "comment":
            positional.append(arg)
    return positional, keywords


def _py_literal(node: Node | None) -> bool:
    return node is not None and (_lit(node) is not None or num(node) is not None)


def _py_schedule(ctx: Ctx, node: Node | None, at: Node) -> str:
    if node is None:
        return ctx.dyn(at)
    seconds = num(node)
    if seconds:
        return f"interval {seconds}s"
    if (
        node.type == "call"
        and _last(node.child_by_field_name("function")) in _PY_SCHEDULES
    ):
        positional, keywords = _py_call_args(node)
        if all(_py_literal(a) for a in [*positional, *keywords.values()]):
            return " ".join(_text(node).split())
    return ctx.dyn(at)


def _dict_get(node: Node, key: str) -> Node | None:
    for pair in node.named_children:
        if pair.type == "pair":
            k = pair.child_by_field_name("key")
            if k is not None and _lit(k) == key:
                return pair.child_by_field_name("value")
    return None


def _beat(ctx: Ctx, table: Node | None, at: Node) -> None:
    if table is None or table.type != "dictionary":
        ctx.dyn(at)
        return
    for pair in table.named_children:
        if pair.type != "pair":
            continue
        key = pair.child_by_field_name("key")
        value = pair.child_by_field_name("value")
        name = _lit(key) if key is not None else None
        if name is None:
            ctx.dyn(pair)
        if value is None or value.type != "dictionary":
            ctx.add(name or DYNAMIC, ctx.dyn(pair), "-", pair)
            continue
        task = _lit(_dict_get(value, "task")) or "-"
        ctx.add(
            name or DYNAMIC,
            _py_schedule(ctx, _dict_get(value, "schedule"), pair),
            task,
            pair,
        )


def _sig_name(node: Node) -> str:
    if node.type == "call":
        fn = node.child_by_field_name("function")
        if (
            fn is not None
            and fn.type == "attribute"
            and _last(fn) in _SIGNATURE_METHODS
        ):
            base = fn.child_by_field_name("object")
            return _sig_name(base) if base is not None else DYNAMIC
        return _sig_name(fn) if fn is not None else DYNAMIC
    return _text(node) if node.type in ("identifier", "attribute") else DYNAMIC


def _periodic_decorators(ctx: Ctx, node: Node) -> None:
    definition = node.child_by_field_name("definition")
    if definition is None or definition.type != "function_definition":
        return
    for dec in node.named_children:
        expr = (
            dec.named_children[0]
            if dec.type == "decorator" and dec.named_children
            else None
        )
        if expr is None:
            continue
        fn = expr.child_by_field_name("function") if expr.type == "call" else expr
        if _last(fn) != "periodic_task":
            continue
        keywords = _py_call_args(expr)[1] if expr.type == "call" else {}
        fname = _text(definition.child_by_field_name("name"))
        handler = qualified(enclosing(definition, _PY_CLASSES), fname)
        ctx.add(fname, _py_schedule(ctx, keywords.get("run_every"), dec), handler, dec)


def _celery(ctx: Ctx) -> None:
    for node in _walk(ctx.root):
        if (
            node.type == "assignment"
            and _last(node.child_by_field_name("left")) in _BEAT_KEYS
        ):
            _beat(ctx, node.child_by_field_name("right"), node)
        elif (
            node.type == "keyword_argument"
            and _text(node.child_by_field_name("name")) in _BEAT_KEYS
        ):
            _beat(ctx, node.child_by_field_name("value"), node)
        elif node.type == "decorated_definition":
            _periodic_decorators(ctx, node)
        elif (
            node.type == "call"
            and _last(node.child_by_field_name("function")) == "add_periodic_task"
        ):
            positional, keywords = _py_call_args(node)
            if len(positional) < 2:
                ctx.dyn(node)
                continue
            handler = _sig_name(positional[1])
            name = _lit(keywords.get("name")) or handler
            ctx.add(name, _py_schedule(ctx, positional[0], node), handler, node)


_PYTHON = [
    Scanner(
        re.compile(rb"beat_schedule|BEAT_SCHEDULE|periodic_task"),
        _celery,
    )
]

# --- PHP (Laravel, Symfony) ----------------------------------------------------------

_SCHEDULE_STARTS = frozenset({"command", "job", "call", "exec"})
_FREQUENCY_RE = re.compile(
    r"(?:cron|every\w*|hourly\w*|daily\w*|twiceDaily\w*|weekly\w*|monthly\w*"
    r"|twiceMonthly|quarterly\w*|yearly\w*|lastDayOfMonth)"
)
_MODIFIERS = frozenset(
    {"at", "days", "weekdays", "weekends", "between", "unlessBetween"}
    | {
        "sundays",
        "mondays",
        "tuesdays",
        "wednesdays",
        "thursdays",
        "fridays",
        "saturdays",
    }
)
_PHP_CLOSURES = frozenset({"anonymous_function", "arrow_function"})
_PHP_CLASSES = frozenset({"class_declaration"})


def _php_args(call: Node) -> list[Node]:
    args = call.child_by_field_name("arguments")
    return [
        a.named_children[-1]
        for a in (args.named_children if args is not None else [])
        if a.type == "argument" and a.named_children
    ]


def _short(name: str) -> str:
    return name.rsplit("\\", 1)[-1]


def _php_name(node: Node) -> str:
    lit = _lit(node)
    if lit is not None:
        return first_token(lit)  # a command line may carry credentials
    if node.type in _PHP_CLOSURES:
        return ANONYMOUS
    if node.type in ("object_creation_expression", "class_constant_access_expression"):
        found = next(
            (c for c in node.named_children if c.type in ("name", "qualified_name")),
            None,
        )
        return _short(_text(found)) if found is not None else DYNAMIC
    return DYNAMIC


def _schedule_start(node: Node) -> str | None:
    if node.type == "member_call_expression":
        obj = node.child_by_field_name("object")
        if obj is None or obj.type != "variable_name" or _text(obj) != "$schedule":
            return None
    elif node.type == "scoped_call_expression":
        if _text(node.child_by_field_name("scope")) != "Schedule":
            return None
    else:
        return None
    name = _text(node.child_by_field_name("name"))
    return name if name in _SCHEDULE_STARTS else None


def _frequency(ctx: Ctx, start: Node) -> str:
    """The frequency method plus the literal `at` / day modifiers of the
    chain; a non-literal argument makes the whole schedule dynamic."""
    freq = ""
    modifiers: list[str] = []
    cur = start
    while (
        cur.parent is not None
        and cur.parent.type == "member_call_expression"
        and cur.parent.child_by_field_name("object") == cur
    ):
        cur = cur.parent
        method = _text(cur.child_by_field_name("name"))
        is_freq = _FREQUENCY_RE.fullmatch(method) is not None
        if not (is_freq and not freq) and method not in _MODIFIERS:
            continue
        args = _php_args(cur)
        if method == "cron":
            text = cron_text(args[0]) if args else None
            part = text or ctx.dyn(cur)
        else:
            values = [_lit(a) or num(a) for a in args]
            part = (
                ctx.dyn(cur)
                if None in values
                else " ".join([method, *(v for v in values if v is not None)])
            )
        if part == DYNAMIC:
            return DYNAMIC
        if is_freq and not freq:
            freq = part
        else:
            modifiers.append(part)
    if not freq and any(m.startswith("at ") for m in modifiers):
        freq = "daily"  # `->at()` is an alias of `->dailyAt()`
    return " ".join([freq, *modifiers]) if freq else ctx.dyn(start)


def _laravel(ctx: Ctx) -> None:
    for node in _walk(ctx.root):
        kind = _schedule_start(node)
        if kind is None:
            continue
        args = _php_args(node)
        # `exec` takes a shell command line: never a name
        name = EXEC if kind == "exec" else _php_name(args[0]) if args else DYNAMIC
        handler = name if kind == "job" else "-"
        ctx.add(name, _frequency(ctx, node), handler, node)


def _php_named(attr: Node) -> tuple[Node | None, dict[str, Node]]:
    first: Node | None = None
    named: dict[str, Node] = {}
    params = attr.child_by_field_name("parameters")
    for arg in params.named_children if params is not None else []:
        parts = arg.named_children
        if len(parts) == 2 and parts[0].type == "name":
            named[_text(parts[0])] = parts[1]
        elif parts and first is None:
            first = parts[-1]
    return first, named


def _symfony(ctx: Ctx) -> None:
    for attr in _walk(ctx.root):
        if attr.type != "attribute":
            continue
        label = next(
            (c for c in attr.named_children if c.type in ("name", "qualified_name")),
            None,
        )
        kind = _short(_text(label))
        if kind not in ("AsCronTask", "AsPeriodicTask"):
            continue
        target = attr.parent
        while target is not None and target.type not in (
            "class_declaration",
            "method_declaration",
        ):
            target = target.parent
        if target is None:
            continue
        first, named = _php_named(attr)
        arg = named.get("expression" if kind == "AsCronTask" else "frequency", first)
        if kind == "AsCronTask":
            schedule = cron_text(arg) or ctx.dyn(attr)
        elif num(arg):
            schedule = f"interval {num(arg)}s"
        else:
            text = cron_text(arg)
            schedule = f"every {text}" if text else ctx.dyn(attr)
        own = _text(target.child_by_field_name("name"))
        if target.type == "class_declaration":
            entry = "__invoke"
            if "method" in named:
                literal = _lit(named["method"])
                if literal is None:
                    ctx.dyn(attr)
                entry = literal if literal and name_only(literal) else ""
            ctx.add(own, schedule, f"{own}.{entry}" if entry else "-", attr)
        else:
            ctx.add(
                own, schedule, qualified(enclosing(target, _PHP_CLASSES), own), attr
            )


_PHP = [
    Scanner(re.compile(rb"\$schedule\b|\bSchedule::"), _laravel),
    Scanner(re.compile(rb"AsCronTask|AsPeriodicTask"), _symfony),
]

SCANNERS: dict[str, list[Scanner]] = {
    "typescript": _JS,
    "tsx": _JS,
    "javascript": _JS,
    "python": _PYTHON,
    "php": _PHP,
    "java": _JVM,
    "kotlin": _JVM,
    "csharp": _DOTNET,
    "go": GO,
    "rust": RUST,
}
