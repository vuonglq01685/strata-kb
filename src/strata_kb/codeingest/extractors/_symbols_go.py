"""Go exported-name reader for `_symbols_lang.EXPORTERS`.

Go exports an identifier whose first letter is an upper-case Unicode letter
(category `Lu`). The reader lists those at the top level of a file: functions
(kind `function`), types (a struct is `class`, an interface `interface`, any
other type or alias `type`), and `const` / `var` names (both `const`; Go has
no kind for a variable). Methods are not top-level -- they belong to their
type -- and neither are struct fields or interface methods, so none is listed.
Names inside `const (...)` / `var (...)` groups and multi-name specs
(`A, B = 1, 2`) are all read. Names only: an initializer is never read.
Test files (`_test.go`) are skipped by `symbols._skip_rule`.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import _text

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["EXPORTERS"]

_Name = tuple[str, str]

_TYPE_KINDS = {"struct_type": "class", "interface_type": "interface"}


def _exported(name: str) -> bool:
    return bool(name) and unicodedata.category(name[0]) == "Lu"


def _specs(decl: Node) -> list[Node]:
    return [
        s
        for c in decl.named_children
        for s in (c.named_children if c.type == "var_spec_list" else [c])
        if s.type in ("var_spec", "const_spec")
    ]


def _go(tree: Tree, _source: bytes) -> list[_Name]:
    found: list[_Name] = []
    for node in tree.root_node.named_children:
        if node.type == "function_declaration":
            found.append((_text(node.child_by_field_name("name")), "function"))
        elif node.type == "type_declaration":
            for spec in node.named_children:
                if spec.type not in ("type_spec", "type_alias"):
                    continue
                body = spec.child_by_field_name("type")
                kind = _TYPE_KINDS.get(body.type if body is not None else "", "type")
                found.append((_text(spec.child_by_field_name("name")), kind))
        elif node.type in ("const_declaration", "var_declaration"):
            found += [
                (_text(n), "const")
                for spec in _specs(node)
                for n in spec.children_by_field_name("name")
            ]
    return list(dict.fromkeys(f for f in found if _exported(f[0])))


EXPORTERS = {"go": _go}
