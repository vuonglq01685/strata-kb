# Ingest review fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `kb ingest` attach body text to the right heading, stop turning
noise headings into sections, never emit a duplicate or whitespace id, report
every sectioning decision it took, and give `--sections` merge semantics.

**Architecture:** The sectioner gains a `SectioningNotes` record and a
`build_units_with_notes()` entry point; every new decision (demotion, fallback,
page re-order, duplicate rename) is recorded there and `ingestcmd` formats it
through the existing `warn` callback. A logging bridge in `run_ingest` routes
parser warnings into the same report. `DocItem` gains a bbox so a page whose
numbered headings arrive out of id order can be re-ordered by layout. Scaffold
learns to merge a `--sections` run into the previous manifest instead of
deleting unnamed chapters.

**Tech Stack:** Python 3.12, dataclasses, `re`, `logging`, `statistics`,
pydantic models (`center_kb.models`), typer + `CliRunner`, pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-08-ingest-review-fixes-design.md`

## Global Constraints

- **No re-ingest of `.kb/`.** `git diff main...HEAD -- .kb/` must be empty
  when the batch ends. All evidence is synthetic `DocItem` fixtures.
- **`build_units()` keeps its signature and behaviour on inputs without
  bboxes or noise.** Every existing test in `tests/test_sectioner.py` passes
  unchanged except the one this plan rewrites by name.
- **Folding algorithm unchanged** (spec decision 2). No edit to
  `_units_from_tree`.
- **No placeholder titles.** An empty title is written as `## <id>` with no
  trailing space and `title: ""` in the manifest.
- **`cli.py` is not edited.** The logging bridge lives in `ingestcmd.py`.
- **`uv.lock` must be regenerated in the same commit as `pyproject.toml`**
  (`uv lock`, then `uv lock --check` must pass; only CI catches this).
- **Run tests with the project venv:**
  `.venv/Scripts/python -m pytest -q <file>` (Windows). `ruff check src tests`
  before every commit.
- **Commit messages:** conventional type prefix, no attribution trailer other
  than the session line the harness adds.

---

## File map

| File | Responsibility after this plan |
|---|---|
| `src/center_kb/ingest/sectioner.py` | Section tree; new: `SectioningNotes` + note dataclasses, `build_units_with_notes`, noise filter, inversion re-order, duplicate rename, id whitespace normalisation |
| `src/center_kb/ingest/parser.py` | Docling → `DocItem` (now with bbox); `bookmark_ids` tri-state; two-way `crosscheck`; `assets/` cleanup |
| `src/center_kb/ingest/scaffold.py` | Write L1/L2/L3; new: id validation, empty-title heading line, `TokenStats`, merge semantics |
| `src/center_kb/ingestcmd.py` | `kb ingest` orchestration; new: logging bridge, notes → report, outline warning, `sections:` line |
| `src/center_kb/mdutils.py` | Heading regexes accept an empty title |
| `pyproject.toml`, `uv.lock` | `rapidocr` in the `ingest` extra |
| `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md`, `README.md` | Rules rewritten to match |

---

### Task 1: Empty-title contract (F3 regex, `mdutils` regexes, scaffold heading line)

**Files:**
- Modify: `src/center_kb/mdutils.py:10,52`
- Modify: `src/center_kb/ingest/sectioner.py:81,146-150`
- Modify: `src/center_kb/ingest/scaffold.py:79-81`
- Test: `tests/test_mdutils.py`, `tests/test_sectioner.py`, `tests/test_scaffold.py`

**Interfaces:**
- Produces: `parse_section_id("5.15") == ("5.15", "")`; `parse_section_id("123") is None`; `slice_section(md, "5.15")` finds a `## 5.15` line; scaffold writes `## <id>` when the title is empty.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mdutils.py`:

```python
def test_slice_section_finds_heading_with_empty_title():
    md = "## 5.14 Fix Type\n\nFix body.\n\n## 5.15\n\nOrphan body.\n\n## 5.16 Real Field\n\nReal body.\n"
    assert mdutils.slice_section(md, "5.15") == "## 5.15\n\nOrphan body."
    assert mdutils.slice_section(md, "5.16") == "## 5.16 Real Field\n\nReal body."


def test_slice_subsection_finds_heading_with_empty_title():
    md = "## 5 NAV\n\nIntro.\n\n### 5.15\n\nFolded body.\n\n### 5.16 Next\n\nNext body.\n"
    assert mdutils.slice_subsection(md, "5.15") == "### 5.15\n\nFolded body."
```

Add to `class TestParseSectionId` in `tests/test_sectioner.py`:

```python
    def test_title_less_dotted_heading_keeps_its_id(self):
        assert parse_section_id("5.15") == ("5.15", "")

    def test_title_less_dotted_heading_with_trailing_dot(self):
        assert parse_section_id("5.15.") == ("5.15", "")

    def test_bare_number_is_still_not_a_section(self):
        assert parse_section_id("123") is None
```

Add a module-level test in `tests/test_sectioner.py` (reviewer case 10):

```python
def test_title_less_numbered_heading_opens_its_own_section():
    big = "Body text. " * 70
    items = [
        DocItem("heading", "5.0 NAV", 1),
        DocItem("text", "chapter body. " + big),
        DocItem("heading", "5.15", 2),
        DocItem("text", "Orphan body for 5.15. " + big),
        DocItem("heading", "5.16 Real Field", 2),
        DocItem("text", "real body. " + big),
    ]
    units = build_units(items)
    by_id = {u.id: u for u in units}
    assert list(by_id) == ["5", "5.15", "5.16"]
    assert by_id["5.15"].title == ""
    assert "Orphan body for 5.15." in by_id["5.15"].body_md
    assert "Orphan body for 5.15." not in by_id["5"].body_md
```

Add to `tests/test_scaffold.py` (import `slice_section` from `center_kb.mdutils` at the top):

```python
def test_scaffold_writes_bare_heading_for_empty_title_and_it_slices(tmp_path: Path):
    kb = tmp_path / ".kb"
    units = [
        SectionUnit("5", "NAV", "5", "Chapter intro.", []),
        SectionUnit("5.15", "", "5", "Orphan body.", []),
    ]
    scaffold_doc(
        units, doc_id="d", title="D", tags=[], revision="",
        source_path=None, kb_dir=kb,
    )
    raw = (kb / "d" / "ch5-nav.raw.md").read_text(encoding="utf-8")
    l2 = (kb / "d" / "ch5-nav.md").read_text(encoding="utf-8")
    assert "## 5.15\n" in raw and "## 5.15 \n" not in raw
    assert "## 5.15\n" in l2 and "## 5.15 \n" not in l2
    assert slice_section(raw, "5.15") == "## 5.15\n\nOrphan body."
    manifest = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert manifest.sections[1].title == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_mdutils.py tests/test_sectioner.py tests/test_scaffold.py -k "empty_title or title_less or bare_number or bare_heading"`
Expected: FAIL — `slice_section` returns `None`, `parse_section_id("5.15")` returns `('5', '15')`, scaffold writes `## 5.15 ` with a trailing space.

- [ ] **Step 3: Relax the two heading regexes in `mdutils.py`**

```python
_HEADING_RE = re.compile(r"^## (?P<sid>\S+)(?:[ \t]+(?P<title>.*?))?\s*$")
```

and

```python
_SUBHEADING_RE = re.compile(r"^### (?P<sid>\S+)(?:[ \t]+(?P<title>.*?))?\s*$")
```

- [ ] **Step 4: Make the numbered regex accept an empty title, but only for dotted ids**

In `sectioner.py` replace line 81:

```python
# The title is optional so a bare "5.15" keeps its id instead of backtracking
# to ("5", "15") and collapsing onto the chapter. A bare undotted number
# ("123") is a page number, never a section — handled below.
_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:[.\s]+(.*?))?\s*$")
```

and replace the numbered branch of `parse_section_id` (lines 146-150):

```python
    if m := _NUMBERED_RE.match(text):
        sid, title = m.group(1), (m.group(2) or "").strip()
        if not title and "." not in sid:
            return None
        if sid.endswith(".0") and sid.count(".") == 1:
            sid = sid[:-2]
        return sid, title
```

- [ ] **Step 5: Strip the trailing space from the heading line in `scaffold.py`**

Replace lines 79-81:

```python
        for unit in chapter_units:
            heading = f"## {unit.id} {unit.title}".rstrip()
            l3_lines += [heading, "", unit.body_md, ""]
            l2_lines += [
                heading,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_mdutils.py tests/test_sectioner.py tests/test_scaffold.py tests/test_ingest_seam.py`
Expected: all PASS (the seam fixture has no empty titles, so it is byte-identical).

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/mdutils.py src/center_kb/ingest/sectioner.py src/center_kb/ingest/scaffold.py tests/test_mdutils.py tests/test_sectioner.py tests/test_scaffold.py
git commit -m "fix(ingest): title-less numbered heading keeps its id; empty title legal end to end (A-F3)"
```

---

### Task 2: `SectioningNotes` and `build_units_with_notes` (fallback notes)

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py` (`_TreeBuilder.__init__`, `_attach_fallback`, `_build_tree`, `build_units`)
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Demotion:  heading: str; reason: str; pages: tuple[int | None, ...]
@dataclass(frozen=True)
class Fallback:  id: str; heading: str; page: int | None
@dataclass(frozen=True)
class Inversion: page: int | None; first_id: str; second_id: str; reordered: bool
@dataclass(frozen=True)
class Duplicate: original: str; renamed: str; chapter: str
@dataclass
class SectioningNotes: demoted: list[Demotion]; fallbacks: list[Fallback]; inversions: list[Inversion]; duplicates: list[Duplicate]

def build_units_with_notes(items, max_depth=3, min_tokens=200, max_unit_tokens=5000, config=None, parts=None) -> tuple[list[SectionUnit], SectioningNotes]
def build_units(items, ...) -> list[SectionUnit]   # == build_units_with_notes(...)[0]
```

- [ ] **Step 1: Write the failing tests**

Replace `test_last_resort_xn_id_logs_warning` in `tests/test_sectioner.py` with:

```python
def test_fallback_heading_is_recorded_in_notes():
    from center_kb.ingest.sectioner import Fallback, build_units_with_notes

    items = [
        DocItem("heading", "5.6 Identifier Field", 1, page=3),
        DocItem("text", "Parent body."),
        DocItem("heading", "NDB Navaid Record", 2, page=4),
        DocItem("text", "Value body."),
    ]
    units, notes = build_units_with_notes(items, min_tokens=1)
    assert [u.id for u in units] == ["5.6", "5.6-ndb-navaid-record"]
    assert notes.fallbacks == [
        Fallback("5.6-ndb-navaid-record", "NDB Navaid Record", 4)
    ]
    assert notes.demoted == [] and notes.inversions == [] and notes.duplicates == []
    # the plain entry point is the same pass without the notes
    assert build_units(items, min_tokens=1) == units


def test_no_fallback_note_when_every_heading_parses():
    from center_kb.ingest.sectioner import build_units_with_notes

    items = [
        DocItem("heading", "5.6 Identifier Field", 1),
        DocItem("text", "Parent body."),
    ]
    _, notes = build_units_with_notes(items, min_tokens=1)
    assert notes.fallbacks == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_sectioner.py -k "recorded_in_notes or no_fallback_note"`
Expected: FAIL with `ImportError: cannot import name 'Fallback'`.

- [ ] **Step 3: Add the note dataclasses after `Part`**

In `sectioner.py`, after the `Part` dataclass (line 49):

```python
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
```

- [ ] **Step 4: Thread notes through the tree builder**

Change `_TreeBuilder.__init__` signature and body (line 217):

```python
    def __init__(
        self,
        cfg: HeadingConfig,
        part: Part | None,
        notes: SectioningNotes | None = None,
    ) -> None:
        self.cfg = cfg
        self.part = part
        self.notes = notes if notes is not None else SectioningNotes()
```

(keep the rest of `__init__` as is). In `_attach_fallback`, after `self.seen[sid] = list(self.stack)` (line 371):

```python
        self.notes.fallbacks.append(Fallback(sid, normalized, self.last_page))
```

Change `_build_tree`:

```python
def _build_tree(
    items: list[DocItem],
    config: HeadingConfig | None = None,
    part: Part | None = None,
    notes: SectioningNotes | None = None,
) -> _Node:
    builder = _TreeBuilder(config or _DEFAULT_CONFIG, part, notes)
    for item in items:
        builder.feed(item)
    return builder.finish()
```

- [ ] **Step 5: Split `build_units` into `build_units_with_notes` + wrapper**

Replace the whole `build_units` function (lines 420-451):

```python
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
    if not parts:
        front, rest = _split_front_matter(items, cfg)
        front_units: list[SectionUnit] = []
        if front:
            froot = _build_tree(
                front, cfg, part=Part("front-matter", "Front Matter", 1), notes=notes
            )
            front_units = _units_from_tree(
                froot, max_depth, min_tokens, max_unit_tokens, "front-matter"
            )
        root = _build_tree(rest, cfg, notes=notes)
        units = order_units(front_units + _units_from_tree(
            root, max_depth, min_tokens, max_unit_tokens, None
        ))
        return units, notes
    units: list[SectionUnit] = []
    for part, part_items in split_by_parts(items, parts):
        if not part_items:
            continue
        root = _build_tree(part_items, cfg, part=part, notes=notes)
        units += _units_from_tree(
            root, max_depth, min_tokens, max_unit_tokens, part.id
        )
    return order_units(units), notes


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
```

- [ ] **Step 6: Run the sectioner tests**

Run: `.venv/Scripts/python -m pytest -q tests/test_sectioner.py`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/ingest/sectioner.py tests/test_sectioner.py
git commit -m "feat(ingest): SectioningNotes and build_units_with_notes record fallback ids"
```

---

### Task 3: Heading-noise filter (F1: caption, label line, repeated on ≥ 3 pages)

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py` (`feed`, `_TreeBuilder.__init__`, `_build_tree`, `build_units_with_notes`)
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Consumes: `SectioningNotes`, `Demotion` (Task 2).
- Produces: `_noise_reason(normalized: str, repeated_pages: int) -> str | None`; `_repeated_unparsed_headings(items, cfg) -> dict[str, tuple[int | None, ...]]`; `_TreeBuilder(cfg, part, notes, repeated)`; `_build_tree(items, config, part, notes, repeated)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sectioner.py`:

```python
def test_table_caption_heading_is_demoted_to_text():
    from center_kb.ingest.sectioner import Demotion, build_units_with_notes

    items = [
        DocItem("heading", "5.7 SID Records", 1, page=129),
        DocItem("text", "Field body."),
        DocItem("heading", "Table 5-6 Airport and Heliport SID Record", 2, page=129),
        DocItem("table", "| a | b |\n|---|---|\n| 1 | 2 |"),
    ]
    units, notes = build_units_with_notes(items, min_tokens=1)
    assert [u.id for u in units] == ["5.7"]
    assert "**Table 5-6 Airport and Heliport SID Record**" in units[0].body_md
    assert "| a | b |" in units[0].body_md
    assert notes.demoted == [
        Demotion("Table 5-6 Airport and Heliport SID Record", "caption", (129,))
    ]
    assert notes.fallbacks == []


def test_label_line_heading_is_demoted_to_text():
    from center_kb.ingest.sectioner import Demotion, build_units_with_notes

    label = "Used On: Runway Record Length: 1 Character Character Type: Alpha"
    items = [
        DocItem("heading", "5.319 Runway Transition", 1, page=300),
        DocItem("text", "Field body."),
        DocItem("heading", label, 2, page=300),
        DocItem("text", "Value body."),
    ]
    units, notes = build_units_with_notes(items, min_tokens=1)
    assert [u.id for u in units] == ["5.319"]
    assert f"**{label}**" in units[0].body_md
    assert notes.demoted == [Demotion(label, "label line", (300,))]


def test_heading_repeated_on_three_pages_is_demoted():
    from center_kb.ingest.sectioner import Demotion, build_units_with_notes

    items = []
    for n, page in enumerate((61, 88, 104), start=1):
        items += [
            DocItem("heading", f"5.{n} Field {n}", 1, page=page),
            DocItem("text", f"Field {n} body."),
            DocItem("heading", "COMMENTARY", 2, page=page),
            DocItem("text", f"Commentary {n}."),
        ]
    units, notes = build_units_with_notes(items, min_tokens=1)
    assert [u.id for u in units] == ["5.1", "5.2", "5.3"]
    assert all("**COMMENTARY**" in u.body_md for u in units)
    assert "Commentary 2." in units[1].body_md
    assert notes.demoted == [Demotion("COMMENTARY", "repeated", (61, 88, 104))]


def test_heading_repeated_on_two_pages_is_still_a_fallback():
    from center_kb.ingest.sectioner import build_units_with_notes

    items = []
    for n, page in enumerate((61, 88), start=1):
        items += [
            DocItem("heading", f"5.{n} Field {n}", 1, page=page),
            DocItem("text", f"Field {n} body."),
            DocItem("heading", "COMMENTARY", 2, page=page),
            DocItem("text", f"Commentary {n}."),
        ]
    units, notes = build_units_with_notes(items, min_tokens=1)
    assert [u.id for u in units] == ["5.1", "5.1-commentary", "5.2", "5.2-commentary"]
    assert notes.demoted == []


def test_repeated_heading_counted_across_parts():
    from center_kb.ingest.sectioner import Part, build_units_with_notes

    parts = [Part("5", "NAV", 1), Part("6", "PROC", 50)]
    items = [
        DocItem("heading", "5.0 NAV", 1, page=1),
        DocItem("text", "nav body.", page=1),
        DocItem("heading", "COMMENTARY", 2, page=2),
        DocItem("text", "c1.", page=2),
        DocItem("heading", "6.0 PROC", 1, page=50),
        DocItem("text", "proc body.", page=50),
        DocItem("heading", "COMMENTARY", 2, page=51),
        DocItem("text", "c2.", page=51),
        DocItem("heading", "COMMENTARY", 2, page=52),
        DocItem("text", "c3.", page=52),
    ]
    units, notes = build_units_with_notes(items, min_tokens=1, parts=parts)
    assert [u.id for u in units] == ["5", "6"]
    assert len(notes.demoted) == 1 and notes.demoted[0].pages == (2, 51, 52)


def test_numbered_figure_title_is_not_a_caption():
    items = [
        DocItem("heading", "5.0 NAV", 1),
        DocItem("text", "nav body."),
        DocItem("heading", "5.149 Figure of Merit", 2),
        DocItem("text", "fom body."),
    ]
    assert [u.id for u in build_units(items, min_tokens=1)] == ["5", "5.149"]


def test_noise_reason_does_not_match_table_of_contents():
    from center_kb.ingest.sectioner import _noise_reason

    assert _noise_reason("Table of Contents", 1) is None
    assert _noise_reason("Figure of Merit", 1) is None
    assert _noise_reason("Table 5-6 SID Record", 1) == "caption"
    assert _noise_reason("Fig. A1 Layout", 1) == "caption"
    assert _noise_reason("Note: see below", 1) is None  # one label only
    assert _noise_reason("Used On: X Length: 5", 1) == "label line"
    assert _noise_reason("FOREWORD", 2) is None
    assert _noise_reason("FOREWORD", 3) == "repeated"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_sectioner.py -k "caption or label_line or repeated or noise_reason or figure_title"`
Expected: FAIL — captions/labels become fallback sections, `_noise_reason` does not exist.

- [ ] **Step 3: Add the filter helpers after `_fallback_slug`**

```python
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
```

- [ ] **Step 4: Give the builder the repeat map and a demote path**

`_TreeBuilder.__init__` gains a fourth parameter and one attribute:

```python
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
```

Replace the tail of `feed` (from `parsed = parse_section_id(...)`):

```python
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
```

`_build_tree` gains `repeated` and passes it through:

```python
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
```

In `build_units_with_notes`, right after `cfg = config or _DEFAULT_CONFIG`:

```python
    repeated = _repeated_unparsed_headings(items, cfg)
```

and pass `repeated=repeated` to all three `_build_tree` calls.

- [ ] **Step 5: Run the sectioner tests**

Run: `.venv/Scripts/python -m pytest -q tests/test_sectioner.py`
Expected: all PASS, including the pre-existing `test_label_heading_with_colon_demoted_to_text` and `test_unmatched_heading_without_colon_still_fallback`.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/ingest/sectioner.py tests/test_sectioner.py
git commit -m "fix(ingest): captions, label lines and repeated headings become body text, not sections (A-F1)"
```

---

### Task 4: Duplicate-id rename (F7) and id whitespace normalisation (F8, sectioner side)

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py` (`parse_section_id`, `_part_id`, `build_units_with_notes`)
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Produces: `_dedupe_ids(units, notes) -> list[SectionUnit]`; `_clean_id(identifier: str) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
def test_duplicate_id_across_parts_is_renamed_and_noted():
    from center_kb.ingest.sectioner import Duplicate, Part, build_units_with_notes

    big = "Body text. " * 70
    parts = [Part("5", "NAV", 1), Part("6", "PROC", 10)]
    items = [
        DocItem("heading", "5.0 NAV", 1, page=1),
        DocItem("text", "nav body. " + big, page=1),
        DocItem("heading", "5.3 Airways", 2, page=2),
        DocItem("text", "airways body. " + big, page=2),
        DocItem("heading", "6.0 PROC", 1, page=10),
        DocItem("text", "proc body. " + big, page=10),
        # stray: physically inside chapter 6's page range
        DocItem("heading", "5.3 Airways", 2, page=11),
        DocItem("text", "airways tail. " + big, page=11),
    ]
    units, notes = build_units_with_notes(items, parts=parts)
    assert [(u.id, u.chapter) for u in units] == [
        ("5", "5"), ("5.3", "5"), ("6", "6"), ("5.3-2", "6"),
    ]
    assert units[3].title == "Airways"
    assert "airways tail." in units[3].body_md
    assert notes.duplicates == [Duplicate("5.3", "5.3-2", "6")]


def test_custom_chapter_pattern_id_never_contains_whitespace():
    from center_kb.ingest.sectioner import HeadingConfig

    cfg = HeadingConfig(chapter_pattern=r"^(part\s+[A-Z])\s*[-–—.:]\s*(.*)$")
    assert parse_section_id("Part A - Definitions", cfg) == ("Part-A", "Definitions")
    cfg2 = HeadingConfig(appendix_pattern=r"^annex\s+([A-Z] [0-9])\s*[-–—.:]?\s*(.*)$")
    assert parse_section_id("Annex B 2 - Tables", cfg2) == ("appendix-b-2", "Tables")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_sectioner.py -k "duplicate_id or never_contains_whitespace"`
Expected: FAIL — two units with id `5.3`; id `Part A` contains a space.

- [ ] **Step 3: Normalise whitespace in pattern-derived ids**

Add after `_part_id` in `sectioner.py`:

```python
def _clean_id(identifier: str) -> str:
    """An id is one `\\S+` token in the `## <id> <title>` line; a custom
    pattern whose identifier group captured a space would otherwise emit a
    section nothing can slice."""
    return re.sub(r"\s+", "-", identifier.strip())
```

Change `_part_id` to use it:

```python
def _part_id(kind: str, identifier: str | None) -> str:
    return f"{kind}-{_clean_id(identifier).lower()}" if identifier else kind
```

and the chapter branch of `parse_section_id`:

```python
    if m := cfg.chapter_re.match(text):
        return _clean_id(m.group(1)), (m.group(2) or text).strip()
```

- [ ] **Step 4: Add `_dedupe_ids` and call it in both branches**

Add after `order_units`:

```python
def _dedupe_ids(units: list[SectionUnit], notes: SectioningNotes) -> list[SectionUnit]:
    """Ingest never emits two units with one id: `kb get` and the citation
    format address a section by id alone. A repeat (a page-range stray in
    parts mode, a Part that restarts numbering) is renamed `<id>-2`, `-3`…
    — fallback slugs are never digit-only, so the suffix cannot collide."""
    seen: set[str] = set()
    out: list[SectionUnit] = []
    for unit in units:
        sid = unit.id
        if sid in seen:
            n = 2
            while f"{unit.id}-{n}" in seen:
                n += 1
            sid = f"{unit.id}-{n}"
            notes.duplicates.append(Duplicate(unit.id, sid, unit.chapter))
            unit = replace(unit, id=sid)
        seen.add(sid)
        out.append(unit)
    return out
```

In `build_units_with_notes`, wrap both return values:

```python
        return _dedupe_ids(units, notes), notes
```

(non-parts branch, where `units = order_units(...)` was assigned) and

```python
    return _dedupe_ids(order_units(units), notes), notes
```

(parts branch).

- [ ] **Step 5: Run the sectioner tests**

Run: `.venv/Scripts/python -m pytest -q tests/test_sectioner.py`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/ingest/sectioner.py tests/test_sectioner.py
git commit -m "fix(ingest): rename duplicate section ids and strip whitespace from pattern ids (A-F7, A-F8)"
```

---

### Task 5: `DocItem.bbox` from docling provenance

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py:13-18` (`DocItem`)
- Modify: `src/center_kb/ingest/parser.py:150-172` (`doc_to_items`)
- Test: `tests/test_parser.py`

**Interfaces:**
- Produces: `DocItem.bbox: tuple[float, float, float, float] | None` = `(left, top, right, bottom)` in TOPLEFT coordinates; every `DocItem` built by `doc_to_items` carries it when docling has provenance with a bbox and the page height is known.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_parser.py`:

```python
def test_doc_to_items_carries_topleft_bbox():
    doc = _StubDoc(
        items=[
            _StubItem(
                _StubLabel("section_header"),
                text="5.84 RUNWAY TRANS",
                prov=[_StubProv(page_no=1, bbox=_StubBBox(l=300, t=700, r=550, b=680))],
            ),
            _StubItem(
                _StubLabel("text"),
                text="Body.",
                prov=[_StubProv(page_no=1, bbox=_StubBBox(l=10, t=100, r=200, b=120, coord_origin="TOPLEFT"))],
            ),
            _StubItem(
                _StubLabel("table"),
                table_md="| A | B |\n|---|---|\n| 1 | 2 |",
                prov=[_StubProv(page_no=1, bbox=_StubBBox(l=10, t=300, r=500, b=200))],
            ),
            _StubItem(_StubLabel("text"), text="No prov."),
        ],
        pages={1: _StubPage()},  # height 792
    )
    items = parser.doc_to_items(doc)
    assert items[0].bbox == (300, 92, 550, 112)  # BOTTOMLEFT flipped: 792-700, 792-680
    assert items[1].bbox == (10, 100, 200, 120)
    assert items[2].bbox == (10, 492, 500, 592)
    assert items[3].bbox is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest -q tests/test_parser.py -k topleft_bbox`
Expected: FAIL with `AttributeError: 'DocItem' object has no attribute 'bbox'`.

- [ ] **Step 3: Add the field to `DocItem`**

```python
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
```

- [ ] **Step 4: Populate it in `doc_to_items`**

Replace the item loop in `parser.doc_to_items` (from `items: list[DocItem] = []`):

```python
    items: list[DocItem] = []
    for item, label in entries:
        page, box = _prov_box(item, doc)
        bbox = (box.left, box.top, box.right, box.bottom) if box else None
        if label in _SKIP_LABELS:
            continue
        if label in _HEADING_LABELS:
            heading_level = getattr(item, "level", 1) if label == "section_header" else 1
            items.append(
                DocItem("heading", item.text, heading_level, page=page, bbox=bbox)
            )
        elif label == "table":
            md = item.export_to_markdown(doc=doc)
            if md and md.strip():
                md = tableimages.inject(md, placements.get(id(item), {}))
                items.append(DocItem("table", md, page=page, bbox=bbox))
        elif label == "picture":
            if assets_dir is None or id(item) in consumed:
                continue
            md = _picture_md(item, doc, assets_dir)
            if md:
                items.append(DocItem("image", md, page=page, bbox=bbox))
        elif getattr(item, "text", "") and item.text.strip():
            items.append(DocItem("text", item.text, page=page, bbox=bbox))
    return items
```

(`_prov_box` already exists at `parser.py:62-67` and returns `(page, Box | None)`; `_page_of` is no longer needed in this loop but stays for other callers.)

- [ ] **Step 5: Run parser + sectioner tests**

Run: `.venv/Scripts/python -m pytest -q tests/test_parser.py tests/test_sectioner.py tests/test_ingest_seam.py`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/ingest/sectioner.py src/center_kb/ingest/parser.py tests/test_parser.py
git commit -m "feat(ingest): DocItem carries a TOPLEFT bbox from docling provenance"
```

---

### Task 6: Intra-page heading inversion — detect, warn, re-order by layout (F2)

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py` (new helpers before `build_units_with_notes`; one call inside it)
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Consumes: `DocItem.bbox` (Task 5), `Inversion`, `SectioningNotes` (Task 2).
- Produces: `_reorder_inverted_pages(items, cfg, notes) -> list[DocItem]`.

- [ ] **Step 1: Write the failing tests**

```python
def _two_column_page(page: int = 212) -> list[DocItem]:
    """Reviewer case 9 with layout: 5.83 in the left column, 5.84 in the
    right; docling emitted 5.84 first and interleaved 5.83 between 5.84's
    two paragraphs."""
    big = "Body text. " * 70
    return [
        DocItem("heading", "5.84 RUNWAY TRANS", 2, page=page, bbox=(310, 80, 550, 95)),
        DocItem("text", "para-a of 5.84. " + big, page=page, bbox=(310, 100, 550, 300)),
        DocItem("heading", "5.83 To FIX", 2, page=page, bbox=(50, 80, 290, 95)),
        DocItem("text", "para-b of 5.84. " + big, page=page, bbox=(310, 310, 550, 500)),
        DocItem("text", "body of 5.83. " + big, page=page, bbox=(50, 100, 290, 400)),
    ]


def _chapter_head(page: int = 200) -> list[DocItem]:
    big = "Body text. " * 70
    return [
        DocItem("heading", "5.0 NAV", 1, page=page, bbox=(50, 40, 550, 60)),
        DocItem("text", "chapter body. " + big, page=page, bbox=(50, 70, 550, 300)),
    ]


def test_inverted_headings_on_one_page_are_reordered_by_layout():
    from center_kb.ingest.sectioner import Inversion, build_units_with_notes

    units, notes = build_units_with_notes(_chapter_head() + _two_column_page())
    by_id = {u.id: u for u in units}
    assert [u.id for u in units] == ["5", "5.83", "5.84"]
    assert "para-a of 5.84." in by_id["5.84"].body_md
    assert "para-b of 5.84." in by_id["5.84"].body_md
    assert "body of 5.83." in by_id["5.83"].body_md
    assert "para-b of 5.84." not in by_id["5.83"].body_md
    assert notes.inversions == [Inversion(212, "5.84", "5.83", True)]


def test_inverted_headings_without_bboxes_are_only_reported():
    from dataclasses import replace

    from center_kb.ingest.sectioner import Inversion, build_units_with_notes

    items = [replace(i, bbox=None) for i in _chapter_head() + _two_column_page()]
    units, notes = build_units_with_notes(items)
    by_id = {u.id: u for u in units}
    assert [u.id for u in units] == ["5", "5.84", "5.83"]
    assert "para-b of 5.84." in by_id["5.83"].body_md  # today's misattribution, now visible
    assert notes.inversions == [Inversion(212, "5.84", "5.83", False)]


def test_spanning_heading_stays_first_when_a_page_is_reordered():
    from center_kb.ingest.sectioner import build_units_with_notes

    big = "Body text. " * 70
    title = DocItem("heading", "5.0 NAV", 1, page=212, bbox=(50, 20, 550, 40))
    intro = DocItem("text", "chapter body. " + big, page=212, bbox=(50, 45, 550, 70))
    units, notes = build_units_with_notes([title, intro] + _two_column_page())
    assert [u.id for u in units] == ["5", "5.83", "5.84"]
    assert "chapter body." in units[0].body_md
    assert len(notes.inversions) == 1 and notes.inversions[0].reordered


def test_page_without_inversion_keeps_docling_order_even_with_bboxes():
    from center_kb.ingest.sectioner import build_units_with_notes

    big = "Body text. " * 70
    # bboxes deliberately contradict docling order: docling is trusted here
    items = _chapter_head() + [
        DocItem("heading", "5.83 To FIX", 2, page=212, bbox=(310, 80, 550, 95)),
        DocItem("text", "body of 5.83. " + big, page=212, bbox=(310, 100, 550, 300)),
        DocItem("heading", "5.84 RUNWAY TRANS", 2, page=212, bbox=(50, 80, 290, 95)),
        DocItem("text", "body of 5.84. " + big, page=212, bbox=(50, 100, 290, 300)),
    ]
    units, notes = build_units_with_notes(items)
    by_id = {u.id: u for u in units}
    assert [u.id for u in units] == ["5", "5.83", "5.84"]
    assert "body of 5.84." in by_id["5.84"].body_md
    assert notes.inversions == []


def test_inversion_across_pages_is_not_reported():
    from center_kb.ingest.sectioner import build_units_with_notes

    big = "Body text. " * 70
    items = _chapter_head() + [
        DocItem("heading", "5.84 RUNWAY TRANS", 2, page=212),
        DocItem("text", "body of 5.84. " + big, page=212),
        DocItem("heading", "5.83 To FIX", 2, page=213),
        DocItem("text", "body of 5.83. " + big, page=213),
    ]
    _, notes = build_units_with_notes(items)
    assert notes.inversions == []


def test_inversion_only_compares_siblings():
    from center_kb.ingest.sectioner import build_units_with_notes

    big = "Body text. " * 70
    # 5.3.9 then 5.4 on one page is normal nesting, not an inversion
    items = _chapter_head() + [
        DocItem("heading", "5.3 Airspace", 2, page=212),
        DocItem("text", "a. " + big, page=212),
        DocItem("heading", "5.3.9 Sub", 3, page=212),
        DocItem("text", "b. " + big, page=212),
        DocItem("heading", "5.4 Airways", 2, page=212),
        DocItem("text", "c. " + big, page=212),
    ]
    _, notes = build_units_with_notes(items)
    assert notes.inversions == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_sectioner.py -k "inverted or inversion or spanning or docling_order"`
Expected: `test_inverted_headings_on_one_page_are_reordered_by_layout` FAILS (ids `['5', '5.84', '5.83']`, para-b under 5.83); the "not reported" tests fail on `notes.inversions` only if the attribute is missing — after Task 2 they pass trivially, which is fine.

- [ ] **Step 3: Add the inversion helpers before `build_units_with_notes`**

```python
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
    if item.kind != "heading":
        return None
    parsed = parse_section_id(" ".join(item.text.split()), cfg)
    if not parsed or not parsed[0][:1].isdigit() or "." not in parsed[0]:
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
        l, t, r, _b = boxes[idx]
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
```

- [ ] **Step 4: Call it first thing in `build_units_with_notes`**

Right after `repeated = _repeated_unparsed_headings(items, cfg)`:

```python
    items = _reorder_inverted_pages(items, cfg, notes)
```

- [ ] **Step 5: Run the sectioner tests**

Run: `.venv/Scripts/python -m pytest -q tests/test_sectioner.py`
Expected: all PASS. `test_units_ordered_by_heading_page_not_emission_order` (cross-page, no bboxes) is untouched.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/ingest/sectioner.py tests/test_sectioner.py
git commit -m "fix(ingest): re-order a page by layout when its numbered headings arrive out of id order (A-F2)"
```

---

### Task 7: Parser — `bookmark_ids` tri-state, two-way `crosscheck`, `assets/` cleanup (F5, F9)

**Files:**
- Modify: `src/center_kb/ingest/parser.py` (imports, `doc_to_items:133-135`, `bookmark_ids`, `crosscheck`)
- Test: `tests/test_parser.py`

**Interfaces:**
- Produces: `bookmark_ids(pdf_path, config=None) -> set[str] | None` (`None` = outline unreadable); `crosscheck(unit_ids, bm_ids, max_depth=3) -> list[str]` now also yields `section '<id>' not in the PDF outline`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_parser.py`:

```python
def test_crosscheck_fallback_child_does_not_cover_missing_numeric_bookmark():
    warnings = parser.crosscheck(unit_ids={"5.6-commentary"}, bm_ids={"5.6"})
    assert warnings == ["bookmark section '5.6' not found in the extracted tree"]


def test_crosscheck_reports_units_absent_from_a_sibling_level_outline():
    warnings = parser.crosscheck(unit_ids={"5", "5.6", "5.6.1"}, bm_ids={"5", "5.7"})
    assert warnings == [
        "bookmark section '5.7' not found in the extracted tree",
        "section '5.6' not in the PDF outline",
    ]


def test_crosscheck_is_silent_about_extras_when_outline_stops_at_chapters():
    assert parser.crosscheck(unit_ids={"5", "5.6"}, bm_ids={"5"}) == []


def test_crosscheck_flags_renamed_duplicates_but_not_fallback_slugs():
    warnings = parser.crosscheck(
        unit_ids={"5", "5.3", "5.3-2", "5.6", "5.6-commentary"},
        bm_ids={"5", "5.3", "5.6"},
    )
    assert "section '5.3-2' not in the PDF outline" in warnings
    assert not any("5.6-commentary" in w for w in warnings)


def test_bookmark_ids_returns_none_when_outline_unreadable(tmp_path):
    assert parser.bookmark_ids(tmp_path / "nope.pdf") is None


def test_bookmark_ids_returns_ids_from_a_real_outline(tmp_path):
    ids = parser.bookmark_ids(_pdf_with_outline(tmp_path))
    assert ids == {"1", "1.1", "2", "attachment-1"}


def test_bookmark_ids_returns_empty_set_without_outline(tmp_path):
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    path = tmp_path / "plain.pdf"
    with path.open("wb") as f:
        w.write(f)
    assert parser.bookmark_ids(path) == set()


def test_doc_to_items_clears_stale_assets_including_subdirectories(tmp_path):
    (tmp_path / "deadbeef.png").write_bytes(b"old")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "x.png").write_bytes(b"old")
    parser.doc_to_items(_StubDoc(items=[]), assets_dir=tmp_path)
    assert tmp_path.is_dir() and list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_parser.py -k "crosscheck or bookmark_ids or subdirectories"`
Expected: FAIL — `5.6-commentary` covers `5.6`; no extra warnings; `bookmark_ids` returns `set()` for a missing file; `unlink()` raises `PermissionError`/`IsADirectoryError` on the subdirectory.

- [ ] **Step 3: `assets/` cleanup with `shutil.rmtree`**

Add `import shutil` to the parser imports. Replace `parser.py:133-135`:

```python
    if assets_dir is not None and assets_dir.exists():
        shutil.rmtree(assets_dir)  # re-ingest: assets are re-derived
        assets_dir.mkdir(parents=True)
```

- [ ] **Step 4: `bookmark_ids` returns `None` on an unreadable outline**

Change the signature and the `except`:

```python
def bookmark_ids(pdf_path: Path, config: HeadingConfig | None = None) -> set[str] | None:
    """Section ids named by the PDF outline. None when the outline cannot be
    read at all (missing/corrupt file) — the caller must say the cross-check
    was skipped; an empty set means a readable PDF with no usable outline."""
```

(keep the existing body) and

```python
    try:
        reader = PdfReader(str(pdf_path))
        walk(reader.outline)
    except Exception as exc:
        logger.debug("outline unreadable for %s: %s", pdf_path, exc)
        return None
    return ids
```

- [ ] **Step 5: Two-way `crosscheck`**

Add `_is_part_root` to the sectioner import at the top of `parser.py`:

```python
from center_kb.ingest.sectioner import (
    DocItem,
    HeadingConfig,
    Part,
    _is_part_root,
    parse_section_id,
)
```

Replace `crosscheck` (from `def crosscheck(` to the end of the file):

```python
# A numeric unit id, optionally carrying a duplicate-rename suffix ("5.3-2").
# Fallback slugs ("5.6-commentary") never match: they have their own warning.
_NUMERIC_UNIT_RE = re.compile(r"^\d+(?:\.\d+)+(?:-\d+)?$")


def _parent_id(sid: str) -> str:
    return sid.rsplit(".", 1)[0]


def _missing_bookmarks(unit_ids: set[str], bm_ids: set[str], max_depth: int) -> list[str]:
    warnings: list[str] = []
    for bm in sorted(bm_ids):
        if bm[0].isdigit() and bm.count(".") + 1 > max_depth:
            continue
        covered = False
        for uid in unit_ids:
            if bm == uid:
                covered = True
            elif bm.startswith(uid + ".") and _is_leaf_unit(uid, unit_ids):
                covered = True
            elif uid.startswith(bm + "."):
                covered = True
            elif uid.startswith(bm + "-") and _is_part_root(bm):
                # appendix-3 is covered by appendix-3-2.1; a numeric bookmark
                # is NOT covered by a fallback child like 5.6-commentary
                covered = True
            if covered:
                break
        if not covered:
            warnings.append(f"bookmark section '{bm}' not found in the extracted tree")
    return warnings


def _units_outside_outline(unit_ids: set[str], bm_ids: set[str]) -> list[str]:
    """Numeric units the outline does not name, judged only at levels the
    outline enumerates: a unit is extra when some bookmark shares its
    parent. An outline that stops at chapters says nothing about 5.x."""
    bm_parents = {_parent_id(bm) for bm in bm_ids if _NUMERIC_UNIT_RE.match(bm)}
    return [
        f"section '{uid}' not in the PDF outline"
        for uid in sorted(unit_ids)
        if _NUMERIC_UNIT_RE.match(uid)
        and uid not in bm_ids
        and _parent_id(uid) in bm_parents
    ]


def crosscheck(
    unit_ids: set[str], bm_ids: set[str], max_depth: int = 3
) -> list[str]:
    """Both directions of the outline cross-check (phase-1 spec §4.3:
    'section thiếu/thừa'): bookmarks no unit covers, then units the
    outline does not name."""
    return _missing_bookmarks(unit_ids, bm_ids, max_depth) + _units_outside_outline(
        unit_ids, bm_ids
    )
```

Add `import re` to the parser imports.

- [ ] **Step 6: Run the parser tests**

Run: `.venv/Scripts/python -m pytest -q tests/test_parser.py tests/test_ingest_cli.py`
Expected: all PASS. (`test_ingest_creates_kb_and_reports_warnings` still sees `5.9`; its units `{5, 5.3}` have no extras.)

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/ingest/parser.py tests/test_parser.py
git commit -m "fix(ingest): two-way outline crosscheck, unreadable outline is reported, assets dir cleanup survives subdirs (A-F5, A-F9)"
```

---

### Task 8: Scaffold — id validation (F8) and `TokenStats` on `ScaffoldReport` (F4)

**Files:**
- Modify: `src/center_kb/ingest/scaffold.py`
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class TokenStats: n: int; min: int; median: int; max: int; below_300: int; above_5000: int
class ScaffoldReport: ...; token_stats: TokenStats | None = None
def validate_unit_ids(units: list[SectionUnit]) -> None   # raises ValueError
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scaffold.py`:

```python
def test_scaffold_rejects_section_id_with_whitespace_before_writing(tmp_path: Path):
    units = [SectionUnit("Part A", "Definitions", "Part A", "Body.", [])]
    with pytest.raises(ValueError, match="'Part A'"):
        scaffold_doc(
            units, doc_id="d", title="D", tags=[], revision="",
            source_path=None, kb_dir=tmp_path / ".kb",
        )
    assert not (tmp_path / ".kb" / "d").exists()


def test_scaffold_rejects_empty_section_id(tmp_path: Path):
    units = [SectionUnit("", "Nameless", "5", "Body.", [])]
    with pytest.raises(ValueError, match="empty"):
        scaffold_doc(
            units, doc_id="d", title="D", tags=[], revision="",
            source_path=None, kb_dir=tmp_path / ".kb",
        )


def test_scaffold_report_carries_token_stats(tmp_path: Path):
    from center_kb.ingest.scaffold import TokenStats

    report = scaffold_doc(
        _units(), doc_id="d", title="D", tags=[], revision="",
        source_path=None, kb_dir=tmp_path / ".kb",
    )
    stats = report.token_stats
    assert isinstance(stats, TokenStats)
    assert stats.n == 3
    assert stats.below_300 == 3 and stats.above_5000 == 0
    assert 0 < stats.min <= stats.median <= stats.max


def test_scaffold_report_token_stats_none_without_sections(tmp_path: Path):
    report = scaffold_doc(
        [], doc_id="d", title="D", tags=[], revision="",
        source_path=None, kb_dir=tmp_path / ".kb",
    )
    assert report.token_stats is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_scaffold.py -k "whitespace_before_writing or empty_section_id or token_stats"`
Expected: FAIL — no `ValueError`, no `TokenStats`.

- [ ] **Step 3: Add `TokenStats`, `validate_unit_ids`, and wire them**

After `ScaffoldReport` in `scaffold.py` (and add `import statistics` plus the two constants):

```python
_TARGET_MIN_TOKENS = 300   # phase-1 spec §4.4-3: a measured target, not a rule
_TARGET_MAX_TOKENS = 5000
_WHITESPACE_RE = re.compile(r"\s")


@dataclass(frozen=True)
class TokenStats:
    """L3 token distribution over the sections written this run."""

    n: int
    min: int
    median: int
    max: int
    below_300: int
    above_5000: int


def token_stats(sections: list[models.SectionEntry]) -> TokenStats | None:
    counts = [s.tokens.l3 for s in sections]
    if not counts:
        return None
    return TokenStats(
        n=len(counts),
        min=min(counts),
        median=int(statistics.median(counts)),
        max=max(counts),
        below_300=sum(1 for c in counts if c < _TARGET_MIN_TOKENS),
        above_5000=sum(1 for c in counts if c > _TARGET_MAX_TOKENS),
    )


def validate_unit_ids(units: list[SectionUnit]) -> None:
    """The id is one `\\S+` token in `## <id> <title>`; slice_section() can
    never find an id with a space in it, and an empty id is no address."""
    for unit in units:
        if not unit.id:
            raise ValueError(
                f"section {unit.title!r} has an empty id — every unit needs an id"
            )
        if _WHITESPACE_RE.search(unit.id):
            raise ValueError(
                f"section id {unit.id!r} contains whitespace — adjust the "
                "chapter/appendix/attachment pattern so its identifier group "
                "has no spaces"
            )
```

Extend `ScaffoldReport`:

```python
@dataclass
class ScaffoldReport:
    doc_id: str
    files: list[str]
    n_sections: int
    token_stats: TokenStats | None = None
```

In `scaffold_doc`, right after `validate_doc_id(doc_id)`:

```python
    validate_unit_ids(units)
```

and change the return:

```python
    return ScaffoldReport(
        doc_id=doc_id,
        files=files,
        n_sections=len(sections),
        token_stats=token_stats(sections),
    )
```

Add `"TokenStats", "token_stats", "validate_unit_ids"` to `__all__`.

- [ ] **Step 4: Run the scaffold tests**

Run: `.venv/Scripts/python -m pytest -q tests/test_scaffold.py tests/test_ingest_seam.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/scaffold.py tests/test_scaffold.py
git commit -m "feat(ingest): scaffold validates section ids and reports the L3 token distribution (A-F8, A-F4)"
```

---

### Task 9: Scaffold — `--sections` merge semantics (F6)

**Files:**
- Modify: `src/center_kb/ingest/scaffold.py` (`scaffold_doc`)
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Consumes: `models.Manifest`, `models.SectionEntry`, `chapter_stem`.
- Produces: unchanged `scaffold_doc(...)` signature; new behaviour when `chapters` is given **and** `<doc_dir>/_manifest.yaml` exists.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scaffold.py`:

```python
def _three_chapter_units() -> list[SectionUnit]:
    return [
        SectionUnit("5", "NAV", "5", "Nav intro.", []),
        SectionUnit("5.3", "Airspace", "5", "Airspace body.", []),
        SectionUnit("6", "PROC", "6", "Proc intro.", []),
        SectionUnit("7", "COMMS", "7", "Comms intro.", []),
    ]


def _scaffold(units, kb: Path, chapters=None):
    return scaffold_doc(
        units, doc_id="d", title="D", tags=[], revision="",
        source_path=None, kb_dir=kb, chapters=chapters,
    )


def _snapshot(doc: Path, *prefixes: str) -> dict[str, bytes]:
    return {
        p.name: p.read_bytes()
        for p in doc.iterdir()
        if any(p.name.startswith(pre) for pre in prefixes)
    }


def test_sections_reingest_keeps_other_chapters_and_their_review_state(tmp_path: Path):
    kb = tmp_path / ".kb"
    _scaffold(_three_chapter_units(), kb)
    doc = kb / "d"
    manifest_path = doc / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    reviewed = manifest.sections[1].model_copy(
        update={"status": "reviewed", "summary": "Approved summary."}
    )
    models.save_yaml_model(
        manifest_path,
        manifest.model_copy(update={"sections": [manifest.sections[0], reviewed, *manifest.sections[2:]]}),
    )
    (doc / "ch5-nav.md").write_text("## 5.3 Airspace\n\nApproved L2 text.\n", encoding="utf-8")
    before = _snapshot(doc, "ch5-", "ch7-")

    new6 = [
        SectionUnit("6", "PROCEDURES", "6", "Proc intro rewritten.", []),
        SectionUnit("6.1", "Steps", "6", "Steps body.", []),
    ]
    report = _scaffold(new6, kb, chapters={"6"})

    assert _snapshot(doc, "ch5-", "ch7-") == before
    merged = models.load_yaml_model(manifest_path, models.Manifest)
    assert [s.id for s in merged.sections] == ["5", "5.3", "6", "6.1", "7"]
    assert merged.sections[1].status == "reviewed"
    assert merged.sections[1].summary == "Approved summary."
    assert merged.sections[2].file == "ch6-procedures"
    assert not (doc / "ch6-proc.md").exists()        # old stem of the rewritten chapter is gone
    assert not (doc / "ch6-proc.raw.md").exists()
    assert "Proc intro rewritten." in (doc / "ch6-procedures.raw.md").read_text(encoding="utf-8")
    assert report.n_sections == 2
    assert report.files == ["ch6-procedures.md", "ch6-procedures.raw.md"]


def test_sections_reingest_of_a_new_chapter_appends(tmp_path: Path):
    kb = tmp_path / ".kb"
    _scaffold(_three_chapter_units(), kb)
    _scaffold([SectionUnit("8", "GLOSSARY", "8", "Gloss.", [])], kb, chapters={"8"})
    merged = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert [s.id for s in merged.sections] == ["5", "5.3", "6", "7", "8"]
    assert (kb / "d" / "ch5-nav.raw.md").exists()


def test_sections_without_previous_manifest_writes_only_named_chapters(tmp_path: Path):
    kb = tmp_path / ".kb"
    report = _scaffold(_three_chapter_units(), kb, chapters={"6"})
    assert [s.id for s in models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest).sections] == ["6"]
    assert report.n_sections == 1


def test_full_reingest_still_replaces_everything(tmp_path: Path):
    kb = tmp_path / ".kb"
    _scaffold(_three_chapter_units(), kb)
    _scaffold([SectionUnit("5", "NAV", "5", "Only nav now.", [])], kb)
    doc = kb / "d"
    assert {p.name for p in doc.glob("*.md")} == {"ch5-nav.md", "ch5-nav.raw.md"}
    assert [s.id for s in models.load_yaml_model(doc / "_manifest.yaml", models.Manifest).sections] == ["5"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_scaffold.py -k "sections_reingest or without_previous or full_reingest"`
Expected: the first two FAIL (ch5/ch7 deleted, manifest holds only `6`/`8`); the last two PASS already (they pin today's behaviour).

- [ ] **Step 3: Implement the merge**

Add helpers after `chapter_stem` in `scaffold.py`:

```python
def _stem_prefix(chapter: str) -> str:
    """The part of chapter_stem() that does not depend on the title."""
    return f"ch{chapter}" if chapter and chapter[0].isdigit() else chapter


def _stem_of(filename: str) -> str:
    for suffix in (".raw.md", ".md"):
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def _belongs_to(stem: str, prefixes: list[str]) -> bool:
    return any(stem == p or stem.startswith(p + "-") for p in prefixes)


def _load_previous(doc_dir: Path) -> models.Manifest | None:
    path = doc_dir / "_manifest.yaml"
    return models.load_yaml_model(path, models.Manifest) if path.exists() else None


def _merge_sections(
    old: list[models.SectionEntry],
    new: list[models.SectionEntry],
    prefixes: list[str],
) -> list[models.SectionEntry]:
    """Old entries of the rewritten chapters drop out; the new ones take
    their place (or the end, for a chapter never ingested before). Every
    other entry is copied verbatim — status, summary, tokens included."""
    kept: list[models.SectionEntry] = []
    insert_at: int | None = None
    for entry in old:
        if _belongs_to(entry.file, prefixes):
            if insert_at is None:
                insert_at = len(kept)
            continue
        kept.append(entry)
    at = len(kept) if insert_at is None else insert_at
    return kept[:at] + new + kept[at:]
```

In `scaffold_doc`, replace lines 56-63 (`if chapters is not None: ... stale.unlink()`):

```python
    doc_dir = kb_dir / doc_id
    previous = _load_previous(doc_dir) if chapters is not None else None
    if chapters is not None:
        units = [u for u in units if u.chapter in chapters]
    rewritten = [_stem_prefix(c) for c in sorted(chapters)] if chapters else []

    doc_dir.mkdir(parents=True, exist_ok=True)
    for stale in doc_dir.glob("*.md"):
        # Full ingest (or --sections with nothing to merge into): replace
        # everything. --sections onto an existing doc: only the files of
        # the chapters being rewritten go; the rest is someone's reviewed
        # work and stays byte-for-byte.
        if previous is None or _belongs_to(_stem_of(stale.name), rewritten):
            stale.unlink()
```

and where the manifest is built, replace `sections=sections,` with:

```python
        sections=(
            _merge_sections(previous.sections, sections, rewritten)
            if previous is not None
            else sections
        ),
```

- [ ] **Step 4: Run the scaffold tests and the seam**

Run: `.venv/Scripts/python -m pytest -q tests/test_scaffold.py tests/test_ingest_seam.py tests/test_ingest_cli.py`
Expected: all PASS (`test_scaffold_chapter_filter` has no previous manifest → unchanged path).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/scaffold.py tests/test_scaffold.py
git commit -m "feat(ingest): --sections re-ingest merges into the existing manifest instead of deleting unnamed chapters (A-F6)"
```

---

### Task 10: `run_ingest` — logging bridge, notes → report, outline warning, `sections:` line

**Files:**
- Modify: `src/center_kb/ingestcmd.py`
- Test: `tests/test_ingest_cli.py`

**Interfaces:**
- Consumes: `sectioner.build_units_with_notes`, `SectioningNotes` (Tasks 2-6); `parser.bookmark_ids -> set | None` (Task 7); `ScaffoldReport.token_stats` (Task 8).
- Produces: report lines listed in the spec §3; `run_ingest` signature unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ingest_cli.py`:

```python
def _stub_parser(monkeypatch, items, bookmark_ids=frozenset()):
    from center_kb.ingest import parser

    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: object())
    monkeypatch.setattr(parser, "doc_to_items", lambda doc, assets_dir=None, pdf_path=None: items)
    monkeypatch.setattr(parser, "bookmark_ids", lambda pdf, config=None: bookmark_ids)
    monkeypatch.setattr(parser, "outline_parts", lambda pdf, config=None: None)


BIG = "Body text. " * 70

NOISY_ITEMS = [
    DocItem("heading", "5.0 NAVIGATION DATA", 1, page=1),
    DocItem("text", "Chapter intro. " + BIG, page=1),
    DocItem("heading", "5.6 Identifier", 2, page=2),
    DocItem("text", "Field body. " + BIG, page=2),
    DocItem("heading", "Table 5-6 Airport SID Record", 2, page=2),
    DocItem("table", "| a | b |\n|---|---|\n| 1 | 2 |", page=2),
    DocItem("heading", "NDB Navaid Record", 2, page=3),
    DocItem("text", "Value body. " + BIG, page=3),
]

INVERTED_ITEMS = [
    DocItem("heading", "5.0 NAVIGATION DATA", 1, page=1),
    DocItem("text", "Chapter intro. " + BIG, page=1),
    DocItem("heading", "5.84 RUNWAY TRANS", 2, page=212),
    DocItem("text", "para-a. " + BIG, page=212),
    DocItem("heading", "5.83 To FIX", 2, page=212),
    DocItem("text", "para-b. " + BIG, page=212),
]


def test_ingest_report_names_demotions_fallbacks_and_token_stats(tmp_path: Path, monkeypatch):
    _stub_parser(monkeypatch, NOISY_ITEMS)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert result.exit_code == 0, result.output
    assert "[warn] heading demoted to text (caption, page 2): 'Table 5-6 Airport SID Record'" in result.output
    assert "[warn] fallback id '5.6-ndb-navaid-record' for unparsed heading 'NDB Navaid Record' (page 3)" in result.output
    assert "sections: 3 · L3 tokens min/median/max " in result.output
    assert "below 300, 0 above 5000 · 1 fallback ids" in result.output


def test_ingest_report_names_a_page_inversion_without_layout_data(tmp_path: Path, monkeypatch):
    _stub_parser(monkeypatch, INVERTED_ITEMS)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert result.exit_code == 0, result.output
    assert (
        "[warn] heading order inverted on page 212: 5.84 before 5.83 — "
        "no layout data, body attribution may be wrong"
    ) in result.output


def test_ingest_report_carries_parser_logger_warnings_and_detaches(tmp_path: Path, monkeypatch):
    import logging

    from center_kb.ingest import parser

    def _items(doc, assets_dir=None, pdf_path=None):
        logging.getLogger("center_kb.ingest.parser").warning("picture on page 7 skipped: boom")
        return FAKE_ITEMS

    _stub_parser(monkeypatch, FAKE_ITEMS)
    monkeypatch.setattr(parser, "doc_to_items", _items)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert result.exit_code == 0, result.output
    assert "[warn] picture on page 7 skipped: boom" in result.output
    assert logging.getLogger("center_kb.ingest").handlers == []


def test_ingest_warns_when_the_outline_is_unreadable(tmp_path: Path, monkeypatch):
    _stub_parser(monkeypatch, FAKE_ITEMS, bookmark_ids=None)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert "[warn] PDF outline unreadable — bookmark cross-check skipped" in result.output


def test_ingest_warns_when_sections_filter_matches_nothing(tmp_path: Path, monkeypatch):
    _stub_parser(monkeypatch, FAKE_ITEMS)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none", "--sections", "9"]))
    assert result.exit_code == 0, result.output
    assert "[warn] no sections found for --sections 9" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_ingest_cli.py -k "report_names or carries_parser or outline_is_unreadable or matches_nothing"`
Expected: FAIL — none of the new lines appear; `bookmark_ids=None` raises `TypeError` in `crosscheck`.

- [ ] **Step 3: Rewrite `ingestcmd.py`**

Replace the file body from `_MAX_UNCOVERED_SHOWN = 10` to the end with:

```python
_MAX_UNCOVERED_SHOWN = 10
_MAX_NOTES_SHOWN = 20
_INGEST_LOGGER = "center_kb.ingest"


class _ReportHandler(logging.Handler):
    """Routes sectioner/parser/images warnings into the ingest report.
    cli.py never configures logging, so without this they fall to Python's
    lastResort handler: a bare stderr line outside the report."""

    def __init__(self, warn: Callable[[str], None]) -> None:
        super().__init__(level=logging.WARNING)
        self._warn = warn

    def emit(self, record: logging.LogRecord) -> None:
        self._warn(record.getMessage())


def _warn_capped(lines: list[str], label: str, warn: Callable[[str], None]) -> None:
    for line in lines[:_MAX_NOTES_SHOWN]:
        warn(line)
    if len(lines) > _MAX_NOTES_SHOWN:
        warn(f"{len(lines) - _MAX_NOTES_SHOWN} more {label} not shown")


def _page(page: int | None) -> str:
    return f"page {page}" if page else "page unknown"


def _warn_uncovered(missing, warn: Callable[[str], None]) -> None:
    """L3 is the complete-content layer: anything the section tree failed to
    place is content the KB no longer has. Name it rather than lose it."""
    for item in missing[:_MAX_UNCOVERED_SHOWN]:
        warn(f"content never reached L3 ({_page(item.page)}): {item.text[:100]}")
    if len(missing) > _MAX_UNCOVERED_SHOWN:
        warn(
            f"content never reached L3: {len(missing) - _MAX_UNCOVERED_SHOWN} "
            "more item(s) not shown"
        )


def _warn_notes(notes: sectioner.SectioningNotes, warn: Callable[[str], None]) -> None:
    demoted = []
    for d in notes.demoted:
        if d.reason == "repeated":
            pages = ", ".join(str(p) for p in d.pages if p is not None)
            where = f"repeated on {len(d.pages)} pages: {pages}"
        else:
            where = f"{d.reason}, {_page(d.pages[0] if d.pages else None)}"
        demoted.append(f"heading demoted to text ({where}): '{d.heading}'")
    _warn_capped(demoted, "demoted headings", warn)
    _warn_capped(
        [
            f"fallback id '{f.id}' for unparsed heading '{f.heading}' ({_page(f.page)})"
            for f in notes.fallbacks
        ],
        "fallback ids",
        warn,
    )
    _warn_capped(
        [
            f"heading order inverted on {_page(i.page)}: {i.first_id} before {i.second_id} — "
            + (
                "page re-ordered by layout, check both sections"
                if i.reordered
                else "no layout data, body attribution may be wrong"
            )
            for i in notes.inversions
        ],
        "page inversions",
        warn,
    )
    _warn_capped(
        [
            f"duplicate section id '{d.original}' in part {d.chapter} renamed to '{d.renamed}'"
            for d in notes.duplicates
        ],
        "duplicate ids",
        warn,
    )


def _echo_token_stats(
    report: ScaffoldReport, n_fallback: int, echo: Callable[[str], None]
) -> None:
    s = report.token_stats
    if s is None:
        return
    echo(
        f"sections: {s.n} · L3 tokens min/median/max {s.min}/{s.median}/{s.max} · "
        f"{s.below_300} below 300, {s.above_5000} above 5000 · {n_fallback} fallback ids"
    )


def run_ingest(
    opts: IngestOptions,
    echo: Callable[[str], None],
    warn: Callable[[str], None],
) -> ScaffoldReport:
    """Parse the PDF, split into sections, write the L3 + L1/L2 scaffold.

    Raises ValueError (invalid doc id / heading config) or RuntimeError
    (parse failure) — the CLI turns both into a red message + exit 1.
    """
    handler = _ReportHandler(warn)
    ingest_logger = logging.getLogger(_INGEST_LOGGER)
    ingest_logger.addHandler(handler)
    try:
        return _run_ingest(opts, echo, warn)
    finally:
        ingest_logger.removeHandler(handler)


def _run_ingest(
    opts: IngestOptions,
    echo: Callable[[str], None],
    warn: Callable[[str], None],
) -> ScaffoldReport:
    scaffold.validate_doc_id(opts.doc_id)  # before doc_id touches any path
    manifest_path = opts.kb_dir / opts.doc_id / "_manifest.yaml"
    previous = None
    if manifest_path.exists():
        previous = models.load_yaml_model(manifest_path, models.Manifest).ingest
    heading_config = sectioner.resolve_heading_config(
        opts.chapter_pattern, opts.appendix_pattern, opts.attachment_pattern, previous
    )

    doc = parser.load_or_parse(opts.pdf, opts.work_dir / opts.doc_id)
    items = parser.doc_to_items(
        doc, assets_dir=opts.kb_dir / opts.doc_id / "assets", pdf_path=opts.pdf
    )
    parts = (
        None if opts.no_bookmarks else parser.outline_parts(opts.pdf, heading_config)
    )
    if parts:
        echo(f"sectioning: bookmarks ({len(parts)} parts)")
    else:
        echo("sectioning: heading patterns")
    units, notes = sectioner.build_units_with_notes(
        items, config=heading_config, parts=parts
    )

    _warn_notes(notes, warn)
    _warn_uncovered(sectioner.uncovered(items, units), warn)

    bm_ids = parser.bookmark_ids(opts.pdf, heading_config)
    if bm_ids is None:
        warn("PDF outline unreadable — bookmark cross-check skipped")
    elif bm_ids:
        for warning in parser.crosscheck({u.id for u in units}, bm_ids):
            warn(warning)

    chapters = {s.strip() for s in opts.sections.split(",") if s.strip()} or None
    if chapters and not any(u.chapter in chapters for u in units):
        warn(f"no sections found for --sections {opts.sections}; nothing written for those chapters")
    tag_list = [t.strip() for t in opts.tags.split(",") if t.strip()]
    report = scaffold.scaffold_doc(
        units,
        doc_id=opts.doc_id,
        title=(
            opts.doc_id
            if not hasattr(doc, "name")
            else (getattr(doc, "name", "") or opts.doc_id)
        ),
        tags=tag_list,
        revision=opts.revision,
        source_path=opts.pdf,
        kb_dir=opts.kb_dir,
        chapters=chapters,
        heading_config=heading_config,
        part_titles={p.id: p.title for p in parts} if parts else None,
        used_bookmarks=bool(parts),
    )
    _echo_token_stats(report, len(notes.fallbacks), echo)
    return report
```

Add `import logging` to the imports at the top of the file.

- [ ] **Step 4: Run the CLI tests**

Run: `.venv/Scripts/python -m pytest -q tests/test_ingest_cli.py tests/test_ingest_seam.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingestcmd.py tests/test_ingest_cli.py
git commit -m "feat(ingest): report every sectioning decision, bridge logger warnings, print the token distribution (A-F1, A-F4, A-F5)"
```

---

### Task 11: `rapidocr` in the `ingest` extra, lock regenerated

**Files:**
- Modify: `pyproject.toml:34`
- Modify: `uv.lock` (generated)

**Interfaces:** none.

- [ ] **Step 1: Confirm the package name the code imports**

Run: `grep -n "from rapidocr" src/center_kb/ingest/images.py`
Expected: `from rapidocr import RapidOCR` — the distribution is `rapidocr`, already in `uv.lock` transitively (`grep -n 'name = "rapidocr"' uv.lock`).

- [ ] **Step 2: Declare it**

```toml
ingest = [
    "docling>=2.0", "imagehash>=4.3", "Pillow>=10.0", "pypdfium2>=4.30,<6",
    # rapidocr: the second image-description source (images.ocr_image).
    # Without it captionless images silently lose their `Figure:` line.
    "rapidocr>=3.0",
]
```

- [ ] **Step 3: Regenerate and check the lock**

Run: `uv lock && uv lock --check`
Expected: `uv lock` rewrites `uv.lock` (the `center-kb` package's `ingest` extra gains `rapidocr`); `uv lock --check` exits 0.

- [ ] **Step 4: Commit both files together**

```bash
git add pyproject.toml uv.lock
git commit -m "build: declare rapidocr in the ingest extra (A-F9)"
```

---

### Task 12: Spec §4 and README §7.1 rewritten to match

**Files:**
- Modify: `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md` (§4.2, §4.3, §4.4, §4.7)
- Modify: `README.md` (§7.1, the "Re-ingest is a full replace" paragraph and the paragraph before it)

**Interfaces:** none.

- [ ] **Step 1: Phase-1 spec §4.2 — after the id table, add**

```markdown
Heading không khớp mẫu nào nhưng là nhiễu Docling gán nhầm — **không** thành section, hạ thành text in đậm trong section đang mở (nội dung không mất), và báo cáo ingest ghi một dòng `[warn] heading demoted to text (<lý do>, page N): '<heading>'`:

- caption: `^(Table|Figure|Fig\.?|Diagram|Chart|Exhibit)\s+[A-Z]?\d` (không phân biệt hoa thường) — `Table 5-6 …`, `Fig. A1 …`; `Table of Contents` và `5.149 Figure of Merit` không bị ảnh hưởng;
- dòng nhãn: có ≥ 2 nhóm `Nhãn:` (`Used On: … Length: … Character Type: Alpha`);
- lặp: cùng một heading không parse được xuất hiện trên ≥ 3 trang khác nhau (running header, khối `COMMENTARY`).

Heading số **không có tiêu đề** (`5.15`) giữ nguyên id với `title: ""`; L2/L3 ghi `## 5.15`. Không bao giờ gộp về id chương.

Mọi fallback id còn lại được liệt kê: `[warn] fallback id '<id>' for unparsed heading '<heading>' (page N)`. Id trùng (part lặp số) đổi thành `<id>-2`, `-3`… kèm `[warn] duplicate section id …`. Id từ pattern tuỳ chỉnh không bao giờ chứa khoảng trắng (`Part A` → `Part-A`); scaffold từ chối id rỗng hoặc có khoảng trắng.

Trang có heading số cùng cha đảo thứ tự (`5.84` rồi `5.83`) được sắp lại theo bố cục (cột trái trước phải, trên xuống dưới, tiêu đề trải ngang dẫn đầu) khi mọi item có bbox; luôn có `[warn] heading order inverted on page N: …`. Trang không đảo giữ nguyên thứ tự đọc của Docling.
```

- [ ] **Step 2: Phase-1 spec §4.3 — replace the paragraph**

```markdown
### 4.3 Đối chiếu bookmark (validation, không chặn)

Với tài liệu có bookmark chuẩn: so cây section Docling với outline PDF (pypdf), **hai chiều**. Bookmark không unit nào phủ → `[warn] bookmark section 'X' not found in the extracted tree`. Unit số không có trong outline, tại cấp mà outline có liệt kê anh em cùng cha → `[warn] section 'X' not in the PDF outline` (outline chỉ tới chương thì không phán xét `5.x`). Một fallback con (`5.6-commentary`) **không** phủ bookmark `5.6`; chỉ appendix/attachment mới được phủ bởi con namespaced. Outline không đọc được → `[warn] PDF outline unreadable — bookmark cross-check skipped`. Annex 4 bỏ qua bước này.
```

- [ ] **Step 3: Phase-1 spec §4.4 — replace the numbered list**

```markdown
Áp theo thứ tự:

1. **Độ sâu tối đa 3 cấp** (`x.y.z`) — heading sâu hơn nhập vào section cha.
2. **Gộp section nhỏ, all-or-nothing theo cha**: section lá có L3 < 200 token nhập vào cha **chỉ khi** cha sau khi gộp mọi lá nhỏ vẫn ≤ 5.000 token; ngược lại không gộp lá nào của cha đó. Chương định nghĩa field (ARINC ch5: 324 field) vì thế giữ **mỗi field một section** — đó là chủ ý, để cite được `§5.83` (quyết định 2026-09-08).
3. **Mục tiêu đo được, không phải luật**: mỗi đơn vị L3 khoảng 300–5.000 token. `kb ingest` in phân bố cuối báo cáo (`sections: N · L3 tokens min/median/max … · K below 300, M above 5000 · F fallback ids`); tài liệu field-definition được phép nằm ngoài band.
```

- [ ] **Step 4: Phase-1 spec §4.7 — replace the paragraph**

```markdown
`kb ingest <pdf> --id <id> --tags <tags> [--sections 5,6]` — Docling parse cả PDF (cache), nhưng chỉ scaffold + summarize các chương được chọn. Trên doc đã có manifest, `--sections` là **merge**: chỉ file và entry manifest của chương được nêu bị ghi lại; chương khác giữ nguyên byte-for-byte (kể cả `status`/`summary` đã duyệt). Không có `--sections` là full replace.
```

- [ ] **Step 5: README §7.1 — replace the "Re-ingest is a full replace" paragraph**

```markdown
**Re-ingest:** without `--sections`, `kb ingest` on an existing `--id` is a full replace — every `.md` of that doc is deleted before the new split is written. With `--sections 6`, only chapter 6's files and manifest entries are rewritten; every other chapter, including reviewed L2 summaries and their `status`, is left untouched. A `--sections` value that matches no chapter writes nothing and says so.

The ingest report names every sectioning decision so nothing is silent: headings demoted to text (table captions, `Used On: … Length: …` label lines, headings repeated on 3+ pages), every fallback id, pages whose numbered headings arrived out of order (re-ordered by layout when the PDF gives coordinates, flagged either way), duplicate ids renamed `<id>-2`, bookmarks the split missed and sections the PDF outline does not name, and the L3 token distribution (`sections: N · L3 tokens min/median/max … · K below 300, M above 5000`). Field-definition documents legitimately sit below the 300-token target — each field is its own section so it can be cited.
```

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md README.md
git commit -m "docs: phase-1 §4 and README §7.1 match the ingest report, merge --sections and the per-field decision"
```

---

### Task 13: Whole-suite verification and branch review

**Files:** none new.

- [ ] **Step 1: Lint**

Run: `.venv/Scripts/ruff check src tests`
Expected: clean. Fix any `E741`/unused-import complaints inline.

- [ ] **Step 2: Full test run**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass; `tests/test_ingest_seam.py` green without touching `tests-gate/fixtures/pending-kb/`. If the seam test is red, run `.venv/Scripts/python scripts/gen_e2e_fixture.py`, read `git diff tests-gate/`, and only commit it if the diff is the intended heading-line change (it should be empty — the demo-doc has titles on every unit).

- [ ] **Step 3: Lock and tree checks**

Run: `uv lock --check && git status --short -- .kb/`
Expected: lock check exits 0; `.kb/` shows no changes.

- [ ] **Step 4: Request the whole-branch review**

Use superpowers:requesting-code-review against the spec. The reviewer must confirm: every F1–F9 item in the spec's "Tests and trip-wires" has a test by name; `build_units` behaviour on the pre-existing fixtures is unchanged; no `.kb/` diff; the `_HEADING_RE` change has no other consumer (grep `## ` parsing in `src/`).

- [ ] **Step 5: Finish the branch**

Use superpowers:finishing-a-development-branch (PR to `main`; the PR description lists the F-numbers closed and names the follow-ups: re-ingest after B-4/B-5, per-Part namespacing, one-row tables in the build batch).
