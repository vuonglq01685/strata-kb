# Bookmark-First Sectioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split ingested PDFs along the document's own outline (bookmarks) — chapters, attachments, front/back matter get real names — with the existing heading-regex path (plus a new attachment pattern) as fallback for PDFs without bookmarks.

**Architecture:** `parser.outline_parts` extracts part boundaries (id, title, page) from the PDF outline; `DocItem` gains a `page`; `sectioner.split_by_parts` buckets the item stream by part page ranges; `build_units(parts=…)` builds one tree per part (non-numeric parts namespace their internal numbering, killing fake chapters and id collisions). `scaffold_doc` clears stale files on re-ingest. CLI `ingest` wires it with `--no-bookmarks` / `--attachment-pattern`.

**Tech Stack:** Python 3.13, pypdf (already a dependency — used by `bookmark_ids`), Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-07-11-bookmark-sectioning-design.md`

## Global Constraints

- Part ids: numeric chapters `"1"`…; attachments `attN` (lowercased id group); appendices `appX` (existing); front matter grouped as `front-matter`; other unmatched top-level outline entries → slugified title, deduped with `-2`, `-3` suffixes.
- A bookmark entry is a part when its title parses as chapter/attachment/appendix at ANY outline depth and its section id contains no `.` (sub-section bookmarks are not parts). Fewer than 2 such matches (or no outline / pypdf error) → `outline_parts` returns `None` → regex fallback mode.
- `DEFAULT_ATTACHMENT_PATTERN = r"^attachment\s+([0-9A-Za-z]+)\s*[.:–—-]?\s*(.*)$"` (mirrors the appendix pattern).
- Backward compat: old manifests (no `attachment_pattern`, no `used_bookmarks`) must still load — pydantic defaults `""` / `False`.
- In per-part mode every unit's `chapter` is the part id (never `_chapter_of`).
- Existing flat-mode behavior unchanged when `parts is None` — the whole existing test suite must stay green: `.venv/bin/python -m pytest tests/ -q`.
- Commit style: conventional commits, no attribution footer.

---

### Task 1: attachment pattern (fallback mode B) + model fields

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py` (`DEFAULT_ATTACHMENT_PATTERN`, `HeadingConfig`, `parse_section_id`, `resolve_heading_config`, namespacing condition)
- Modify: `src/center_kb/models.py` (`IngestConfig`)
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Consumes: existing `HeadingConfig`, `parse_section_id`, `_build_tree`.
- Produces: `HeadingConfig(chapter_pattern, appendix_pattern, attachment_pattern)` with compiled `attachment_re`; `parse_section_id("ATTACHMENT 5 PATH AND TERMINATOR")` → `("att5", "PATH AND TERMINATOR")`; `resolve_heading_config(chapter_pattern, appendix_pattern, attachment_pattern, previous)` (new 3rd arg); `models.IngestConfig` gains `attachment_pattern: str = ""` and `used_bookmarks: bool = False`; numeric headings after an open `att*` top node namespace like `app*` ones.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sectioner.py` (class `TestParseSectionId` gets two methods; the rest are module-level, matching file style):

```python
    def test_attachment_heading(self):
        sid, title = parse_section_id("ATTACHMENT 5 PATH AND TERMINATOR")
        assert sid == "att5"
        assert title == "PATH AND TERMINATOR"

    def test_attachment_heading_with_separator(self):
        assert parse_section_id("Attachment 2: Datum List")[0] == "att2"
```

```python
def test_attachment_numeric_sections_namespaced_in_flat_mode():
    # NOTE: 80x keeps each leaf > 200 tokens (min_tokens) so it is NOT
    # folded into its parent — same convention as _items_basic's comment.
    items = [
        DocItem("heading", "ATTACHMENT 1 FLOW DIAGRAM", 1),
        DocItem("text", "Attachment intro. " * 80),
        DocItem("heading", "2.1 Diagram Conventions", 2),
        DocItem("text", "Convention body. " * 80),
    ]
    units = build_units(items)
    ids = [u.id for u in units]
    assert "att1" in ids
    assert "att1-2.1" in ids          # namespaced — no collision with chapter 2.1
    assert "2.1" not in ids


def test_resolve_heading_config_attachment_priority():
    from center_kb import models
    from center_kb.ingest.sectioner import (
        DEFAULT_ATTACHMENT_PATTERN,
        resolve_heading_config,
    )

    cfg = resolve_heading_config("", "", "", None)
    assert cfg.attachment_pattern == DEFAULT_ATTACHMENT_PATTERN
    prev = models.IngestConfig(chapter_pattern="c", appendix_pattern="a")
    assert prev.attachment_pattern == ""      # backward-compat default
    assert prev.used_bookmarks is False
    custom = r"^annex\s+(\d+)\s*(.*)$"
    cfg2 = resolve_heading_config("", "", custom, None)
    assert cfg2.attachment_pattern == custom
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sectioner.py -v -k "attachment or resolve_heading"`
Expected: FAIL — `TypeError`/`AttributeError` (no attachment pattern yet).

- [ ] **Step 3: Implement**

In `sectioner.py`:

```python
DEFAULT_ATTACHMENT_PATTERN = r"^attachment\s+([0-9A-Za-z]+)\s*[.:–—-]?\s*(.*)$"
```

`HeadingConfig` gains the field + compilation:

```python
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
```

`parse_section_id` — add the attachment branch between chapter and appendix:

```python
    if m := cfg.attachment_re.match(text):
        return f"att{m.group(1).lower()}", (m.group(2) or text).strip()
```

`resolve_heading_config` — third pattern, same priority chain:

```python
def resolve_heading_config(
    chapter_pattern: str,
    appendix_pattern: str,
    attachment_pattern: str,
    previous: "models.IngestConfig | None",
) -> HeadingConfig:
    """Priority: explicit arg > previous config in manifest (re-ingest) > default."""
    prev_ch = previous.chapter_pattern if previous else DEFAULT_CHAPTER_PATTERN
    prev_app = previous.appendix_pattern if previous else DEFAULT_APPENDIX_PATTERN
    prev_att = (previous.attachment_pattern if previous else "") or DEFAULT_ATTACHMENT_PATTERN
    return HeadingConfig(
        chapter_pattern=chapter_pattern or prev_ch,
        appendix_pattern=appendix_pattern or prev_app,
        attachment_pattern=attachment_pattern or prev_att,
    )
```

In `_build_tree`, generalize the namespacing condition from `top.id.startswith("app")` to `top.id.startswith(("app", "att"))` (update the adjacent comment: "ICAO appendices and attachments restart numeric numbering…").

In `models.py`, `IngestConfig`:

```python
class IngestConfig(BaseModel):
    chapter_pattern: str
    appendix_pattern: str
    attachment_pattern: str = ""   # "" = default pattern (backward compat)
    used_bookmarks: bool = False
```

Fix the ONE existing caller of `resolve_heading_config` (cli.py:113) by adding `""` as the third argument for now — Task 7 replaces it with the real CLI option.

- [ ] **Step 4: Run the sectioner + full suite**

Run: `.venv/bin/python -m pytest tests/test_sectioner.py -q && .venv/bin/python -m pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/sectioner.py src/center_kb/models.py src/center_kb/cli.py tests/test_sectioner.py
git commit -m "feat: attachment heading pattern — attN ids, namespaced internals, config plumbing"
```

---

### Task 2: DocItem.page from docling provenance

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py` (`DocItem`)
- Modify: `src/center_kb/ingest/parser.py` (`doc_to_items`)
- Test: `tests/test_parser.py`

**Interfaces:**
- Produces: `DocItem` gains `page: int | None = None`; `doc_to_items` fills it from `item.prov[0].page_no` when present.

- [ ] **Step 1: Write the failing test**

`tests/test_parser.py` has `_StubItem`/`_StubDoc` at the top. Extend `_StubItem` with a `prov` field defaulting to `None`:

```python
@dataclass
class _StubProv:
    page_no: int
```

(add `prov: list = None` to `_StubItem`'s fields — dataclass default `None`.)

Append:

```python
def test_doc_to_items_carries_page_numbers():
    doc = _StubDoc(
        items=[
            _StubItem(
                _StubLabel("section_header"),
                text="1.0 INTRO",
                prov=[_StubProv(page_no=21)],
            ),
            _StubItem(_StubLabel("text"), text="Body."),  # no prov -> page None
        ]
    )
    items = parser.doc_to_items(doc)
    assert items[0].page == 21
    assert items[1].page is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_parser.py::test_doc_to_items_carries_page_numbers -v`
Expected: FAIL — `TypeError: DocItem.__init__() got an unexpected keyword argument 'page'` or `AttributeError`.

- [ ] **Step 3: Implement**

`sectioner.py`:

```python
@dataclass
class DocItem:
    kind: str  # "heading" | "text" | "table"
    text: str
    level: int = 0
    page: int | None = None
```

`parser.py` — helper + fill in `doc_to_items`:

```python
def _page_of(item) -> int | None:
    prov = getattr(item, "prov", None)
    if prov:
        return getattr(prov[0], "page_no", None)
    return None
```

Each `items.append(DocItem(...))` in `doc_to_items` gains `page=_page_of(item)` (headings, tables, and text alike).

- [ ] **Step 4: Run parser + sectioner tests**

Run: `.venv/bin/python -m pytest tests/test_parser.py tests/test_sectioner.py -q`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/sectioner.py src/center_kb/ingest/parser.py tests/test_parser.py
git commit -m "feat: DocItem carries the source page number from docling provenance"
```

---

### Task 3: Part dataclass + split_by_parts

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py`
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Produces: `Part(id: str, title: str, page: int)` (frozen dataclass); `split_by_parts(items: list[DocItem], parts: list[Part]) -> list[tuple[Part, list[DocItem]]]` — parts assumed sorted by page; each item goes to the last part whose `page <= item.page`; items with `page=None` inherit the previous item's page; items before the first part's page go to the first part.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sectioner.py`:

```python
def test_split_by_parts_buckets_by_page():
    from center_kb.ingest.sectioner import Part, split_by_parts

    parts = [Part("front-matter", "Front Matter", 1), Part("1", "INTRO", 21),
             Part("att1", "FLOW DIAGRAM", 331)]
    items = [
        DocItem("heading", "FOREWORD", 1, page=4),
        DocItem("text", "no page follows previous", page=None),
        DocItem("heading", "1.0 INTRO", 1, page=21),
        DocItem("text", "chapter body", page=25),
        DocItem("heading", "ATTACHMENT 1 FLOW DIAGRAM", 1, page=331),
        DocItem("text", "att body", page=340),
    ]
    result = split_by_parts(items, parts)
    by_id = {part.id: [i.text for i in bucket] for part, bucket in result}
    assert by_id["front-matter"] == ["FOREWORD", "no page follows previous"]
    assert by_id["1"] == ["1.0 INTRO", "chapter body"]
    assert by_id["att1"] == ["ATTACHMENT 1 FLOW DIAGRAM", "att body"]


def test_split_by_parts_item_before_first_part_page():
    from center_kb.ingest.sectioner import Part, split_by_parts

    parts = [Part("1", "INTRO", 21)]
    items = [DocItem("text", "stray cover text", page=1)]
    result = split_by_parts(items, parts)
    assert [i.text for i in result[0][1]] == ["stray cover text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sectioner.py -v -k split_by_parts`
Expected: FAIL — `ImportError: cannot import name 'Part'`.

- [ ] **Step 3: Implement in sectioner.py**

```python
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
```

- [ ] **Step 4: Run the sectioner tests**

Run: `.venv/bin/python -m pytest tests/test_sectioner.py -q`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/sectioner.py tests/test_sectioner.py
git commit -m "feat: Part dataclass + split_by_parts page bucketing"
```

---

### Task 4: per-part tree building in build_units

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py` (`_build_tree`, `build_units`)
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Produces: `_build_tree(items, config=None, part: Part | None = None)` — when `part` is given and `part.id` does not start with a digit, the tree is seeded with an open node `(id=part.id, title=part.title, depth=1)`; numeric headings namespace under that seeded node (`att1-2.1`) exactly like `app*` nodes. `build_units(items, max_depth=3, min_tokens=200, max_unit_tokens=5000, config=None, parts=None)` — with `parts`, runs `split_by_parts` and builds each part separately; every resulting unit's `chapter` is the part id.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sectioner.py`:

```python
def test_build_units_with_parts_assigns_part_chapter():
    from center_kb.ingest.sectioner import Part

    parts = [Part("front-matter", "Front Matter", 1), Part("1", "INTRODUCTION", 21)]
    items = [
        DocItem("heading", "FOREWORD", 1, page=4),
        DocItem("text", "Foreword body. " * 60, page=4),
        DocItem("heading", "1.0 INTRODUCTION", 1, page=21),
        DocItem("text", "Chapter one body. " * 60, page=21),
    ]
    units = build_units(items, parts=parts)
    chapters = {u.id: u.chapter for u in units}
    # FOREWORD is a fallback under the seeded front-matter node
    assert any(u.chapter == "front-matter" for u in units)
    assert chapters.get("1") == "1"
    # no top-level fake chapters
    assert not any(u.chapter.startswith("x") for u in units)


def test_build_units_with_parts_namespaces_attachment_numbering():
    from center_kb.ingest.sectioner import Part

    parts = [Part("2", "GLOSSARY", 25), Part("att1", "FLOW DIAGRAM", 331)]
    items = [
        DocItem("heading", "2.0 GLOSSARY", 1, page=25),
        DocItem("text", "Glossary body. " * 60, page=25),
        DocItem("heading", "ATTACHMENT 1 FLOW DIAGRAM", 1, page=331),
        DocItem("text", "Attachment intro. " * 80, page=331),
        DocItem("heading", "2.1 Diagram Conventions", 2, page=332),
        # 80x keeps the leaf > min_tokens so it is not folded into att1
        DocItem("text", "Convention body. " * 80, page=332),
    ]
    units = build_units(items, parts=parts)
    ids = {u.id for u in units}
    assert "att1-2.1" in ids           # namespaced under the attachment part
    assert "2.1" not in ids            # chapter 2 never polluted
    att_units = [u for u in units if u.chapter == "att1"]
    assert {u.id for u in att_units} >= {"att1", "att1-2.1"}


def test_build_units_without_parts_unchanged():
    units = build_units(_items_basic())
    assert [u.id for u in units] == ["5", "5.3", "5.4"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sectioner.py -v -k "with_parts or without_parts"`
Expected: FAIL — `TypeError: build_units() got an unexpected keyword argument 'parts'`.

- [ ] **Step 3: Implement**

`_build_tree` — new optional `part` param; seed a part-root node for non-numeric parts and extend the namespacing condition to it:

```python
def _build_tree(
    items: list[DocItem],
    config: HeadingConfig | None = None,
    part: Part | None = None,
) -> _Node:
    cfg = config or _DEFAULT_CONFIG
    root = _Node(id="", title="", depth=0)
    stack = [root]
    if part is not None and not part.id[:1].isdigit():
        part_node = _Node(id=part.id, title=part.title, depth=1)
        root.children.append(part_node)
        stack.append(part_node)
    ...
```

In the namespacing branch, the condition becomes:

```python
                if (
                    sid[0].isdigit()
                    and top is not None
                    and (
                        top.id.startswith(("app", "att"))
                        or (part is not None and top.id == part.id)
                    )
                    and not cfg.chapter_re.match(" ".join(item.text.split()))
                ):
```

(keep the existing comment, extended: part-root nodes namespace exactly like appendices/attachments).

Note: the seeded part node is on the stack, so the part's own heading in the stream (same id, e.g. `ATTACHMENT 1 …` → `att1`) hits the existing `any(n.id == sid for n in stack)` no-op branch and merges instead of duplicating.

`build_units` — extract the existing walk into a helper and add the parts path:

```python
def build_units(
    items: list[DocItem],
    max_depth: int = 3,
    min_tokens: int = 200,
    max_unit_tokens: int = 5000,
    config: HeadingConfig | None = None,
    parts: list[Part] | None = None,
) -> list[SectionUnit]:
    if not parts:
        root = _build_tree(items, config)
        return _units_from_tree(root, max_depth, min_tokens, max_unit_tokens, None)
    units: list[SectionUnit] = []
    for part, part_items in split_by_parts(items, parts):
        if not part_items:
            continue
        root = _build_tree(part_items, config, part=part)
        units += _units_from_tree(
            root, max_depth, min_tokens, max_unit_tokens, part.id
        )
    return units


def _units_from_tree(
    root: _Node,
    max_depth: int,
    min_tokens: int,
    max_unit_tokens: int,
    chapter_override: str | None,
) -> list[SectionUnit]:
    ...  # the existing walk() body verbatim, except the SectionUnit gets
         # chapter=chapter_override if chapter_override is not None
         # else _chapter_of(node.id)
```

- [ ] **Step 4: Run sectioner + full suite**

Run: `.venv/bin/python -m pytest tests/test_sectioner.py -q && .venv/bin/python -m pytest tests/ -q`
Expected: ALL PASS (flat mode is untouched).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/sectioner.py tests/test_sectioner.py
git commit -m "feat: per-part tree building — part-rooted namespacing, chapter from part id"
```

---

### Task 5: outline_parts — extract parts from the PDF outline

**Files:**
- Modify: `src/center_kb/mdutils.py` (move `slugify` here)
- Modify: `src/center_kb/ingest/scaffold.py` (import `slugify` from mdutils, keep the name exported)
- Modify: `src/center_kb/ingest/parser.py` (`outline_parts`)
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `parse_section_id` (Task 1 handles attachments), `Part` (Task 3), pypdf.
- Produces: `parser.outline_parts(pdf_path: Path, config: HeadingConfig | None = None) -> list[Part] | None` — parts sorted by page; `None` when no outline / pypdf error / fewer than 2 chapter-attachment-appendix matches. `mdutils.slugify` (moved; `scaffold.slugify` stays importable).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_parser.py`:

```python
def _pdf_with_outline(tmp_path):
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(12):
        w.add_blank_page(width=200, height=200)
    w.add_outline_item("COVER PAGE", 0)
    toc = w.add_outline_item("TABLE OF CONTENTS", 1)
    w.add_outline_item("1.0 INTRODUCTION", 2, parent=toc)
    w.add_outline_item("1.1 Sub Section", 3, parent=toc)     # sub-bookmark: not a part
    w.add_outline_item("2.0 DATA", 4, parent=toc)
    w.add_outline_item("ATTACHMENT 1 FLOW DIAGRAM", 6, parent=toc)
    w.add_outline_item("SUPPLEMENT 22", 8)
    w.add_outline_item("ERRATA", 10)
    path = tmp_path / "outlined.pdf"
    with path.open("wb") as f:
        w.write(f)
    return path


def test_outline_parts_extracts_and_orders_parts(tmp_path):
    path = _pdf_with_outline(tmp_path)
    parts = parser.outline_parts(path)
    assert parts is not None
    assert [(p.id, p.page) for p in parts] == [
        ("front-matter", 1),   # COVER PAGE + TABLE OF CONTENTS grouped
        ("1", 3),
        ("2", 5),
        ("att1", 7),
        ("supplement-22", 9),
        ("errata", 11),
    ]
    titles = {p.id: p.title for p in parts}
    assert titles["att1"] == "FLOW DIAGRAM"
    assert titles["front-matter"] == "Front Matter"


def test_outline_parts_returns_none_without_outline(tmp_path):
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    path = tmp_path / "plain.pdf"
    with path.open("wb") as f:
        w.write(f)
    assert parser.outline_parts(path) is None


def test_outline_parts_returns_none_for_missing_file(tmp_path):
    assert parser.outline_parts(tmp_path / "nope.pdf") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_parser.py -v -k outline_parts`
Expected: FAIL — `AttributeError: module ... has no attribute 'outline_parts'`.

- [ ] **Step 3: Move slugify to mdutils**

Move the `slugify` function body from `scaffold.py` to `mdutils.py` (it needs `re` and `unicodedata` imports there). In `scaffold.py` replace the definition with `from center_kb.mdutils import slugify` (existing `tests/test_scaffold.py::test_slugify` keeps importing it from scaffold — the re-export preserves that).

- [ ] **Step 4: Implement outline_parts in parser.py**

```python
from center_kb.ingest.sectioner import (  # extend the existing import line
    DocItem,
    HeadingConfig,
    Part,
    parse_section_id,
)
from center_kb.mdutils import slugify
```

```python
def outline_parts(
    pdf_path: Path, config: HeadingConfig | None = None
) -> list[Part] | None:
    """Extract top-level document parts from the PDF outline.

    A bookmark is a part when its title parses as a chapter/attachment/
    appendix at ANY depth (some PDFs nest chapters under a "TABLE OF
    CONTENTS" entry) and its id has no sub-numbering. Unparsed TOP-LEVEL
    entries become front matter (grouped, before the first match) or
    named back-matter parts. Returns None (→ regex fallback) when there
    is no usable outline.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(pdf_path))
        outline = reader.outline
    except Exception:
        return None

    matched: list[Part] = []
    seen_ids: set[str] = set()
    top_unmatched: list[tuple[str, int]] = []

    def walk(entries, depth: int) -> None:
        for entry in entries:
            if isinstance(entry, list):
                walk(entry, depth + 1)
                continue
            title = " ".join(((getattr(entry, "title", "") or "")).split())
            try:
                page = reader.get_destination_page_number(entry) + 1
            except Exception:
                continue
            parsed = parse_section_id(title, config)
            if parsed and "." not in parsed[0]:
                if parsed[0] not in seen_ids:
                    seen_ids.add(parsed[0])
                    matched.append(Part(parsed[0], parsed[1], page))
            elif depth == 0 and not parsed:
                top_unmatched.append((title, page))

    walk(outline, 0)
    if len(matched) < 2:
        return None

    matched.sort(key=lambda p: p.page)
    first_page = matched[0].page
    front = [(t, pg) for t, pg in top_unmatched if pg < first_page]
    back = [(t, pg) for t, pg in top_unmatched if pg >= first_page]

    parts = list(matched)
    if front:
        parts.append(Part("front-matter", "Front Matter", min(pg for _, pg in front)))
        seen_ids.add("front-matter")
    for title, pg in back:
        pid = slugify(title)[:40].rstrip("-") or "part"
        base, n = pid, 2
        while pid in seen_ids:
            pid, n = f"{base}-{n}", n + 1
        seen_ids.add(pid)
        parts.append(Part(pid, title, pg))
    parts.sort(key=lambda p: p.page)
    return parts
```

- [ ] **Step 5: Run parser + scaffold tests**

Run: `.venv/bin/python -m pytest tests/test_parser.py tests/test_scaffold.py -q`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/mdutils.py src/center_kb/ingest/scaffold.py src/center_kb/ingest/parser.py tests/test_parser.py
git commit -m "feat: outline_parts — derive document parts from PDF bookmarks"
```

---

### Task 6: scaffold — stale-file cleanup + stem dedup

**Files:**
- Modify: `src/center_kb/ingest/scaffold.py` (`scaffold_doc`, `chapter_stem`)
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Produces: `scaffold_doc` deletes every `*.md` (includes `.raw.md`) in the doc dir before writing (spec decision #7); `chapter_stem` returns just the prefix when the slug equals it (`chapter_stem("errata", "ERRATA") == "errata"`, not `errata-errata`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scaffold.py`:

```python
def test_chapter_stem_no_duplicate_when_slug_equals_prefix():
    assert chapter_stem("errata", "ERRATA") == "errata"
    assert chapter_stem("front-matter", "Front Matter") == "front-matter"
    assert chapter_stem("att1", "FLOW DIAGRAM") == "att1-flow-diagram"


def test_scaffold_reingest_removes_stale_files(tmp_path: Path):
    kb = tmp_path / ".kb"
    doc_dir = kb / "doc1"
    doc_dir.mkdir(parents=True)
    (doc_dir / "ch9-fake-chapter.md").write_text("stale", encoding="utf-8")
    (doc_dir / "ch9-fake-chapter.raw.md").write_text("stale", encoding="utf-8")
    units = [
        SectionUnit(
            id="1", title="INTRO", chapter="1",
            body_md="Body. " * 60, tables=[],
        )
    ]
    scaffold_doc(
        units, doc_id="doc1", title="Doc", tags=[], revision="",
        source_path=None, kb_dir=kb,
    )
    names = {p.name for p in doc_dir.iterdir()}
    assert "ch9-fake-chapter.md" not in names
    assert "ch9-fake-chapter.raw.md" not in names
    assert "ch1-intro.md" in names
```

(`chapter_stem`, `SectionUnit`, `scaffold_doc` are already imported at the top of the file — check and extend the import if needed.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scaffold.py -v -k "stale or duplicate"`
Expected: FAIL on `errata-errata` and on the stale file still existing.

- [ ] **Step 3: Implement**

`chapter_stem`:

```python
def chapter_stem(chapter: str, title: str) -> str:
    prefix = f"ch{chapter}" if chapter and chapter[0].isdigit() else chapter
    slug = slugify(title)[:40].rstrip("-")
    return f"{prefix}-{slug}" if slug and slug != prefix else prefix
```

`scaffold_doc`, right after `doc_dir.mkdir(...)`:

```python
    for stale in doc_dir.glob("*.md"):  # re-ingest may change the file split
        stale.unlink()
```

- [ ] **Step 4: Run scaffold + full suite**

Run: `.venv/bin/python -m pytest tests/test_scaffold.py -q && .venv/bin/python -m pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/scaffold.py tests/test_scaffold.py
git commit -m "feat: scaffold clears stale doc files on re-ingest; stem dedup for named parts"
```

---

### Task 7: CLI wiring — --no-bookmarks, --attachment-pattern, mode echo, persistence

**Files:**
- Modify: `src/center_kb/cli.py` (`ingest` command)
- Modify: `src/center_kb/ingest/scaffold.py` (`scaffold_doc` gains `used_bookmarks: bool = False`, persisted into `IngestConfig`)
- Test: `tests/test_ingest_cli.py`

**Interfaces:**
- Consumes: `parser.outline_parts` (Task 5), `build_units(parts=…)` (Task 4), `resolve_heading_config(ch, app, att, prev)` (Task 1).
- Produces: `kb ingest` options `--attachment-pattern` (default `""`, remembered like the other patterns) and `--no-bookmarks`; output line `sectioning: bookmarks (N parts)` or `sectioning: heading patterns`; manifest `ingest.used_bookmarks` reflects the mode actually used and `ingest.attachment_pattern` the pattern actually used.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_ingest_cli.py` first — it stubs the parser layer with monkeypatch. Add two tests following the file's existing fixture pattern:

1. `test_ingest_uses_bookmark_parts_when_available`: monkeypatch `parser.outline_parts` to return `[Part("1", "INTRO", 1), Part("att1", "FLOW", 5)]` (and the existing `load_or_parse`/`doc_to_items` stubs to yield items with pages 1 and 5). Invoke `kb ingest`. Assert: output contains `sectioning: bookmarks (2 parts)`; the doc dir contains a file whose name starts with `att1-`; `_manifest.yaml` contains `used_bookmarks: true`.
2. `test_ingest_no_bookmarks_flag_forces_regex_mode`: same stubs but invoke with `--no-bookmarks`; assert `outline_parts` was NOT called (monkeypatch it to raise `AssertionError` if called), output contains `sectioning: heading patterns`, and `used_bookmarks` is false/absent-default in the manifest.

Write these concretely against the file's existing helpers — do not invent new stub machinery.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ingest_cli.py -v -k bookmark`
Expected: FAIL — no `sectioning:` output, no `--no-bookmarks` option.

- [ ] **Step 3: Implement**

`cli.py` `ingest` — add options:

```python
    attachment_pattern: str = typer.Option(
        "",
        help="Attachment heading regex (default: 'Attachment N', remembered from the previous ingest)",
    ),
    no_bookmarks: bool = typer.Option(
        False,
        "--no-bookmarks",
        help="Ignore PDF bookmarks; split by heading patterns only",
    ),
```

Pass `attachment_pattern` as the third arg to `resolve_heading_config`. After `items = parser.doc_to_items(doc)`:

```python
    parts = None if no_bookmarks else parser.outline_parts(pdf, heading_config)
    if parts:
        typer.echo(f"sectioning: bookmarks ({len(parts)} parts)")
    else:
        typer.echo("sectioning: heading patterns")
    units = sectioner.build_units(items, config=heading_config, parts=parts)
```

`scaffold_doc` signature gains `used_bookmarks: bool = False`; the manifest write becomes:

```python
        ingest=models.IngestConfig(
            chapter_pattern=cfg.chapter_pattern,
            appendix_pattern=cfg.appendix_pattern,
            attachment_pattern=cfg.attachment_pattern,
            used_bookmarks=used_bookmarks,
        ),
```

and the `ingest` command passes `used_bookmarks=bool(parts)`.

- [ ] **Step 4: Run ingest CLI + full suite**

Run: `.venv/bin/python -m pytest tests/test_ingest_cli.py -q && .venv/bin/python -m pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/cli.py src/center_kb/ingest/scaffold.py tests/test_ingest_cli.py
git commit -m "feat: kb ingest bookmark-first sectioning — --no-bookmarks, --attachment-pattern"
```

---

### Task 8: full suite + operational re-ingest of CENTER-KB (controller-run)

**Files:** none in this repo (operational).

- [ ] **Step 1: Full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 2 (controller, NOT a subagent):** re-ingest the real doc — the docling cache in `.kb-work` is reused (no re-parse cost), summaries are all pending anyway:

```bash
cd /Users/vuonglq01685/Documents/Projects/CENTER-KB
/Users/vuonglq01685/Documents/Projects/AERO-KB/.venv/bin/kb ingest source/ARINC424-22.pdf --id arinc-424 --no-summarize
ls .kb/arinc-424/
```

Expected: `sectioning: bookmarks (12 parts)` (front-matter, ch 1–8, att 1–5, supplement-22, errata, apim — exact count depends on grouping); file list matches the document's real structure (`att1-flow-diagram.md`, `errata.md`, no `ch9-*`/`ch10-*`/`x1-*`/`ch5-x212-*`). Then hand off to the user for `kb summarize` (their call — they run it themselves).

---

## Out of scope (from the spec)

- `.kb/` format, summarize, build, query changes.
- OCR / image-only PDFs.
- Outline editor/UI.
