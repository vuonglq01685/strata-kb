"""`@Route(...)` docblock annotations (Doctrine syntax) for the Symfony adapter.

Reads the arguments the route table needs: the path (first positional
string, `path=` or `value=`) and `methods=` (a string or `{"GET", "POST"}`).
Every other argument (`name=`, `requirements=`, ...) is skipped. A
`@Route` whose path or methods are not plain string literals, or that has no
argument list at all, is returned as `None`, which the caller turns into a site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["DocRoute", "doc_methods", "doc_routes"]

# group 2 is the opening paren: a bare `@Route` carries no arguments to read
_OPEN = re.compile(
    r"@((?:[\w\\]*\\)?(?:Route|Get|Post|Put|Patch|Delete|Head|Options))(?![\w\\])(\s*\()?"
)
_METHOD = re.compile(r"@(?:[\w\\]*\\)?Method\s*\(")
_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
_KEYED = re.compile(r"(\w+)\s*=\s*(.*)", re.DOTALL)
_LEADING_STAR = re.compile(r"^[ \t]*(?:/\*+|\*+/?)?[ \t]?", re.MULTILINE)


@dataclass(frozen=True)
class DocRoute:
    path: str
    methods: tuple[str, ...]
    has_path: bool


def _balanced(text: str, start: int) -> str | None:
    """Text up to the `)` that closes the call opened just before `start`."""
    depth, quote = 1, False
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = False
        elif ch == '"':
            quote = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


def _split(body: str) -> list[str]:
    parts: list[str] = []
    depth, quote, begin, i = 0, False, 0, 0
    while i < len(body):
        ch = body[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = False
        elif ch == '"':
            quote = True
        elif ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(body[begin:i])
            begin = i + 1
        i += 1
    parts.append(body[begin:])
    return [p.strip() for p in parts if p.strip()]


def _strings(value: str) -> list[str] | None:
    """One string, or `{"a", "b"}`; None for anything else."""
    value = value.strip()
    single = _STRING.fullmatch(value)
    if single:
        return [single.group(1)]
    if value.startswith("{") and value.endswith("}"):
        items = _split(value[1:-1])
        found = [_STRING.fullmatch(i) for i in items]
        if all(found):
            return [m.group(1) for m in found if m]
    return None


def _read(body: str) -> DocRoute | None:
    path: str | None = None
    methods: list[str] = []
    for position, arg in enumerate(_split(body)):
        keyed = _KEYED.fullmatch(arg)
        if keyed is None:
            if position == 0:
                one = _strings(arg)
                if one is None or len(one) != 1:
                    return None
                path = one[0]
            continue
        key, value = keyed.groups()
        if key in ("path", "value"):
            one = _strings(value)
            if one is None or len(one) != 1:
                return None
            path = one[0]
        elif key == "methods":
            found = _strings(value)
            if found is None:
                return None
            methods = [m.upper() for m in found]
    return DocRoute(path or "", tuple(methods), path is not None)


def doc_routes(comment: str) -> list[tuple[int, str, DocRoute | None]]:
    """Every `@Route(...)` / `@Get(...)`-style annotation of a docblock as
    (line offset inside the comment, name as written, route); the route is
    None when it could not be read."""
    text = _LEADING_STAR.sub("", comment)
    out: list[tuple[int, str, DocRoute | None]] = []
    for match in _OPEN.finditer(text):
        body = _balanced(text, match.end()) if match.group(2) else None
        out.append(
            (
                text.count("\n", 0, match.start()),
                match.group(1),
                None if body is None else _read(body),
            )
        )
    return out


def doc_methods(comment: str) -> list[str] | None:
    """Verbs of the docblock's Sensio `@Method(...)` annotations (empty when
    there is none); None when one cannot be read."""
    text = _LEADING_STAR.sub("", comment)
    found: list[str] = []
    for match in _METHOD.finditer(text):
        body = _balanced(text, match.end())
        values = _strings(body) if body is not None else None
        if values is None:
            return None
        found += [v.upper() for v in values]
    return found
