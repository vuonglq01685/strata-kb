"""Dart exported-name reader for `_symbols_lang.EXPORTERS`.

Dart has one visibility rule: a top-level name that starts with `_` is
library-private, anything else is public. The reader lists those names at the
top level of a file: classes (also `abstract` / `base` / `sealed` /
`interface` / `final` / `mixin class`, and `class A = B with C`), mixins,
extensions with a name and extension types (all `class`), enums (`enum`),
typedefs (`type`), functions and getters / setters (`function`), and
top-level variables (`const` / `final` / `var` / typed; kind `const`, Dart
has no kind for a variable). A public enum's values are listed as
`Enum.value`, kind `member`; a value starting with `_` is private. Class
members are not listed: only top-level names and enum values.

A file that is `part of` a library is read like any other: its top-level
names belong to the library's namespace, so skipping it would hide real
public names. Code generated into such files (`*.g.dart`, `*.freezed.dart`,
...) is skipped by `symbols._skip_rule` instead. Names only: an initializer
or an enum value's constructor arguments are never read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import _text
from strata_kb.codeingest.extractors._swift_ast import first_of, kids

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["EXPORTERS"]

_Name = tuple[str, str]

_CLASS_LIKE = frozenset(
    {"class_definition", "mixin_declaration", "extension_declaration",
     "extension_type_declaration"}
)  # fmt: skip
_VARIABLE_LISTS = frozenset(
    {"initialized_identifier_list", "static_final_declaration_list"}
)
_ACCESSORS = frozenset({"function_signature", "getter_signature", "setter_signature"})


def _ident(node: Node | None) -> str:
    return _text(node) if node is not None and node.type == "identifier" else ""


def _class_name(decl: Node) -> str:
    named = decl.child_by_field_name("name")
    if named is not None:
        return _ident(named)
    if decl.type == "mixin_declaration":
        return _ident(first_of(decl, "identifier"))
    # `class A = B with C;`
    alias = first_of(decl, "mixin_application_class")
    return _ident(first_of(alias, "identifier")) if alias is not None else ""


def _typedef_name(decl: Node) -> str:
    """`typedef Cb = ...` names its first type; the old form
    `typedef R Name(args);` names the last type before the parameters."""
    types = [c for c in kids(decl) if c.type == "type_identifier"]
    if any(not c.is_named and c.type == "=" for c in decl.children):
        return _text(types[0]) if types else ""
    before = []
    for child in kids(decl):
        if child.type == "formal_parameter_list":
            break
        if child.type == "type_identifier":
            before.append(child)
    return _text(before[-1]) if before else ""


def _enum_values(decl: Node, name: str) -> list[_Name]:
    body = decl.child_by_field_name("body")
    return [
        (f"{name}.{value}", "member")
        for c in (kids(body) if body is not None else [])
        if c.type == "enum_constant"
        and (value := _ident(c.child_by_field_name("name")))
        and not value.startswith("_")
    ]


def _top_level(node: Node) -> list[_Name]:
    kind = node.type
    if kind in _CLASS_LIKE:
        return [(_class_name(node), "class")]
    if kind == "enum_declaration":
        name = _ident(node.child_by_field_name("name"))
        return [(name, "enum"), *(_enum_values(node, name) if name else [])]
    if kind == "type_alias":
        return [(_typedef_name(node), "type")]
    if kind in _ACCESSORS:
        return [(_ident(node.child_by_field_name("name")), "function")]
    if kind in _VARIABLE_LISTS:
        return [
            (_ident(first_of(item, "identifier")), "const")
            for item in kids(node)
            if item.type in ("initialized_identifier", "static_final_declaration")
        ]
    return []


def _dart(tree: Tree, _source: bytes) -> list[_Name]:
    found = [f for node in kids(tree.root_node) for f in _top_level(node)]
    return list(
        dict.fromkeys(
            (n, k) for n, k in found if n and not n.split(".")[0].startswith("_")
        )
    )


EXPORTERS = {"dart": _dart}
