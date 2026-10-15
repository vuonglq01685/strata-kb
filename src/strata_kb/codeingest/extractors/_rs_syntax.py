"""Small tree-sitter-rust readers shared by the Rust route adapters and the
module index: path segments, attributes, token trees, strings.

Everything here is iterative (no recursion on tree depth) and tolerant: a
shape it does not know gives `None` / an empty list, never an exception.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tree_sitter import Node

__all__ = [
    "Attr",
    "attrs_before",
    "crate_tail",
    "elements",
    "is_cfg_test",
    "line_of",
    "plain_path",
    "segments",
    "string_of",
    "text",
    "walk",
]

_IDENT = {"identifier", "type_identifier", "crate", "self", "super", "metavariable"}
_PLAIN_PATH = re.compile(r"[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*")
_TEST_ATTRS = frozenset({"test", "rstest", "test_case"})


def text(node: Node | None) -> str:
    return _ts.node_text(node) if node is not None else ""


def line_of(node: Node) -> int:
    return _ts.line_of(node)


def walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        stack.extend(reversed(cur.children))


def segments(node: Node | None) -> tuple[str, ...] | None:
    """`a::b::<T>::c` -> ("a", "b", "c"); generics are dropped; None for
    anything that is not a plain path."""
    out: list[str] = []
    cur = node
    while cur is not None:
        kind = cur.type
        if kind in _IDENT:
            out.append(text(cur))
            return tuple(reversed(out))
        if kind in ("scoped_identifier", "scoped_type_identifier"):
            out.append(text(cur.child_by_field_name("name")))
            cur = cur.child_by_field_name("path")
        elif kind == "generic_type":
            cur = cur.child_by_field_name("type")
        elif kind == "generic_function":
            cur = cur.child_by_field_name("function")
        else:
            return None
    return tuple(reversed(out)) if out else None


def crate_tail(segs: tuple[str, ...], names: tuple[str, ...]) -> tuple[str, ...] | None:
    """`shuttle_axum::axum::routing::get` -> ("axum", "routing", "get"): the
    path from the framework crate on, also when a wrapper crate re-exports
    it (first two segments only). None when the path is not the framework's."""
    for i, seg in enumerate(segs[:2]):
        if seg in names:
            return segs[i:]
    return None


def plain_path(node: Node | None) -> str | None:
    """Handler text: an identifier or `a::b::c` path, else None."""
    if node is None or node.type not in ("identifier", "scoped_identifier"):
        return None
    flat = "".join(text(node).split())
    return flat if _PLAIN_PATH.fullmatch(flat) else None


def string_of(node: Node | None) -> str | None:
    return _ts.string_literal(node) if node is not None else None


class Attr:
    """One `#[...]` attribute: path segments, the argument token tree."""

    __slots__ = ("args", "line", "node", "segs", "value")

    def __init__(self, node: Node):
        self.node = node
        self.line = line_of(node)
        inner = next((c for c in node.named_children if c.type == "attribute"), None)
        self.segs: tuple[str, ...] = ()
        self.args: Node | None = None
        self.value: Node | None = None
        if inner is not None:
            head = next(
                (c for c in inner.named_children if c.type != "token_tree"), None
            )
            self.segs = segments(head) or ()
            self.args = inner.child_by_field_name("arguments")
            self.value = inner.child_by_field_name("value")

    @property
    def name(self) -> str:
        return self.segs[-1] if self.segs else ""


def attrs_before(parent: Node) -> Iterator[tuple[list[Attr], Node]]:
    """(attributes, item) pairs of `parent`'s children, in order. Attributes
    are siblings that precede the item they annotate; comments between them
    are skipped."""
    pending: list[Attr] = []
    for child in parent.named_children:
        if child.type == "attribute_item":
            pending.append(Attr(child))
        elif child.type in ("line_comment", "block_comment", "inner_attribute_item"):
            continue
        else:
            yield pending, child
            pending = []


def is_cfg_test(attrs: list[Attr]) -> bool:
    """`#[cfg(test)]`, `#[test]`, `#[tokio::test]`, `#[actix_web::test]`..."""
    for attr in attrs:
        if attr.name in _TEST_ATTRS:
            return True
        if attr.name == "cfg" and re.search(
            r"(?<!not\()\btest\b", "".join(text(attr.args).split())
        ):
            return True
    return False


def elements(tree: Node | None) -> list[list[Node]]:
    """Comma-separated top-level elements of a token tree / macro body, as
    node lists (delimiters stripped). Anonymous tokens (`::`, `=`) stay."""
    if tree is None:
        return []
    kids = list(tree.children)
    if len(kids) >= 2 and text(kids[0]) in ("(", "[", "{"):
        kids = kids[1:-1] if text(kids[-1]) in (")", "]", "}") else kids[1:]
    out: list[list[Node]] = [[]]
    for kid in kids:
        if kid.type == "," or text(kid) == ",":
            out.append([])
        elif kid.type not in ("line_comment", "block_comment"):
            out[-1].append(kid)
    return [e for e in out if e]
