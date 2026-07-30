from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace

from center_kb import models
from center_kb.mdutils import count_tokens, extract_tables, slugify_id

logger = logging.getLogger("center_kb.ingest.sectioner")


@dataclass
class DocItem:
    kind: str  # "heading" | "text" | "table" | "image"
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
    fallback: bool = False  # id synthesized from an unparsed heading
    page: int | None = None  # page of the heading that opened this node


@dataclass
class SectionUnit:
    id: str
    title: str
    chapter: str
    body_md: str
    tables: list[str]
    page: int | None = None


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
# The identifier is optional: a document with exactly one appendix numbers
# nothing ("APPENDIX. SEARCH AND RESCUE SIGNALS" — ICAO Annex 12). That form
# is only accepted when a separator follows the word, so a heading that merely
# starts with it still takes the identifier branch.
_UNNUMBERED_PART = r"(?:\s*[.:–—-]\s*|\s+([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)\s*[.:–—-]?\s*)"
DEFAULT_APPENDIX_PATTERN = rf"^appendix{_UNNUMBERED_PART}(.*)$"
DEFAULT_ATTACHMENT_PATTERN = rf"^attachment{_UNNUMBERED_PART}(.*)$"
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
        return _part_id("attachment", m.group(1)), (m.group(2) or text).strip()
    if m := cfg.appendix_re.match(text):
        return _part_id("appendix", m.group(1)), (m.group(2) or text).strip()
    if m := _NUMBERED_RE.match(text):
        sid = m.group(1)
        if sid.endswith(".0") and sid.count(".") == 1:
            sid = sid[:-2]
        return sid, m.group(2).strip()
    return None


def _part_id(kind: str, identifier: str | None) -> str:
    return f"{kind}-{identifier.lower()}" if identifier else kind


def _is_part_root(sid: str) -> bool:
    """True for 'appendix', 'attachment-4' and any id namespaced under them."""
    return sid.split("-", 1)[0] in {"appendix", "attachment"}


def _depth_of(sid: str) -> int:
    if sid and sid[0].isdigit():
        return sid.count(".") + 1
    return 1


def _fallback_slug(title: str) -> str:
    """Human-readable id fragment for an unparsed heading. Empty when the
    title has no usable characters, or would masquerade as a numbered
    section id (e.g. a bare page number "123")."""
    slug = slugify_id(title)
    if not slug or slug.replace("-", "").isdigit():
        return ""
    return slug


def _split_front_matter(
    items: list[DocItem], cfg: HeadingConfig
) -> tuple[list[DocItem], list[DocItem]]:
    """Split the stream where the document body starts; everything before
    (cover, TOC, foreword) is front matter — kept out of chapter 1.

    The body starts at the first "Chapter N" heading when the document uses
    that convention — a numbered heading in the foreword ("1. Material
    comprising the Annex proper") must not end the front matter. Without
    that convention the body starts at the first top-level numbered heading
    ("1.0 INTRODUCTION") or appendix/attachment, whichever comes first.
    """
    first_chapter: int | None = None
    first_other: int | None = None
    for i, item in enumerate(items):
        if item.kind != "heading":
            continue
        text = " ".join(item.text.split())
        if text.endswith(":"):  # list intro misread as heading, never structure
            continue
        if cfg.chapter_re.match(text):
            first_chapter = i
            break
        if first_other is None:
            parsed = parse_section_id(text, cfg)
            if parsed and (not parsed[0][0].isdigit() or "." not in parsed[0]):
                first_other = i
    split = first_chapter if first_chapter is not None else first_other
    if split is None:
        return [], items
    return items[:split], items[split:]


class _TreeBuilder:
    """One pass over DocItems -> section tree. State that the old inline loop
    shared across branches (open-node stack, seen paths, buffered orphans)
    lives on the instance so each heading kind gets its own focused method."""

    def __init__(self, cfg: HeadingConfig, part: Part | None) -> None:
        self.cfg = cfg
        self.part = part
        self.root = _Node(id="", title="", depth=0)
        self.stack: list[_Node] = [self.root]
        if part is not None and not part.id[:1].isdigit():
            part_node = _Node(id=part.id, title=part.title, depth=1)
            self.root.children.append(part_node)
            self.stack.append(part_node)
        self.fallback_seq = 0
        # sid -> saved stack path (root..node) from when the node was first
        # seen. Lets a repeated heading (e.g. a running page header) reopen
        # its original node instead of spawning a duplicate.
        self.seen: dict[str, list[_Node]] = {}
        # numeric parent id -> orphan nodes buffered under it. Docling can
        # emit a numbered sub-clause before its structural parent heading
        # (a reading-order artifact, not a document defect -- e.g. a
        # centered "3.6.3" heading physically above a left-margin "3.6.3.1.1"
        # heading gets traversed out of order). When that happens the child
        # would otherwise attach to whatever ancestor is still open (a
        # sibling like "3.6.2"), contaminating it. Buffer it instead and
        # splice it under its true parent once that parent opens; if the
        # parent never opens (skip-level numbering is legitimate elsewhere
        # in this corpus), attach it at the root at the end so content is
        # never silently dropped.
        self.pending_orphans: dict[str, list[_Node]] = {}
        self.last_page: int | None = None

    def feed(self, item: DocItem) -> None:
        if item.page is not None:
            self.last_page = item.page
        if item.kind != "heading":
            if item.text.strip():
                self.stack[-1].body.append(item.text.strip())
            return
        normalized = " ".join(item.text.split())
        if not any(ch.isalnum() for ch in normalized):
            # Horizontal-rule / footnote-separator artifact ("_____",
            # "---"): pure graphics, no content -- skip entirely so it
            # never opens a fallback node.
            return
        if normalized.endswith(":"):
            # List intro / field label misclassified as a heading (e.g.
            # "Source/Content:" or "1.Material comprising the Annex
            # proper:") -- demote to text in the current node so it can
            # never open a spurious section.
            self.stack[-1].body.append(f"**{normalized}**")
            return
        parsed = parse_section_id(normalized, self.cfg)
        if parsed:
            self._attach_parsed(normalized, *parsed)
        else:
            self._attach_fallback(normalized)

    def _namespace(self, sid: str, depth: int, normalized: str) -> tuple[str, int]:
        """ICAO appendices and attachments restart numeric numbering ("1.",
        "2.1"...). Namespace the id under the appendix/attachment top-level
        node so appendix "2.1" becomes "appendix-3-2.1" and never collides
        with chapter section "2.1". Only appendix and attachment nodes
        namespace, plus a seeded part-root node (per-part tree building):
        numeric chapters after a front-matter fallback node (FOREWORD) must
        open normally at root."""
        top = self.stack[1] if len(self.stack) > 1 else None
        if (
            sid[0].isdigit()
            and top is not None
            and (
                _is_part_root(top.id)
                or (
                    self.part is not None
                    and not self.part.id[:1].isdigit()
                    and top.id == self.part.id
                )
            )
            and not self.cfg.chapter_re.match(normalized)
        ):
            return f"{top.id}-{sid}", depth + 1
        return sid, depth

    def _attach_parsed(self, normalized: str, sid: str, title: str) -> None:
        depth = _depth_of(sid)
        sid, depth = self._namespace(sid, depth, normalized)
        if any(n.id == sid for n in self.stack):
            # Heading repeats a node already open (self or ancestor),
            # e.g. a running page header mid-section -> no-op so the
            # following content keeps accumulating where it belongs.
            return
        if sid in self.seen:
            self.stack = list(self.seen[sid])
            return
        while self.stack[-1].depth >= depth:
            self.stack.pop()
        anchor = self.stack[-1]
        node = _Node(id=sid, title=title, depth=depth, page=self.last_page)
        # Detect the orphan pattern: a numeric id whose current
        # attachment point is neither itself nor a real dotted/
        # namespaced ancestor of it. A legitimate skip-level
        # heading (child attaching under a valid but non-immediate
        # ancestor) still passes this check, since the ancestor's
        # id remains a genuine prefix of the child's id.
        is_orphan = (
            sid[0].isdigit()
            and "." in sid
            and anchor is not self.root
            and anchor.id
            and sid != anchor.id
            and not sid.startswith(anchor.id + ".")
            and not sid.startswith(anchor.id + "-")
        )
        if is_orphan:
            parent_sid = sid.rsplit(".", 1)[0]
            self.pending_orphans.setdefault(parent_sid, []).append(node)
        else:
            anchor.children.append(node)
        self.stack.append(node)
        self.seen[sid] = list(self.stack)
        if sid in self.pending_orphans:
            node.children.extend(self.pending_orphans.pop(sid))

    def _attach_fallback(self, normalized: str) -> None:
        # Unparsed heading -> named after its title so SMEs can read
        # the id. Consecutive fallbacks are siblings (never x1-x2-x3
        # chains): pop any open fallback before attaching.
        while self.stack[-1].fallback:
            self.stack.pop()
        parent = self.stack[-1]
        slug = _fallback_slug(normalized)
        if not slug:
            if any(ch.isdigit() for ch in normalized):
                # Bare page number leaked in as a heading — content
                # noise, not structure: demote to body text so it
                # never opens an opaque x{n} section.
                self.stack[-1].body.append(normalized)
                return
            self.fallback_seq += 1
            slug = f"x{self.fallback_seq}"
            logger.warning(
                "synthetic fallback id %r for unparsed heading %r",
                slug,
                normalized,
            )
        sid = f"{parent.id}-{slug}" if parent.id else slug
        if any(n.id == sid for n in self.stack):
            return
        if sid in self.seen:
            # Same heading again (running page header) -> reopen.
            self.stack = list(self.seen[sid])
            return
        node = _Node(
            id=sid, title=normalized, depth=parent.depth + 1,
            fallback=True, page=self.last_page,
        )
        parent.children.append(node)
        self.stack.append(node)
        self.seen[sid] = list(self.stack)

    def finish(self) -> _Node:
        # Any buffered orphan whose implied parent never showed up in this
        # item stream (legitimate skip-level numbering, or a parent lost to
        # some other extraction issue) still needs a home -- attach it at
        # the root rather than lose it.
        for orphans in self.pending_orphans.values():
            self.root.children.extend(orphans)
        return self.root


def _build_tree(
    items: list[DocItem],
    config: HeadingConfig | None = None,
    part: Part | None = None,
) -> _Node:
    builder = _TreeBuilder(config or _DEFAULT_CONFIG, part)
    for item in items:
        builder.feed(item)
    return builder.finish()


def _subtree_md(node: _Node) -> str:
    parts = ["\n\n".join(node.body)]
    for child in node.children:
        parts.append(f"### {child.id} {child.title}")
        parts.append(_subtree_md(child))
    return "\n\n".join(p for p in parts if p.strip())


def order_units(units: list[SectionUnit]) -> list[SectionUnit]:
    """Stable-sort units by heading page (forward-filled).

    Docling can emit headings out of physical order on complex layouts;
    anchoring each unit to its heading's page restores TOC order. Units
    without a page inherit the previous unit's page, so front matter and
    part seeds keep their position. Body items are NOT re-sorted — docling's
    in-page reading order (multi-column aware) is better than a bbox sort.
    """
    keyed: list[tuple[int, int]] = []
    last = 0
    for i, unit in enumerate(units):
        if unit.page is not None:
            last = unit.page
        keyed.append((last, i))
    return [u for _, u in sorted(zip(keyed, units), key=lambda t: t[0])]


def build_units(
    items: list[DocItem],
    max_depth: int = 3,
    min_tokens: int = 200,
    max_unit_tokens: int = 5000,
    config: HeadingConfig | None = None,
    parts: list[Part] | None = None,
) -> list[SectionUnit]:
    if not parts:
        cfg = config or _DEFAULT_CONFIG
        front, rest = _split_front_matter(items, cfg)
        front_units: list[SectionUnit] = []
        if front:
            froot = _build_tree(
                front, config, part=Part("front-matter", "Front Matter", 1)
            )
            front_units = _units_from_tree(
                froot, max_depth, min_tokens, max_unit_tokens, "front-matter"
            )
        root = _build_tree(rest, config)
        return order_units(front_units + _units_from_tree(
            root, max_depth, min_tokens, max_unit_tokens, None
        ))
    units: list[SectionUnit] = []
    for part, part_items in split_by_parts(items, parts):
        if not part_items:
            continue
        root = _build_tree(part_items, config, part=part)
        units += _units_from_tree(
            root, max_depth, min_tokens, max_unit_tokens, part.id
        )
    return order_units(units)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def uncovered(items: list[DocItem], units: list[SectionUnit]) -> list[DocItem]:
    """Content items no unit carries — L3 is the complete-content layer, so
    this must come back empty. Headings are excluded: they become unit ids and
    titles rather than body text, and missing structure is what crosscheck()
    reports. Comparison is whitespace-insensitive because rendering re-joins
    paragraphs."""
    haystack = "\n\n".join(u.body_md for u in units)
    blocks = {_collapse(b) for b in haystack.split("\n\n") if b.strip()}
    blocks.discard("")
    missing = []
    for item in items:
        if item.kind == "heading":
            continue
        needle = _collapse(item.text)
        if not needle:
            continue
        if needle in blocks or f"**{needle}**" in blocks:
            continue
        if needle in _collapse(haystack):  # folded into a larger block
            continue
        missing.append(item)
    return missing


def _units_from_tree(
    root: _Node,
    max_depth: int,
    min_tokens: int,
    max_unit_tokens: int,
    chapter_override: str | None,
) -> list[SectionUnit]:
    units: list[SectionUnit] = []

    def walk(node: _Node, chapter: str) -> None:
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
                    chapter=chapter,
                    body_md=body_md,
                    tables=extract_tables(body_md),
                    page=node.page,
                )
            )
        for child in kept:
            walk(child, chapter)

    for top in root.children:
        # A unit's chapter is the top-level node it lives under -- grouping
        # follows the tree structure, never re-parsed from the id string.
        walk(top, chapter_override if chapter_override is not None else top.id)
    return _with_root_body(root, units)


def _with_root_body(root: _Node, units: list[SectionUnit]) -> list[SectionUnit]:
    """Fold text that arrived before the first heading into the opening unit.

    A numeric part seeds no node of its own (its subsections must keep flat
    ids), so a caption or figure ahead of its first heading accumulates on the
    root -- which nothing renders. Prepending keeps it in reading order without
    inventing a section id. With no units at all there is nowhere to put it;
    ingest's uncovered() check reports that case instead of hiding it.
    """
    lead = "\n\n".join(b for b in root.body if b.strip())
    if not lead or not units:
        return units
    first = units[0]
    body = f"{lead}\n\n{first.body_md}" if first.body_md.strip() else lead
    return [replace(first, body_md=body, tables=extract_tables(body))] + units[1:]
