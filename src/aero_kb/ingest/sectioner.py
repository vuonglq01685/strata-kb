from __future__ import annotations

import re
from dataclasses import dataclass, field

from aero_kb.mdutils import count_tokens, extract_tables


@dataclass
class DocItem:
    kind: str  # "heading" | "text" | "table"
    text: str
    level: int = 0


@dataclass
class _Node:
    id: str
    title: str
    depth: int
    body: list[str] = field(default_factory=list)
    children: list["_Node"] = field(default_factory=list)


@dataclass
class SectionUnit:
    id: str
    title: str
    chapter: str
    body_md: str
    tables: list[str]


_CHAPTER_RE = re.compile(r"^chapter\s+(\d+)\s*[.:–—-]?\s*(.*)$", re.IGNORECASE)
_APPENDIX_RE = re.compile(
    r"^appendix\s+([0-9A-Za-z]+)\s*[.:–—-]?\s*(.*)$", re.IGNORECASE
)
_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)[.\s]+(.*\S)\s*$")


def parse_section_id(text: str) -> tuple[str, str] | None:
    text = " ".join(text.split())
    if m := _CHAPTER_RE.match(text):
        return m.group(1), (m.group(2) or text).strip()
    if m := _APPENDIX_RE.match(text):
        return f"app{m.group(1).lower()}", (m.group(2) or text).strip()
    if m := _NUMBERED_RE.match(text):
        sid = m.group(1)
        if sid.endswith(".0") and sid.count(".") == 1:
            sid = sid[:-2]
        return sid, m.group(2).strip()
    return None


def _depth_of(sid: str) -> int:
    if sid and sid[0].isdigit():
        return sid.count(".") + 1
    return 1


def _chapter_of(sid: str) -> str:
    if sid and sid[0].isdigit():
        return sid.split(".")[0]
    # Namespaced appendix id like "app3-2.1" -> chapter "app3". Fallback
    # ids ("x1", "app3-x1") have a non-digit after "-" and stay whole.
    head, sep, rest = sid.partition("-")
    if sep and rest[:1].isdigit():
        return head
    return sid


def _build_tree(items: list[DocItem]) -> _Node:
    root = _Node(id="", title="", depth=0)
    stack = [root]
    fallback_seq = 0
    # sid -> saved stack path (root..node) from when the node was first seen.
    # Lets a repeated heading (e.g. a running page header) reopen its
    # original node instead of spawning a duplicate.
    seen: dict[str, list[_Node]] = {}
    for item in items:
        if item.kind == "heading":
            parsed = parse_section_id(item.text)
            if parsed:
                sid, title = parsed
                depth = _depth_of(sid)
                top = stack[1] if len(stack) > 1 else None
                if (
                    sid[0].isdigit()
                    and top is not None
                    and not top.id[0].isdigit()
                    and not _CHAPTER_RE.match(" ".join(item.text.split()))
                ):
                    # ICAO appendices restart numeric numbering ("1.",
                    # "2.1"...). Namespace the id under the non-numeric
                    # top-level node so appendix "2.1" becomes "app3-2.1"
                    # and never collides with chapter section "2.1".
                    sid = f"{top.id}-{sid}"
                    depth += 1
                if any(n.id == sid for n in stack):
                    # Heading repeats a node already open (self or ancestor),
                    # e.g. a running page header mid-section -> no-op so the
                    # following content keeps accumulating where it belongs.
                    continue
                if sid in seen:
                    stack = list(seen[sid])
                    continue
                while stack[-1].depth >= depth:
                    stack.pop()
                node = _Node(id=sid, title=title, depth=depth)
                stack[-1].children.append(node)
                stack.append(node)
                seen[sid] = list(stack)
            else:
                normalized = " ".join(item.text.split())
                if normalized.endswith(":"):
                    # Bold field label misclassified as a heading (e.g.
                    # "Source/Content:") -- demote to text in current node.
                    stack[-1].body.append(f"**{normalized}**")
                    continue
                fallback_seq += 1
                parent = stack[-1]
                sid = f"{parent.id}-x{fallback_seq}" if parent.id else f"x{fallback_seq}"
                title = normalized
                depth = parent.depth + 1
                while stack[-1].depth >= depth:
                    stack.pop()
                node = _Node(id=sid, title=title, depth=depth)
                stack[-1].children.append(node)
                stack.append(node)
        else:
            if item.text.strip():
                stack[-1].body.append(item.text.strip())
    return root


def _subtree_md(node: _Node) -> str:
    parts = ["\n\n".join(node.body)]
    for child in node.children:
        parts.append(f"### {child.id} {child.title}")
        parts.append(_subtree_md(child))
    return "\n\n".join(p for p in parts if p.strip())


def build_units(
    items: list[DocItem],
    max_depth: int = 3,
    min_tokens: int = 200,
    max_unit_tokens: int = 5000,
) -> list[SectionUnit]:
    root = _build_tree(items)
    units: list[SectionUnit] = []

    def walk(node: _Node) -> None:
        def is_depth_fold(child: _Node) -> bool:
            return child.depth > max_depth

        def is_small_leaf(child: _Node) -> bool:
            return (
                not is_depth_fold(child)
                and not child.children
                and count_tokens(_subtree_md(child)) < min_tokens
            )

        def render(fold_predicate) -> str:
            parts = ["\n\n".join(node.body)]
            parts += [
                f"### {c.id} {c.title}\n\n{_subtree_md(c)}"
                for c in node.children
                if fold_predicate(c)
            ]
            return "\n\n".join(p for p in parts if p.strip())

        has_small_leaf = any(is_small_leaf(c) for c in node.children)

        def all_folds(child: _Node) -> bool:
            return is_depth_fold(child) or is_small_leaf(child)

        if has_small_leaf and count_tokens(render(all_folds)) > max_unit_tokens:
            # Folding every small leaf would push this parent's body past the
            # cap -> fold none of them (all-or-nothing); depth folding is
            # unconditional and still applies.
            fold_predicate = is_depth_fold
        else:
            fold_predicate = all_folds

        body_md = render(fold_predicate)
        kept = [c for c in node.children if not fold_predicate(c)]
        if node.depth > 0 and body_md.strip():
            units.append(
                SectionUnit(
                    id=node.id,
                    title=node.title,
                    chapter=_chapter_of(node.id),
                    body_md=body_md,
                    tables=extract_tables(body_md),
                )
            )
        for child in kept:
            walk(child)

    for top in root.children:
        walk(top)
    return units
