"""Swift exported-name reader for `_symbols_lang.EXPORTERS`.

Exported means `public` or `open`; `internal` (the default), `package`,
`fileprivate` and `private` are not, and nothing inside a type that is not
exported is. A setter restriction (`public private(set) var`,
`private(set) public var`) does not change the getter's access. Listed:
structs, classes and actors (`class`), enums (`enum`), protocols
(`interface`), type aliases and associated types (`type`), functions
(`function`), and `var` / `let` names (`const`; Swift has no kind for a
variable). Members are named `Owner.name`: nested types, methods, properties
and type aliases of an exported type, and an enum's cases as kind `member`
(`Enum.case`). A protocol's requirements are public when the protocol is.

An extension is not a declaration: its members are listed under the extended
type's short name (`extension Array` -> `Array.sum`). Members of a
`public extension` are public unless they say otherwise; members of an
internal extension need an explicit `public`; a `private` / `fileprivate`
extension exports nothing. Initializers, subscripts, deinitializers and
operators have no name and are not listed.

Names only: a property initializer or an enum raw value is never read. Test
code (`Tests/`) is skipped by `symbols._skip_rule`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import _text
from strata_kb.codeingest.extractors._swift_ast import (
    access_of,
    decl_keyword,
    decl_name,
    first_of,
    kids,
    pattern_names,
)

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["EXPORTERS", "HINTS"]

_Name = tuple[str, str]
_Frame = tuple[list["Node"], str, bool]

_PUBLIC = frozenset({"public", "open"})
_HIDDEN = frozenset({"private", "fileprivate"})
_TYPE_KINDS = {"struct": "class", "class": "class", "actor": "class", "enum": "enum"}


def _visible(decl: Node, implicit: bool) -> bool:
    access = access_of(decl)
    return access in _PUBLIC or (implicit and not access)


def _first_ident(decl: Node, kind: str) -> str:
    node = first_of(decl, kind)
    return _text(node).strip("`") if node is not None else ""


def _members(decl: Node, owner: str, implicit: bool) -> list[_Name]:
    """Names one member declaration exports (not its nested members)."""
    kind = decl.type
    if kind == "enum_entry":
        return [
            (f"{owner}.{_text(n).strip('`')}", "member")
            for n in decl.children_by_field_name("name")
            if n.type == "simple_identifier"
        ]
    if not _visible(decl, implicit):
        return []
    if (
        kind in ("function_declaration", "protocol_function_declaration")
        or kind == "macro_declaration"
    ):
        names = [(_first_ident(decl, "simple_identifier"), "function")]
    elif kind in ("property_declaration", "protocol_property_declaration"):
        names = [(n, "const") for n in pattern_names(decl)]
    elif kind in ("typealias_declaration", "associatedtype_declaration"):
        names = [(_first_ident(decl, "type_identifier"), "type")]
    else:
        return []
    return [(f"{owner}.{n}" if owner else n, k) for n, k in names if n]


def _swift(tree: Tree, _source: bytes) -> list[_Name]:
    found: list[_Name] = []
    stack: list[_Frame] = [(kids(tree.root_node), "", False)]
    while stack:
        members, owner, implicit = stack.pop()
        for member in members:
            if member.type not in ("class_declaration", "protocol_declaration"):
                found += _members(member, owner, implicit)
                continue
            body = member.child_by_field_name("body")
            inner = kids(body) if body is not None else []
            keyword = decl_keyword(member)
            name = decl_name(member)
            if keyword == "extension":
                access = access_of(member)
                if name and access not in _HIDDEN:
                    stack.append((inner, name, access in _PUBLIC))
                continue
            if not name or not _visible(member, implicit):
                continue
            full = f"{owner}.{name}" if owner else name
            kind = (
                "interface"
                if keyword == "protocol"
                else _TYPE_KINDS.get(keyword, "class")
            )
            found.append((full, kind))
            stack.append((inner, full, keyword == "protocol"))
    return list(dict.fromkeys(found))


EXPORTERS = {"swift": _swift}
HINTS = {"swift": re.compile(rb"\b(?:public|open)\b")}  # nothing else is exported
