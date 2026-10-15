"""Tree-sitter helpers shared by the JS/TS route adapters (`_routes_js.py`,
`_routes_express.py`): tree walking, literal/argument access, scope-file
filtering, the plain-declaration reader behind the L3 request-type field
tables. Internal to the `_routes_*` modules.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_model import AdapterResult
from strata_kb.codeingest.extractors._scopes import Scope

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

Field = tuple[str, str, bool]  # (name, type, required)

_JS_LANGS = frozenset({"javascript", "typescript", "tsx"})
_TS_LANGS = frozenset({"typescript", "tsx"})
_EXTS = (".ts", ".tsx", ".js", ".mjs", ".cjs", ".jsx")
_CLASS_TYPES = ("class_declaration", "abstract_class_declaration")
# Only unambiguous test markers: a directory named `test` / `e2e` can hold
# product routes (`app/api/test/route.ts`), so those are never skipped.
_TEST_RE = re.compile(
    r"(?:^|/)(?:__tests__|__mocks__)/|\.(?:test|spec|e2e-spec)\.[cm]?[jt]sx?$"
)
# Nitro's default ignore: `*.{spec,test}.{js,cts,mts,ts,jsx,tsx}`
_SUFFIX_RE = re.compile(r"\.(?:spec|test)\.(?:js|cts|mts|ts|jsx|tsx)$")
_SCRIPT_EXT_RE = re.compile(r"\.[cm]?[jt]sx?$")


def _walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _text(node: Node | None) -> str:
    return " ".join(_ts.node_text(node).split()) if node is not None else ""


def _lit(node: Node | None) -> str | None:
    return _ts.string_literal(node) if node is not None else None


def _args(call: Node | None) -> list[Node]:
    args = call.child_by_field_name("arguments") if call is not None else None
    if args is None or args.type != "arguments":
        return []
    return [c for c in args.named_children if c.type != "comment"]


def _site(rel: str, node: Node) -> str:
    return f"{rel}:{_ts.line_of(node)}"


def _source_files(files: list[str], tests: str = "all") -> list[str]:
    """JS/TS files of a scope. `tests`: "all" skips test dirs and suffixes,
    "suffix" only `*.test.*` / `*.spec.*` (Nitro ignores those itself), "none"
    skips nothing -- file-system routers list every file under a route dir."""
    return [
        f
        for f in files
        if _ts.language_for(f) in _JS_LANGS
        and not f.endswith(".d.ts")
        and not (tests == "all" and _TEST_RE.search(f))
        and not (tests == "suffix" and _SUFFIX_RE.search(f))
    ]


def _read(root: Path, rel: str) -> bytes | None:
    try:
        return (root / rel).read_bytes()
    except OSError:
        return None


def _error_line(tree: Tree) -> int | None:
    """Line of the first syntax error, or None for a clean parse."""
    row = _ts.first_error_row(tree)
    return None if row is None else row + 1


def _parse(rel: str, data: bytes) -> Tree:
    # callers pass files already filtered by `language_for`
    return _ts.parse(_ts.language_for(rel) or "javascript", data)


def _scan(
    root: Path, files: list[str], hint: re.Pattern[bytes], result: AdapterResult
) -> list[tuple[str, Tree]]:
    """Parse the scope's source files that match `hint`. An unreadable file
    or a syntax error is a site: routes in it may have been missed."""
    out: list[tuple[str, Tree]] = []
    for rel in _source_files(files):
        data = _read(root, rel)
        if data is None:
            result.dynamic_sites.append(f"{rel}:1")
            continue
        if not hint.search(data):
            continue
        tree = _parse(rel, data)
        line = _error_line(tree)
        if line is not None:
            result.dynamic_sites.append(f"{rel}:{line}")
        out.append((rel, tree))
    return out


def _local(rel: str, scope: Scope) -> str:
    return rel if scope.path == "." else rel[len(scope.path) + 1 :]


def _config_sites(
    root: Path, scope: Scope, files: list[str], names: frozenset[str], option: bytes
) -> list[str]:
    """A config option that rewrites every served path (`basePath`,
    `baseURL`, `srcDir`, ...) makes each listed path wrong: site every line
    that sets one."""
    sites = []
    for rel in files:
        if PurePosixPath(_local(rel, scope)).name not in names:
            continue
        data = _read(root, rel) or b""
        for number, line in enumerate(data.splitlines(), start=1):
            if re.search(rb"\b(?:" + option + rb")\b", line):
                sites.append(f"{rel}:{number}")
    return sites


def _last_name(node: Node | None) -> str:
    if node is None:
        return ""
    if node.type == "member_expression":
        return _text(node.child_by_field_name("property"))
    return _text(node) if node.type == "identifier" else ""


def _common_dirs(a: str, b: str) -> int:
    n = 0
    for left, right in zip(
        PurePosixPath(a).parent.parts, PurePosixPath(b).parent.parts, strict=False
    ):
        if left != right:
            break
        n += 1
    return n


def _field(member: Node) -> Field | None:
    name = member.child_by_field_name("name")
    if name is None or name.type not in ("property_identifier", "string"):
        return None
    annotation = member.child_by_field_name("type")
    inner = (
        annotation.named_children[0]
        if annotation is not None and annotation.named_children
        else None
    )
    return (
        (_lit(name) or "") if name.type == "string" else _text(name),
        _text(inner) or "unknown",
        not any(c.type == "?" for c in member.children),
    )


def _plain_fields(decl: Node) -> list[Field] | None:
    """Fields of a plain `class T {...}` / `interface T {...}`; None when the
    declaration has a base class, index signature, parameter properties or
    anything else that would make the list incomplete."""
    out: list[Field] = []
    if decl.type == "interface_declaration":
        if any(c.type == "extends_type_clause" for c in decl.children):
            return None
        body = decl.child_by_field_name("body")
        for member in body.named_children if body is not None else []:
            if member.type == "property_signature":
                parsed = _field(member)
                if parsed is None:
                    return None
                out.append(parsed)
            elif member.type not in ("method_signature", "comment"):
                return None
        return out
    for child in decl.children:
        if child.type == "class_heritage" and any(
            c.type == "extends_clause" for c in child.children
        ):
            return None
    body = decl.child_by_field_name("body")
    for member in body.named_children if body is not None else []:
        if member.type == "public_field_definition":
            if any(c.type == "static" for c in member.children):
                continue
            parsed = _field(member)
            if parsed is None:
                return None
            out.append(parsed)
        elif member.type == "method_definition":
            params = member.child_by_field_name("parameters")
            if _text(member.child_by_field_name("name")) == "constructor" and any(
                c.type == "accessibility_modifier"
                for p in (params.named_children if params is not None else [])
                for c in p.children
            ):
                return None
        elif member.type not in ("decorator", "comment"):
            return None
    return out


def declared_fields(
    root: Path, files: list[str], type_name: str, near: str
) -> list[Field] | None:
    """Fields of `type_name` when it is a plain class/interface declared in
    the repo, else None. The declaration in `near` (the route's own file)
    wins; otherwise the closest directory does (shortcut: imports are not
    followed, so two same-named types in different folders resolve by
    proximity -- upgrade if a repo hits that)."""
    if _ts.language_for(near) not in _JS_LANGS:  # a JS/TS route reads TS types only
        return None
    type_name, wrapper = _unwrap_type(type_name)
    fields = _declared_fields(root, files, type_name, near)
    if fields is None or wrapper is None:
        return fields
    return [(n, t, wrapper) for n, t, _req in fields]


_ARRAY_RE = re.compile(r"(?:Readonly)?Array<(.+)>$|(.+)\[\]$")
_WRAPPER_RE = re.compile(r"(Partial|Required|Readonly)<(.+)>$")


def _unwrap_type(name: str) -> tuple[str, bool | None]:
    """`CreateDto[]` / `Array<X>` -> the element; `Partial<X>` makes every
    field optional, `Required<X>` required (returned as the forced flag)."""
    forced: bool | None = None
    while True:
        array = _ARRAY_RE.match(name)
        wrapper = _WRAPPER_RE.match(name)
        if array:
            name = array.group(1) or array.group(2)
        elif wrapper:
            name = wrapper.group(2)
            if forced is None:  # the outermost wrapper decides
                forced = {"Partial": False, "Required": True}.get(wrapper.group(1))
        else:
            return name, forced


def _declared_fields(
    root: Path, files: list[str], type_name: str, near: str
) -> list[Field] | None:
    pattern = re.compile(
        rb"\b(?:class|interface)\s+" + re.escape(type_name.encode()) + rb"\b"
    )
    candidates = []
    for rel in files:
        if _ts.language_for(rel) in _TS_LANGS:
            data = _read(root, rel)
            if data is not None and pattern.search(data):
                candidates.append(rel)
    candidates.sort(key=lambda rel: (rel != near, -_common_dirs(rel, near), rel))
    for rel in candidates:
        data = _read(root, rel)
        if data is None:
            continue
        for node in _walk(_parse(rel, data).root_node):
            if (
                node.type in (*_CLASS_TYPES, "interface_declaration")
                and _text(node.child_by_field_name("name")) == type_name
            ):
                return _plain_fields(node)
    return None
