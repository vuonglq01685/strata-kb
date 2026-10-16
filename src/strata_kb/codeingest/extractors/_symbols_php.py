"""PHP exported-name reader for `_symbols_lang.EXPORTERS`.

Exports the classes (also `abstract`, `final`, `readonly`) and traits of a
file as kind `class`, its interfaces as `interface` and its enums as `enum`,
under their short names (the namespace is not part of the name). Each type's
non-private, non-protected constants are listed as `Type::CONST` and an
enum's cases as `Enum.CASE`, both kind `member`; constants of an interface
are public without saying so. Types under a braced `namespace`, an `if`
guard (`if (!class_exists(...)) { class X {} }`) or a block at the top level
are found; types inside a function body or an anonymous class are not.
Names only: a constant's or case's value is never read. Top-level functions
and `define()` / `const` constants are not exported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import _text

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["EXPORTERS"]

_Name = tuple[str, str]

_KINDS = {
    "class_declaration": "class",
    "trait_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
}
_BLOCKS = frozenset(
    {
        "namespace_definition", "compound_statement", "if_statement", "else_clause",
        "else_if_clause", "colon_block", "declare_statement", "try_statement",
        "catch_clause", "finally_clause",
    }
)  # fmt: skip


def _members(owner: str, decl: Node) -> list[_Name]:
    body = decl.child_by_field_name("body")
    out: list[_Name] = []
    for member in body.named_children if body is not None else []:
        if member.type == "enum_case":
            case = member.child_by_field_name("name")
            out.append((f"{owner}.{_text(case)}", "member"))
        elif member.type == "const_declaration":
            visibility = next(
                (_text(c) for c in member.children if c.type == "visibility_modifier"),
                "public",
            )
            if visibility != "public":
                continue
            out += [
                (f"{owner}::{_text(e.named_children[0])}", "member")
                for e in member.named_children
                if e.type == "const_element" and e.named_children
            ]
    return out


def _php(tree: Tree, _source: bytes) -> list[_Name]:
    found: list[_Name] = []
    stack = list(reversed(tree.root_node.named_children))
    while stack:
        node = stack.pop()
        if node.type in _KINDS:
            name = _text(node.child_by_field_name("name"))
            found.append((name, _KINDS[node.type]))
            found += _members(name, node)
        elif node.type in _BLOCKS:
            stack.extend(reversed(node.named_children))
    return list(dict.fromkeys(found))


EXPORTERS = {"php": _php}
