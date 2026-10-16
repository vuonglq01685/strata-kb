"""Request-type field reader for C#: the fields of a `[FromBody]` type when it
is a plain class, struct or record declared in the repo.

**Required.** The `required` keyword or a `[Required]` attribute (also
`[property: Required]`) is required; every other member is not. A positional
record parameter has no keyword to carry, so it is required unless it has a
default value. A type with a base class, an interface other than an `I...`
name, a `partial` declaration, an enum or an interface is not plain (its list
would be incomplete), so it reads as undeclared -- the same rule the TS and
JVM readers follow. Public instance properties with a getter and public
instance fields are listed; `[JsonIgnore]` members are skipped and
`[JsonPropertyName("x")]` / `[JsonProperty("x")]` renames.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _cs_ast as ast
from strata_kb.codeingest.extractors._routes_jsutil import Field, _common_dirs, _text

if TYPE_CHECKING:
    from tree_sitter import Node

_WRAPPED = re.compile(
    r"(?:\w+\.)*(?:List|IList|IEnumerable|ICollection|IReadOnlyList|IReadOnlyCollection"
    r"|HashSet|ISet|Collection|Task|ActionResult)<\s*(.+)>"
)
_INTERFACE = re.compile(r"I[A-Z]\w*")
_PLAIN = frozenset({"class_declaration", "struct_declaration", "record_declaration"})


def element_type(name: str) -> str:
    """`List<Foo>` / `Foo[]` / `Foo?` / `a.b.Foo<T>` -> `Foo`."""
    name = name.strip()
    while True:
        wrapped = _WRAPPED.fullmatch(name)
        if wrapped:
            name = wrapped.group(1).strip()
        elif name.endswith(("[]", "?")):
            name = name[:-2] if name.endswith("[]") else name[:-1]
        else:
            break
    return ast.simple_name(name)


def _json_name(attrs: list[ast.Attr], default: str) -> str:
    for attr in attrs:
        if attr.name in ("JsonPropertyName", "JsonProperty"):
            return (
                ast.literal(attr.arg("", "name", "propertyName", "PropertyName"))
                or default
            )
    return default


def _member(member: Node) -> list[Field]:
    mods = ast.modifiers(member)
    if "public" not in mods or mods & {"static", "const"}:
        return []
    attrs = ast.attrs_of(member)
    if any(a.name == "JsonIgnore" for a in attrs):
        return []
    required = "required" in mods or any(a.name == "Required" for a in attrs)
    if member.type == "property_declaration":
        accessors = member.child_by_field_name("accessors")
        names = {
            _text(c.child_by_field_name("name"))
            for c in (accessors.named_children if accessors is not None else [])
        }
        if "get" not in names:  # write-only, or `=> expr`: computed
            return []
        name = _text(member.child_by_field_name("name"))
        typ = _text(member.child_by_field_name("type"))
        return [(_json_name(attrs, name), typ, required)]
    if member.type == "field_declaration":
        decl = next(
            (c for c in member.children if c.type == "variable_declaration"), None
        )
        typ = _text(decl.child_by_field_name("type")) if decl is not None else ""
        return [
            (_json_name(attrs, name), typ, required)
            for d in (decl.children if decl is not None else [])
            if d.type == "variable_declarator"
            for name in [_text(d.child_by_field_name("name"))]
        ]
    return []


def _plain_fields(decl: Node) -> list[Field] | None:
    if decl.type not in _PLAIN or "partial" in ast.modifiers(decl):
        return None
    if any(not _INTERFACE.fullmatch(b) for b in ast.base_names(decl)):
        return None
    out: list[Field] = []
    positional = next((c for c in decl.children if c.type == "parameter_list"), None)
    if decl.type == "record_declaration" and positional is not None:
        for param in ast.params(decl):
            if any(a.name == "JsonIgnore" for a in param.attrs):
                continue
            explicit = any(a.name == "Required" for a in param.attrs)
            out.append(
                (
                    _json_name(param.attrs, param.name),
                    param.type,
                    explicit or not param.default,
                )
            )
    for member in ast.body_members(decl):
        out += _member(member)
    return out


def declared_fields(
    root: Path, files: list[str], type_name: str, near: str
) -> list[Field] | None:
    """Fields of `type_name` when it is a plain class/struct/record declared
    in the repo, else None. A declaration in `near` (the route's file) wins,
    then the closest directory (shortcut: namespaces and usings are not
    followed -- upgrade if a repo hits two same-named types). Only a C# route
    reads C# types."""
    if not near.endswith(".cs"):
        return None
    name = element_type(type_name)
    candidates = sorted(
        ast.declared_names(root, files).get(name, []),
        key=lambda rel: (rel != near, -_common_dirs(rel, near), rel),
    )
    for rel in candidates:
        data = ast.source(root, rel)
        if data is None:
            continue
        for decl in ast.type_decls(ast.tree(root, rel, data).root_node):
            if ast.decl_name(decl) == name:
                return _plain_fields(decl)
    return None
