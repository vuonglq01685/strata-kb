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
    return sid


def _build_tree(items: list[DocItem]) -> _Node:
    root = _Node(id="", title="", depth=0)
    stack = [root]
    fallback_seq = 0
    for item in items:
        if item.kind == "heading":
            parsed = parse_section_id(item.text)
            if parsed:
                sid, title = parsed
                depth = _depth_of(sid)
            else:
                fallback_seq += 1
                parent = stack[-1]
                sid = f"{parent.id}-x{fallback_seq}" if parent.id else f"x{fallback_seq}"
                title = " ".join(item.text.split())
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
    items: list[DocItem], max_depth: int = 3, min_tokens: int = 200
) -> list[SectionUnit]:
    root = _build_tree(items)
    units: list[SectionUnit] = []

    def walk(node: _Node) -> None:
        kept: list[_Node] = []
        folded: list[_Node] = []
        for child in node.children:
            if child.depth > max_depth or (
                not child.children and count_tokens(_subtree_md(child)) < min_tokens
            ):
                folded.append(child)
            else:
                kept.append(child)
        parts = ["\n\n".join(node.body)]
        parts += [f"### {c.id} {c.title}\n\n{_subtree_md(c)}" for c in folded]
        body_md = "\n\n".join(p for p in parts if p.strip())
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
