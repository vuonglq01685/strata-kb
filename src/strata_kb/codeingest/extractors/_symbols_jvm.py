"""Java and Kotlin exported-name readers for `_symbols_lang.EXPORTERS`.

Java exports a file's `public` top-level types, their `public static
final` fields (every field of an interface) and an enum's constants.
Kotlin exports its top-level declarations that are not `private` or
`internal`, plus the `const val`s of an `object` or companion object and
an enum's entries. Members are `Owner.NAME` with kind `member`. Names only:
a constant's value is never read. Nested types are not exported (spec 5.6
lists top-level types).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import _text

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["EXPORTERS"]

_Name = tuple[str, str]

_JAVA_KINDS = {
    "class_declaration": "class",
    "record_declaration": "class",
    "interface_declaration": "interface",
    "annotation_type_declaration": "interface",
    "enum_declaration": "enum",
}
_HIDDEN = frozenset({"private", "internal", "protected"})


def _modifiers(decl: Node) -> set[str]:
    """Keyword modifiers (`public`, `static`, ...); annotations excluded."""
    return {
        c.type
        for mods in decl.children
        if mods.type == "modifiers"
        for c in mods.children
        if not c.type.endswith("annotation")
    }


def _java_fields(owner: str, body: Node, implicit: bool) -> list[_Name]:
    out: list[_Name] = []
    for member in body.children:
        if member.type not in ("field_declaration", "constant_declaration"):
            continue
        if not implicit and not {"public", "static", "final"} <= _modifiers(member):
            continue
        out += [
            (f"{owner}.{_text(d.child_by_field_name('name'))}", "member")
            for d in member.children_by_field_name("declarator")
        ]
    return out


def _java(tree: Tree, _source: bytes) -> list[_Name]:
    out: list[_Name] = []
    for decl in tree.root_node.children:
        kind = _JAVA_KINDS.get(decl.type)
        if kind is None or "public" not in _modifiers(decl):
            continue
        name = _text(decl.child_by_field_name("name"))
        out.append((name, kind))
        body = decl.child_by_field_name("body")
        if body is None:
            continue
        if kind == "enum":
            out += [
                (f"{name}.{_text(c.child_by_field_name('name'))}", "member")
                for c in body.children
                if c.type == "enum_constant"
            ]
            for extra in (
                c for c in body.children if c.type == "enum_body_declarations"
            ):
                out += _java_fields(name, extra, implicit=False)
        else:
            out += _java_fields(name, body, implicit=kind == "interface")
    return out


# --- Kotlin -----------------------------------------------------------------


def _first_name(node: Node, types: tuple[str, ...]) -> str:
    return _text(next((c for c in node.children if c.type in types), None))


def _property_names(prop: Node) -> list[str]:
    return [
        _text(next((c for c in v.children if c.type == "simple_identifier"), None))
        for v in prop.children
        if v.type == "variable_declaration"
    ] + [
        _text(next((c for c in w.children if c.type == "simple_identifier"), None))
        for m in prop.children
        if m.type == "multi_variable_declaration"
        for w in m.children
        if w.type == "variable_declaration"
    ]


def _const_members(owner: str, body: Node | None) -> list[_Name]:
    out: list[_Name] = []
    for prop in body.children if body is not None else []:
        if prop.type != "property_declaration":
            continue
        words = _text_modifiers(prop)
        if "const" in words and not words & _HIDDEN:
            out += [(f"{owner}.{n}", "member") for n in _property_names(prop)]
    return out


def _kotlin_class(decl: Node) -> list[_Name]:
    name = _first_name(decl, ("type_identifier", "simple_identifier"))
    keywords = {c.type for c in decl.children}
    kind = (
        "interface"
        if "interface" in keywords
        else "enum"
        if "enum" in keywords
        else "class"
    )
    out = [(name, kind)]
    body = next(
        (c for c in decl.children if c.type in ("class_body", "enum_class_body")), None
    )
    for member in body.children if body is not None else []:
        if member.type == "enum_entry":
            out.append(
                (f"{name}.{_first_name(member, ('simple_identifier',))}", "member")
            )
        elif (
            member.type == "companion_object" and not _text_modifiers(member) & _HIDDEN
        ):
            inner = next((c for c in member.children if c.type == "class_body"), None)
            out += _const_members(name, inner)
    return out


def _text_modifiers(decl: Node) -> set[str]:
    return {
        _text(c)
        for mods in decl.children
        if mods.type == "modifiers"
        for c in mods.children
    }


def _kotlin(tree: Tree, _source: bytes) -> list[_Name]:
    out: list[_Name] = []
    for decl in tree.root_node.children:
        if _text_modifiers(decl) & _HIDDEN:
            continue
        if decl.type == "class_declaration":
            out += _kotlin_class(decl)
        elif decl.type == "object_declaration":
            name = _first_name(decl, ("type_identifier", "simple_identifier"))
            body = next((c for c in decl.children if c.type == "class_body"), None)
            out += [(name, "class"), *_const_members(name, body)]
        elif decl.type == "function_declaration":
            out.append((_first_name(decl, ("simple_identifier",)), "function"))
        elif decl.type == "property_declaration":
            out += [(n, "const") for n in _property_names(decl)]
        elif decl.type == "type_alias":
            out.append((_first_name(decl, ("type_identifier",)), "type"))
    return out


EXPORTERS = {"java": _java, "kotlin": _kotlin}
