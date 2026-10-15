"""C# exported-name reader for `_symbols_lang.EXPORTERS`.

Exports the `public` types of a file (class, record and struct are `class`,
`interface`, `enum`, `delegate` is `type`), including `public` types nested
in a public type (`Outer.Inner`); their `public const` and `public static
readonly` fields; and an enum's members, all as `Owner.NAME` with kind
`member`. `internal`, `private`, `protected` and `file` declarations are not
exported, nor is anything inside a non-public type. A `partial` type spread
over several declarations of one file is listed once. Names only: a
constant's initializer is never read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _cs_ast as ast
from strata_kb.codeingest.extractors._routes_jsutil import _text

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["EXPORTERS"]

_Name = tuple[str, str]

_KINDS = {
    "class_declaration": "class",
    "struct_declaration": "class",
    "record_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "delegate_declaration": "type",
}
_NAMESPACES = ("namespace_declaration", "file_scoped_namespace_declaration")


def _fields(owner: str, decl: Node) -> list[_Name]:
    # interface members are public without saying so
    implicit = decl.type == "interface_declaration"
    out: list[_Name] = []
    for member in ast.body_members(decl):
        if member.type != "field_declaration":
            continue
        mods = ast.modifiers(member)
        if "public" not in mods and not (implicit and "const" in mods):
            continue
        if not ("const" in mods or {"static", "readonly"} <= mods):
            continue
        variables = next(
            (c for c in member.children if c.type == "variable_declaration"), None
        )
        out += [
            (f"{owner}.{_text(d.child_by_field_name('name'))}", "member")
            for d in (variables.children if variables is not None else [])
            if d.type == "variable_declarator"
        ]
    return out


def _type(decl: Node, prefix: str) -> list[_Name]:
    kind = _KINDS[decl.type]
    mods = ast.modifiers(decl)
    if "public" not in mods or "file" in mods:
        return []
    name = prefix + ast.decl_name(decl)
    out: list[_Name] = [(name, kind)]
    if kind == "enum":
        body = decl.child_by_field_name("body")
        out += [
            (f"{name}.{ast.decl_name(m)}", "member")
            for m in (body.named_children if body is not None else [])
            if m.type == "enum_member_declaration"
        ]
    elif kind != "type":
        out += _fields(name, decl)
        for nested in ast.body_members(decl):
            if nested.type in _KINDS:
                out += _type(nested, name + ".")
    return out


def _scope(node: Node, out: list[_Name]) -> None:
    for child in ast.members_of(node):
        if child.type in _KINDS:
            out += _type(child, "")
        elif child.type in _NAMESPACES:
            body = child.child_by_field_name("body")
            _scope(body if body is not None else child, out)


def _csharp(tree: Tree, _source: bytes) -> list[_Name]:
    found: list[_Name] = []
    _scope(tree.root_node, found)
    return list(dict.fromkeys(found))


EXPORTERS = {ast.LANG: _csharp}
