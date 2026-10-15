"""Rust exported-name reader for `_symbols_lang.EXPORTERS`.

Exported means plain `pub` (`pub(crate)`, `pub(super)`, `pub(in ..)`, `pub(self)`
and private items are not). Listed at file level and inside `pub mod { .. }`
(items of a nested module are `module::name`; items of a non-`pub` module are
not reachable and are skipped): functions (`function`, also `async` /
`const` / `unsafe` / `extern`), structs and unions (`class`), enums (`enum`),
traits (`interface`), type aliases (`type`), `const` and `static` (`const`),
and modules (`pub mod x`, kind `const` -- the TS `namespace` precedent). A
`pub enum` has every variant exported: `Enum.Variant`, kind `member`
(the `X.KEY` form the other languages use). Items of `extern { .. }` blocks
are listed; `impl` items, trait items, struct fields and macros are not.
Items under `#[cfg(test)]` are skipped (tests/benches/examples directories by
`symbols._skip_rule`).

Re-exports: `pub use a::{B, c as d}` exports `B` and `d`; the kind is guessed
from the spelling (`CamelCase` class, `UPPER_CASE` const, else function) --
the same shortcut the Python reader takes. `pub use a::*` cannot be
enumerated from one file: it is reported as an unreadable line (a partial
coverage site). Names only: a const / static / discriminant value is never
read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._rs_index import flatten_use
from strata_kb.codeingest.extractors._rs_syntax import (
    attrs_before,
    is_cfg_test,
    line_of,
    text,
)

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["EXPORTERS", "unreadable_lines"]

_Name = tuple[str, str]
_KINDS = {
    "function_item": "function",
    "function_signature_item": "function",
    "struct_item": "class",
    "union_item": "class",
    "enum_item": "enum",
    "trait_item": "interface",
    "type_item": "type",
    "const_item": "const",
    "static_item": "const",
}


def _is_pub(item: Node) -> bool:
    vis = next((c for c in item.children if c.type == "visibility_modifier"), None)
    return vis is not None and text(vis) == "pub"


def _guess(name: str) -> str:
    if name[:1].isupper() and not name.isupper():
        return "class"
    return "const" if name.isupper() else "function"


def _variants(owner: str, enum: Node) -> list[_Name]:
    body = enum.child_by_field_name("body")
    return [
        (f"{owner}.{text(v.child_by_field_name('name'))}", "member")
        for v in (body.named_children if body is not None else [])
        if v.type == "enum_variant"
    ]


def _walk(tree: Tree, out: list[_Name], globs: list[int]) -> None:
    stack: list[tuple[Node, str]] = [(tree.root_node, "")]
    while stack:
        parent, prefix = stack.pop()
        for attrs, item in attrs_before(parent):
            kind = item.type
            if is_cfg_test(attrs):
                continue
            if kind == "use_declaration":
                if _is_pub(item):
                    named, star = flatten_use(item)
                    out += [(prefix + a, _guess(a)) for a, _p in named]
                    globs += [line_of(item)] * bool(star)
            elif kind == "foreign_mod_item":
                body = item.child_by_field_name("body")
                if body is not None:
                    stack.append((body, prefix))
            elif not _is_pub(item):
                continue
            elif kind == "mod_item":
                name = text(item.child_by_field_name("name"))
                out.append((prefix + name, "const"))
                body = item.child_by_field_name("body")
                if body is not None:
                    stack.append((body, f"{prefix}{name}::"))
            elif kind in _KINDS:
                name = text(item.child_by_field_name("name"))
                if name and name != "_":
                    out.append((prefix + name, _KINDS[kind]))
                    if kind == "enum_item":
                        out += [(prefix + n, k) for n, k in _variants(name, item)]


def _rust(tree: Tree, _source: bytes) -> list[_Name]:
    out: list[_Name] = []
    _walk(tree, out, [])
    return list(dict.fromkeys(out))


def unreadable_lines(tree: Tree) -> tuple[int, ...]:
    """Lines of `pub use path::*`, whose names this file cannot enumerate."""
    globs: list[int] = []
    _walk(tree, [], globs)
    return tuple(sorted(set(globs)))


EXPORTERS = {"rust": _rust}
