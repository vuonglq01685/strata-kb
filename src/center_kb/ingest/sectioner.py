from __future__ import annotations

import re
from dataclasses import dataclass, field

from center_kb import models
from center_kb.mdutils import count_tokens, extract_tables


@dataclass
class DocItem:
    kind: str  # "heading" | "text" | "table"
    text: str
    level: int = 0
    page: int | None = None


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


@dataclass(frozen=True)
class Part:
    """One top-level segment of the document, taken from the PDF outline."""

    id: str
    title: str
    page: int  # 1-based page where the part starts


def split_by_parts(
    items: list[DocItem], parts: list[Part]
) -> list[tuple[Part, list[DocItem]]]:
    """Bucket the item stream by part page ranges (parts sorted by page).

    An item belongs to the last part whose page <= the item's page; items
    without a page inherit the previous item's page; items before the first
    part's page fall into the first part.
    """
    buckets: dict[str, list[DocItem]] = {p.id: [] for p in parts}
    idx = 0
    last_page: int | None = None
    for item in items:
        page = item.page if item.page is not None else last_page
        if item.page is not None:
            last_page = item.page
        while idx + 1 < len(parts) and page is not None and page >= parts[idx + 1].page:
            idx += 1
        buckets[parts[idx].id].append(item)
    return [(p, buckets[p.id]) for p in parts]


DEFAULT_CHAPTER_PATTERN = r"^chapter\s+(\d+)\s*[.:–—-]?\s*(.*)$"
DEFAULT_APPENDIX_PATTERN = r"^appendix\s+([0-9A-Za-z]+)\s*[.:–—-]?\s*(.*)$"
DEFAULT_ATTACHMENT_PATTERN = r"^attachment\s+([0-9A-Za-z]+)\s*[.:–—-]?\s*(.*)$"
_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)[.\s]+(.*\S)\s*$")


def _compile_heading(name: str, pattern: str) -> re.Pattern[str]:
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"{name}: invalid regex — {exc}") from exc
    if rx.groups < 2:
        raise ValueError(f"{name}: needs at least 2 capture groups (identifier, title)")
    return rx


@dataclass
class HeadingConfig:
    """Document heading convention. Defaults to the common English convention
    ("Chapter N", "Appendix X", "Attachment N") — documents using a different
    convention override it at ingest time; the config used is persisted to
    _manifest.yaml."""

    chapter_pattern: str = DEFAULT_CHAPTER_PATTERN
    appendix_pattern: str = DEFAULT_APPENDIX_PATTERN
    attachment_pattern: str = DEFAULT_ATTACHMENT_PATTERN

    def __post_init__(self) -> None:
        self.chapter_re = _compile_heading("chapter_pattern", self.chapter_pattern)
        self.appendix_re = _compile_heading("appendix_pattern", self.appendix_pattern)
        self.attachment_re = _compile_heading(
            "attachment_pattern", self.attachment_pattern
        )


_DEFAULT_CONFIG = HeadingConfig()


def resolve_heading_config(
    chapter_pattern: str,
    appendix_pattern: str,
    attachment_pattern: str,
    previous: "models.IngestConfig | None",
) -> HeadingConfig:
    """Priority: explicit arg > previous config in manifest (re-ingest) > default."""
    prev_ch = previous.chapter_pattern if previous else DEFAULT_CHAPTER_PATTERN
    prev_app = previous.appendix_pattern if previous else DEFAULT_APPENDIX_PATTERN
    prev_att = (
        previous.attachment_pattern if previous else ""
    ) or DEFAULT_ATTACHMENT_PATTERN
    return HeadingConfig(
        chapter_pattern=chapter_pattern or prev_ch,
        appendix_pattern=appendix_pattern or prev_app,
        attachment_pattern=attachment_pattern or prev_att,
    )


def parse_section_id(
    text: str, config: HeadingConfig | None = None
) -> tuple[str, str] | None:
    cfg = config or _DEFAULT_CONFIG
    text = " ".join(text.split())
    if m := cfg.chapter_re.match(text):
        return m.group(1), (m.group(2) or text).strip()
    if m := cfg.attachment_re.match(text):
        return f"att{m.group(1).lower()}", (m.group(2) or text).strip()
    if m := cfg.appendix_re.match(text):
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


def _build_tree(items: list[DocItem], config: HeadingConfig | None = None) -> _Node:
    cfg = config or _DEFAULT_CONFIG
    root = _Node(id="", title="", depth=0)
    stack = [root]
    fallback_seq = 0
    # sid -> saved stack path (root..node) from when the node was first seen.
    # Lets a repeated heading (e.g. a running page header) reopen its
    # original node instead of spawning a duplicate.
    seen: dict[str, list[_Node]] = {}
    for item in items:
        if item.kind == "heading":
            parsed = parse_section_id(item.text, cfg)
            if parsed:
                sid, title = parsed
                depth = _depth_of(sid)
                top = stack[1] if len(stack) > 1 else None
                if (
                    sid[0].isdigit()
                    and top is not None
                    and top.id.startswith(("app", "att"))
                    and not cfg.chapter_re.match(" ".join(item.text.split()))
                ):
                    # ICAO appendices and attachments restart numeric
                    # numbering ("1.", "2.1"...). Namespace the id under the
                    # appendix/attachment top-level node so appendix "2.1"
                    # becomes "app3-2.1" and never collides with chapter
                    # section "2.1". Only appendix ("app*") and attachment
                    # ("att*") nodes namespace: numeric chapters after a
                    # front-matter fallback node (FOREWORD -> "x1") must
                    # open normally at root.
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
    config: HeadingConfig | None = None,
) -> list[SectionUnit]:
    root = _build_tree(items, config)
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
