"""PHP tree-sitter helpers shared by the Laravel and Symfony route adapters
and the PHP symbol reader.

Everything here is iterative (no recursion over the tree) so a hostile file
cannot raise `RecursionError` from this layer, and returns plain text or
`None`: a name is identifier text, a literal is a plain string literal or
`None` (interpolation, concatenation, heredoc, constants). Namespaces are
resolved through the file's `use` clauses only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_jsutil import _text, _walk

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = [
    "CALLS",
    "CLOSURES",
    "Arg",
    "Attr",
    "Link",
    "attributes",
    "call_args",
    "chain",
    "class_ref",
    "is_closure",
    "literal",
    "literal_list",
    "resolve",
    "short",
    "source_files",
    "unwrap",
    "use_map",
]

_NAME_TYPES = ("name", "qualified_name", "namespace_name", "relative_name")
CLOSURES = ("anonymous_function", "arrow_function")
CALLS = (
    "member_call_expression",
    "nullsafe_member_call_expression",
    "scoped_call_expression",
)


_TEST_DIR = re.compile(r"(?:^|/)(?:tests|Tests|__tests__)/")


def source_files(files: list[str]) -> list[str]:
    """PHP files that can hold product code: no Blade templates, no test
    directories."""
    return sorted(
        f
        for f in files
        if f.endswith(".php")
        and not f.endswith(".blade.php")
        and not _TEST_DIR.search(f)
    )


@dataclass(frozen=True)
class Arg:
    name: str | None  # PHP 8 named argument
    value: Node
    index: int  # position among all arguments


@dataclass(frozen=True)
class Attr:
    name: str  # as written, namespace separators kept
    fqcn: str  # resolved through the file's `use` clauses
    args: tuple[Arg, ...]
    line: int


@dataclass(frozen=True)
class Link:
    """One call of a method chain: `->name(args)` or `Scope::name(args)`."""

    name: str  # "" when the method name is computed
    args: tuple[Arg, ...]
    node: Node  # the call expression

    @property
    def line(self) -> int:
        named = self.node.child_by_field_name("name")
        return _ts.line_of(named if named is not None else self.node)


def short(name: str) -> str:
    return name.replace(" ", "").rsplit("\\", 1)[-1]


def use_map(root: Node) -> dict[str, str]:
    """Alias -> fully qualified class name (no leading backslash) for every
    class-importing `use` clause of the file."""
    out: dict[str, str] = {}
    for decl in _walk(root):
        if decl.type != "namespace_use_declaration":
            continue
        group = next(
            (c for c in decl.children if c.type == "namespace_use_group"), None
        )
        base = "".join(_text(c) for c in decl.children if c.type == "namespace_name")
        clauses = (
            [c for c in group.children if c.type == "namespace_use_clause"]
            if group is not None
            else [c for c in decl.children if c.type == "namespace_use_clause"]
        )
        for clause in clauses:
            if any(c.type in ("function", "const") for c in clause.children):
                continue
            target = next((c for c in clause.children if c.type in _NAME_TYPES), None)
            if target is None:
                continue
            full = _text(target).replace(" ", "").lstrip("\\")
            if group is not None:
                full = f"{base.rstrip(chr(92))}\\{full}"
            alias = clause.child_by_field_name("alias")
            out[_text(alias) if alias is not None else short(full)] = full
    return out


def resolve(name: str, uses: dict[str, str]) -> str:
    """Fully qualified name of a class name as written in the file."""
    written = name.replace(" ", "")
    if written.startswith("\\"):
        return written.lstrip("\\")
    head, sep, rest = written.partition("\\")
    return uses[head] + sep + rest if head in uses else written


def call_args(node: Node | None) -> tuple[Arg, ...]:
    """Arguments of a call (`arguments` node) or an attribute."""
    if node is None:
        return ()
    out: list[Arg] = []
    for child in node.named_children:
        if child.type != "argument":
            continue
        name = child.child_by_field_name("name")
        value = next(
            (c for c in reversed(child.named_children) if c is not name),
            None,
        )
        if value is not None and value.type != "comment":
            out.append(Arg(_text(name) if name is not None else None, value, len(out)))
    return tuple(out)


def attributes(node: Node, uses: dict[str, str]) -> list[Attr]:
    """The attributes (`#[...]`) of a class, method or enum declaration, in
    source order, with their names resolved by `uses`."""
    out: list[Attr] = []
    for lst in node.children:
        if lst.type != "attribute_list":
            continue
        for found in _walk(lst):
            if found.type != "attribute":
                continue
            target = next((c for c in found.children if c.type in _NAME_TYPES), None)
            written = _text(target).replace(" ", "") if target is not None else ""
            out.append(
                Attr(
                    written,
                    resolve(written, uses),
                    call_args(found.child_by_field_name("parameters")),
                    _ts.line_of(found),
                )
            )
    return out


def unwrap(node: Node | None) -> Node | None:
    while node is not None and node.type == "parenthesized_expression":
        inner = [c for c in node.named_children if c.type != "comment"]
        if len(inner) != 1:
            break
        node = inner[0]
    return node


def literal(node: Node | None) -> str | None:
    node = unwrap(node)
    return _ts.string_literal(node) if node is not None else None


def literal_list(node: Node | None) -> list[str] | None:
    """A string literal as `[s]`, an array of string literals as the list;
    anything else (variable, constant, spread, key => value) is None."""
    node = unwrap(node)
    if node is None:
        return None
    single = literal(node)
    if single is not None:
        return [single]
    if node.type != "array_creation_expression":
        return None
    out: list[str] = []
    for element in node.named_children:
        if element.type == "comment":
            continue
        parts = [c for c in element.named_children if c.type != "comment"]
        value = literal(parts[0]) if len(parts) == 1 else None
        if element.type != "array_element_initializer" or value is None:
            return None
        out.append(value)
    return out


def class_ref(node: Node | None) -> str | None:
    """`Foo::class` / `\\App\\Foo::class` as the short class name; `self`,
    `static` and `parent` are not names."""
    node = unwrap(node)
    if node is None or node.type != "class_constant_access_expression":
        return None
    parts = [c for c in node.named_children if c.type != "comment"]
    if len(parts) != 2 or _text(parts[1]).lower() != "class":
        return None
    if parts[0].type not in _NAME_TYPES:
        return None
    name = short(_text(parts[0]))
    return None if name.lower() in ("self", "static", "parent") else name


def is_closure(node: Node | None) -> bool:
    node = unwrap(node)
    return node is not None and node.type in CLOSURES


def chain(node: Node) -> tuple[Node, list[Link]]:
    """Flatten a call chain `base->a()->b()` into (base, links in call
    order). The base is the scope of a static call (`Route`), the receiver
    of the first instance call, or the expression that is not a call."""
    links: list[Link] = []
    current = node
    while current.type in CALLS:
        named = current.child_by_field_name("name")
        links.append(
            Link(
                _text(named) if named is not None and named.type == "name" else "",
                call_args(current.child_by_field_name("arguments")),
                current,
            )
        )
        if current.type == "scoped_call_expression":
            current = current.child_by_field_name("scope") or current
            break
        nxt = current.child_by_field_name("object")
        if nxt is None:
            break
        current = nxt
    links.reverse()
    return current, links
