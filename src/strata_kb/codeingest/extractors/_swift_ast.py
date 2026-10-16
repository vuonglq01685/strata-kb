"""Tree-sitter helpers for Swift shared by the Vapor route adapter and the
Swift symbol reader: names, access levels, type names, call anatomy.
Internal to `_routes_swift`, `_vapor_index` and `_symbols_swift`.

The grammar reuses the field name `name` for identifiers, types and
patterns alike, so the readers here select children by node type, never by
field name alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import _text

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = [
    "COMMENTS",
    "Arg",
    "Call",
    "access_of",
    "call_of",
    "decl_keyword",
    "decl_name",
    "first_of",
    "kids",
    "pattern_names",
    "type_name",
]

COMMENTS = frozenset({"comment", "multiline_comment"})
_KEYWORDS = frozenset({"struct", "class", "enum", "extension", "actor"})
_TYPE_WRAPPERS = frozenset(
    {"existential_type", "opaque_type", "optional_type", "type_modifiers"}
)


@dataclass(frozen=True)
class Arg:
    label: str | None
    value: Node


@dataclass(frozen=True)
class Call:
    args: list[Arg]
    # trailing closures; the first one is unlabeled, later ones carry a label
    trailing: list[Arg]


def kids(node: Node) -> list[Node]:
    return [c for c in node.named_children if c.type not in COMMENTS]


def first_of(node: Node, *types: str) -> Node | None:
    return next((c for c in kids(node) if c.type in types), None)


def call_of(suffix: Node | None) -> Call:
    """Arguments and trailing closures of a `call_suffix`."""
    args: list[Arg] = []
    trailing: list[Arg] = []
    label: str | None = None
    for child in kids(suffix) if suffix is not None else []:
        if child.type == "value_arguments":
            for arg in kids(child):
                if arg.type != "value_argument":
                    continue
                tag = arg.child_by_field_name("name")
                value = arg.child_by_field_name("value")
                if value is None:
                    continue
                args.append(Arg(_text(tag) if tag is not None else None, value))
        elif child.type == "simple_identifier":
            label = _text(child)
        elif child.type == "lambda_literal":
            trailing.append(Arg(label, child))
            label = None
    return Call(args, trailing)


def decl_keyword(decl: Node) -> str:
    """`struct` / `class` / `enum` / `extension` / `actor` of a
    `class_declaration`, else `protocol` for a protocol."""
    if decl.type == "protocol_declaration":
        return "protocol"
    return next((c.type for c in decl.children if c.type in _KEYWORDS), "")


def type_name(node: Node | None) -> str:
    """The nominal base name of a type node (`any RoutesBuilder?` ->
    `RoutesBuilder`, `Vapor.Application` -> `Application`), `Array` /
    `Dictionary` for the literal sugar, else an empty string."""
    while node is not None:
        if node.type in _TYPE_WRAPPERS:
            inner = node.child_by_field_name("wrapped")
            node = inner if inner is not None else first_of(node, "user_type")
            continue
        if node.type == "tuple_type":
            items = kids(node)
            node = items[0].child_by_field_name("element") if len(items) == 1 else None
            continue
        break
    if node is None:
        return ""
    if node.type == "array_type":
        return "Array"
    if node.type == "dictionary_type":
        return "Dictionary"
    if node.type != "user_type":
        return ""
    parts = [_text(c) for c in kids(node) if c.type == "type_identifier"]
    return parts[-1] if parts else ""


def decl_name(decl: Node) -> str:
    """Short name of a type declaration; for an extension the extended type,
    dotted when qualified (`extension Foo.Bar` -> `Foo.Bar`)."""
    for child in kids(decl):
        if child.type == "type_identifier":
            return _text(child)
        if child.type == "user_type":
            return ".".join(
                _text(c) for c in kids(child) if c.type == "type_identifier"
            )
        if child.type in ("class_body", "enum_class_body", "protocol_body"):
            break
    return ""


def access_of(decl: Node) -> str:
    """Access a declaration spells out: its first visibility modifier that is
    not a setter restriction (`private(set)`), else an empty string (the
    default, which is `internal` unless a `public extension` or a protocol
    says otherwise)."""
    mods = first_of(decl, "modifiers")
    for mod in kids(mods) if mods is not None else []:
        if mod.type == "visibility_modifier" and "(set)" not in _text(mod):
            return _text(mod)
    return ""


def pattern_names(decl: Node) -> list[str]:
    """Names bound by a property declaration's patterns (tuple patterns
    bind several); the initializer is never read."""
    names: list[str] = []
    stack = [c for c in reversed(kids(decl)) if c.type == "pattern"]
    while stack:
        node = stack.pop()
        if node.type == "simple_identifier":
            names.append(_text(node).strip("`"))
        else:
            stack.extend(reversed(kids(node)))
    return names
