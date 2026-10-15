"""Kotlin parsing that survives tree-sitter-kotlin's silent misparses.

The grammar has two known failure modes, both without an ERROR node:

- a class whose annotations end in a positional argument
  (`@RestController @RequestMapping("/c") class C {...}`) is read as an
  expression statement (`prefix_expression`) as soon as another top-level
  declaration follows it in the file, and
- a body closed on its own line (`companion object { val x = 1 }`) breaks the
  declaration around it the same way, or leaves a missing
  `_automatic_semicolon` / an ERROR node wrapping complete declarations.

A `.kt` file has declarations at top level, never expression statements, so
one there means the declaration was lost. `parse()` then re-reads the file
one top-level declaration at a time (each padded with blank lines so line
numbers stay true), and adds a `;` before the `}` of a one-line body, which
the grammar accepts. A chunk that still misparses is an error line, so the
scanners report a site instead of silently dropping what it held.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_jsutil import _error_line, _parse

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

_DECLARATIONS = frozenset(
    {
        "package_header",
        "import_list",
        "import_header",
        "class_declaration",
        "object_declaration",
        "function_declaration",
        "property_declaration",
        "type_alias",
        "file_annotation",
        "line_comment",
        "multiline_comment",
        "shebang_line",
    }
)
# What an ERROR node may wrap without losing a declaration (one-line bodies).
_WRAPPED = frozenset(
    {
        "function_declaration",
        "property_declaration",
        "class_declaration",
        "object_declaration",
        "companion_object",
        "type_alias",
        "secondary_constructor",
    }
)


@dataclass
class _Root:
    """Top-level nodes of several chunk trees, shaped like a root node for
    the walkers that only read `.children`, `.type` and the error flags."""

    children: list[Node]
    type: str = "source_file"
    is_missing: bool = False
    start_point: tuple[int, int] = (0, 0)

    @property
    def has_error(self) -> bool:
        return any(c.has_error for c in self.children)

    @property
    def named_children(self) -> list[Node]:
        return [c for c in self.children if c.is_named]


@dataclass
class SplitTree:
    root_node: _Root
    keep: list[Tree] = field(default_factory=list)  # keeps the nodes alive
    bad_line: int | None = None  # first top-level node no repair could read


def _misparsed(root: Node) -> int | None:
    """Line of the first top-level node that is not a declaration."""
    for child in root.children:
        if child.type == "ERROR":
            if not all(g.type in _WRAPPED and not g.has_error for g in child.children):
                return _ts.line_of(child)
        elif child.is_named and child.type not in _DECLARATIONS:
            return _ts.line_of(child)
    return None


def _code_braces(data: bytes) -> list[tuple[int, bytes]]:
    """(offset, b"{" | b"}") of every brace that is code: strings, raw
    strings, `${...}` templates, char literals and comments are skipped."""
    out: list[tuple[int, bytes]] = []
    modes = ["code"]
    template_depth: list[int] = []
    i, n, comment = 0, len(data), 0
    while i < n:
        mode, c = modes[-1], data[i : i + 1]
        if comment:
            if data.startswith(b"*/", i):
                comment -= 1
                i += 2
            elif data.startswith(b"/*", i):
                comment += 1
                i += 2
            else:
                i += 1
        elif mode in ("code", "template"):
            if data.startswith(b"//", i):
                end = data.find(b"\n", i)
                i = n if end < 0 else end
            elif data.startswith(b"/*", i):
                comment, i = 1, i + 2
            elif data.startswith(b'"""', i):
                modes.append("raw")
                i += 3
            elif c == b'"':
                modes.append("string")
                i += 1
            elif c == b"'":
                end = data.find(b"'", i + (3 if data[i + 1 : i + 2] == b"\\" else 2))
                i = n if end < 0 else end + 1
            elif c == b"{":
                if mode == "template":
                    template_depth[-1] += 1
                else:
                    out.append((i, c))
                i += 1
            elif c == b"}":
                if mode == "template" and template_depth[-1] == 0:
                    modes.pop()
                    template_depth.pop()
                elif mode == "template":
                    template_depth[-1] -= 1
                else:
                    out.append((i, c))
                i += 1
            else:
                i += 1
        elif c == b"\\" and mode == "string":
            i += 2
        elif data.startswith(b"${", i):
            modes.append("template")
            template_depth.append(0)
            i += 2
        elif mode == "string" and c == b'"':
            modes.pop()
            i += 1
        elif mode == "raw" and data.startswith(b'"""', i):
            modes.pop()
            i += 3
        else:
            i += 1
    return out


def _chunks(data: bytes) -> list[tuple[int, bytes]]:
    """(first line index, text) per top-level block; each ends at the line of
    a `}` that closes depth 0, so annotations stay with their declaration."""
    cuts, depth = [0], 0
    for offset, brace in _code_braces(data):
        depth += 1 if brace == b"{" else -1
        if depth == 0:
            end = data.find(b"\n", offset)
            cuts.append(len(data) if end < 0 else end + 1)
    if cuts[-1] < len(data):
        cuts.append(len(data))
    return [
        (data.count(b"\n", 0, a), data[a:b])
        for a, b in zip(cuts, cuts[1:], strict=False)
        if data[a:b].strip()
    ]


def _semicolons(data: bytes) -> bytes:
    """`{ stmt }` on one line -> `{ stmt; }`, which the grammar reads."""
    opened: list[int] = []
    insert: list[int] = []
    for offset, brace in _code_braces(data):
        if brace == b"{":
            opened.append(offset)
            continue
        if not opened:
            continue
        start = opened.pop()
        body = data[start + 1 : offset]
        if b"\n" not in body and body.strip() and not body.rstrip().endswith(b";"):
            insert.append(offset)
    out = bytearray(data)
    for offset in sorted(insert, reverse=True):
        out[offset:offset] = b";"
    return bytes(out)


def _read_chunk(line: int, text: bytes) -> tuple[Tree, int | None]:
    padded = b"\n" * line + text
    tree = _parse("x.kt", padded)
    bad = _misparsed(tree.root_node)
    if bad is None:
        return tree, None
    fixed = _parse("x.kt", _semicolons(padded))
    again = _misparsed(fixed.root_node)
    return (fixed, None) if again is None else (tree, bad)


def parse(rel: str, data: bytes) -> Tree:
    """The tree of `data`; for Kotlin, re-read piecewise when the whole-file
    parse lost a declaration (see the module docstring)."""
    tree = _parse(rel, data)
    if _ts.language_for(rel) != "kotlin" or rel.endswith(".kts"):
        return tree
    if _misparsed(tree.root_node) is None:
        return tree
    split = SplitTree(_Root([]))
    for line, text in _chunks(data):
        piece, bad = _read_chunk(line, text)
        split.keep.append(piece)
        split.root_node.children += piece.root_node.children
        if bad is not None and split.bad_line is None:
            split.bad_line = bad
    # duck-typed: callers only read `.root_node.children` and the error flags
    return cast("Tree", split)


def error_line(tree: Tree, lang: str) -> int | None:
    """Line of the first syntax error, or None. For Kotlin a missing
    `_automatic_semicolon` and an ERROR node wrapping only complete
    declarations (a one-line body) lose nothing and are not errors."""
    if lang != "kotlin":
        return _error_line(tree)
    bad_line = getattr(tree, "bad_line", None)
    if bad_line is not None:
        return bad_line
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if not node.has_error and not node.is_missing:
            continue
        if node.is_missing:
            if node.type != "_automatic_semicolon":
                return _ts.line_of(node)
            continue
        if node.type == "ERROR":
            kids = node.children
            if kids and all(c.type in _WRAPPED and not c.has_error for c in kids):
                continue
            return _ts.line_of(node)
        stack.extend(reversed(node.children))
    return None
