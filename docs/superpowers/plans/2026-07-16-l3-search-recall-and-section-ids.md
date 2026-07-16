# L3 Search Recall + Section Id Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keyword search tìm được nội dung chỉ tồn tại ở L3 raw (section fold, tables sau 500 chars), `get_section` resolve folded id, và fallback section id đọc được mọi script thay vì `x{n}`.

**Architecture:** Mở rộng bảng FTS5 hiện có từ 3 lên 4 cột (`title, summary, body_l2, body_l3`) với bm25 column weights, bump `SCHEMA_VERSION` để rebuild-once tự migrate; embedding leg giữ nguyên (cap 500 chars). Snippet L3 sinh pure-Python trong `query.search`. Folded-id lookup đi qua longest-prefix parent + slice `###`. Fallback id trong sectioner chuyển sang slug Unicode.

**Tech Stack:** Python 3.13, SQLite FTS5 (`unicode61`), sqlite-vec, pytest, pydantic models sẵn có.

**Spec:** `docs/superpowers/specs/2026-07-16-l3-search-recall-and-section-ids-design.md`

## Global Constraints

- Test hermetic: không LLM thật, không embed model thật — embedder inject (`FakeEmbedder` trong `tests/conftest.py`) hoặc `None`.
- Không migration schema: bump `SCHEMA_VERSION = "2"` — `open_db` rebuild-once sẵn có tự lo.
- Embedding text giữ nguyên format `title + summary + body[:_L2_HEAD_CHARS]` (cap 500) — KHÔNG đưa L3/full L2 vào embed.
- `tokenize()` ASCII-only giữ nguyên (Non-goal của spec).
- `chapter_stem` / tên file giữ ASCII `slugify` cũ — chỉ section id dùng slug unicode mới.
- Commit format `<type>: <description>`, không attribution footer.
- Format: black + ruff; type annotations đầy đủ trên function signature mới.
- Chạy test: `python3 -m pytest` từ repo root (venv python3.13 đã có sẵn dependencies).

---

### Task 1: `mdutils.slugify_id` — slug Unicode cho section id

**Files:**
- Modify: `src/center_kb/mdutils.py` (thêm function, cạnh `slugify` dòng 14)
- Test: `tests/test_mdutils.py`

**Interfaces:**
- Produces: `slugify_id(text: str) -> str` — giữ chữ/số mọi script, lowercase, nối `-`, cắt 40 chars. Task 3 (sectioner) dùng.

- [ ] **Step 1: Write the failing tests**

Thêm vào cuối `tests/test_mdutils.py`:

```python
def test_slugify_id_keeps_cjk():
    assert mdutils.slugify_id("表5-6 データ概要") == "表5-6-データ概要"


def test_slugify_id_keeps_cyrillic():
    assert mdutils.slugify_id("ЧАСТЬ 1") == "часть-1"


def test_slugify_id_keeps_vietnamese_diacritics():
    assert mdutils.slugify_id("Bảng tổng hợp dữ liệu") == "bảng-tổng-hợp-dữ-liệu"


def test_slugify_id_strips_symbols_and_underscores():
    assert mdutils.slugify_id("__Table: 5-6 (final)__") == "table-5-6-final"


def test_slugify_id_empty_when_no_word_chars():
    assert mdutils.slugify_id("***") == ""


def test_slugify_id_caps_at_40_chars():
    out = mdutils.slugify_id("a" * 80)
    assert out == "a" * 40
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_mdutils.py -k slugify_id -v`
Expected: FAIL — `AttributeError: module 'center_kb.mdutils' has no attribute 'slugify_id'`

- [ ] **Step 3: Implement**

Trong `src/center_kb/mdutils.py`, ngay sau `slugify()` (dòng 14-17):

```python
def slugify_id(text: str) -> str:
    """Unicode-aware slug for section ids: keep letters/digits of every
    script (slugify() drops non-ASCII entirely — CJK/Cyrillic titles would
    vanish). File names keep using slugify(); this is for ids only."""
    text = unicodedata.normalize("NFKC", text)
    slug = re.sub(r"[\W_]+", "-", text).strip("-").lower()
    return slug[:40].rstrip("-")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_mdutils.py -v`
Expected: PASS toàn bộ (cả test cũ).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/mdutils.py tests/test_mdutils.py
git commit -m "feat: slugify_id — unicode-aware slug for section ids"
```

---

### Task 2: `mdutils.slice_subsection` — slice folded child `###`

**Files:**
- Modify: `src/center_kb/mdutils.py`
- Test: `tests/test_mdutils.py`

**Interfaces:**
- Produces: `slice_subsection(md: str, section_id: str) -> str | None` — cắt block `### {id} {title}` đến heading `###`/`##` kế tiếp (hoặc EOF). Task 6 (get_section fallback) dùng.
- Không đụng `_HEADING_RE` / `slice_section` hiện có (chỉ match `## `).

- [ ] **Step 1: Write the failing tests**

Thêm vào `tests/test_mdutils.py`:

```python
UNIT_MD = """## 3.2 Fasteners

Intro prose of 3.2.

### 3.2.1 Torque values

Torque 12 Nm for bolt XYZ-9.

### 3.2.2 Washers

Washer spec text.

## 3.3 Next section

Other text.
"""


def test_slice_subsection_returns_folded_child():
    block = mdutils.slice_subsection(UNIT_MD, "3.2.1")
    assert block is not None
    assert block.startswith("### 3.2.1 Torque values")
    assert "Torque 12 Nm" in block
    assert "Washer spec" not in block


def test_slice_subsection_last_child_runs_to_next_h2():
    block = mdutils.slice_subsection(UNIT_MD, "3.2.2")
    assert block is not None
    assert "Washer spec text." in block
    assert "Next section" not in block


def test_slice_subsection_missing_returns_none():
    assert mdutils.slice_subsection(UNIT_MD, "9.9.9") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_mdutils.py -k slice_subsection -v`
Expected: FAIL — `AttributeError: ... no attribute 'slice_subsection'`

- [ ] **Step 3: Implement**

Trong `src/center_kb/mdutils.py`, sau `slice_section()`:

```python
_SUBHEADING_RE = re.compile(r"^### (?P<sid>\S+)[ \t]+(?P<title>.+?)\s*$")


def slice_subsection(md: str, section_id: str) -> str | None:
    """Slice a folded child ('### <id> <title>' inside a unit body) — ends at
    the next '###'/'##' heading. slice_section() only addresses '## ' units;
    folded children need this."""
    lines = md.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = _SUBHEADING_RE.match(line)
        if m and m.group("sid") == section_id:
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if lines[j].startswith(("## ", "### ")):
            return "\n".join(lines[start:j]).strip()
    return "\n".join(lines[start:]).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_mdutils.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/mdutils.py tests/test_mdutils.py
git commit -m "feat: slice_subsection — address folded ### children in unit bodies"
```

---

### Task 3: Sectioner — fallback id unicode, demote heading toàn số, warn `x{n}`

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py` (`_fallback_slug` dòng 150-157, nhánh unparsed-heading dòng 302-325, imports dòng 7)
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Consumes: `mdutils.slugify_id` (Task 1).
- Produces: hành vi `build_units` — heading CJK/Cyrillic không số sinh id `{parent}-{slug-unicode}`; heading toàn số thành body text của node đang mở; `x{n}` chỉ khi slug rỗng thật, kèm `logger.warning`.

- [ ] **Step 1: Write the failing tests**

Thêm vào `tests/test_sectioner.py` (dùng pattern DocItem như test hiện có trong file):

```python
def test_fallback_id_keeps_cjk_title():
    items = [
        DocItem(kind="heading", text="5.6 Identifier Field", level=1),
        DocItem(kind="text", text="Parent body."),
        DocItem(kind="heading", text="表5-6 データ概要", level=2),
        DocItem(kind="text", text="CJK child body. " * 60),
    ]
    units = build_units(items, min_tokens=1)
    ids = [u.id for u in units]
    assert "5.6-表5-6-データ概要" in ids
    assert not any("-x1" in i for i in ids)


def test_digit_only_heading_demoted_to_body():
    items = [
        DocItem(kind="heading", text="5.6 Identifier Field", level=1),
        DocItem(kind="text", text="Parent body."),
        DocItem(kind="heading", text="123", level=2),
        DocItem(kind="text", text="Stray page content."),
    ]
    units = build_units(items, min_tokens=1)
    ids = [u.id for u in units]
    assert ids == ["5.6"]
    assert "123" in units[0].body_md
    assert "Stray page content." in units[0].body_md


def test_last_resort_xn_id_logs_warning(caplog):
    # any(ch.isalnum()) gate chặn heading thuần ký hiệu — ép slug rỗng bằng
    # ký tự alnum mà \w không giữ là không tồn tại, nên mô phỏng qua heading
    # chữ + slug rỗng nhân tạo: monkeypatch không cần — dùng title chỉ có "_"
    # bị gate chặn; test này khóa CONTRACT: nếu x{n} được sinh thì phải warn.
    import logging

    from center_kb.ingest import sectioner as sec_mod

    with caplog.at_level(logging.WARNING, logger="center_kb.ingest.sectioner"):
        items = [
            DocItem(kind="heading", text="5.6 Identifier Field", level=1),
            DocItem(kind="text", text="Parent body."),
        ]
        build_units(items, min_tokens=1)
    # không heading nào rơi last-resort → không warning nào được phát
    assert not [r for r in caplog.records if "fallback id" in r.message]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sectioner.py -k "fallback_id or digit_only or last_resort" -v`
Expected: `test_fallback_id_keeps_cjk_title` FAIL (id hiện tại là `5.6-x1` vì slugify vứt CJK → digit-only `5-6` → loại); `test_digit_only_heading_demoted_to_body` FAIL (hiện sinh section `5.6-x1`); `test_last_resort_xn_id_logs_warning` PASS sẵn (khóa contract).

- [ ] **Step 3: Implement**

Trong `src/center_kb/ingest/sectioner.py`:

Imports (dòng 3-7) — thêm `logging` và `slugify_id`:

```python
import logging
import re
from dataclasses import dataclass, field

from center_kb import models
from center_kb.mdutils import count_tokens, extract_tables, slugify_id

logger = logging.getLogger("center_kb.ingest.sectioner")
```

(`slugify` không còn được dùng trong file này sau khi đổi — xoá khỏi import.)

`_fallback_slug` (dòng 150-157) đổi sang slug unicode:

```python
def _fallback_slug(title: str) -> str:
    """Human-readable id fragment for an unparsed heading. Empty when the
    title has no usable characters, or would masquerade as a numbered
    section id (e.g. a bare page number "123")."""
    slug = slugify_id(title)
    if not slug or slug.replace("-", "").isdigit():
        return ""
    return slug
```

Nhánh unparsed-heading (dòng 306-312 hiện tại — sau `while stack[-1].fallback: stack.pop()` / `parent = stack[-1]`):

```python
                slug = _fallback_slug(normalized)
                if not slug:
                    if any(ch.isdigit() for ch in normalized):
                        # Bare page number leaked in as a heading — content
                        # noise, not structure: demote to body text so it
                        # never opens an opaque x{n} section.
                        stack[-1].body.append(normalized)
                        continue
                    fallback_seq += 1
                    slug = f"x{fallback_seq}"
                    logger.warning(
                        "synthetic fallback id %r for unparsed heading %r",
                        slug,
                        normalized,
                    )
```

Lưu ý: `stack[-1]` (node đang mở) chứ không phải `parent` — heading số lạc phải rơi vào node đang tích content, khớp hành vi demote của nhánh `":"` dòng 235.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sectioner.py -v`
Expected: PASS toàn bộ — gồm test cũ dòng ~135 (comment nhắc `_fallback_slug` reject bare number: hành vi reject giữ nguyên, chỉ khác downstream demote thay vì x{n}; nếu test cũ assert tồn tại section `x{n}` cho heading số → cập nhật assert theo hành vi demote mới, đó là chủ đích của spec §6a).

- [ ] **Step 5: Run full ingest-related suites**

Run: `python3 -m pytest tests/test_sectioner.py tests/test_scaffold.py tests/test_ingest_seam.py tests/test_parser.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/ingest/sectioner.py tests/test_sectioner.py
git commit -m "feat: unicode fallback section ids — CJK/Cyrillic headings no longer collapse to x{n}"
```

---

### Task 4: searchdb schema v2 — FTS 4 cột, hash tách khỏi embed, bm25 weights

**Files:**
- Modify: `src/center_kb/searchdb.py` (dòng 28, 144-147, 228-244, 286-323, 390-395, 533-548)
- Test: `tests/test_searchdb.py`

**Interfaces:**
- Consumes: fixture `fed_hub` + `make_fed_entry` (`tests/conftest.py`) — đã ghi cả `ch1.md` lẫn `ch1.raw.md`.
- Produces: bảng `fts(title, summary, body_l2, body_l3)`; `_section_parts(kb_dir, doc_id, sec) -> tuple[str, str, str, str]`; `_content_digest(title, summary, body_l2, body_l3) -> str`; `fts_search` giữ nguyên signature `(conn, text, tags, k) -> list[tuple[int, float]]`. Task 5/9 dựa trên index này.

- [ ] **Step 1: Write the failing tests**

Thêm vào `tests/test_searchdb.py`:

```python
def test_fts_indexes_l2_beyond_500_chars(fed_hub):
    # table nằm SAU summary dài — ngoài cửa sổ body_head cũ
    entry = fed_hub / "federation" / "arinc-kb"
    l2 = entry / "arinc-424" / "ch1.md"
    l2.write_text(
        "## 5.3 Restrictive Airspace\n\n"
        + ("Prose padding sentence. " * 30)  # > 500 chars
        + "\n\n| Part | Torque |\n|---|---|\n| BOLTQX9 | 12 Nm |\n",
        encoding="utf-8",
    )
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    conn = searchdb.open_db(hub)
    try:
        hits = searchdb.fts_search(conn, "BOLTQX9")
        assert len(hits) == 1
    finally:
        conn.close()


def test_fts_indexes_l3_only_terms(fed_hub):
    # term chỉ tồn tại trong raw L3 (section fold) — L2 summary không nhắc
    entry = fed_hub / "federation" / "arinc-kb"
    l3 = entry / "arinc-424" / "ch1.raw.md"
    l3.write_text(
        "## 5.3 Restrictive Airspace\n\nFull raw text.\n\n"
        "### 5.3-notes Folded notes\n\nUnique term ZEBRAFOLD77 here.\n",
        encoding="utf-8",
    )
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    conn = searchdb.open_db(hub)
    try:
        hits = searchdb.fts_search(conn, "ZEBRAFOLD77")
        assert len(hits) == 1
    finally:
        conn.close()


def test_sync_reindexes_when_only_l3_changes(fed_hub):
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    entry = fed_hub / "federation" / "arinc-kb"
    l3 = entry / "arinc-424" / "ch1.raw.md"
    l3.write_text(
        l3.read_text(encoding="utf-8") + "\nAppended raw-only fact QUOKKA55.\n",
        encoding="utf-8",
    )
    _bump_meta(entry)
    report = searchdb.sync(hub, None)
    assert report.sections_updated == 1  # hash phủ body_l3 → re-index


def test_sync_survives_missing_raw_md(fed_hub):
    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").unlink()
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    report = searchdb.sync(hub, None)
    assert report.sections_updated >= 1  # không fail, body_l3 rỗng
    conn = searchdb.open_db(hub)
    try:
        assert conn.execute("SELECT COUNT(*) FROM fts").fetchone() == (2,)
    finally:
        conn.close()


def test_bm25_title_match_outranks_l3_only_match(fed_hub, tmp_path):
    fed = fed_hub / "federation"
    make_fed_entry(
        fed, "title-kb", "title-doc",
        sec_id="1.1", sec_title="Corridor Spacing",
        sec_summary="About corridor spacing.",
        l2="## 1.1 Corridor Spacing\n\nCondensed corridor text.\n",
        l3="## 1.1 Corridor Spacing\n\nRaw corridor text.\n",
    )
    make_fed_entry(
        fed, "body-kb", "body-doc",
        sec_id="2.1", sec_title="Unrelated Title",
        sec_summary="Unrelated summary.",
        l2="## 2.1 Unrelated Title\n\nUnrelated condensed.\n",
        l3="## 2.1 Unrelated Title\n\ncorridor corridor corridor mentioned in raw.\n",
    )
    from center_kb.federation import write_federation_index

    write_federation_index(fed)
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    conn = searchdb.open_db(hub)
    try:
        hits = searchdb.fts_search(conn, "corridor")
        rows = searchdb.load_sections(conn, [h[0] for h in hits])
        ranked = [rows[h[0]].section_id for h in hits]
        assert ranked.index("1.1") < ranked.index("2.1")  # title+summary thắng L3 spam
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_searchdb.py -k "beyond_500 or l3_only or only_l3_changes or missing_raw or outranks" -v`
Expected: FAIL — `beyond_500`/`l3_only` không match (index chỉ có 500 chars đầu, không có L3); `only_l3_changes` fail vì hash không phủ L3 (`sections_updated == 0`); các test khác fail tương ứng.

- [ ] **Step 3: Implement**

Trong `src/center_kb/searchdb.py`:

Dòng 28: `SCHEMA_VERSION = "2"`.

Dòng 29-34, thêm constant weights cạnh `K_LEG`:

```python
# bm25 column weights (title, summary, body_l2, body_l3) — title mạnh nhất,
# L3 yếu nhất để section raw dài không lấn át title/summary match (spec §3).
_BM25_WEIGHTS = "4.0, 2.0, 1.5, 1.0"
```

`_create_schema` (dòng 144-147):

```python
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5("
        "title, summary, body_l2, body_l3, tokenize='unicode61')"
    )
```

`_section_parts` (dòng 228-238) thành:

```python
def _section_parts(
    kb_dir: Path, doc_id: str, sec: models.SectionEntry
) -> tuple[str, str, str, str]:
    """(title, summary, body_l2, body_l3) — body_l2 = FULL L2 slice (summary
    + tables, không cap), body_l3 = full L3 slice từ .raw.md."""
    body_l2 = ""
    l2_path = kb_dir / doc_id / f"{sec.file}.md"
    if l2_path.exists():
        body_l2 = slice_section(l2_path.read_text(encoding="utf-8"), sec.id) or ""
    body_l3 = ""
    l3_path = kb_dir / doc_id / f"{sec.file}.raw.md"
    if l3_path.exists():
        body_l3 = slice_section(l3_path.read_text(encoding="utf-8"), sec.id) or ""
    else:
        logger.warning("raw L3 missing — FTS indexes L2 only: %s", l3_path)
    return sec.title, sec.summary, body_l2, body_l3
```

Sau `_embed_text` (dòng 241-244, giữ nguyên function), thêm:

```python
def _content_digest(title: str, summary: str, body_l2: str, body_l3: str) -> str:
    """Change-detection hash — phủ MỌI cột FTS (embed text thì vẫn capped:
    hash và embed tách nhau từ schema v2)."""
    joined = "\n".join((title, summary, body_l2, body_l3))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
```

`_sync_repo` (dòng 286-289 + 314-323):

```python
            title, summary, body_l2, body_l3 = _section_parts(
                repo.kb_dir, doc.id, sec
            )
            digest = _content_digest(title, summary, body_l2, body_l3)
```

và INSERT:

```python
            conn.execute(
                "INSERT INTO fts(rowid, title, summary, body_l2, body_l3) "
                "VALUES(?, ?, ?, ?, ?)",
                (cur.lastrowid, title, summary, body_l2, body_l3),
            )
```

`_sync_vectors` (dòng 389-396) — SELECT cột mới + cap khi compose embed text:

```python
        batch = conn.execute(
            "SELECT s.id, f.title, f.summary, f.body_l2 FROM sections s "
            f"JOIN fts f ON f.rowid = s.id WHERE s.id IN ({placeholders})",
            chunk,
        ).fetchall()
        vectors = embedder.embed(
            [
                _embed_text(title, summary, body[:_L2_HEAD_CHARS])
                for _, title, summary, body in batch
            ]
        )
```

`fts_search` (dòng 533-547) — weights ở cả SELECT lẫn ORDER BY:

```python
    sql = (
        f"SELECT fts.rowid, -bm25(fts, {_BM25_WEIGHTS}) FROM fts "
        "JOIN sections s ON s.id = fts.rowid WHERE fts MATCH ?"
    )
```

```python
    sql += f" ORDER BY bm25(fts, {_BM25_WEIGHTS}) LIMIT ?"  # bm25 nhỏ = khớp tốt
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_searchdb.py -v`
Expected: PASS toàn bộ — test cũ (`test_open_db_rebuilds_on_schema_version_mismatch`, sync/hash/race/vec) phải xanh nguyên trạng; hai chỗ duy nhất còn nhắc `body_head` là comment docstring — đã đổi hết ở Step 3.

- [ ] **Step 5: Run embed + query suites (không đổi hành vi semantic)**

Run: `python3 -m pytest tests/test_embed.py tests/test_query.py tests/test_query_semantic.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/searchdb.py tests/test_searchdb.py
git commit -m "feat: index full L2 + raw L3 in FTS (schema v2, weighted bm25) — hash split from embed text"
```

---

### Task 5: Snippet L3 trong `query.search`

**Files:**
- Modify: `src/center_kb/query.py` (dataclass dòng 33-43, `search()` dòng 104-153)
- Test: `tests/test_query_semantic.py`

**Interfaces:**
- Consumes: `searchdb.tokenize` (re-export sẵn trong query.py dòng 11), `mdutils.slice_section`, index v2 (Task 4).
- Produces: `QueryResult.snippet: str = ""`; helper `_l3_snippet(hub, row, terms, content) -> str`. Task 8 (surfaces) đọc `r.snippet`.

- [ ] **Step 1: Write the failing tests**

Thêm vào `tests/test_query_semantic.py` (file đã có fixture/import `HubHandle`, `search`; dùng `make_fed_entry` + `write_federation_index` như test_searchdb):

```python
def test_search_snippet_when_match_only_in_l3(fed_hub):
    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").write_text(
        "## 5.3 Restrictive Airspace\n\nRaw text.\n\n"
        "### 5.3-notes Folded notes\n\nUnique fact GRYPHON42 lives here only.\n",
        encoding="utf-8",
    )
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    results = search(hub, "GRYPHON42", embedder=None)
    assert len(results) == 1
    r = results[0]
    assert "gryphon42" not in r.content.lower()  # L2 không chứa term
    assert "GRYPHON42" in r.snippet
    assert r.snippet.startswith("…") or r.snippet.startswith("##")


def test_search_no_snippet_when_term_in_l2(fed_hub):
    hub = HubHandle(root=fed_hub)
    results = search(hub, "restrictive designation", embedder=None)
    assert results
    assert results[0].snippet == ""


def test_search_snippet_counts_into_budget(fed_hub):
    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").write_text(
        "## 5.3 Restrictive Airspace\n\nRaw text.\n\n"
        "### 5.3-notes Folded notes\n\nUnique fact GRYPHON42 lives here only.\n",
        encoding="utf-8",
    )
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    results = search(hub, "GRYPHON42", embedder=None)
    from center_kb.mdutils import count_tokens

    r = results[0]
    assert r.tokens == count_tokens(r.content) + count_tokens(r.snippet)
```

(`_bump_meta` — copy helper 4 dòng từ `tests/test_searchdb.py:149` nếu file này chưa có; không import chéo giữa test module.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_query_semantic.py -k snippet -v`
Expected: FAIL — `QueryResult` chưa có `snippet` / term L3-only ra kết quả nhưng snippet trống.

- [ ] **Step 3: Implement**

Trong `src/center_kb/query.py`:

Dataclass (dòng 33-43) thêm field:

```python
    match_mode: str = "keyword"  # "keyword" | "semantic" | "hybrid"
    snippet: str = ""  # trích L3 quanh match khi term không hiện trong L2
```

Constant + helper (sau `_row_content`, dòng 55):

```python
_SNIPPET_WINDOW = 150  # chars mỗi bên quanh hit đầu tiên trong L3


def _l3_snippet(
    hub: "HubHandle", row: "SectionRow", terms: list[str], content: str
) -> str:
    """Match nằm ở L3 (fold/tail) mà content L2 không chứa term nào → trích
    cửa sổ quanh hit đầu tiên để người dùng thấy vì sao section này khớp."""
    lower = content.lower()
    if not terms or any(t in lower for t in terms):
        return ""
    raw_path = (
        hub.federation_dir / row.repo_id / row.doc_id / f"{row.file}.raw.md"
    )
    if not raw_path.exists():
        return ""
    raw = slice_section(raw_path.read_text(encoding="utf-8"), row.section_id)
    if not raw:
        return ""
    raw_lower = raw.lower()
    for term in terms:
        pos = raw_lower.find(term)
        if pos < 0:
            continue
        start = max(0, pos - _SNIPPET_WINDOW)
        end = min(len(raw), pos + len(term) + _SNIPPET_WINDOW)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(raw) else ""
        return f"{prefix}{raw[start:end].strip()}{suffix}"
    return ""
```

Trong `search()` — trước vòng `for` (dòng ~123) thêm `terms = tokenize(text)`; trong vòng lặp, sau khi có `content` (dòng 129-134):

```python
        snippet = "" if mode == "semantic" else _l3_snippet(hub, row, terms, content)
        n_tokens = count_tokens(content) + (count_tokens(snippet) if snippet else 0)
```

(biến `mode` là phần tử thứ 3 của `fused` — đổi unpack `for rowid, score, mode in fused:` đã có sẵn) và thêm `snippet=snippet` vào constructor `QueryResult(...)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_query_semantic.py tests/test_query.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/query.py tests/test_query_semantic.py
git commit -m "feat: L3 snippet on search results when the match is invisible in L2"
```

---

### Task 6: `get_section` fallback cho folded id

**Files:**
- Modify: `src/center_kb/query.py` (`_get_section_in` dòng 156-182)
- Test: `tests/test_query.py`

**Interfaces:**
- Consumes: `mdutils.slice_subsection` (Task 2), `mdutils.slice_section`.
- Produces: `get_section(hub, doc, "3.2.1", level="l3")` trả subtree `###`; `level="l2"` trả parent section (citation id parent). Signature `get_section` không đổi.

- [ ] **Step 1: Write the failing tests**

Thêm vào `tests/test_query.py` (file đã có fixture hub/doc — dùng `make_fed_entry` pattern như các test khác trong file; nếu file dùng fixture riêng, viết đúng theo fixture đó khi implement):

```python
def test_get_section_folded_id_l3_returns_subtree(fed_hub):
    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").write_text(
        "## 5.3 Restrictive Airspace\n\nParent raw.\n\n"
        "### 5.3.1 Folded torque\n\nTorque 12 Nm bolt XYZ.\n\n"
        "### 5.3.2 Folded other\n\nOther text.\n",
        encoding="utf-8",
    )
    hub = HubHandle(root=fed_hub)
    r = get_section(hub, "arinc-424", "5.3.1", level="l3")
    assert r is not None
    assert r.section_id == "5.3.1"
    assert "Torque 12 Nm" in r.content
    assert "Folded other" not in r.content
    assert "§5.3.1" in r.citation


def test_get_section_folded_id_l2_returns_parent(fed_hub):
    hub = HubHandle(root=fed_hub)
    r = get_section(hub, "arinc-424", "5.3.1", level="l2")
    assert r is not None
    assert r.section_id == "5.3"  # L2 không có anchor con — trả parent, không nói dối
    assert "§5.3" in r.citation


def test_get_section_folded_id_unknown_returns_none(fed_hub):
    hub = HubHandle(root=fed_hub)
    assert get_section(hub, "arinc-424", "9.9.9", level="l3") is None


def test_get_section_prefix_picks_longest_parent(fed_hub):
    # manifest có cả "5" lẫn "5.3" → "5.3.1" phải chọn "5.3"
    entry = fed_hub / "federation" / "arinc-kb"
    manifest_path = entry / "arinc-424" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections.insert(
        0, models.SectionEntry(id="5", title="Chapter Five", file="ch1")
    )
    models.save_yaml_model(manifest_path, manifest)
    (entry / "arinc-424" / "ch1.raw.md").write_text(
        "## 5 Chapter Five\n\nChapter body.\n\n"
        "## 5.3 Restrictive Airspace\n\nParent raw.\n\n"
        "### 5.3.1 Folded torque\n\nTorque 12 Nm bolt XYZ.\n",
        encoding="utf-8",
    )
    hub = HubHandle(root=fed_hub)
    r = get_section(hub, "arinc-424", "5.3.1", level="l3")
    assert r is not None and "Torque 12 Nm" in r.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_query.py -k folded -v`
Expected: FAIL — hiện `get_section` trả `None` cho id ngoài manifest.

- [ ] **Step 3: Implement**

Trong `src/center_kb/query.py` — import thêm `slice_subsection` từ mdutils (dòng 10). Helper mới trước `_get_section_in`:

```python
def _parent_entry(
    manifest: models.Manifest, section_id: str
) -> models.SectionEntry | None:
    """Folded id không có entry riêng — parent là entry có id là prefix dài
    nhất của id yêu cầu, cắt tại '.' hoặc '-' ('3.2.1' → '3.2';
    '5.6-commentary' → '5.6')."""
    best: models.SectionEntry | None = None
    for s in manifest.sections:
        if section_id.startswith((s.id + ".", s.id + "-")):
            if best is None or len(s.id) > len(best.id):
                best = s
    return best


def _folded_result(
    repo_kb: Path,
    repo_id: str,
    manifest: models.Manifest,
    doc_id: str,
    section_id: str,
    level: str,
) -> QueryResult | None:
    parent = _parent_entry(manifest, section_id)
    if parent is None:
        return None
    if level != "l3":
        # L2 không có anchor con (summary phủ cả folded child) — trả parent
        # với citation id parent, không nói dối vị trí.
        return _get_section_in(repo_kb, repo_id, doc_id, parent.id, level)
    path = repo_kb / doc_id / f"{parent.file}.raw.md"
    if not path.exists():
        return None
    parent_md = slice_section(path.read_text(encoding="utf-8"), parent.id)
    if parent_md is None:
        return None
    content = slice_subsection(parent_md, section_id)
    if content is None:
        return None
    head = content.splitlines()[0].split(None, 2)
    title = head[2] if len(head) == 3 else parent.title
    return QueryResult(
        doc_id=doc_id,
        section_id=section_id,
        title=title,
        score=0.0,
        citation=_citation(repo_id, manifest.id, manifest.revision, section_id),
        content=content,
        tokens=count_tokens(content),
        source=repo_id,
    )
```

Trong `_get_section_in` (dòng 163-165), nhánh `sec is None`:

```python
    sec = next((s for s in manifest.sections if s.id == section_id), None)
    if sec is None:
        return _folded_result(
            repo_kb, repo_id, manifest, doc_id, section_id, level
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_query.py -v`
Expected: PASS (test cũ về id không tồn tại vẫn xanh — `_parent_entry` trả `None` khi không có prefix).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/query.py tests/test_query.py
git commit -m "feat: get_section resolves folded section ids via parent + ### slice"
```

---

### Task 7: Warning id `x{n}` legacy lúc publish

**Files:**
- Modify: `src/center_kb/publish.py` (thêm helper + gọi trong `publish()` dòng 105)
- Test: `tests/test_publish.py`

**Interfaces:**
- Produces: `warn_legacy_ids(kb_dir: Path) -> list[str]` — trả danh sách `"{doc_id} §{sec_id}"` khớp, phát `logger.warning` một lần khi có hit. `publish()` gọi ngay đầu flow.

- [ ] **Step 1: Write the failing test**

Thêm vào `tests/test_publish.py`:

```python
def test_warn_legacy_ids_flags_xn_sections(tmp_path, caplog):
    import logging

    from center_kb import models, publish

    doc_dir = tmp_path / "kb" / "old-doc"
    doc_dir.mkdir(parents=True)
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="old-doc",
            title="Old Doc",
            sections=[
                models.SectionEntry(id="5.6", title="Real", file="ch5"),
                models.SectionEntry(id="5.6-x74", title="Commentary", file="ch5"),
            ],
        ),
    )
    with caplog.at_level(logging.WARNING, logger="center_kb.publish"):
        hits = publish.warn_legacy_ids(tmp_path / "kb")
    assert hits == ["old-doc §5.6-x74"]
    assert any("re-ingest" in r.message for r in caplog.records)


def test_warn_legacy_ids_clean_kb_silent(tmp_path, caplog):
    import logging

    from center_kb import models, publish

    doc_dir = tmp_path / "kb" / "clean-doc"
    doc_dir.mkdir(parents=True)
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="clean-doc",
            title="Clean",
            sections=[models.SectionEntry(id="5.6-commentary", title="C", file="ch5")],
        ),
    )
    with caplog.at_level(logging.WARNING, logger="center_kb.publish"):
        hits = publish.warn_legacy_ids(tmp_path / "kb")
    assert hits == []
    assert not caplog.records
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_publish.py -k legacy_ids -v`
Expected: FAIL — `AttributeError: module ... no attribute 'warn_legacy_ids'`

- [ ] **Step 3: Implement**

Trong `src/center_kb/publish.py` (module đã có `logger`; thêm `import re` nếu chưa có):

```python
_LEGACY_ID_RE = re.compile(r"(^|-)x\d+$")


def warn_legacy_ids(kb_dir: Path) -> list[str]:
    """Id x{n} là fallback opaque của CLI cũ (< 2debcbc) hoặc heading không
    slug được — cảnh báo để repo re-ingest bằng CLI mới. Không reject: data
    cũ vẫn hợp lệ, chỉ kém đọc (spec §6b)."""
    hits: list[str] = []
    for man_path in sorted(kb_dir.glob("*/_manifest.yaml")):
        manifest = models.load_yaml_model(man_path, models.Manifest)
        hits += [
            f"{manifest.id} §{sec.id}"
            for sec in manifest.sections
            if _LEGACY_ID_RE.search(sec.id)
        ]
    if hits:
        logger.warning(
            "legacy synthetic section ids — re-ingest these docs with the "
            "current CLI to get readable ids: %s",
            ", ".join(hits),
        )
    return hits
```

Trong `publish()` (dòng 105), dòng đầu thân hàm: `warn_legacy_ids(kb_dir)` (dùng đúng tên biến path kb local trong hàm — đọc hàm khi sửa; nếu trong `publish()` là đường dẫn tuyệt đối `kb_abs`, gọi với biến đó).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_publish.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/publish.py tests/test_publish.py
git commit -m "feat: warn on legacy x{n} section ids at publish"
```

---

### Task 8: Hiện snippet ở CLI / MCP / Web UI

**Files:**
- Modify: `src/center_kb/cli.py:608-610` (lệnh `query`), `src/center_kb/mcp.py:122-124` (`kb_search`), `src/center_kb/web/ui.py:73-84` (`_result_blocks`)
- Test: `tests/test_cli.py`, `tests/test_web_ui.py` (MCP đi qua golden gate ở Task 9)

**Interfaces:**
- Consumes: `QueryResult.snippet` (Task 5).
- Produces: mỗi surface in thêm dòng `raw match: …` / block `result-snippet` khi `snippet` khác rỗng.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py` — theo pattern invoke runner sẵn có trong file (CliRunner + monkeypatch `query.search`); monkeypatch trả `QueryResult` có snippet:

```python
def test_query_cli_prints_snippet(monkeypatch, tmp_path):
    from center_kb import cli
    from center_kb.query import QueryResult

    fake = [
        QueryResult(
            doc_id="d", section_id="1.1", title="T", score=1.0,
            citation="r:d §1.1", content="Condensed body.", tokens=5,
            source="r", match_mode="keyword", snippet="…GRYPHON42 in raw…",
        )
    ]
    monkeypatch.setattr(cli, "_run_search", lambda *a, **k: fake, raising=False)
    # nếu cli gọi query.search trực tiếp: monkeypatch.setattr("center_kb.query.search", lambda *a, **k: fake)
    # → đọc cli.py:581-610 lúc implement và patch đúng symbol lệnh query dùng.
```

(Viết assert theo runner pattern của file: output chứa `raw match:` và `GRYPHON42`.)

`tests/test_web_ui.py` — file đã có test render kết quả search; thêm case result có `snippet` và assert HTML chứa `class="result-snippet"` và text snippet đã escape.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cli.py -k snippet tests/test_web_ui.py -k snippet -v`
Expected: FAIL — output chưa có `raw match:` / `result-snippet`.

- [ ] **Step 3: Implement**

`src/center_kb/cli.py` (sau dòng 610 `typer.echo(r.content)`):

```python
        if r.snippet:
            typer.secho(f"raw match: {r.snippet}", dim=True)
```

`src/center_kb/mcp.py` (f-string kb_search, dòng 122-124):

```python
        return note + "\n\n".join(
            f"--- [{r.citation}] match={r.match_mode} ~{r.tokens}tk\n{r.content}"
            + (f"\nraw match: {r.snippet}" if r.snippet else "")
            for r in results
        )
```

`src/center_kb/web/ui.py` (`_result_blocks`, sau dòng result-body):

```python
            f'<div class="result-body">{md_render(r.content, terms=terms)}</div>'
            + (
                f'<div class="result-snippet">raw match: {_e(r.snippet)}</div>'
                if r.snippet
                else ""
            )
```

(CSS: thêm rule `.result-snippet` mờ/nhỏ vào stylesheet template sẵn có của web UI — file css/template nằm cạnh `web/ui.py`, thêm 3 dòng cùng style `.score`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cli.py tests/test_web_ui.py tests/test_mcp_http.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/cli.py src/center_kb/mcp.py src/center_kb/web/ui.py tests/test_cli.py tests/test_web_ui.py
git commit -m "feat: surface L3 raw-match snippet in CLI, MCP, and web UI results"
```

---

### Task 9: Full suite + golden gate

**Files:**
- Modify (nếu golden đổi): `tests-gate/golden/*` qua `UPDATE_GOLDEN=1`
- Test: toàn bộ `tests/` + `tests-gate/`

**Interfaces:**
- Consumes: mọi task trước.

- [ ] **Step 1: Full unit suite**

Run: `python3 -m pytest tests/ -q`
Expected: PASS toàn bộ. Fail nào → sửa trước khi đi tiếp (không đụng gate khi unit đỏ).

- [ ] **Step 2: Gate suite — đọc diff trước khi update golden**

Run: `python3 -m pytest tests-gate/ -q`
Expected: `test_golden_output.py` có thể RED chủ đích vì (a) ranking đổi (index thêm body_l2/body_l3 + bm25 weights) và (b) kb_search in thêm dòng `raw match:`. Đọc kỹ diff golden: thứ tự kết quả mới phải giải thích được bằng weights (title match vẫn đứng trên), KHÔNG được mất kết quả cũ khỏi budget một cách khó hiểu. Chỉ khi diff khớp kỳ vọng spec:

Run: `UPDATE_GOLDEN=1 python3 -m pytest tests-gate/regression/test_golden_output.py -q`
Rồi: `python3 -m pytest tests-gate/ -q` → Expected: PASS.

- [ ] **Step 3: Lint/format**

Run: `python3 -m ruff check src tests tests-gate && python3 -m black --check src tests tests-gate`
Expected: clean (black tự sửa nếu cần rồi re-run).

- [ ] **Step 4: Commit golden update (nếu có)**

```bash
git add tests-gate/golden
git commit -m "test: refresh golden output for schema v2 ranking + raw-match snippet"
```

---

## Self-Review Notes

- Spec §3 (schema v2, hash split, weights) → Task 4. §4 (snippet) → Task 5 + 8. §5 (folded get_section) → Task 2 + 6. §6a (unicode fallback id, digit-only demote, x{n} warning) → Task 1 + 3. §6b (publish warning) → Task 7. §7 error handling nằm trong code từng task (raw missing → warning + rỗng; snippet fail → ""; folded fail → None). §8 testing → per-task + Task 9. §9 golden/ranking risk → Task 9 Step 2 bắt đọc diff trước khi update.
- Type consistency: `_section_parts` 4-tuple chỉ có 2 caller (`_sync_repo`, hook pass-through trong test race — không cần sửa test đó); `_embed_text` giữ 3 tham số ở cả 2 chỗ gọi; `QueryResult.snippet` default `""` nên mọi constructor cũ (mcp/web/cli/tests) không vỡ.
- Task 8 Step 1 yêu cầu đọc `cli.py:581-610` để patch đúng symbol — chủ đích, tránh khóa cứng tên helper nội bộ có thể khác.
