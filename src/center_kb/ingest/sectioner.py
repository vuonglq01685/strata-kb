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
    # (left, top, right, bottom), TOPLEFT origin, page units — None when
    # docling has no provenance. Only consulted on a page whose numbered
    # headings arrive out of id order (see _reorder_inverted_pages).
    bbox: tuple[float, float, float, float] | None = None


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


@dataclass(frozen=True)
class Demotion:
    """A heading turned into body text instead of opening a section."""

    heading: str
    reason: str  # "caption" | "label line" | "repeated"
    pages: tuple[int | None, ...]


@dataclass(frozen=True)
class Fallback:
    """A heading that parsed to nothing and opened a slug-id section."""

    id: str
    heading: str
    page: int | None


@dataclass(frozen=True)
class Inversion:
    """Numbered sibling headings emitted out of id order on one page."""

    page: int | None
    first_id: str
    second_id: str
    reordered: bool  # True when the page had bboxes and was re-ordered


@dataclass(frozen=True)
class Duplicate:
    """A unit whose id repeated an earlier unit and was renamed."""

    original: str
    renamed: str
    chapter: str


@dataclass
class SectioningNotes:
    """Everything the sectioner decided that the ingest report must show."""

    demoted: list[Demotion] = field(default_factory=list)
    fallbacks: list[Fallback] = field(default_factory=list)
    inversions: list[Inversion] = field(default_factory=list)
    duplicates: list[Duplicate] = field(default_factory=list)


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
# The title is optional so a bare "5.15" keeps its id instead of backtracking
# to ("5", "15") and collapsing onto the chapter. A bare undotted number
# ("123") is a page number, never a section — handled below.
_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:[.\s]+(.*?))?\s*$")


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
        if m.group(1) is None:
            raise ValueError(
                f"chapter_pattern {cfg.chapter_pattern} matched {text!r} but its "
                "identifier group captured nothing (an optional group with no "
                "fallback) -- make the group required or give it a fallback id"
            )
        return _clean_id(m.group(1)), (m.group(2) or text).strip()
    if m := cfg.attachment_re.match(text):
        return _part_id("attachment", m.group(1)), (m.group(2) or text).strip()
    if m := cfg.appendix_re.match(text):
        return _part_id("appendix", m.group(1)), (m.group(2) or text).strip()
    if m := _NUMBERED_RE.match(text):
        sid, title = m.group(1), (m.group(2) or "").strip()
        if not title and "." not in sid:
            return None
        if sid.endswith(".0") and sid.count(".") == 1:
            sid = sid[:-2]
        return sid, title
    return None


def _clean_id(identifier: str) -> str:
    """An id is one `\\S+` token in the `## <id> <title>` line; a custom
    pattern whose identifier group captured a space would otherwise emit a
    section nothing can slice."""
    return re.sub(r"\s+", "-", identifier.strip())


def _part_id(kind: str, identifier: str | None) -> str:
    return f"{kind}-{_clean_id(identifier).lower()}" if identifier else kind


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


# Noise that docling labels as a heading but which is never document
# structure. Checked only after parse_section_id() failed, so a numbered
# "5.149 Figure of Merit" is unaffected. The caption form requires a
# number after the word ("Table 5-6", "Fig. A1") so "Table of Contents"
# and "Figure of Merit" pass through.
_CAPTION_RE = re.compile(
    r"^(table|figure|fig\.?|diagram|chart|exhibit)\s+[a-z]?\d", re.IGNORECASE
)
_LABEL_RE = re.compile(r"\b[\w/]+:\s")  # "Used On: ", "Length: ", "Source/Content: "
_MIN_LABELS_FOR_NOISE = 2
_MIN_REPEAT_PAGES = 3


def _noise_reason(normalized: str, repeated_pages: int) -> str | None:
    """Why an unparsed heading is body text, not a section — or None."""
    if _CAPTION_RE.match(normalized):
        return "caption"
    if len(_LABEL_RE.findall(normalized)) >= _MIN_LABELS_FOR_NOISE:
        return "label line"
    if repeated_pages >= _MIN_REPEAT_PAGES:
        return "repeated"
    return None


def _repeated_unparsed_headings(
    items: list[DocItem], cfg: HeadingConfig
) -> dict[str, tuple[int | None, ...]]:
    """Normalised heading text -> distinct pages it appears on, for headings
    that parse to nothing. Counted over the whole document, before any
    part split, so a running header is seen across parts."""
    pages: dict[str, set[int | None]] = {}
    last_page: int | None = None
    for item in items:
        if item.page is not None:
            last_page = item.page
        if item.kind != "heading":
            continue
        normalized = " ".join(item.text.split())
        if normalized.endswith(":") or parse_section_id(normalized, cfg):
            continue
        pages.setdefault(normalized, set()).add(last_page)
    return {
        text: tuple(sorted(p, key=lambda x: (x is None, x or 0)))
        for text, p in pages.items()
    }


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

    def __init__(
        self,
        cfg: HeadingConfig,
        part: Part | None,
        notes: SectioningNotes | None = None,
        repeated: dict[str, tuple[int | None, ...]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.part = part
        self.notes = notes if notes is not None else SectioningNotes()
        self.repeated = repeated or {}
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
            return
        pages = self.repeated.get(normalized, ())
        reason = _noise_reason(normalized, len(pages))
        if reason:
            self._demote(normalized, reason, pages or (self.last_page,))
            return
        self._attach_fallback(normalized)

    def _demote(
        self, normalized: str, reason: str, pages: tuple[int | None, ...]
    ) -> None:
        # Same treatment as a "Label:" heading: bold body text in the open
        # node, so the words survive even though no section opens. One note
        # per distinct heading, however many times it recurs.
        self.stack[-1].body.append(f"**{normalized}**")
        if not any(d.heading == normalized for d in self.notes.demoted):
            self.notes.demoted.append(Demotion(normalized, reason, pages))

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
        self.notes.fallbacks.append(Fallback(sid, normalized, self.last_page))

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
    notes: SectioningNotes | None = None,
    repeated: dict[str, tuple[int | None, ...]] | None = None,
) -> _Node:
    builder = _TreeBuilder(config or _DEFAULT_CONFIG, part, notes, repeated)
    for item in items:
        builder.feed(item)
    return builder.finish()


def _subtree_md(node: _Node) -> str:
    parts = ["\n\n".join(node.body)]
    for child in node.children:
        parts.append(f"### {child.id} {child.title}".rstrip())
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


def _dedupe_ids(units: list[SectionUnit], notes: SectioningNotes) -> list[SectionUnit]:
    """Ingest never emits two units with one id: `kb get` and the citation
    format address a section by id alone. A repeat (a page-range stray in
    parts mode, a Part that restarts numbering) is renamed `<id>-2`, `-3`…
    — fallback slugs are never digit-only, so the suffix cannot collide.

    `taken` is seeded with every id already present in `units`, so the
    suffix search also skips an id a later (real, not-yet-renamed) unit
    still owns — otherwise a stray duplicate walked early can steal the id
    a genuine unit needs, bumping that genuine unit into an unnecessary
    rename of its own once the walk reaches it."""
    taken = {u.id for u in units}
    seen: set[str] = set()
    out: list[SectionUnit] = []
    for unit in units:
        sid = unit.id
        if sid in seen:
            n = 2
            while f"{unit.id}-{n}" in seen or f"{unit.id}-{n}" in taken:
                n += 1
            sid = f"{unit.id}-{n}"
            notes.duplicates.append(Duplicate(unit.id, sid, unit.chapter))
            unit = replace(unit, id=sid)
        seen.add(sid)
        out.append(unit)
    return out


_SPANNING_FRACTION = 0.6  # of the page's item span: a full-width title/table


def _group_by_page(items: list[DocItem]) -> list[tuple[int | None, list[DocItem]]]:
    """Consecutive runs of items on one (forward-filled) page."""
    groups: list[tuple[int | None, list[DocItem]]] = []
    last: int | None = None
    for item in items:
        page = item.page if item.page is not None else last
        if item.page is not None:
            last = item.page
        if groups and groups[-1][0] == page:
            groups[-1][1].append(item)
        else:
            groups.append((page, [item]))
    return groups


def _numeric_heading_id(item: DocItem, cfg: HeadingConfig) -> str | None:
    """The item's id when it is a *purely* numeric dotted id ("5.83"), else
    None. The dot requirement is what excludes bare chapter/appendix/
    attachment/fallback ids ("5", "appendix-b-2") from sibling comparison;
    the all-digits requirement additionally excludes a custom
    --chapter-pattern id like "5.2b" whose later segment isn't a number —
    _id_tuple's int() has no fallback for that, so it must never see one."""
    if item.kind != "heading":
        return None
    parsed = parse_section_id(" ".join(item.text.split()), cfg)
    if not parsed or "." not in parsed[0] or not all(
        p.isdecimal() for p in parsed[0].split(".")
    ):
        return None
    return parsed[0]


def _id_tuple(sid: str) -> tuple[int, ...]:
    return tuple(int(p) for p in sid.split("."))


def _find_inversion(page_items: list[DocItem], cfg: HeadingConfig) -> tuple[str, str] | None:
    """First pair of numbered *sibling* headings on this page whose ids
    descend (5.84 then 5.83) — docling read the columns out of order."""
    last_by_parent: dict[str, str] = {}
    for item in page_items:
        sid = _numeric_heading_id(item, cfg)
        if sid is None:
            continue
        parent = sid.rsplit(".", 1)[0]
        prev = last_by_parent.get(parent)
        if prev is not None and _id_tuple(sid) < _id_tuple(prev):
            return prev, sid
        last_by_parent[parent] = sid
    return None


def _layout_order(page_items: list[DocItem]) -> list[DocItem]:
    """Column-aware reading order from bboxes: a spanning item (>= 60 % of
    the page's item span) cuts the page into bands and leads its band;
    inside a band, left column before right, top to bottom. Stable, so
    docling's order breaks ties."""
    boxes = [i.bbox for i in page_items]
    assert all(b is not None for b in boxes)
    left = min(b[0] for b in boxes)
    right = max(b[2] for b in boxes)
    span = right - left
    mid = (left + right) / 2

    def spanning(box) -> bool:
        return span > 0 and (box[2] - box[0]) >= _SPANNING_FRACTION * span

    tops = sorted(b[1] for b in boxes if spanning(b))

    def key(idx: int):
        l, t, r, _b = boxes[idx]  # noqa: E741 — l/r mirror docling's own bbox field names
        band = sum(1 for st in tops if st <= t)
        column = -1 if spanning(boxes[idx]) else (0 if (l + r) / 2 < mid else 1)
        return (band, column, t, idx)

    return [page_items[i] for i in sorted(range(len(page_items)), key=key)]


def _reorder_inverted_pages(
    items: list[DocItem], cfg: HeadingConfig, notes: SectioningNotes
) -> list[DocItem]:
    """Docling's in-page reading order is trusted everywhere except on a
    page whose numbered headings arrive out of id order. That page is
    re-ordered by layout when every item has a bbox, and named in the
    notes either way."""
    out: list[DocItem] = []
    for page, page_items in _group_by_page(items):
        pair = _find_inversion(page_items, cfg)
        if pair is None:
            out += page_items
            continue
        can_fix = all(i.bbox is not None for i in page_items)
        notes.inversions.append(Inversion(page, pair[0], pair[1], can_fix))
        out += _layout_order(page_items) if can_fix else page_items
    return out


def build_units_with_notes(
    items: list[DocItem],
    max_depth: int = 3,
    min_tokens: int = 200,
    max_unit_tokens: int = 5000,
    config: HeadingConfig | None = None,
    parts: list[Part] | None = None,
) -> tuple[list[SectionUnit], SectioningNotes]:
    """Section the item stream and return what the sectioner decided along
    the way — the ingest report prints the notes; build_units() drops them."""
    notes = SectioningNotes()
    cfg = config or _DEFAULT_CONFIG
    repeated = _repeated_unparsed_headings(items, cfg)
    items = _reorder_inverted_pages(items, cfg, notes)
    if not parts:
        front, rest = _split_front_matter(items, cfg)
        front_units: list[SectionUnit] = []
        if front:
            froot = _build_tree(
                front,
                cfg,
                part=Part("front-matter", "Front Matter", 1),
                notes=notes,
                repeated=repeated,
            )
            front_units = _units_from_tree(
                froot, max_depth, min_tokens, max_unit_tokens, "front-matter"
            )
        root = _build_tree(rest, cfg, notes=notes, repeated=repeated)
        units = order_units(front_units + _units_from_tree(
            root, max_depth, min_tokens, max_unit_tokens, None
        ))
        return _dedupe_ids(units, notes), notes
    units: list[SectionUnit] = []
    for part, part_items in split_by_parts(items, parts):
        if not part_items:
            continue
        root = _build_tree(part_items, cfg, part=part, notes=notes, repeated=repeated)
        units += _units_from_tree(
            root, max_depth, min_tokens, max_unit_tokens, part.id
        )
    return _dedupe_ids(order_units(units), notes), notes


def build_units(
    items: list[DocItem],
    max_depth: int = 3,
    min_tokens: int = 200,
    max_unit_tokens: int = 5000,
    config: HeadingConfig | None = None,
    parts: list[Part] | None = None,
) -> list[SectionUnit]:
    return build_units_with_notes(
        items, max_depth, min_tokens, max_unit_tokens, config, parts
    )[0]


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
                f"### {c.id} {c.title}".rstrip() + f"\n\n{_subtree_md(c)}"
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
