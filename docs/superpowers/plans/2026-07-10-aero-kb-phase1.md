# AERO-KB Phase 1 (PoC) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python package `aero_kb` + CLI `kb` biến PDF hàng trăm trang thành knowledge base 4 tầng L0–L3, query được với citation, theo design doc `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md`.

**Architecture:** Pipeline deterministic: Docling parse PDF (cache JSON) → sectioner dựng cây section + gộp/tách → scaffold sinh L3 hoàn chỉnh + khung L2 (bảng chép nguyên văn bằng code, marker TODO cho văn xuôi) + manifest L1 + entry L0. Claude Code điền summary qua skill `kb-summarize`. `kb build` là chốt chặn (hết TODO, toàn vẹn bảng). Query = tag match trên L0 → BM25 trên L1 → trả L2 theo budget kèm citation.

**Tech Stack:** Python 3.13, Typer, Pydantic v2, PyYAML, Docling (optional extra `ingest`), pypdf, rank-bm25, tiktoken, pytest.

## Global Constraints

- Python venv tạo bằng `python3.13` (Docling/PyTorch chưa chắc có wheel cho 3.14 đang là default của máy).
- Layout `src/`, package `aero_kb`, entry point CLI tên `kb`.
- Docling nằm trong optional extra `[ingest]` và chỉ được import **lazy bên trong hàm** — mọi lệnh khác (build/query/stats) và toàn bộ test suite phải chạy được khi chưa cài Docling.
- Summary viết **tiếng Anh**. Bảng markdown giữ **nguyên văn** ở cả L2 lẫn L3 — L2 do code chép, LLM không chép bảng.
- Quy tắc đơn vị section: độ sâu tối đa **3 cấp**; section lá < **200 token** gộp vào cha.
- Marker chờ summarize trong L2: `<!-- TODO:summarize <section-id> -->` (đúng chuỗi này, `kb build` và skill đều bám vào nó).
- Mọi section unit ghi ra file ở heading **cấp 2**: `## <id> <title>` — cả L2 lẫn L3 (giúp cắt anchor deterministic).
- Token đếm bằng tiktoken encoding `cl100k_base`.
- Citation format: `<doc-id> §<section-id> (<revision>)`; bỏ phần `(...)` nếu revision rỗng.
- `sources/` và `.kb-work/` đã gitignore — không bao giờ commit PDF gốc hoặc cache parse.
- Commit theo conventional commits (`feat:`, `test:`, `chore:`…), KHÔNG thêm footer attribution (đã tắt toàn cục theo rule của user).
- Test không phụ thuộc PDF thật (bản quyền): unit/integration chạy trên dữ liệu tổng hợp; PDF thật chỉ dùng ở Task 12 (verify thủ công, local).

## File Structure (toàn cảnh)

```
AERO-KB/
├── pyproject.toml
├── src/aero_kb/
│   ├── __init__.py
│   ├── cli.py              # Typer app: ingest/status/build/query/get/stats
│   ├── models.py           # Pydantic: SectionEntry, Manifest, IndexEntry, KBIndex + YAML IO
│   ├── mdutils.py          # count_tokens, slice_section, extract_tables, normalize_table
│   ├── build.py            # validate + cập nhật token counts; stats
│   ├── query.py            # tag match → BM25 → budget assembly
│   └── ingest/
│       ├── __init__.py
│       ├── parser.py       # Docling adapter (lazy import), cache, bookmark crosscheck
│       ├── sectioner.py    # DocItem, parse_section_id, build_units (gộp/tách)
│       └── scaffold.py     # sinh L3/L2/_manifest.yaml/index.yaml
├── .claude/skills/kb-summarize/SKILL.md
└── tests/
    ├── conftest.py         # fixture_kb: cây .kb/ mẫu đã điền summary
    ├── test_cli.py
    ├── test_models.py
    ├── test_mdutils.py
    ├── test_sectioner.py
    ├── test_parser.py
    ├── test_scaffold.py
    ├── test_ingest_cli.py
    ├── test_build.py
    ├── test_query.py
    └── test_stats.py
```

---

### Task 1: Project scaffold + CLI skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/aero_kb/__init__.py`
- Create: `src/aero_kb/cli.py`
- Create: `src/aero_kb/ingest/__init__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: Typer app `aero_kb.cli:app` — mọi task sau đăng ký command vào app này; lệnh `kb` chạy được từ shell sau `pip install -e`.

- [ ] **Step 1: Tạo venv bằng python3.13**

```bash
cd /Users/vuonglq01685/Documents/Projects/AERO-KB
python3.13 -m venv .venv
.venv/bin/python --version
```
Expected: `Python 3.13.x`

- [ ] **Step 2: Viết pyproject.toml**

```toml
[project]
name = "aero-kb"
version = "0.1.0"
description = "Knowledge Base as Code cho tài liệu hàng không — 4 tầng L0-L3"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12",
    "pydantic>=2.7",
    "PyYAML>=6.0",
    "rank-bm25>=0.2.2",
    "tiktoken>=0.7",
    "pypdf>=4.0",
]

[project.optional-dependencies]
ingest = ["docling>=2.0"]
dev = ["pytest>=8.0"]

[project.scripts]
kb = "aero_kb.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/aero_kb"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Viết package skeleton**

`src/aero_kb/__init__.py`:
```python
__version__ = "0.1.0"
```

`src/aero_kb/ingest/__init__.py`:
```python
```
(file rỗng)

`src/aero_kb/cli.py`:
```python
import typer

app = typer.Typer(
    help="AERO-KB — Knowledge Base as Code cho tài liệu hàng không.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """AERO-KB CLI."""
```

- [ ] **Step 4: Cài đặt editable (chưa cài ingest extra — Docling nặng, để Task 12)**

```bash
.venv/bin/pip install -e ".[dev]"
```
Expected: cài thành công, không lỗi.

- [ ] **Step 5: Viết failing test**

`tests/test_cli.py`:
```python
from typer.testing import CliRunner

from aero_kb.cli import app

runner = CliRunner()


def test_cli_help_shows_app_description():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "AERO-KB" in result.output
```

- [ ] **Step 6: Chạy test**

```bash
.venv/bin/pytest tests/test_cli.py -v
```
Expected: PASS (skeleton đã có sẵn từ Step 3 — test này là smoke test chốt cấu trúc project).

- [ ] **Step 7: Smoke test lệnh kb từ shell**

```bash
.venv/bin/kb --help
```
Expected: in help, exit 0.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/ tests/test_cli.py
git commit -m "feat: project scaffold — package aero_kb + CLI kb (Typer)"
```

---

### Task 2: Schema Pydantic + YAML IO (models.py)

**Files:**
- Create: `src/aero_kb/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `SectionTokens(l2: int = 0, l3: int = 0)`
  - `SectionEntry(id, title, summary="", status: Literal["pending","summarized","reviewed"]="pending", file, tokens: SectionTokens)` — `file` là stem của chapter file (không đuôi `.md`)
  - `Manifest(id, title, revision="", ingested: date|None, source_sha256="", sections: list[SectionEntry])`
  - `IndexEntry(id, title, revision="", tags: list[str], summary="")`
  - `KBIndex(docs: list[IndexEntry])`
  - `load_yaml_model(path: Path, model: type[T]) -> T`
  - `save_yaml_model(path: Path, obj: BaseModel) -> None`

- [ ] **Step 1: Viết failing tests**

`tests/test_models.py`:
```python
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from aero_kb import models


def test_manifest_yaml_roundtrip(tmp_path: Path):
    manifest = models.Manifest(
        id="arinc-424",
        title="ARINC 424",
        revision="Supplement 22",
        ingested=date(2026, 7, 10),
        sections=[
            models.SectionEntry(
                id="5.3",
                title="Restrictive Airspace",
                summary="UR/PR record structure.",
                status="summarized",
                file="ch5-navigation-data",
                tokens=models.SectionTokens(l2=810, l3=2900),
            )
        ],
    )
    path = tmp_path / "_manifest.yaml"
    models.save_yaml_model(path, manifest)
    loaded = models.load_yaml_model(path, models.Manifest)
    assert loaded == manifest


def test_section_entry_defaults_pending():
    sec = models.SectionEntry(id="1.1", title="General", file="ch1-general")
    assert sec.status == "pending"
    assert sec.summary == ""
    assert sec.tokens.l2 == 0


def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        models.SectionEntry(id="1.1", title="x", file="f", status="done")


def test_index_yaml_roundtrip(tmp_path: Path):
    index = models.KBIndex(
        docs=[
            models.IndexEntry(
                id="arinc-424",
                title="ARINC 424",
                tags=["arinc424", "navdata"],
                summary="Navigation data spec.",
            )
        ]
    )
    path = tmp_path / "index.yaml"
    models.save_yaml_model(path, index)
    loaded = models.load_yaml_model(path, models.KBIndex)
    assert loaded == index
    assert "arinc424" in path.read_text()
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
.venv/bin/pytest tests/test_models.py -v
```
Expected: FAIL — `ModuleNotFoundError` hoặc `AttributeError` (models chưa tồn tại).

- [ ] **Step 3: Implement models.py**

`src/aero_kb/models.py`:
```python
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, TypeVar

import yaml
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class SectionTokens(BaseModel):
    l2: int = 0
    l3: int = 0


class SectionEntry(BaseModel):
    id: str
    title: str
    summary: str = ""
    status: Literal["pending", "summarized", "reviewed"] = "pending"
    file: str
    tokens: SectionTokens = Field(default_factory=SectionTokens)


class Manifest(BaseModel):
    id: str
    title: str
    revision: str = ""
    ingested: date | None = None
    source_sha256: str = ""
    sections: list[SectionEntry] = Field(default_factory=list)


class IndexEntry(BaseModel):
    id: str
    title: str
    revision: str = ""
    tags: list[str] = Field(default_factory=list)
    summary: str = ""


class KBIndex(BaseModel):
    docs: list[IndexEntry] = Field(default_factory=list)


def load_yaml_model(path: Path, model: type[T]) -> T:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return model.model_validate(data)


def save_yaml_model(path: Path, obj: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        obj.model_dump(mode="json"), allow_unicode=True, sort_keys=False
    )
    path.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Chạy test — phải PASS**

```bash
.venv/bin/pytest tests/test_models.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/models.py tests/test_models.py
git commit -m "feat: schema Pydantic cho manifest L1 va index L0 + YAML IO"
```

---

### Task 3: Tiện ích markdown & token (mdutils.py)

**Files:**
- Create: `src/aero_kb/mdutils.py`
- Test: `tests/test_mdutils.py`

**Interfaces:**
- Produces:
  - `count_tokens(text: str) -> int` — tiktoken cl100k_base, cache encoder
  - `slice_section(md: str, section_id: str) -> str | None` — cắt từ dòng `## <id> <title>` đến trước heading `## ` kế tiếp (hoặc EOF); None nếu không thấy
  - `extract_tables(md: str) -> list[str]` — các khối liên tiếp ≥ 2 dòng bắt đầu bằng `|`
  - `normalize_table(table_md: str) -> str` — bỏ separator row, trim cell, collapse whitespace trong cell

- [ ] **Step 1: Viết failing tests**

`tests/test_mdutils.py`:
```python
from aero_kb import mdutils

CHAPTER_MD = """## 5.1 Airport Records

Intro text for airports.

## 5.3 Restrictive Airspace

Body of restrictive airspace.

| Code | Meaning  |
|------|----------|
| P    | Prohibited |
| R    | Restricted |

## 5.4 Something Else

Tail content.
"""


def test_count_tokens_positive_and_monotonic():
    short = mdutils.count_tokens("restrictive airspace")
    long = mdutils.count_tokens("restrictive airspace " * 50)
    assert 0 < short < long


def test_slice_section_returns_only_that_section():
    block = mdutils.slice_section(CHAPTER_MD, "5.3")
    assert block is not None
    assert block.startswith("## 5.3 Restrictive Airspace")
    assert "Prohibited" in block
    assert "Airport Records" not in block
    assert "Something Else" not in block


def test_slice_section_last_section_runs_to_eof():
    block = mdutils.slice_section(CHAPTER_MD, "5.4")
    assert block is not None
    assert "Tail content." in block


def test_slice_section_missing_returns_none():
    assert mdutils.slice_section(CHAPTER_MD, "9.9") is None


def test_extract_tables_finds_table():
    tables = mdutils.extract_tables(CHAPTER_MD)
    assert len(tables) == 1
    assert "Prohibited" in tables[0]


def test_normalize_table_ignores_formatting_differences():
    a = "| Code | Meaning |\n|---|---|\n| P | Prohibited |"
    b = "| Code   | Meaning    |\n|------|----------|\n| P    | Prohibited |"
    assert mdutils.normalize_table(a) == mdutils.normalize_table(b)


def test_normalize_table_detects_value_change():
    a = "| Code | Meaning |\n|---|---|\n| P | Prohibited |"
    b = "| Code | Meaning |\n|---|---|\n| P | Permitted |"
    assert mdutils.normalize_table(a) != mdutils.normalize_table(b)
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
.venv/bin/pytest tests/test_mdutils.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.mdutils'`.

- [ ] **Step 3: Implement mdutils.py**

`src/aero_kb/mdutils.py`:
```python
from __future__ import annotations

import re

import tiktoken

_ENCODER = None

_HEADING_RE = re.compile(r"^## (?P<sid>\S+)[ \t]+(?P<title>.+?)\s*$")
_SEP_ROW_RE = re.compile(r"^\|[\s:|-]+\|$")


def count_tokens(text: str) -> int:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return len(_ENCODER.encode(text))


def slice_section(md: str, section_id: str) -> str | None:
    lines = md.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and m.group("sid") == section_id:
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            return "\n".join(lines[start:j]).strip()
    return "\n".join(lines[start:]).strip()


def extract_tables(md: str) -> list[str]:
    tables: list[str] = []
    current: list[str] = []
    for line in md.splitlines() + [""]:
        if line.lstrip().startswith("|"):
            current.append(line.strip())
        else:
            if len(current) >= 2:
                tables.append("\n".join(current))
            current = []
    return tables


def normalize_table(table_md: str) -> str:
    rows: list[str] = []
    for line in table_md.splitlines():
        line = line.strip()
        if not line or _SEP_ROW_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append("|".join(" ".join(c.split()) for c in cells))
    return "\n".join(rows)
```

- [ ] **Step 4: Chạy test — phải PASS**

```bash
.venv/bin/pytest tests/test_mdutils.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/mdutils.py tests/test_mdutils.py
git commit -m "feat: mdutils — token count, cat section theo anchor, trich/chuan hoa bang"
```

---

### Task 4: Sectioner — đánh id, dựng cây, gộp/tách

**Files:**
- Create: `src/aero_kb/ingest/sectioner.py`
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Consumes: `mdutils.count_tokens`, `mdutils.extract_tables`
- Produces:
  - `DocItem(kind: str, text: str, level: int = 0)` — dataclass; kind ∈ {"heading","text","table"}; đây là format trung gian mà parser (Task 5) sinh ra và mock trong test CLI (Task 7)
  - `SectionUnit(id: str, title: str, chapter: str, body_md: str, tables: list[str])` — dataclass
  - `parse_section_id(text: str) -> tuple[str, str] | None` — (id, title) hoặc None nếu heading không khớp mẫu
  - `build_units(items: list[DocItem], max_depth: int = 3, min_tokens: int = 200) -> list[SectionUnit]`

- [ ] **Step 1: Viết failing tests**

`tests/test_sectioner.py`:
```python
from aero_kb.ingest.sectioner import DocItem, build_units, parse_section_id


class TestParseSectionId:
    def test_numbered_heading(self):
        assert parse_section_id("5.3 Restrictive Airspace") == (
            "5.3",
            "Restrictive Airspace",
        )

    def test_chapter_zero_suffix_stripped(self):
        assert parse_section_id("5.0 NAVIGATION DATA") == ("5", "NAVIGATION DATA")

    def test_chapter_word_heading(self):
        assert parse_section_id("CHAPTER 2. GENERAL PROVISIONS") == (
            "2",
            "GENERAL PROVISIONS",
        )

    def test_appendix_heading(self):
        sid, _ = parse_section_id("Appendix 3 — Meteorological tables")
        assert sid == "app3"

    def test_unmatched_returns_none(self):
        assert parse_section_id("FOREWORD") is None


def _items_basic() -> list[DocItem]:
    long_text = "Restrictive airspace body text. " * 60  # > 200 tokens
    return [
        DocItem("heading", "5.0 NAVIGATION DATA", 1),
        DocItem("text", "Chapter intro. " * 60),
        DocItem("heading", "5.3 Restrictive Airspace", 2),
        DocItem("text", long_text),
        DocItem("table", "| Code | Meaning |\n|---|---|\n| P | Prohibited |"),
        DocItem("heading", "5.4 Airways", 2),
        DocItem("text", "Airways body. " * 60),
    ]


class TestBuildUnits:
    def test_units_have_ids_and_chapter(self):
        units = build_units(_items_basic())
        ids = [u.id for u in units]
        assert ids == ["5", "5.3", "5.4"]
        assert all(u.chapter == "5" for u in units)

    def test_tables_collected_on_unit(self):
        units = build_units(_items_basic())
        u53 = next(u for u in units if u.id == "5.3")
        assert len(u53.tables) == 1
        assert "Prohibited" in u53.tables[0]

    def test_small_leaf_merged_into_parent(self):
        items = _items_basic() + [
            DocItem("heading", "5.4.1 Tiny", 3),
            DocItem("text", "Very short."),  # < 200 tokens -> gop vao 5.4
        ]
        units = build_units(items)
        assert "5.4.1" not in [u.id for u in units]
        u54 = next(u for u in units if u.id == "5.4")
        assert "Very short." in u54.body_md
        assert "### 5.4.1 Tiny" in u54.body_md

    def test_depth_beyond_max_folded(self):
        items = [
            DocItem("heading", "1.0 INTRO", 1),
            DocItem("heading", "1.1 Purpose", 2),
            DocItem("text", "Purpose body. " * 60),
            DocItem("heading", "1.1.1 Coverage", 3),
            DocItem("text", "Coverage body. " * 60),
            DocItem("heading", "1.1.1.1 Deep detail", 4),
            DocItem("text", "Deep body. " * 60),
        ]
        units = build_units(items)
        ids = [u.id for u in units]
        assert "1.1.1.1" not in ids  # sau hon 3 cap -> gap vao 1.1.1
        u111 = next(u for u in units if u.id == "1.1.1")
        assert "Deep body." in u111.body_md

    def test_unmatched_heading_gets_fallback_id(self):
        items = [
            DocItem("heading", "FOREWORD", 1),
            DocItem("text", "Foreword body. " * 60),
        ]
        units = build_units(items)
        assert len(units) == 1
        assert units[0].title == "FOREWORD"
        assert units[0].id  # co id fallback, khong rong
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
.venv/bin/pytest tests/test_sectioner.py -v
```
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Implement sectioner.py**

`src/aero_kb/ingest/sectioner.py`:
```python
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
```

- [ ] **Step 4: Chạy test — phải PASS**

```bash
.venv/bin/pytest tests/test_sectioner.py -v
```
Expected: tất cả pass. Nếu `test_small_leaf_merged_into_parent` fail vì 5.4.1 vẫn thành unit riêng: kiểm tra lại điều kiện fold (leaf + `< min_tokens`).

- [ ] **Step 5: Chạy toàn bộ suite**

```bash
.venv/bin/pytest -v
```
Expected: tất cả pass.

- [ ] **Step 6: Commit**

```bash
git add src/aero_kb/ingest/sectioner.py tests/test_sectioner.py
git commit -m "feat: sectioner — danh id section, dung cay, quy tac gop/tach"
```

---

### Task 5: Parser — Docling adapter + bookmark crosscheck

**Files:**
- Create: `src/aero_kb/ingest/parser.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `sectioner.DocItem`, `sectioner.parse_section_id`
- Produces:
  - `load_or_parse(pdf_path: Path, work_dir: Path)` — trả `DoclingDocument`; cache tại `work_dir/parsed.json`; import docling **bên trong hàm**, raise `RuntimeError` với message hướng dẫn `pip install -e ".[ingest]"` nếu thiếu
  - `doc_to_items(doc) -> list[DocItem]` — dispatch theo `item.label` (string value), KHÔNG isinstance — để test được bằng stub
  - `bookmark_ids(pdf_path: Path) -> set[str]` — đọc outline bằng pypdf, parse id qua `parse_section_id`
  - `crosscheck(unit_ids: set[str], bm_ids: set[str], max_depth: int = 3) -> list[str]` — cảnh báo bookmark không được cover

- [ ] **Step 1: Viết failing tests**

`tests/test_parser.py`:
```python
from dataclasses import dataclass, field

from aero_kb.ingest import parser


@dataclass
class _StubLabel:
    value: str


@dataclass
class _StubItem:
    label: _StubLabel
    text: str = ""
    level: int = 1
    table_md: str = ""

    def export_to_markdown(self, doc=None):
        return self.table_md


@dataclass
class _StubDoc:
    items: list = field(default_factory=list)

    def iterate_items(self):
        for it in self.items:
            yield it, 0


def test_doc_to_items_maps_labels():
    doc = _StubDoc(
        items=[
            _StubItem(_StubLabel("section_header"), text="5.3 Restrictive Airspace", level=2),
            _StubItem(_StubLabel("text"), text="Body paragraph."),
            _StubItem(
                _StubLabel("table"),
                table_md="| A | B |\n|---|---|\n| 1 | 2 |",
            ),
            _StubItem(_StubLabel("page_footer"), text="Trang 5"),  # bi bo qua
            _StubItem(_StubLabel("text"), text="   "),  # rong -> bo qua
        ]
    )
    items = parser.doc_to_items(doc)
    assert [i.kind for i in items] == ["heading", "text", "table"]
    assert items[0].level == 2
    assert "| A | B |" in items[2].text


def test_crosscheck_reports_missing_bookmark():
    warnings = parser.crosscheck(
        unit_ids={"5", "5.3"}, bm_ids={"5", "5.3", "5.4"}
    )
    assert len(warnings) == 1
    assert "5.4" in warnings[0]


def test_crosscheck_covered_by_prefix_not_reported():
    # 5.3.2 nam trong unit 5.3 (bi gop) -> khong canh bao
    warnings = parser.crosscheck(unit_ids={"5", "5.3"}, bm_ids={"5.3.2"})
    assert warnings == []


def test_crosscheck_ignores_bookmarks_deeper_than_max_depth():
    warnings = parser.crosscheck(unit_ids={"5"}, bm_ids={"5.1.2.3"})
    assert warnings == []


def test_load_or_parse_without_docling_raises_helpful_error(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("docling"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        parser.load_or_parse(tmp_path / "x.pdf", tmp_path / "work")
    except RuntimeError as e:
        assert "ingest" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
.venv/bin/pytest tests/test_parser.py -v
```
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Implement parser.py**

`src/aero_kb/ingest/parser.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

from aero_kb.ingest.sectioner import DocItem, parse_section_id

_HEADING_LABELS = {"section_header", "title"}
_TEXT_LABELS = {"text", "paragraph", "list_item", "formula", "code", "caption"}


def _label_value(item) -> str:
    label = getattr(item, "label", "")
    return getattr(label, "value", None) or str(label)


def load_or_parse(pdf_path: Path, work_dir: Path):
    try:
        from docling_core.types.doc import DoclingDocument
    except ImportError as exc:
        raise RuntimeError(
            "Docling chua duoc cai. Chay: pip install -e \".[ingest]\""
        ) from exc

    cache = work_dir / "parsed.json"
    if cache.exists():
        return DoclingDocument.model_validate_json(cache.read_text(encoding="utf-8"))

    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(str(pdf_path))
    doc = result.document
    work_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(doc.export_to_dict()), encoding="utf-8")
    return doc


def doc_to_items(doc) -> list[DocItem]:
    items: list[DocItem] = []
    for item, _level in doc.iterate_items():
        label = _label_value(item)
        if label in _HEADING_LABELS:
            heading_level = getattr(item, "level", 1) if label == "section_header" else 1
            items.append(DocItem("heading", item.text, heading_level))
        elif label == "table":
            md = item.export_to_markdown(doc=doc)
            if md and md.strip():
                items.append(DocItem("table", md))
        elif label in _TEXT_LABELS:
            if item.text and item.text.strip():
                items.append(DocItem("text", item.text))
    return items


def bookmark_ids(pdf_path: Path) -> set[str]:
    from pypdf import PdfReader

    ids: set[str] = set()

    def walk(outline) -> None:
        for entry in outline:
            if isinstance(entry, list):
                walk(entry)
            else:
                title = getattr(entry, "title", "") or ""
                parsed = parse_section_id(title)
                if parsed:
                    ids.add(parsed[0])

    try:
        reader = PdfReader(str(pdf_path))
        walk(reader.outline)
    except Exception:
        return set()
    return ids


def crosscheck(
    unit_ids: set[str], bm_ids: set[str], max_depth: int = 3
) -> list[str]:
    warnings: list[str] = []
    for bm in sorted(bm_ids):
        if bm[0].isdigit() and bm.count(".") + 1 > max_depth:
            continue
        covered = any(
            bm == uid or bm.startswith(uid + ".") or uid.startswith(bm + ".")
            for uid in unit_ids
        )
        if not covered:
            warnings.append(f"bookmark section '{bm}' khong thay trong cay da trich")
    return warnings
```

- [ ] **Step 4: Chạy test — phải PASS**

```bash
.venv/bin/pytest tests/test_parser.py -v
```
Expected: 5 passed.

**Lưu ý cho executor:** API Docling (`iterate_items`, `export_to_markdown(doc=...)`, `export_to_dict`, `model_validate_json`) viết theo docling>=2.0. Ở Task 12 (chạy thật lần đầu), nếu API lệch, dùng Context7 tra docs docling hiện hành và chỉ sửa trong `parser.py` — các module khác không đụng đến Docling.

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/ingest/parser.py tests/test_parser.py
git commit -m "feat: parser — Docling adapter (lazy import, cache) + bookmark crosscheck"
```

---

### Task 6: Scaffold — sinh L3, khung L2, manifest, index

**Files:**
- Create: `src/aero_kb/ingest/scaffold.py`
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Consumes: `sectioner.SectionUnit`, `models.*`, `mdutils.count_tokens`
- Produces:
  - `slugify(text: str) -> str`
  - `chapter_stem(chapter: str, title: str) -> str` — vd `("5", "NAVIGATION DATA")` → `"ch5-navigation-data"`; `("app3", "...")` → `"app3-..."`
  - `ScaffoldReport(doc_id: str, files: list[str], n_sections: int)` — dataclass
  - `scaffold_doc(units, *, doc_id, title, tags, revision, source_path: Path | None, kb_dir: Path, chapters: set[str] | None = None) -> ScaffoldReport`

- [ ] **Step 1: Viết failing tests**

`tests/test_scaffold.py`:
```python
from pathlib import Path

from aero_kb import models
from aero_kb.ingest.scaffold import chapter_stem, scaffold_doc, slugify
from aero_kb.ingest.sectioner import SectionUnit

TABLE = "| Code | Meaning |\n|---|---|\n| P | Prohibited |"


def _units() -> list[SectionUnit]:
    return [
        SectionUnit("5", "NAVIGATION DATA", "5", "Chapter intro.", []),
        SectionUnit(
            "5.3",
            "Restrictive Airspace",
            "5",
            f"Airspace body.\n\n{TABLE}",
            [TABLE],
        ),
        SectionUnit("6", "OTHER CHAPTER", "6", "Other body.", []),
    ]


def test_slugify():
    assert slugify("NAVIGATION DATA — Field/Spec") == "navigation-data-field-spec"


def test_chapter_stem():
    assert chapter_stem("5", "NAVIGATION DATA") == "ch5-navigation-data"
    assert chapter_stem("app3", "Met tables") == "app3-met-tables"


def test_scaffold_writes_l3_l2_manifest_index(tmp_path: Path):
    kb = tmp_path / ".kb"
    report = scaffold_doc(
        _units(),
        doc_id="arinc-424",
        title="ARINC 424",
        tags=["arinc424", "navdata"],
        revision="Supplement 22",
        source_path=None,
        kb_dir=kb,
    )
    assert report.n_sections == 3

    l3 = (kb / "arinc-424" / "ch5-navigation-data.raw.md").read_text()
    assert "## 5.3 Restrictive Airspace" in l3
    assert "Prohibited" in l3

    l2 = (kb / "arinc-424" / "ch5-navigation-data.md").read_text()
    assert "<!-- TODO:summarize 5.3 -->" in l2
    assert "Prohibited" in l2  # bang duoc code chep nguyen van vao L2
    assert "Airspace body." not in l2  # van xuoi KHONG nam trong khung L2

    manifest = models.load_yaml_model(
        kb / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert [s.id for s in manifest.sections] == ["5", "5.3", "6"]
    sec53 = next(s for s in manifest.sections if s.id == "5.3")
    assert sec53.status == "pending"
    assert sec53.file == "ch5-navigation-data"
    assert sec53.tokens.l3 > 0

    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].id == "arinc-424"
    assert "arinc424" in index.docs[0].tags


def test_scaffold_chapter_filter(tmp_path: Path):
    kb = tmp_path / ".kb"
    report = scaffold_doc(
        _units(),
        doc_id="arinc-424",
        title="ARINC 424",
        tags=[],
        revision="",
        source_path=None,
        kb_dir=kb,
        chapters={"5"},
    )
    assert report.n_sections == 2
    assert not (kb / "arinc-424" / "ch6-other-chapter.md").exists()


def test_scaffold_reingest_replaces_index_entry(tmp_path: Path):
    kb = tmp_path / ".kb"
    for _ in range(2):
        scaffold_doc(
            _units(),
            doc_id="arinc-424",
            title="ARINC 424",
            tags=["arinc424"],
            revision="",
            source_path=None,
            kb_dir=kb,
        )
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert len(index.docs) == 1
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
.venv/bin/pytest tests/test_scaffold.py -v
```
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Implement scaffold.py**

`src/aero_kb/ingest/scaffold.py`:
```python
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from aero_kb import models
from aero_kb.ingest.sectioner import SectionUnit
from aero_kb.mdutils import count_tokens


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def chapter_stem(chapter: str, title: str) -> str:
    prefix = f"ch{chapter}" if chapter and chapter[0].isdigit() else chapter
    slug = slugify(title)[:40].rstrip("-")
    return f"{prefix}-{slug}" if slug else prefix


@dataclass
class ScaffoldReport:
    doc_id: str
    files: list[str]
    n_sections: int


def scaffold_doc(
    units: list[SectionUnit],
    *,
    doc_id: str,
    title: str,
    tags: list[str],
    revision: str,
    source_path: Path | None,
    kb_dir: Path,
    chapters: set[str] | None = None,
) -> ScaffoldReport:
    if chapters is not None:
        units = [u for u in units if u.chapter in chapters]

    doc_dir = kb_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    groups: dict[str, list[SectionUnit]] = {}
    for unit in units:
        groups.setdefault(unit.chapter, []).append(unit)

    sections: list[models.SectionEntry] = []
    files: list[str] = []
    for chapter, chapter_units in groups.items():
        head = next((u for u in chapter_units if u.id == chapter), chapter_units[0])
        stem = chapter_stem(chapter, head.title)

        l3_lines: list[str] = []
        l2_lines: list[str] = []
        for unit in chapter_units:
            l3_lines += [f"## {unit.id} {unit.title}", "", unit.body_md, ""]
            l2_lines += [
                f"## {unit.id} {unit.title}",
                "",
                f"<!-- TODO:summarize {unit.id} -->",
                "",
            ]
            for table in unit.tables:
                l2_lines += [table, ""]
            sections.append(
                models.SectionEntry(
                    id=unit.id,
                    title=unit.title,
                    file=stem,
                    tokens=models.SectionTokens(l3=count_tokens(unit.body_md)),
                )
            )

        (doc_dir / f"{stem}.raw.md").write_text("\n".join(l3_lines), encoding="utf-8")
        (doc_dir / f"{stem}.md").write_text("\n".join(l2_lines), encoding="utf-8")
        files += [f"{stem}.md", f"{stem}.raw.md"]

    sha = (
        hashlib.sha256(source_path.read_bytes()).hexdigest()
        if source_path and source_path.exists()
        else ""
    )
    manifest = models.Manifest(
        id=doc_id,
        title=title,
        revision=revision,
        ingested=date.today(),
        source_sha256=sha,
        sections=sections,
    )
    models.save_yaml_model(doc_dir / "_manifest.yaml", manifest)

    index_path = kb_dir / "index.yaml"
    index = (
        models.load_yaml_model(index_path, models.KBIndex)
        if index_path.exists()
        else models.KBIndex()
    )
    kept = [d for d in index.docs if d.id != doc_id]
    entry = models.IndexEntry(id=doc_id, title=title, revision=revision, tags=tags)
    models.save_yaml_model(index_path, models.KBIndex(docs=kept + [entry]))

    return ScaffoldReport(doc_id=doc_id, files=files, n_sections=len(sections))
```

- [ ] **Step 4: Chạy test — phải PASS**

```bash
.venv/bin/pytest tests/test_scaffold.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/ingest/scaffold.py tests/test_scaffold.py
git commit -m "feat: scaffold — sinh L3, khung L2 (bang chep nguyen van), manifest, index"
```

---

### Task 7: CLI `kb ingest` + `kb status`

**Files:**
- Modify: `src/aero_kb/cli.py`
- Test: `tests/test_ingest_cli.py`

**Interfaces:**
- Consumes: `parser.load_or_parse`, `parser.doc_to_items`, `parser.bookmark_ids`, `parser.crosscheck`, `sectioner.build_units`, `scaffold.scaffold_doc`
- Produces: lệnh shell
  - `kb ingest <pdf> --id <doc-id> --tags a,b --revision "..." [--sections 5,6] [--kb-dir .kb] [--work-dir .kb-work]`
  - `kb status [--kb-dir .kb]` — liệt kê section `pending` theo doc; exit 0 kể cả khi còn pending (status chỉ báo cáo)

- [ ] **Step 1: Viết failing tests**

`tests/test_ingest_cli.py`:
```python
from pathlib import Path

from typer.testing import CliRunner

from aero_kb import models
from aero_kb.cli import app
from aero_kb.ingest.sectioner import DocItem

runner = CliRunner()

FAKE_ITEMS = [
    DocItem("heading", "5.0 NAVIGATION DATA", 1),
    DocItem("text", "Chapter intro. " * 60),
    DocItem("heading", "5.3 Restrictive Airspace", 2),
    DocItem("text", "Airspace body. " * 60),
]


def _fake_parse(monkeypatch):
    from aero_kb.ingest import parser

    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: object())
    monkeypatch.setattr(parser, "doc_to_items", lambda doc: FAKE_ITEMS)
    monkeypatch.setattr(parser, "bookmark_ids", lambda pdf: {"5", "5.3", "5.9"})


def test_ingest_creates_kb_and_reports_warnings(tmp_path: Path, monkeypatch):
    _fake_parse(monkeypatch)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-fake")
    result = runner.invoke(
        app,
        [
            "ingest", str(pdf),
            "--id", "arinc-424",
            "--tags", "arinc424,navdata",
            "--revision", "Supplement 22",
            "--kb-dir", str(tmp_path / ".kb"),
            "--work-dir", str(tmp_path / ".kb-work"),
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert [s.id for s in manifest.sections] == ["5", "5.3"]
    assert "5.9" in result.output  # canh bao bookmark khong duoc cover


def test_status_lists_pending_sections(tmp_path: Path, monkeypatch):
    _fake_parse(monkeypatch)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-fake")
    runner.invoke(
        app,
        [
            "ingest", str(pdf),
            "--id", "arinc-424",
            "--tags", "arinc424",
            "--kb-dir", str(tmp_path / ".kb"),
            "--work-dir", str(tmp_path / ".kb-work"),
        ],
    )
    result = runner.invoke(app, ["status", "--kb-dir", str(tmp_path / ".kb")])
    assert result.exit_code == 0
    assert "arinc-424" in result.output
    assert "5.3" in result.output
    assert "pending" in result.output.lower()
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
.venv/bin/pytest tests/test_ingest_cli.py -v
```
Expected: FAIL — command `ingest` chưa tồn tại (exit code 2, "No such command").

- [ ] **Step 3: Thêm 2 command vào cli.py**

Thay toàn bộ nội dung `src/aero_kb/cli.py` bằng:
```python
from __future__ import annotations

from pathlib import Path

import typer

from aero_kb import models

app = typer.Typer(
    help="AERO-KB — Knowledge Base as Code cho tài liệu hàng không.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """AERO-KB CLI."""


@app.command()
def ingest(
    pdf: Path = typer.Argument(..., help="File PDF nguồn"),
    doc_id: str = typer.Option(..., "--id", help="ID tài liệu, vd arinc-424"),
    tags: str = typer.Option("", help="Tags, phân cách bằng dấu phẩy"),
    revision: str = typer.Option("", help="Bản sửa đổi, vd 'Supplement 22'"),
    sections: str = typer.Option(
        "", help="Chỉ scaffold các chương này, vd '5,6' (rỗng = tất cả)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    work_dir: Path = typer.Option(Path(".kb-work"), help="Thư mục cache trung gian"),
) -> None:
    """Parse PDF → cắt section → sinh L3 + khung L1/L2 chờ summarize."""
    from aero_kb.ingest import parser, scaffold, sectioner

    doc = parser.load_or_parse(pdf, work_dir / doc_id)
    items = parser.doc_to_items(doc)
    units = sectioner.build_units(items)

    bm_ids = parser.bookmark_ids(pdf)
    if bm_ids:
        for warning in parser.crosscheck({u.id for u in units}, bm_ids):
            typer.secho(f"  [warn] {warning}", fg=typer.colors.YELLOW)

    chapters = {s.strip() for s in sections.split(",") if s.strip()} or None
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    report = scaffold.scaffold_doc(
        units,
        doc_id=doc_id,
        title=doc_id if not hasattr(doc, "name") else (getattr(doc, "name", "") or doc_id),
        tags=tag_list,
        revision=revision,
        source_path=pdf,
        kb_dir=kb_dir,
        chapters=chapters,
    )
    typer.echo(
        f"Ingested '{report.doc_id}': {report.n_sections} sections, "
        f"{len(report.files)} files trong {kb_dir / report.doc_id}"
    )
    typer.echo("Tiếp theo: mở Claude Code và chạy skill kb-summarize, rồi `kb build`.")


@app.command()
def status(
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Liệt kê các section đang chờ summarize (status=pending)."""
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        typer.echo("KB trống — chưa có index.yaml.")
        raise typer.Exit(0)
    index = models.load_yaml_model(index_path, models.KBIndex)
    total_pending = 0
    for entry in index.docs:
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        pending = [s for s in manifest.sections if s.status == "pending"]
        total_pending += len(pending)
        typer.echo(
            f"{entry.id}: {len(pending)}/{len(manifest.sections)} section pending"
        )
        for sec in pending:
            typer.echo(f"  - §{sec.id} {sec.title} (file: {sec.file}.md)")
    typer.echo(f"Tổng: {total_pending} section pending.")
```

Ghi chú: title của doc lấy từ `doc_id` khi Docling không cung cấp tên — SME/skill sẽ chỉnh title trong manifest/index nếu cần (bước điền L0).

- [ ] **Step 4: Chạy test — phải PASS**

```bash
.venv/bin/pytest tests/test_ingest_cli.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Chạy toàn bộ suite**

```bash
.venv/bin/pytest -q
```
Expected: tất cả pass (test_cli.py cũ vẫn pass).

- [ ] **Step 6: Commit**

```bash
git add src/aero_kb/cli.py tests/test_ingest_cli.py
git commit -m "feat: CLI kb ingest + kb status"
```

---

### Task 8: `kb build` — validate, toàn vẹn bảng, token counts (+ fixture KB dùng chung)

**Files:**
- Create: `src/aero_kb/build.py`
- Create: `tests/conftest.py`
- Modify: `src/aero_kb/cli.py` (thêm command `build`)
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: `models.*`, `mdutils.slice_section`, `mdutils.extract_tables`, `mdutils.normalize_table`, `mdutils.count_tokens`
- Produces:
  - `BuildReport(errors: list[str], warnings: list[str])` — dataclass; property `ok: bool` = không có errors
  - `build_kb(kb_dir: Path, allow_pending: bool = False) -> BuildReport` — validate + ghi lại token counts vào manifest
  - Lệnh `kb build [--allow-pending] [--kb-dir .kb]` — exit 1 nếu có errors
  - Fixture pytest `fixture_kb(tmp_path) -> Path` trong conftest — cây `.kb/` hoàn chỉnh đã điền summary, dùng lại cho Task 9, 10

- [ ] **Step 1: Viết conftest với fixture KB mẫu**

`tests/conftest.py`:
```python
from pathlib import Path

import pytest

from aero_kb import models

TABLE = "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n| R | Restricted |"

L2_CONTENT = f"""## 1.1 Airspace Records

Condensed: airspace record structure with designation and type fields.

{TABLE}

## 1.2 Airway Records

Condensed: airway record structure, route identifiers.
"""

L3_CONTENT = f"""## 1.1 Airspace Records

Full raw text about airspace records. Designation, type, multiple code, level.

{TABLE}

## 1.2 Airway Records

Full raw text about airway records and route identifiers.
"""


@pytest.fixture
def fixture_kb(tmp_path: Path) -> Path:
    kb = tmp_path / ".kb"
    doc_dir = kb / "demo-doc"
    doc_dir.mkdir(parents=True)
    (doc_dir / "ch1-records.md").write_text(L2_CONTENT, encoding="utf-8")
    (doc_dir / "ch1-records.raw.md").write_text(L3_CONTENT, encoding="utf-8")
    manifest = models.Manifest(
        id="demo-doc",
        title="Demo Document",
        revision="Rev 1",
        sections=[
            models.SectionEntry(
                id="1.1",
                title="Airspace Records",
                summary="Airspace record structure: designation, type, level.",
                status="summarized",
                file="ch1-records",
            ),
            models.SectionEntry(
                id="1.2",
                title="Airway Records",
                summary="Airway record structure and route identifiers.",
                status="summarized",
                file="ch1-records",
            ),
        ],
    )
    models.save_yaml_model(doc_dir / "_manifest.yaml", manifest)
    index = models.KBIndex(
        docs=[
            models.IndexEntry(
                id="demo-doc",
                title="Demo Document",
                revision="Rev 1",
                tags=["demo", "airspace"],
                summary="Demo aviation data spec.",
            )
        ]
    )
    models.save_yaml_model(kb / "index.yaml", index)
    return kb
```

- [ ] **Step 2: Viết failing tests**

`tests/test_build.py`:
```python
from pathlib import Path

from aero_kb import models
from aero_kb.build import build_kb


def test_build_ok_on_valid_kb(fixture_kb: Path):
    report = build_kb(fixture_kb)
    assert report.ok, report.errors
    manifest = models.load_yaml_model(
        fixture_kb / "demo-doc" / "_manifest.yaml", models.Manifest
    )
    sec = manifest.sections[0]
    assert sec.tokens.l2 > 0
    assert sec.tokens.l3 > sec.tokens.l2


def test_build_fails_on_todo_marker(fixture_kb: Path):
    l2_path = fixture_kb / "demo-doc" / "ch1-records.md"
    text = l2_path.read_text().replace(
        "Condensed: airspace record structure with designation and type fields.",
        "<!-- TODO:summarize 1.1 -->",
    )
    l2_path.write_text(text)
    report = build_kb(fixture_kb)
    assert not report.ok
    assert any("TODO" in e for e in report.errors)


def test_build_allow_pending_downgrades_to_warning(fixture_kb: Path):
    l2_path = fixture_kb / "demo-doc" / "ch1-records.md"
    text = l2_path.read_text().replace(
        "Condensed: airspace record structure with designation and type fields.",
        "<!-- TODO:summarize 1.1 -->",
    )
    l2_path.write_text(text)
    report = build_kb(fixture_kb, allow_pending=True)
    assert report.ok
    assert any("TODO" in w for w in report.warnings)


def test_build_fails_on_empty_summary(fixture_kb: Path):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(mpath, models.Manifest)
    manifest.sections[0].summary = ""
    models.save_yaml_model(mpath, manifest)
    report = build_kb(fixture_kb)
    assert not report.ok


def test_build_fails_when_l3_table_missing_from_l2(fixture_kb: Path):
    l2_path = fixture_kb / "demo-doc" / "ch1-records.md"
    text = l2_path.read_text().replace("| P    | Prohibited |", "| P    | Permitted |")
    # sua bang trong L2 -> khac L3 -> toan ven bang fail
    l2_path.write_text(text.replace("| P | Prohibited |", "| P | Permitted |"))
    report = build_kb(fixture_kb)
    assert not report.ok
    assert any("bang" in e.lower() or "table" in e.lower() for e in report.errors)


def test_build_fails_when_section_missing_in_l2(fixture_kb: Path):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(mpath, models.Manifest)
    manifest.sections.append(
        models.SectionEntry(
            id="1.9",
            title="Ghost Section",
            summary="x",
            status="summarized",
            file="ch1-records",
        )
    )
    models.save_yaml_model(mpath, manifest)
    report = build_kb(fixture_kb)
    assert not report.ok
```

- [ ] **Step 3: Chạy test — phải FAIL**

```bash
.venv/bin/pytest tests/test_build.py -v
```
Expected: FAIL — `aero_kb.build` chưa tồn tại.

- [ ] **Step 4: Implement build.py**

`src/aero_kb/build.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from aero_kb import models
from aero_kb.mdutils import (
    count_tokens,
    extract_tables,
    normalize_table,
    slice_section,
)

TODO_MARKER = "<!-- TODO:summarize"


@dataclass
class BuildReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def build_kb(kb_dir: Path, allow_pending: bool = False) -> BuildReport:
    report = BuildReport()
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        report.errors.append(f"khong thay {index_path}")
        return report
    index = models.load_yaml_model(index_path, models.KBIndex)

    for entry in index.docs:
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            report.errors.append(f"{entry.id}: thieu _manifest.yaml")
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        file_cache: dict[str, str] = {}

        for sec in manifest.sections:
            l2_text = _read_cached(kb_dir / entry.id / f"{sec.file}.md", file_cache)
            l3_text = _read_cached(
                kb_dir / entry.id / f"{sec.file}.raw.md", file_cache
            )
            ref = f"{entry.id} §{sec.id}"

            l2_slice = slice_section(l2_text, sec.id) if l2_text else None
            l3_slice = slice_section(l3_text, sec.id) if l3_text else None
            if l2_slice is None or l3_slice is None:
                report.errors.append(f"{ref}: khong tim thay section trong file L2/L3")
                continue

            is_pending = TODO_MARKER in l2_slice or not sec.summary.strip()
            if is_pending:
                msg = f"{ref}: con TODO marker hoac summary rong"
                if allow_pending:
                    report.warnings.append(msg)
                else:
                    report.errors.append(msg)

            l2_tables = {normalize_table(t) for t in extract_tables(l2_slice)}
            for table in extract_tables(l3_slice):
                if normalize_table(table) not in l2_tables:
                    report.errors.append(
                        f"{ref}: bang trong L3 khong khop nguyen van voi L2 "
                        f"(table integrity fail)"
                    )
                    break

            sec.tokens = models.SectionTokens(
                l2=count_tokens(l2_slice), l3=count_tokens(l3_slice)
            )

        models.save_yaml_model(manifest_path, manifest)

    l0_tokens = count_tokens(index_path.read_text(encoding="utf-8"))
    if l0_tokens > 1000:
        report.warnings.append(
            f"L0 index.yaml = {l0_tokens} token (> 1000, xem lai muc tieu spec)"
        )
    return report


def _read_cached(path: Path, cache: dict[str, str]) -> str:
    key = str(path)
    if key not in cache:
        cache[key] = path.read_text(encoding="utf-8") if path.exists() else ""
    return cache[key]
```

- [ ] **Step 5: Thêm command build vào cli.py**

Thêm vào cuối `src/aero_kb/cli.py`:
```python
@app.command()
def build(
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    allow_pending: bool = typer.Option(
        False, "--allow-pending", help="Không fail khi còn section pending"
    ),
) -> None:
    """Validate KB: hết TODO, toàn vẹn bảng, cập nhật token counts."""
    from aero_kb.build import build_kb

    report = build_kb(kb_dir, allow_pending=allow_pending)
    for warning in report.warnings:
        typer.secho(f"[warn] {warning}", fg=typer.colors.YELLOW)
    for error in report.errors:
        typer.secho(f"[error] {error}", fg=typer.colors.RED)
    if not report.ok:
        raise typer.Exit(1)
    typer.echo("kb build: OK")
```

- [ ] **Step 6: Chạy test — phải PASS**

```bash
.venv/bin/pytest tests/test_build.py -v
```
Expected: 6 passed.

- [ ] **Step 7: Chạy toàn bộ suite + commit**

```bash
.venv/bin/pytest -q
git add src/aero_kb/build.py src/aero_kb/cli.py tests/conftest.py tests/test_build.py
git commit -m "feat: kb build — validate TODO/summary, toan ven bang, token counts"
```

---

### Task 9: Query engine — `kb query` + `kb get`

**Files:**
- Create: `src/aero_kb/query.py`
- Modify: `src/aero_kb/cli.py` (thêm 2 command)
- Test: `tests/test_query.py`

**Interfaces:**
- Consumes: `models.*`, `mdutils.slice_section`, `mdutils.count_tokens`, fixture `fixture_kb`
- Produces:
  - `QueryResult(doc_id, section_id, title, score: float, citation: str, content: str, tokens: int)` — dataclass
  - `search(kb_dir: Path, text: str, tags: list[str] | None = None, budget: int = 2000) -> list[QueryResult]`
  - `get_section(kb_dir: Path, doc_id: str, section_id: str, level: str = "l2") -> QueryResult | None` — level ∈ {"l2","l3"}
  - Lệnh `kb query "..." [--tags a,b] [--budget 2000] [--kb-dir .kb]` và `kb get <doc-id> <section> [--level l2|l3]` (section chấp nhận cả dạng `§5.3` lẫn `5.3`)

- [ ] **Step 1: Viết failing tests**

`tests/test_query.py`:
```python
from pathlib import Path

from aero_kb.query import get_section, search


def test_search_finds_relevant_section_with_citation(fixture_kb: Path):
    results = search(fixture_kb, "airspace designation type")
    assert results
    top = results[0]
    assert top.doc_id == "demo-doc"
    assert top.section_id == "1.1"
    assert top.citation == "demo-doc §1.1 (Rev 1)"
    assert "designation" in top.content.lower()


def test_search_tag_filter_excludes_unmatched_docs(fixture_kb: Path):
    assert search(fixture_kb, "airspace", tags=["demo"])
    # tag khong ton tai -> khong doc nao match -> khong co ket qua
    assert search(fixture_kb, "airspace", tags=["nonexistent-tag"]) == []


def test_search_doc_id_as_tag_activates_doc(fixture_kb: Path):
    results = search(fixture_kb, "airway route", tags=["demo-doc"])
    assert results
    assert results[0].section_id == "1.2"


def test_search_respects_budget(fixture_kb: Path):
    unlimited = search(fixture_kb, "records structure", budget=100_000)
    assert len(unlimited) == 2
    tiny = search(fixture_kb, "records structure", budget=1)
    assert len(tiny) == 1  # ket qua dau tien luon duoc tra, dung sau do


def test_get_section_l2_and_l3(fixture_kb: Path):
    l2 = get_section(fixture_kb, "demo-doc", "1.1", level="l2")
    assert l2 is not None
    assert "Condensed" in l2.content
    l3 = get_section(fixture_kb, "demo-doc", "§1.1", level="l3")
    assert l3 is not None
    assert "Full raw text" in l3.content


def test_get_section_missing_returns_none(fixture_kb: Path):
    assert get_section(fixture_kb, "demo-doc", "9.9") is None
    assert get_section(fixture_kb, "no-such-doc", "1.1") is None
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
.venv/bin/pytest tests/test_query.py -v
```
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Implement query.py**

`src/aero_kb/query.py`:
```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

from aero_kb import models
from aero_kb.mdutils import count_tokens, slice_section


@dataclass
class QueryResult:
    doc_id: str
    section_id: str
    title: str
    score: float
    citation: str
    content: str
    tokens: int


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _citation(doc: models.IndexEntry | models.Manifest, section_id: str) -> str:
    base = f"{doc.id} §{section_id}"
    return f"{base} ({doc.revision})" if doc.revision else base


def search(
    kb_dir: Path,
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
) -> list[QueryResult]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return []
    index = models.load_yaml_model(index_path, models.KBIndex)

    docs = index.docs
    if tags:
        tagset = {t.strip().lower() for t in tags}
        docs = [
            d for d in index.docs
            if tagset & {t.lower() for t in d.tags} or d.id.lower() in tagset
        ]
        if not docs:
            return []

    corpus: list[tuple[models.IndexEntry, models.SectionEntry]] = []
    for doc in docs:
        manifest_path = kb_dir / doc.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        for sec in manifest.sections:
            corpus.append((doc, sec))
    if not corpus:
        return []

    bm25 = BM25Okapi([_tokenize(f"{s.title} {s.summary}") for _, s in corpus])
    scores = bm25.get_scores(_tokenize(text))
    ranked = sorted(zip(corpus, scores), key=lambda pair: -pair[1])

    results: list[QueryResult] = []
    used = 0
    for (doc, sec), score in ranked:
        if score <= 0:
            break
        l2_path = kb_dir / doc.id / f"{sec.file}.md"
        if not l2_path.exists():
            continue
        content = slice_section(l2_path.read_text(encoding="utf-8"), sec.id)
        if content is None:
            continue
        n_tokens = count_tokens(content)
        if results and used + n_tokens > budget:
            break
        results.append(
            QueryResult(
                doc_id=doc.id,
                section_id=sec.id,
                title=sec.title,
                score=float(score),
                citation=_citation(doc, sec.id),
                content=content,
                tokens=n_tokens,
            )
        )
        used += n_tokens
        if used >= budget:
            break
    return results


def get_section(
    kb_dir: Path, doc_id: str, section_id: str, level: str = "l2"
) -> QueryResult | None:
    section_id = section_id.lstrip("§")
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    sec = next((s for s in manifest.sections if s.id == section_id), None)
    if sec is None:
        return None
    suffix = ".raw.md" if level == "l3" else ".md"
    path = kb_dir / doc_id / f"{sec.file}{suffix}"
    if not path.exists():
        return None
    content = slice_section(path.read_text(encoding="utf-8"), section_id)
    if content is None:
        return None
    return QueryResult(
        doc_id=doc_id,
        section_id=section_id,
        title=sec.title,
        score=0.0,
        citation=_citation(manifest, section_id),
        content=content,
        tokens=count_tokens(content),
    )
```

- [ ] **Step 4: Thêm command query/get vào cli.py**

Thêm vào cuối `src/aero_kb/cli.py`:
```python
@app.command()
def query(
    text: str = typer.Argument(..., help="Câu truy vấn"),
    tags: str = typer.Option("", help="Tags lọc doc, phân cách bằng dấu phẩy"),
    budget: int = typer.Option(2000, help="Token budget cho nội dung trả về"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Tag match → BM25 → trả section L2 trong budget, kèm citation."""
    from aero_kb.query import search

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or None
    results = search(kb_dir, text, tags=tag_list, budget=budget)
    if not results:
        typer.echo("Không tìm thấy section phù hợp.")
        raise typer.Exit(0)
    for r in results:
        typer.secho(f"--- [{r.citation}] score={r.score:.2f} ~{r.tokens}tk", bold=True)
        typer.echo(r.content)
        typer.echo("")


@app.command()
def get(
    doc_id: str = typer.Argument(..., help="ID tài liệu"),
    section: str = typer.Argument(..., help="ID section, vd 5.3 hoặc §5.3"),
    level: str = typer.Option("l2", help="Tầng: l2 hoặc l3"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Lấy chính xác một section ở tầng chỉ định."""
    from aero_kb.query import get_section

    result = get_section(kb_dir, doc_id, section, level=level)
    if result is None:
        typer.secho(f"Không thấy {doc_id} §{section}", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"--- [{result.citation}] ~{result.tokens}tk", bold=True)
    typer.echo(result.content)
```

- [ ] **Step 5: Chạy test — phải PASS**

```bash
.venv/bin/pytest tests/test_query.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Chạy toàn bộ suite + commit**

```bash
.venv/bin/pytest -q
git add src/aero_kb/query.py src/aero_kb/cli.py tests/test_query.py
git commit -m "feat: kb query (tag match + BM25 + budget) va kb get"
```

---

### Task 10: `kb stats` — bảng token từng tầng

**Files:**
- Modify: `src/aero_kb/build.py` (thêm hàm stats)
- Modify: `src/aero_kb/cli.py` (thêm command)
- Test: `tests/test_stats.py`

**Interfaces:**
- Consumes: `models.*`, `mdutils.count_tokens`, fixture `fixture_kb`
- Produces:
  - `DocStats(doc_id: str, n_sections: int, l1_tokens: int, l2_tokens: int, l3_tokens: int)` — dataclass; `saving_pct: float` property = `100 * (1 - l2/l3)` (0 nếu l3=0)
  - `kb_stats(kb_dir: Path) -> tuple[int, list[DocStats]]` — (l0_tokens, per-doc stats); l2/l3 lấy từ tokens đã ghi trong manifest (chạy `kb build` trước để cập nhật)
  - Lệnh `kb stats [--kb-dir .kb]`

- [ ] **Step 1: Viết failing tests**

`tests/test_stats.py`:
```python
from pathlib import Path

from aero_kb.build import build_kb, kb_stats


def test_stats_reports_tokens_per_tier(fixture_kb: Path):
    build_kb(fixture_kb)  # cap nhat token counts truoc
    l0_tokens, docs = kb_stats(fixture_kb)
    assert l0_tokens > 0
    assert len(docs) == 1
    d = docs[0]
    assert d.doc_id == "demo-doc"
    assert d.n_sections == 2
    assert 0 < d.l2_tokens < d.l3_tokens
    assert d.l1_tokens > 0
    assert 0 < d.saving_pct < 100
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
.venv/bin/pytest tests/test_stats.py -v
```
Expected: FAIL — `kb_stats` chưa tồn tại.

- [ ] **Step 3: Thêm vào build.py**

Thêm vào cuối `src/aero_kb/build.py`:
```python
@dataclass
class DocStats:
    doc_id: str
    n_sections: int
    l1_tokens: int
    l2_tokens: int
    l3_tokens: int

    @property
    def saving_pct(self) -> float:
        if self.l3_tokens == 0:
            return 0.0
        return 100.0 * (1 - self.l2_tokens / self.l3_tokens)


def kb_stats(kb_dir: Path) -> tuple[int, list[DocStats]]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return 0, []
    l0_tokens = count_tokens(index_path.read_text(encoding="utf-8"))
    index = models.load_yaml_model(index_path, models.KBIndex)
    stats: list[DocStats] = []
    for entry in index.docs:
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        stats.append(
            DocStats(
                doc_id=entry.id,
                n_sections=len(manifest.sections),
                l1_tokens=count_tokens(manifest_path.read_text(encoding="utf-8")),
                l2_tokens=sum(s.tokens.l2 for s in manifest.sections),
                l3_tokens=sum(s.tokens.l3 for s in manifest.sections),
            )
        )
    return l0_tokens, stats
```

- [ ] **Step 4: Thêm command stats vào cli.py**

Thêm vào cuối `src/aero_kb/cli.py`:
```python
@app.command()
def stats(
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Token size từng tầng, từng tài liệu — theo dõi chi phí."""
    from aero_kb.build import kb_stats

    l0_tokens, docs = kb_stats(kb_dir)
    typer.echo(f"L0 index.yaml: {l0_tokens} tokens")
    if not docs:
        typer.echo("KB trống.")
        raise typer.Exit(0)
    header = f"{'doc':<20} {'sections':>8} {'L1':>8} {'L2':>10} {'L3':>10} {'saving':>8}"
    typer.echo(header)
    for d in docs:
        typer.echo(
            f"{d.doc_id:<20} {d.n_sections:>8} {d.l1_tokens:>8} "
            f"{d.l2_tokens:>10} {d.l3_tokens:>10} {d.saving_pct:>7.1f}%"
        )
```

- [ ] **Step 5: Chạy test — phải PASS, chạy toàn suite, commit**

```bash
.venv/bin/pytest tests/test_stats.py -v
.venv/bin/pytest -q
git add src/aero_kb/build.py src/aero_kb/cli.py tests/test_stats.py
git commit -m "feat: kb stats — bang token L0/L1/L2/L3 va % tiet kiem"
```

---

### Task 11: Skill `kb-summarize` cho Claude Code

**Files:**
- Create: `.claude/skills/kb-summarize/SKILL.md`

**Interfaces:**
- Consumes: `kb status`, `kb get ... --level l3`, `kb build --allow-pending`, cấu trúc marker `<!-- TODO:summarize <id> -->`
- Produces: quy trình chuẩn để bất kỳ phiên Claude Code nào điền summary — đây là "nửa LLM" của pipeline ingest.

- [ ] **Step 1: Viết SKILL.md**

`.claude/skills/kb-summarize/SKILL.md`:
```markdown
---
name: kb-summarize
description: Điền summary L0/L1/L2 cho các section đang pending trong .kb/ sau khi chạy kb ingest. Dùng khi user yêu cầu summarize KB, điền summary, hoặc sau khi vừa ingest tài liệu mới.
---

# KB Summarize — điền tri thức vào khung .kb/

Bạn là "nửa LLM" của pipeline AERO-KB. `kb ingest` đã sinh khung; nhiệm vụ
của bạn là điền phần summary. KHÔNG sửa bất kỳ thứ gì ngoài các vị trí nêu dưới.

## Quy trình

1. Chạy `kb status` — lấy danh sách section pending (doc, section id, file).
2. Với TỪNG section pending, lặp:
   a. Đọc nguyên văn: `kb get <doc-id> <section-id> --level l3`
   b. Mở file L2 (`.kb/<doc-id>/<file>.md`), tìm marker
      `<!-- TODO:summarize <section-id> -->` trong section tương ứng.
   c. Thay marker bằng đoạn văn cô đọng (xem Quy tắc viết). KHÔNG đụng vào
      các bảng markdown đã có sẵn trong section — chúng do code chép nguyên văn.
   d. Mở `.kb/<doc-id>/_manifest.yaml`, điền `summary` (1 câu, ≤ 25 từ)
      cho section đó và đổi `status: pending` → `status: summarized`.
3. Khi mọi section của một doc xong: mở `.kb/index.yaml`, điền/sửa `summary`
   (1 câu) và kiểm tra `title`, `revision`, `tags` của doc đó cho đúng.
4. Chạy `kb build` — phải PASS. Nếu fail vì table integrity: bạn đã lỡ sửa
   bảng, khôi phục bảng về nguyên văn từ file `.raw.md`.
5. Báo cáo: số section đã điền, tổng token L2 (xem `kb stats`).

## Quy tắc viết (bắt buộc)

- Viết **tiếng Anh**.
- Đoạn L2: cô đọng văn xuôi còn ~20–30% độ dài gốc, giữ cấu trúc logic.
- Giữ NGUYÊN VĂN: mọi mã hiệu (P, R, D...), tên record/field (UR, PA...),
  giá trị số, đơn vị, tham chiếu chéo (§x.y). Không diễn đạt lại thuật ngữ.
- KHÔNG suy diễn ngoài văn bản gốc. Thiếu chắc chắn → giữ nguyên câu gốc.
- KHÔNG tóm tắt bảng, không tạo bảng mới, không xóa bảng.
- Summary L1 (manifest): 1 câu ≤ 25 từ, nêu section nói về cái gì và chứa
  loại dữ liệu gì (để BM25 khớp được từ khóa kỹ thuật).

## Làm việc theo lô

Điền lần lượt từng section, mỗi 5–10 section chạy lại `kb build
--allow-pending` để bắt lỗi sớm. Không sửa nhiều file song song.
```

- [ ] **Step 2: Kiểm tra skill được nhận diện**

```bash
ls .claude/skills/kb-summarize/SKILL.md
```
Expected: file tồn tại. (Skill sẽ xuất hiện trong danh sách skill của phiên Claude Code kế tiếp mở trong repo này.)

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/kb-summarize/SKILL.md
git commit -m "feat: skill kb-summarize — quy trinh dien summary chuan cho Claude Code"
```

---

### Task 12: Chạy thật — ARINC 424 chương 5 + Annex 3 (acceptance)

**Files:**
- Không tạo code mới. Sản phẩm: `.kb/` có nội dung thật (commit), báo cáo `kb stats`.

**Interfaces:**
- Consumes: toàn bộ CLI + skill kb-summarize + 2 PDF trong `sources/`.

Đây là task verify thủ công (acceptance của Phase 1). Docling lần đầu sẽ tải model và chạy lâu (ARINC 487 trang: 15–30 phút) — chạy nền, không ngồi chờ.

- [ ] **Step 1: Cài extra ingest**

```bash
.venv/bin/pip install -e ".[ingest]"
.venv/bin/python -c "import docling; print(docling.__version__)"
```
Expected: in version, không lỗi. (Nếu cài fail trên Python 3.13: kiểm tra lỗi cụ thể, thử `pip install docling` riêng để xem dependency nào thiếu wheel.)

- [ ] **Step 2: Ingest ARINC 424 chương 5 (chạy nền)**

```bash
.venv/bin/kb ingest "sources/ARINC424-22.pdf" \
  --id arinc-424 \
  --tags arinc424,navdata,airspace,airport,navaid,airway \
  --revision "Supplement 22" \
  --sections 5
```
Expected: kết thúc với dòng `Ingested 'arinc-424': N sections...`. Đọc kỹ các dòng `[warn]` bookmark crosscheck — nếu hàng loạt section chương 5 bị báo thiếu, dừng lại điều tra sectioner (heading ARINC có thể có format chưa lường). Nếu API Docling lệch so với `parser.py`: tra Context7 docs docling, sửa chỉ trong `parser.py`, chạy lại (cache parsed.json giúp không parse lại PDF).

- [ ] **Step 3: Sanity check khung ARINC**

```bash
.venv/bin/kb status
head -50 .kb/arinc-424/_manifest.yaml
grep -c "TODO:summarize" .kb/arinc-424/*.md
```
Expected: manifest có cây section chương 5 (id 5, 5.1, 5.2...), số section hợp lý (~15–40 sau gộp), file L2 có marker TODO + bảng, file L3 có nội dung. Mở file `.raw.md`, đối chiếu MẮT THƯỜNG 2–3 bảng với PDF gốc — đây là kiểm tra chất lượng Docling quan trọng nhất.

- [ ] **Step 4: Ingest Annex 3 chương 2 (nhỏ hơn, đại diện ICAO format)**

```bash
.venv/bin/kb ingest "sources/003 Annex Meteorological Service 20th Edition [80].pdf" \
  --id icao-annex-3 \
  --tags icao,annex3,met,meteorology \
  --revision "Ed 20" \
  --sections 2
```
Expected: tương tự — kiểm tra manifest và warnings.

- [ ] **Step 5: Điền summary bằng skill**

Trong phiên Claude Code này (hoặc phiên mới), yêu cầu: "chạy skill kb-summarize". Skill sẽ điền toàn bộ section pending của 2 doc.
Expected: `kb status` → 0 pending.

- [ ] **Step 6: Build + stats — bằng chứng nghiệm thu**

```bash
.venv/bin/kb build
.venv/bin/kb stats
```
Expected: `kb build: OK`. Bảng stats: L0 < 1000 token; saving % của mỗi doc ≥ 70% (L2 so với L3 — mục tiêu ≥ 90% của spec tính so với raw document đầy đủ, tức cả phần chưa ingest; ghi số thực tế vào báo cáo).

- [ ] **Step 7: Query thử — tiêu chí "đúng section, đúng citation"**

```bash
.venv/bin/kb query "restrictive airspace record fields" --tags arinc424 --budget 2000
.venv/bin/kb query "aerodrome meteorological observation requirements" --tags annex3
.venv/bin/kb get arinc-424 5.3 --level l3
```
Expected: query 1 trả về section restrictive airspace của arinc-424 với citation `arinc-424 §... (Supplement 22)`; query 2 trả section thuộc icao-annex-3. Nếu section id thực tế khác 5.3 (đánh số theo tài liệu thật), dùng id có thật trong manifest.

- [ ] **Step 8: SME review + commit KB**

User (vai SME) đọc diff `.kb/`, sửa trực tiếp nếu summary sai. Sau đó:

```bash
git add .kb/
git commit -m "feat: ingest ARINC 424 ch5 + ICAO Annex 3 ch2 — KB dau tien qua SME review"
```

- [ ] **Step 9: Ghi lại kết quả nghiệm thu**

Cập nhật cuối design doc (`docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md`) một mục "Kết quả PoC": số section, token từng tầng, saving %, các cảnh báo crosscheck còn lại, case bảng lỗi (nếu có). Commit `docs:`.

---

## Self-Review (đã chạy)

- **Spec coverage:** ingest/cache (§4.1 → T5), id + cây + gộp/tách (§4.2, §4.4 → T4), bookmark crosscheck (§4.3 → T5), bảng nguyên văn code-chép (§4.5 → T6), file theo chương + anchor (§4.6 → T3, T6), `--sections` (§4.7 → T6, T7), khung chờ điền + marker (§5.1 → T6), skill (§5.2 → T11), chốt chặn build + toàn vẹn bảng + token counts (§5.3 → T8), SME review (§5.4 → T12), tag match + BM25 + budget + citation (§6.1 → T9), đủ 6 lệnh CLI (§6.2 → T1, T7–T10), testing trên fixture (§7 → mọi task), chạy thật (§8 bước 7 → T12).
- **Type consistency:** `SectionEntry.file` = stem (T2) dùng nhất quán ở T6/T8/T9; `DocItem`/`SectionUnit` (T4) dùng ở T5/T6/T7; `build_kb`/`kb_stats` cùng module `build.py`; citation format thống nhất qua `_citation`.
- **Placeholder:** không còn TBD/TODO trong plan (marker `TODO:summarize` là nội dung sản phẩm, không phải placeholder của plan).
