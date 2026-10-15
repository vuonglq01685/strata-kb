"""Tree-sitter layer shared by the structural extractors (routes, pages,
jobs, symbols).

Everything here sits behind the optional `code` extra: `tree_sitter` and
`tree_sitter_language_pack` are imported lazily, so importing this module
never fails without them -- callers check `available()` first and degrade
to a "not scanned" row. The pack is pinned to 0.13.0 (grammars bundled in
the wheel); 1.x would fetch grammars over the network, breaking the
"output is a pure function of the working tree" contract.
"""

from __future__ import annotations

import re
from functools import cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

LANG_BY_SUFFIX: dict[str, str] = {
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".swift": "swift",
    ".dart": "dart",
    ".css": "css",
    ".scss": "scss",
}

# Node types that are a string literal in some supported grammar.
_STRING_TYPES = frozenset(
    {
        "string",  # js/ts/tsx/python/php
        "template_string",  # js/ts/tsx
        "string_literal",  # java/kotlin/csharp/rust/dart
        "raw_string_literal",  # csharp/go/rust
        "interpreted_string_literal",  # go
        "verbatim_string_literal",  # csharp
        "encapsed_string",  # php double-quoted
        "line_string_literal",  # swift
        "multi_line_string_literal",  # swift
    }
)
# A literal is plain only when every child is delimiter, text or escape.
# Anything else (interpolation, substitution, php variable_name, ...) means
# the value is computed at runtime, so there is no literal to report.
_PLAIN_CHILD = re.compile(r"(content|fragment|_text|escape|escaped_char|_start|_end)")
_OPEN = re.compile(r"""^(?:[rRbBuUfF]{1,2}|@)?(#*)(\"\"\"|'''|"|'|`)""")


def available() -> bool:
    try:
        import tree_sitter_language_pack  # noqa: F401
    except ImportError:
        return False
    return True


def language_for(rel_path: str) -> str | None:
    dot = rel_path.rfind(".")
    return LANG_BY_SUFFIX.get(rel_path[dot:].lower()) if dot >= 0 else None


@cache
def _parser(lang: str) -> Any:
    from tree_sitter_language_pack import get_parser

    return get_parser(lang)  # type: ignore[arg-type]


@cache
def _query(lang: str, query: str) -> Any:
    from tree_sitter import Query
    from tree_sitter_language_pack import get_language

    return Query(get_language(lang), query)  # type: ignore[arg-type]


# tree-sitter-swift reads the `{` after `if let x = try await f(..)` as a
# trailing closure and loses the rest of the function. Parenthesising the
# awaited expression (same line, so line numbers survive) parses cleanly.
_SWIFT_CONDITION = re.compile(rb"^[ \t]*(?:\}[ \t]*else[ \t]+)?(?:if|while|switch)\b")
_SWIFT_AWAIT = re.compile(rb"\btry[?!]?[ \t]+await\b")
_SWIFT_LINE_LIMIT = 4096  # longer lines are never rewritten: keeps the scan linear


def _swift_parenthesised(source: bytes) -> bytes:
    lines = source.split(b"\n")
    for i, line in enumerate(lines):
        if len(line) > _SWIFT_LINE_LIMIT or b"await" not in line:
            continue
        if not _SWIFT_CONDITION.match(line):
            continue
        found = _SWIFT_AWAIT.search(line)
        brace = line.find(b"{", found.end()) if found else -1
        if found is None or brace < 0:
            continue
        end = len(line[:brace].rstrip(b" \t"))
        lines[i] = (
            line[: found.start()] + b"(" + line[found.start() : end] + b")" + line[end:]
        )
    return b"\n".join(lines)


def first_error_row(tree: Tree) -> int | None:
    """0-based row of the first ERROR or MISSING node, None for a clean parse.
    A MISSING token can hide inside a named node (`let = 3`); then the row is
    the innermost node that holds an error."""
    if not tree.root_node.has_error:
        return None
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "ERROR" or node.is_missing:
            return node.start_point[0]
        stack.extend(reversed(node.children))
    node = tree.root_node
    while (inner := next((c for c in node.children if c.has_error), None)) is not None:
        node = inner
    return node.start_point[0]


def parse(lang: str, source: bytes) -> Tree:
    tree = _parser(lang).parse(source)
    if lang == "swift" and tree.root_node.has_error:
        fixed = _swift_parenthesised(source)
        if fixed != source:
            retry = _parser(lang).parse(fixed)
            # a clean retry, or one whose first error lies beyond the mis-parse
            # it repaired (a real error elsewhere, the line a site must name)
            before, after = first_error_row(tree), first_error_row(retry)
            if after is None or (before is not None and after > before):
                return retry
    return tree


def matches(lang: str, query: str, node: Node) -> list[dict[str, list[Node]]]:
    from tree_sitter import QueryCursor

    return [caps for _, caps in QueryCursor(_query(lang, query)).matches(node)]


def node_text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


def line_of(node: Node) -> int:
    return node.start_point[0] + 1


def string_literal(node: Node) -> str | None:
    """Content of a plain string literal, else None (template with
    substitutions, concatenation, identifier, f-string with fields,
    interpolation)."""
    if node.type not in _STRING_TYPES:
        return None
    if any(not _PLAIN_CHILD.search(c.type) for c in node.named_children):
        return None
    text = node_text(node)
    opened = _OPEN.match(text)
    if not opened:
        return None
    hashes, quote = opened.groups()
    closer = quote + hashes
    if not text.endswith(closer) or len(text) < opened.end() + len(closer):
        return None
    inner = text[opened.end() : len(text) - len(closer)]
    # dart joins adjacent literals ('a' 'b') into one node
    if len(quote) == 1 and quote != "`" and re.search(rf"(?<!\\){quote}", inner):
        return None
    return inner
