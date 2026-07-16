# Image & Icon Ingest (Spec A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep PDF images/icons through ingest, make them searchable via deterministic description text in L2, order sections by the TOC, and render/serve them in the web UI.

**Architecture:** A new `ingest/images.py` owns classification, compression, content-addressed saving, and deterministic descriptions (caption → OCR → phash legend match). `parser.py` gains a docling `PictureItem` branch that emits `DocItem(kind="image")` markdown refs which flow through the existing sectioner body path into L3; `scaffold.py` copies description text into L2. Unit ordering is fixed by anchoring each section to its heading's page. `mdrender.py` + a new authenticated `/assets/{name}` route display the images.

**Tech Stack:** Python ≥3.11, docling ≥2.0 (ingest extra), Pillow, imagehash (phash), RapidOCR (already the pipeline's OCR), Starlette, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-image-icon-ingest-design.md`

## Global Constraints

- Run all tests with `.venv/bin/python -m pytest` from the repo root (venv is Python 3.13).
- Tests are hermetic: no docling import at test time, no network, no LLM, no real OCR engine. Docling objects are faked (see `tests/test_parser.py` for the pattern).
- Table integrity is inviolable: an L2 table cell must equal the L3 table cell byte-for-byte. Table cells render character-for-character in `mdrender`.
- Descriptions are never fabricated: caption → OCR → legend match, else empty string. No VLM, no LLM.
- Committed markdown references are always relative `assets/<sha256>.<png|webp>`; sha is of the **stored (compressed) bytes**.
- Named constants (all in `src/center_kb/ingest/images.py`): `ICON_MAX_DIM_PX = 128` (at `images_scale=2.0`), `WEBP_QUALITY = 80`, `PHASH_MAX_DISTANCE = 5` (Hamming, 64-bit phash), `MIN_OCR_CHARS = 3`.
- Commit messages: `<type>: <description>` (feat/fix/refactor/docs/test/chore), no attribution footer.
- Deliberate deviation from spec §8, decided here: sections (units) are ordered by forward-filled heading **page** (stable sort); body items keep docling's reading order. A naive bbox-y re-sort would scramble multi-column reading order; page anchoring alone fixes the reported scramble class.

---

### Task 1: PoC probe script (manual gate for Task 11)

The PoC needs a real, copyrighted PDF that is never committed — so the deliverable is the probe script plus run instructions; a human runs it and commits a findings note. **This task has no pytest cycle** (the script imports docling, which tests must not).

**Files:**
- Create: `scripts/poc_pictures.py`

**Interfaces:**
- Produces: a findings file at `docs/superpowers/plans/2026-07-16-poc-picture-findings.md` (written by the human who runs the script). Task 11 executes only if that file exists and answers YES to in-cell pictures.

- [ ] **Step 1: Write the probe script**

```python
#!/usr/bin/env python
"""Probe docling picture extraction on a real PDF (manual PoC, not CI).

Usage:
    .venv/bin/python scripts/poc_pictures.py <pdf> [first_page] [last_page]

Prints one line per PictureItem (page, size, caption, inside-table?) and a
summary. Answers the spec §4 gate questions:
  1. large-figure coverage   2. in-cell icon detection   3. legend-table shape
Record the answers in docs/superpowers/plans/2026-07-16-poc-picture-findings.md
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    pdf = Path(sys.argv[1])
    first = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    last = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(
        ocr_options=RapidOcrOptions(backend="torch", lang=["en"]),
        generate_picture_images=True,
        images_scale=2.0,
    )
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    doc = converter.convert(str(pdf)).document

    tables = []
    pictures = []
    for item, _lvl in doc.iterate_items():
        label = getattr(getattr(item, "label", ""), "value", None) or str(
            getattr(item, "label", "")
        )
        prov = getattr(item, "prov", None)
        page = getattr(prov[0], "page_no", None) if prov else None
        if page is None or not (first <= page <= last):
            continue
        if label == "table":
            tables.append((page, getattr(prov[0], "bbox", None)))
        elif label == "picture":
            pictures.append((item, page, getattr(prov[0], "bbox", None)))

    def inside(outer, inner) -> bool:
        if outer is None or inner is None:
            return False
        return (
            inner.l >= outer.l - 2
            and inner.r <= outer.r + 2
            and min(inner.t, inner.b) >= min(outer.t, outer.b) - 2
            and max(inner.t, inner.b) <= max(outer.t, outer.b) + 2
        )

    n_in_table = 0
    for item, page, bbox in pictures:
        img = item.get_image(doc)
        size = f"{img.width}x{img.height}" if img is not None else "NO-PIXELS"
        caption = ""
        try:
            caption = item.caption_text(doc) or ""
        except Exception:
            pass
        in_table = any(tp == page and inside(tb, bbox) for tp, tb in tables)
        n_in_table += in_table
        print(f"p{page} {size} in_table={in_table} caption={caption[:60]!r}")
    print(f"\npictures={len(pictures)} in_table={n_in_table} tables={len(tables)}")
    print("cells: inspect a legend table's TableData below")
    for item, _lvl in doc.iterate_items():
        label = getattr(getattr(item, "label", ""), "value", None) or str(
            getattr(item, "label", "")
        )
        if label == "table":
            prov = getattr(item, "prov", None)
            page = getattr(prov[0], "page_no", None) if prov else None
            if page is not None and first <= page <= last:
                cells = getattr(getattr(item, "data", None), "table_cells", [])
                with_bbox = sum(1 for c in cells if getattr(c, "bbox", None))
                print(f"  table p{page}: {len(cells)} cells, {with_bbox} with bbox")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax-check the script (no docling run)**

Run: `.venv/bin/python -m py_compile scripts/poc_pictures.py && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/poc_pictures.py
git commit -m "feat: add manual PoC probe for docling picture extraction"
```

---

### Task 2: `images.py` — classify, compress, content-addressed save

**Files:**
- Create: `src/center_kb/ingest/images.py`
- Modify: `pyproject.toml` (ingest + dev extras)
- Test: `tests/test_images.py`

**Interfaces:**
- Produces: `classify(width: int, height: int) -> str` ("icon"|"figure"); `encode_image(img: PIL.Image.Image) -> tuple[bytes, str]` (bytes, "png"|"webp"); `save_asset(img, assets_dir: Path) -> str` (returns `<sha256>.<ext>` filename); `image_ref(desc: str, filename: str) -> str` (returns `![desc](assets/<filename>)`); constants `ICON_MAX_DIM_PX`, `WEBP_QUALITY`.
- Consumes: nothing project-internal.

- [ ] **Step 1: Add dependencies**

In `pyproject.toml` change the ingest extra and dev extra:

```toml
ingest = ["docling>=2.0", "imagehash>=4.3", "Pillow>=10.0"]
dev = [
    "pytest>=8.0", "anyio>=4.0", "sqlite-vec>=0.1.6", "twine>=5.0", "build>=1.2",
    "PyJWT[crypto]>=2.8", "python-multipart>=0.0.9", "httpx>=0.27",
    "imagehash>=4.3", "Pillow>=10.0",
]
```

Run: `.venv/bin/python -m pip install -e ".[dev]" -q && .venv/bin/python -c "import PIL, imagehash; print('deps ok')"`
Expected: `deps ok`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_images.py`:

```python
from __future__ import annotations

import hashlib

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from center_kb.ingest import images  # noqa: E402


def _img(w: int, h: int, color=(200, 30, 30)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


def test_classify_icon_vs_figure():
    assert images.classify(64, 64) == "icon"
    assert images.classify(images.ICON_MAX_DIM_PX, 10) == "icon"
    assert images.classify(images.ICON_MAX_DIM_PX + 1, 10) == "figure"
    assert images.classify(800, 600) == "figure"


def test_encode_icon_is_png_and_figure_is_webp():
    icon_bytes, icon_ext = images.encode_image(_img(32, 32))
    fig_bytes, fig_ext = images.encode_image(_img(500, 400))
    assert icon_ext == "png" and icon_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert fig_ext == "webp" and fig_bytes[:4] == b"RIFF"


def test_encode_is_deterministic():
    a, _ = images.encode_image(_img(32, 32))
    b, _ = images.encode_image(_img(32, 32))
    assert a == b


def test_save_asset_content_addressed_and_idempotent(tmp_path):
    name = images.save_asset(_img(32, 32), tmp_path)
    data = (tmp_path / name).read_bytes()
    sha, ext = name.rsplit(".", 1)
    assert sha == hashlib.sha256(data).hexdigest()
    assert ext == "png"
    again = images.save_asset(_img(32, 32), tmp_path)
    assert again == name
    assert len(list(tmp_path.iterdir())) == 1


def test_image_ref_sanitizes_alt():
    ref = images.image_ref("Compulsory | reporting [point]", "a" * 64 + ".png")
    assert "|" not in ref.split("](")[0]
    assert "[point]" not in ref
    assert ref.endswith(f"](assets/{'a' * 64}.png)")
    assert images.image_ref("", "b" * 64 + ".webp") == f"![](assets/{'b' * 64}.webp)"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_images.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.ingest.images'`

- [ ] **Step 4: Write the implementation**

Create `src/center_kb/ingest/images.py`:

```python
"""Image asset handling for ingest: classification, compression,
content-addressed saving, and deterministic descriptions.

Descriptions come only from the source document (caption → OCR → legend
match) — never generated. sha256 is computed over the stored (compressed)
bytes so the filename is stable and hub verification is byte-exact.
"""
from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("center_kb.ingest.images")

ICON_MAX_DIM_PX = 128  # at images_scale=2.0 (≈64 px at print scale)
WEBP_QUALITY = 80
PHASH_MAX_DISTANCE = 5  # Hamming distance on a 64-bit perceptual hash
MIN_OCR_CHARS = 3


def classify(width: int, height: int) -> str:
    return "icon" if max(width, height) <= ICON_MAX_DIM_PX else "figure"


def encode_image(img) -> tuple[bytes, str]:
    """Icon → lossless optimized PNG (sharp, hash-stable);
    figure → lossy WebP (small)."""
    buf = io.BytesIO()
    if classify(img.width, img.height) == "icon":
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "png"
    img.convert("RGB").save(buf, format="WEBP", quality=WEBP_QUALITY, method=6)
    return buf.getvalue(), "webp"


def save_asset(img, assets_dir: Path) -> str:
    data, ext = encode_image(img)
    name = f"{hashlib.sha256(data).hexdigest()}.{ext}"
    assets_dir.mkdir(parents=True, exist_ok=True)
    path = assets_dir / name
    if not path.exists():
        path.write_bytes(data)
    return name


def _sanitize_alt(text: str) -> str:
    """Alt-text must not break markdown (]) or table cells (|)."""
    cleaned = text.replace("|", " ").replace("[", " ").replace("]", " ")
    return " ".join(cleaned.split())


def image_ref(desc: str, filename: str) -> str:
    return f"![{_sanitize_alt(desc)}](assets/{filename})"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_images.py -v`
Expected: PASS (all 5)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/center_kb/ingest/images.py tests/test_images.py
git commit -m "feat: image classification, compression, content-addressed assets"
```

---

### Task 3: `images.py` — description resolution (caption → OCR)

**Files:**
- Modify: `src/center_kb/ingest/images.py`
- Test: `tests/test_images.py`

**Interfaces:**
- Produces: `resolve_description(caption: str, ocr_text: str) -> str`; `ocr_image(img) -> str` (empty string on any failure — never raises); constant `MIN_OCR_CHARS`.
- Consumes: constants from Task 2.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_images.py`)

```python
def test_resolve_description_priority():
    assert images.resolve_description("Figure 5-1. Holding", "ocr junk") == "Figure 5-1. Holding"
    assert images.resolve_description("  ", "VOR DME") == "VOR DME"
    assert images.resolve_description("", "ab") == ""      # below MIN_OCR_CHARS
    assert images.resolve_description("", "") == ""
    assert images.resolve_description("a  b\n c", "") == "a b c"  # whitespace collapsed


def test_ocr_image_returns_empty_on_missing_engine(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def block_rapidocr(name, *a, **kw):
        if name.startswith("rapidocr"):
            raise ImportError(name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", block_rapidocr)
    monkeypatch.setattr(images, "_OCR_ENGINE", None)
    assert images.ocr_image(_img(32, 32)) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_images.py -v -k "resolve or ocr"`
Expected: FAIL — `AttributeError: module ... has no attribute 'resolve_description'`

- [ ] **Step 3: Write the implementation** (append to `src/center_kb/ingest/images.py`)

```python
_OCR_ENGINE = None  # lazily-initialized RapidOCR singleton (heavy to build)


def resolve_description(caption: str, ocr_text: str) -> str:
    """First deterministic source wins; empty when none — never fabricate."""
    cap = " ".join((caption or "").split())
    if cap:
        return cap
    ocr = " ".join((ocr_text or "").split())
    if len(ocr) >= MIN_OCR_CHARS:
        return ocr
    return ""


def ocr_image(img) -> str:
    """OCR the image crop with RapidOCR (already the pipeline's engine).
    Any failure → '' (a missing description is better than a wrong one)."""
    global _OCR_ENGINE
    try:
        import numpy as np
        from rapidocr import RapidOCR
    except ImportError:
        logger.warning("rapidocr unavailable — OCR description source disabled")
        return ""
    try:
        if _OCR_ENGINE is None:
            _OCR_ENGINE = RapidOCR()
        out = _OCR_ENGINE(np.asarray(img.convert("RGB")))
        txts = getattr(out, "txts", None) or ()
        return " ".join(t.strip() for t in txts if t and t.strip())
    except Exception as exc:  # noqa: BLE001 — OCR must never abort an ingest
        logger.warning("OCR failed on image: %s", exc)
        return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_images.py -v`
Expected: PASS (all 7)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/images.py tests/test_images.py
git commit -m "feat: deterministic image descriptions — caption then OCR floor"
```

---

### Task 4: `images.py` — phash legend map

**Files:**
- Modify: `src/center_kb/ingest/images.py`
- Test: `tests/test_images.py`

**Interfaces:**
- Produces: `phash(img) -> imagehash.ImageHash` (64-bit); `LegendMap` with `add(img, meaning: str) -> None` and `match(img) -> str | None`; constant `PHASH_MAX_DISTANCE`.
- Consumes: constants from Task 2. Task 11 consumes `LegendMap`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_images.py`)

```python
imagehash = pytest.importorskip("imagehash")


def _triangle(size=48, jitter=0) -> Image.Image:
    from PIL import ImageDraw

    img = Image.new("RGB", (size, size), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.polygon([(size // 2, 4 + jitter), (4, size - 4), (size - 4, size - 4)], fill=(0, 0, 0))
    return img


def _square(size=48) -> Image.Image:
    from PIL import ImageDraw

    img = Image.new("RGB", (size, size), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, size - 8, size - 8], fill=(0, 0, 0))
    return img


def test_legend_map_matches_identical_and_near_identical():
    legend = images.LegendMap()
    legend.add(_triangle(), "Compulsory reporting point")
    assert legend.match(_triangle()) == "Compulsory reporting point"
    assert legend.match(_triangle(jitter=1)) == "Compulsory reporting point"


def test_legend_map_rejects_different_shape_and_empty_map():
    legend = images.LegendMap()
    assert legend.match(_square()) is None
    legend.add(_triangle(), "Compulsory reporting point")
    assert legend.match(_square()) is None


def test_legend_map_ignores_blank_meaning():
    legend = images.LegendMap()
    legend.add(_triangle(), "   ")
    assert legend.match(_triangle()) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_images.py -v -k legend`
Expected: FAIL — `AttributeError: ... no attribute 'LegendMap'`

- [ ] **Step 3: Write the implementation** (append to `src/center_kb/ingest/images.py`)

```python
def phash(img):
    """64-bit perceptual hash (imagehash default hash_size=8)."""
    import imagehash

    return imagehash.phash(img.convert("RGB"))


@dataclass
class LegendMap:
    """Icon↔meaning map parsed from the document's own legend table.
    Matching is perceptual-hash only — deterministic, no model."""

    entries: list[tuple[object, str]] = field(default_factory=list)

    def add(self, img, meaning: str) -> None:
        text = " ".join((meaning or "").split())
        if text:
            self.entries.append((phash(img), text))

    def match(self, img) -> str | None:
        if not self.entries:
            return None
        h = phash(img)
        best = min(self.entries, key=lambda e: h - e[0])
        return best[1] if (h - best[0]) <= PHASH_MAX_DISTANCE else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_images.py -v`
Expected: PASS (all 10)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/images.py tests/test_images.py
git commit -m "feat: phash legend map for icon-to-meaning grounding"
```

---

### Task 5: parser — enable picture pixels + `PictureItem` branch

**Files:**
- Modify: `src/center_kb/ingest/parser.py` (`load_or_parse` at lines 30–69, `doc_to_items` at lines 72–87)
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `images.save_asset`, `images.image_ref`, `images.resolve_description`, `images.ocr_image` (Tasks 2–3).
- Produces: `doc_to_items(doc, assets_dir: Path | None = None) -> list[DocItem]` — with `assets_dir` set, picture items become `DocItem("image", "![desc](assets/<sha>.<ext>)", page=page)` and the asset file is written; `assets_dir=None` keeps today's behavior exactly. `load_or_parse` caches to `parsed-v2.json`.

- [ ] **Step 1: Read the existing fake-doc test pattern**

Read `tests/test_parser.py` fully. Reuse its fake item/doc classes; extend the fake item with `get_image`/`caption_text` where needed.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_parser.py`, adapting fakes to the file's existing style — the shapes below are canonical)

```python
import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image


class _FakeLabel:
    def __init__(self, value):
        self.value = value


class _FakeProv:
    def __init__(self, page_no):
        self.page_no = page_no


class _FakePicture:
    label = _FakeLabel("picture")

    def __init__(self, page, img, caption=""):
        self.prov = [_FakeProv(page)]
        self._img = img
        self._caption = caption
        self.text = ""

    def get_image(self, doc):
        return self._img

    def caption_text(self, doc):
        return self._caption


class _FakeDoc:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        return [(i, 0) for i in self._items]


def test_doc_to_items_emits_image_with_caption_description(tmp_path):
    img = Image.new("RGB", (32, 32), (0, 0, 0))
    doc = _FakeDoc([_FakePicture(12, img, caption="Figure 5-1. Holding pattern")])
    items = parser.doc_to_items(doc, assets_dir=tmp_path)
    assert len(items) == 1
    it = items[0]
    assert it.kind == "image" and it.page == 12
    assert it.text.startswith("![Figure 5-1. Holding pattern](assets/")
    name = it.text.split("(assets/")[1].rstrip(")")
    assert (tmp_path / name).exists()


def test_doc_to_items_skips_pictures_without_assets_dir():
    img = Image.new("RGB", (32, 32), (0, 0, 0))
    doc = _FakeDoc([_FakePicture(1, img)])
    assert parser.doc_to_items(doc) == []


def test_doc_to_items_image_failure_skips_not_raises(tmp_path):
    class _Broken(_FakePicture):
        def get_image(self, doc):
            raise ValueError("boom")

    doc = _FakeDoc([_Broken(1, None)])
    assert parser.doc_to_items(doc, assets_dir=tmp_path) == []


def test_doc_to_items_clears_stale_assets(tmp_path):
    (tmp_path / "deadbeef.png").write_bytes(b"old")
    doc = _FakeDoc([])
    parser.doc_to_items(doc, assets_dir=tmp_path)
    assert not (tmp_path / "deadbeef.png").exists()
```

Note: `_FakePicture` with no caption and OCR unavailable/blank must still produce a ref with empty alt (`![](assets/...)`) — add one test for that:

```python
def test_doc_to_items_empty_description_kept(tmp_path, monkeypatch):
    from center_kb.ingest import images

    monkeypatch.setattr(images, "ocr_image", lambda img: "")
    img = Image.new("RGB", (32, 32), (0, 0, 0))
    doc = _FakeDoc([_FakePicture(3, img)])
    items = parser.doc_to_items(doc, assets_dir=tmp_path)
    assert items[0].text.startswith("![](assets/")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_parser.py -v -k "image or stale"`
Expected: FAIL — `TypeError: doc_to_items() got an unexpected keyword argument 'assets_dir'`

- [ ] **Step 4: Write the implementation**

In `src/center_kb/ingest/parser.py`:

1. Add near the top:

```python
import logging

logger = logging.getLogger("center_kb.ingest.parser")
```

2. In `load_or_parse`, change the cache name and pipeline options. The cache rename invalidates pre-picture caches (they contain no pixels):

```python
    cache = work_dir / "parsed-v2.json"  # v2: includes generated picture images
```

```python
    pipeline_options = PdfPipelineOptions(
        ocr_options=ocr_options,
        generate_picture_images=True,
        images_scale=2.0,
    )
```

3. Change `doc_to_items` signature and add the picture branch:

```python
def doc_to_items(doc, assets_dir: Path | None = None) -> list[DocItem]:
    items: list[DocItem] = []
    if assets_dir is not None and assets_dir.exists():
        for stale in assets_dir.iterdir():  # re-ingest: assets are re-derived
            stale.unlink()
    for item, _level in doc.iterate_items():
        label = _label_value(item)
        page = _page_of(item)
        if label in _HEADING_LABELS:
            heading_level = getattr(item, "level", 1) if label == "section_header" else 1
            items.append(DocItem("heading", item.text, heading_level, page=page))
        elif label == "table":
            md = item.export_to_markdown(doc=doc)
            if md and md.strip():
                items.append(DocItem("table", md, page=page))
        elif label == "picture":
            if assets_dir is None:
                continue
            md = _picture_md(item, doc, assets_dir)
            if md:
                items.append(DocItem("image", md, page=page))
        elif label in _TEXT_LABELS:
            if item.text and item.text.strip():
                items.append(DocItem("text", item.text, page=page))
    return items


def _picture_md(item, doc, assets_dir: Path) -> str | None:
    """One picture → saved asset + markdown ref, or None on any failure.
    A lost image must never abort the ingest."""
    from center_kb.ingest import images

    try:
        img = item.get_image(doc)
        if img is None:
            return None
        try:
            caption = item.caption_text(doc) or ""
        except Exception:
            caption = ""
        ocr_text = "" if caption.strip() else images.ocr_image(img)
        desc = images.resolve_description(caption, ocr_text)
        filename = images.save_asset(img, assets_dir)
        return images.image_ref(desc, filename)
    except Exception as exc:  # noqa: BLE001 — skip the image, keep the text
        logger.warning("picture on page %s skipped: %s", _page_of(item), exc)
        return None
```

- [ ] **Step 5: Run the parser tests**

Run: `.venv/bin/python -m pytest tests/test_parser.py -v`
Expected: PASS (all, old and new)

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/ingest/parser.py tests/test_parser.py
git commit -m "feat: extract PDF pictures as content-addressed assets in doc_to_items"
```

---

### Task 6: sectioner — `image` kind flows to body; page-anchored unit ordering

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py` (`DocItem` line 13–18, `_Node` line 21–28, `SectionUnit` line 31–37, `_build_tree` line 196–349, `build_units` line 360–391, `_units_from_tree` line 394–455)
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Consumes: `DocItem(kind="image", text="![...](assets/...)", page=N)` from Task 5.
- Produces: `SectionUnit` gains `page: int | None = None`; `order_units(units: list[SectionUnit]) -> list[SectionUnit]` (exported, stable page sort); `build_units(...)` returns units already ordered.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_sectioner.py`, matching its existing import style)

```python
def test_image_item_lands_in_section_body():
    items = [
        DocItem("heading", "2.1 Symbols", page=10),
        DocItem("text", "Intro.", page=10),
        DocItem("image", "![VOR](assets/" + "a" * 64 + ".png)", page=10),
    ]
    units = build_units(items)
    unit = next(u for u in units if u.id == "2.1")
    assert "![VOR](assets/" in unit.body_md
    assert unit.body_md.index("Intro.") < unit.body_md.index("![VOR]")


def test_units_ordered_by_heading_page_not_emission_order():
    # docling emitted 2.10 (page 40) before 2.2 (page 20) — layout artifact
    items = [
        DocItem("heading", "2 GENERAL", page=10),
        DocItem("text", "chapter body", page=10),
        DocItem("heading", "2.10 Last topic", page=40),
        DocItem("text", "late body", page=40),
        DocItem("heading", "2.2 Early topic", page=20),
        DocItem("text", "early body", page=20),
    ]
    units = build_units(items)
    ids = [u.id for u in units]
    assert ids.index("2.2") < ids.index("2.10")


def test_order_units_is_stable_and_forward_fills_pages():
    from center_kb.ingest.sectioner import SectionUnit, order_units

    a = SectionUnit(id="1", title="A", chapter="1", body_md="x", tables=[], page=5)
    b = SectionUnit(id="1.1", title="B", chapter="1", body_md="x", tables=[], page=None)
    c = SectionUnit(id="1.2", title="C", chapter="1", body_md="x", tables=[], page=5)
    assert order_units([a, b, c]) == [a, b, c]  # None inherits 5; stable order kept
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sectioner.py -v -k "image_item or ordered or order_units"`
Expected: FAIL — `TypeError: SectionUnit.__init__() got an unexpected keyword argument 'page'` (and/or ordering assertion failure)

- [ ] **Step 3: Write the implementation**

In `src/center_kb/ingest/sectioner.py`:

1. `DocItem` docstring/comment: `kind: str  # "heading" | "text" | "table" | "image"` (image items carry a markdown ref in `text` and flow into the section body like text — no other branch changes needed; verify the `else` branch at line 340–342 already appends them).

2. Add `page` to `_Node` and `SectionUnit`:

```python
@dataclass
class _Node:
    id: str
    title: str
    depth: int
    body: list[str] = field(default_factory=list)
    children: list["_Node"] = field(default_factory=list)
    fallback: bool = False  # id synthesized from an unparsed heading
    page: int | None = None  # page of the heading that opened this node
```

```python
@dataclass
class SectionUnit:
    id: str
    title: str
    chapter: str
    body_md: str
    tables: list[str]
    page: int | None = None
```

3. In `_build_tree`, track a forward-filled page and stamp nodes. At the top of the item loop add:

```python
    last_page: int | None = None
    for item in items:
        if item.page is not None:
            last_page = item.page
```

Both node constructions get the page — the parsed branch:

```python
                node = _Node(id=sid, title=title, depth=depth, page=last_page)
```

and the fallback branch:

```python
                node = _Node(
                    id=sid, title=normalized, depth=parent.depth + 1,
                    fallback=True, page=last_page,
                )
```

4. In `_units_from_tree`, pass the node page through:

```python
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
```

5. Add `order_units` and apply it at both exits of `build_units`:

```python
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
```

In `build_units`, wrap both return paths:

```python
        return order_units(units + _units_from_tree(
            root, max_depth, min_tokens, max_unit_tokens, None
        ))
```

```python
    return order_units(units)
```

- [ ] **Step 4: Run the sectioner tests**

Run: `.venv/bin/python -m pytest tests/test_sectioner.py -v`
Expected: PASS (all, old and new). If an existing test asserts a specific unit order that the page sort legitimately changes, inspect it: only accept changes where the new order matches the pages given in the test's items; otherwise the implementation is wrong.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/sectioner.py tests/test_sectioner.py
git commit -m "feat: page-anchored section ordering; image items flow to body"
```

---

### Task 7: scaffold + mdutils — figure description text in L2

**Files:**
- Modify: `src/center_kb/mdutils.py`, `src/center_kb/ingest/scaffold.py` (L2 emission at lines 64–73)
- Test: `tests/test_mdutils.py`, `tests/test_scaffold.py`

**Interfaces:**
- Produces: `mdutils.extract_image_descs(md: str) -> list[str]` — alt-texts of standalone (non-table-row) `assets/<sha>` image refs, ordered, deduped, blanks dropped. L2 files gain one `Figure: <desc>` paragraph per described figure.
- Consumes: `SectionUnit` from Task 6 (unchanged fields used here).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mdutils.py`:

```python
def test_extract_image_descs_standalone_only_ordered_deduped():
    from center_kb.mdutils import extract_image_descs

    sha_a, sha_b, sha_c = "a" * 64, "b" * 64, "c" * 64
    md = "\n".join([
        f"![Holding pattern](assets/{sha_a}.webp)",
        "Some text.",
        f"| ![VOR](assets/{sha_b}.png) | VOR |",          # table icon: excluded
        f"![](assets/{sha_c}.png)",                        # empty alt: excluded
        f"![Holding pattern](assets/{sha_a}.webp)",        # duplicate: excluded
        "![not an asset](http://x/y.png)",                 # non-asset ref: excluded
    ])
    assert extract_image_descs(md) == ["Holding pattern"]
```

Append to `tests/test_scaffold.py` (reuse the file's existing helper style for building units and calling `scaffold_doc`):

```python
def test_l2_gets_figure_description_text(tmp_path):
    sha = "d" * 64
    unit = SectionUnit(
        id="5.1",
        title="Symbols",
        chapter="5",
        body_md=f"Intro.\n\n![Holding pattern](assets/{sha}.webp)",
        tables=[],
        page=12,
    )
    scaffold_doc(
        [unit], doc_id="doc", title="T", tags=[], revision="r1",
        source_path=None, kb_dir=tmp_path,
    )
    l2 = (tmp_path / "doc" / "ch5-symbols.md").read_text(encoding="utf-8")
    l3 = (tmp_path / "doc" / "ch5-symbols.raw.md").read_text(encoding="utf-8")
    assert "Figure: Holding pattern" in l2
    assert f"![Holding pattern](assets/{sha}.webp)" in l3
    assert f"![Holding pattern](assets/{sha}.webp)" not in l2  # figures stay text-only in L2


def test_table_icon_cell_identical_in_l2_and_l3(tmp_path):
    sha = "e" * 64
    row = f"| ![VOR](assets/{sha}.png) | VOR station |"
    table = "| Symbol | Meaning |\n| --- | --- |\n" + row
    unit = SectionUnit(
        id="5.2", title="Legend", chapter="5",
        body_md=f"See legend.\n\n{table}", tables=[table], page=13,
    )
    scaffold_doc(
        [unit], doc_id="doc", title="T", tags=[], revision="r1",
        source_path=None, kb_dir=tmp_path,
    )
    l2 = (tmp_path / "doc" / "ch5-legend.md").read_text(encoding="utf-8")
    l3 = (tmp_path / "doc" / "ch5-legend.raw.md").read_text(encoding="utf-8")
    assert row in l2 and row in l3        # byte-identical cell in both layers
    assert "Figure: VOR" not in l2        # table icons are not figure lines
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mdutils.py tests/test_scaffold.py -v -k "image_descs or figure or icon_cell"`
Expected: FAIL — `ImportError: cannot import name 'extract_image_descs'`

- [ ] **Step 3: Write the implementation**

In `src/center_kb/mdutils.py` add (near `extract_tables`):

```python
_IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\(assets/[0-9a-f]{64}\.(?:png|webp)\)")


def extract_image_descs(md: str) -> list[str]:
    """Alt-texts of standalone image refs, in order, deduped, blanks dropped.

    Table rows are skipped: table icons already reach L2 inside the copied
    table, byte-identical — they must not also become 'Figure:' lines.
    """
    descs: list[str] = []
    for line in md.splitlines():
        if line.lstrip().startswith("|"):
            continue
        for m in _IMAGE_MD_RE.finditer(line):
            alt = m.group(1).strip()
            if alt and alt not in descs:
                descs.append(alt)
    return descs
```

(`import re` is already present in `mdutils.py`; verify.)

In `src/center_kb/ingest/scaffold.py`, import it and extend L2 emission. Change the import line:

```python
from center_kb.mdutils import count_tokens, extract_image_descs, slugify
```

and inside the unit loop, after the tables block (line 72–73):

```python
            for table in unit.tables:
                l2_lines += [table, ""]
            for desc in extract_image_descs(unit.body_md):
                l2_lines += [f"Figure: {desc}", ""]
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_mdutils.py tests/test_scaffold.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/mdutils.py src/center_kb/ingest/scaffold.py tests/test_mdutils.py tests/test_scaffold.py
git commit -m "feat: figure description text in L2; table icons ride tables"
```

---

### Task 8: CLI wiring + ingest seam test

**Files:**
- Modify: `src/center_kb/cli.py` (the `ingest` command — `doc_to_items` call, currently `items = parser.doc_to_items(doc)`)
- Test: `tests/test_ingest_seam.py`

**Interfaces:**
- Consumes: `doc_to_items(doc, assets_dir=...)` from Task 5.
- Produces: `kb ingest` writes assets to `<kb_dir>/<doc_id>/assets/`.

- [ ] **Step 1: Read the seam test pattern**

Read `tests/test_ingest_seam.py` and `tests/test_ingest_cli.py` to see how `parser.load_or_parse`/`doc_to_items` are stubbed for the CLI.

- [ ] **Step 2: Write the failing test** (append to `tests/test_ingest_seam.py`, adapted to its stubbing style)

The test stubs `load_or_parse` to return a fake doc containing one heading, one text item, and one fake picture (as in Task 5's `_FakePicture`), runs the `ingest` CLI command with `--no-summarize`, then asserts:

```python
def test_ingest_writes_assets_and_l3_ref(...existing fixture args...):
    # ...stub load_or_parse with the fake doc as this file already does...
    # run: kb ingest fake.pdf --id demo --no-summarize (via the existing CLI runner)
    assets = list((kb_dir / "demo" / "assets").iterdir())
    assert len(assets) == 1
    l3 = next((kb_dir / "demo").glob("*.raw.md")).read_text(encoding="utf-8")
    assert f"](assets/{assets[0].name})" in l3
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ingest_seam.py -v -k assets`
Expected: FAIL — no `assets/` directory created

- [ ] **Step 4: Wire the CLI**

In `src/center_kb/cli.py`, in the `ingest` command, change:

```python
    items = parser.doc_to_items(doc)
```

to:

```python
    items = parser.doc_to_items(doc, assets_dir=kb_dir / doc_id / "assets")
```

- [ ] **Step 5: Run the CLI and seam tests**

Run: `.venv/bin/python -m pytest tests/test_ingest_seam.py tests/test_ingest_cli.py tests/test_cli.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/cli.py tests/test_ingest_seam.py
git commit -m "feat: wire asset extraction into kb ingest"
```

---

### Task 9: mdrender — images as blocks and inside table cells

**Files:**
- Modify: `src/center_kb/web/mdrender.py`
- Test: `tests/test_web_mdrender.py`

**Interfaces:**
- Produces: `render()` turns a standalone line `![alt](assets/<sha>.<png|webp>)` into `<img src="/assets/<sha>.<ext>" alt="..." loading="lazy">`, and a table cell whose entire content is such a ref into the same `<img>` tag. Anything not matching the strict sha pattern renders as escaped text exactly as today.
- Consumes: asset URL shape served by Task 10.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_web_mdrender.py`)

```python
def test_render_block_image():
    sha = "a" * 64
    out = render(f"![Holding pattern](assets/{sha}.webp)")
    assert f'<img src="/assets/{sha}.webp" alt="Holding pattern" loading="lazy">' in out
    assert "<p>![" not in out


def test_render_image_in_table_cell():
    sha = "b" * 64
    md = "| Symbol | Meaning |\n| --- | --- |\n" + f"| ![VOR](assets/{sha}.png) | VOR station |"
    out = render(md)
    assert f'<td><img src="/assets/{sha}.png" alt="VOR" loading="lazy"></td>' in out
    assert "<td>VOR station</td>" in out


def test_render_non_asset_image_ref_stays_escaped_text():
    out = render("![x](http://evil/x.png)")
    assert "<img" not in out
    assert "![x](http://evil/x.png)" in out.replace("&quot;", '"')


def test_render_image_alt_is_escaped():
    sha = "c" * 64
    out = render(f'![a"b<c>](assets/{sha}.png)')
    assert 'alt="a&quot;b&lt;c&gt;"' in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_mdrender.py -v -k image`
Expected: FAIL — `<img` not produced

- [ ] **Step 3: Write the implementation**

In `src/center_kb/web/mdrender.py`:

1. Add after the existing regexes (line 15–17):

```python
_IMG_LINE_RE = re.compile(
    r"^!\[([^\]]*)\]\(assets/([0-9a-f]{64}\.(?:png|webp))\)$"
)


def _img_tag(m: re.Match[str]) -> str:
    alt, name = m.group(1), m.group(2)
    return f'<img src="/assets/{name}" alt="{html.escape(alt, quote=True)}" loading="lazy">'
```

2. In `_render_table` (line 43–53), route cells through a helper — replace the `cells = ...` line with:

```python
        cells = "".join(f"<{tag}>{_cell_html(c, terms)}</{tag}>" for c in _cells(row))
```

and add:

```python
def _cell_html(cell: str, terms: set[str]) -> str:
    m = _IMG_LINE_RE.match(cell)
    if m:
        return _img_tag(m)
    return _highlight(cell, terms)
```

3. In `render()`'s line loop, before the heading match (after the table branch, line 78):

```python
        m_img = _IMG_LINE_RE.match(line.strip())
        if m_img:
            flush_para()
            blocks.append(_img_tag(m_img))
            i += 1
            continue
```

4. Update the module docstring's "Supported:" line to include images.

- [ ] **Step 4: Run the mdrender tests**

Run: `.venv/bin/python -m pytest tests/test_web_mdrender.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/mdrender.py tests/test_web_mdrender.py
git commit -m "feat: render asset images in mdrender, blocks and table cells"
```

---

### Task 10: authenticated asset-serving route

**Files:**
- Modify: `src/center_kb/web/ui.py` (`build_routes`, route list at lines 240–248)
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Produces: `GET /assets/{name}` — 200 with image bytes + immutable cache header for a valid, existing sha-named asset; 404 for bad names or missing files; 401 without auth (middleware default — `/assets/` is NOT added to `EXEMPT_PREFIXES`); 503 when the hub is unreachable.
- Consumes: hub layout (`HubHandle.kb_dir`, `HubHandle.federation_dir` from `center_kb/hub.py:24-29`); test fixtures/patterns from `tests/test_web_ui.py`.

- [ ] **Step 1: Read the existing UI test setup**

Read `tests/test_web_ui.py` to reuse its app/client fixtures and hub stubbing.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_web_ui.py`, adapted to its fixture style)

```python
def test_asset_route_serves_png(...fixtures...):
    sha = "a" * 64
    # place a file at <hub_root>/.kb/somedoc/assets/<sha>.png with bytes b"PNGDATA"
    resp = client.get(f"/assets/{sha}.png", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert "immutable" in resp.headers["cache-control"]
    assert resp.content == b"PNGDATA"


def test_asset_route_rejects_bad_names(...fixtures...):
    for bad in ("../../etc/passwd", "x.png", "A" * 64 + ".png", "a" * 64 + ".gif"):
        resp = client.get(f"/assets/{bad}", headers=auth_headers)
        assert resp.status_code == 404


def test_asset_route_missing_file_404(...fixtures...):
    resp = client.get(f"/assets/{'f' * 64}.webp", headers=auth_headers)
    assert resp.status_code == 404


def test_asset_route_requires_auth(...fixtures...):
    resp = client.get(f"/assets/{'a' * 64}.png")  # no token, no cookie
    assert resp.status_code == 401
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_ui.py -v -k asset`
Expected: FAIL — 404 on every request (route absent) including the happy path asserting 200

- [ ] **Step 4: Write the implementation**

In `src/center_kb/web/ui.py`, add `import re` if absent, then inside `build_routes` add the handler and route:

```python
    asset_name_re = re.compile(r"^[0-9a-f]{64}\.(?:png|webp)$")

    async def asset(request: Request) -> Response:
        name = request.path_params["name"]
        if not asset_name_re.match(name):
            return Response("not found", status_code=404)
        hub = api.hub_handle(config)
        if hub is None:
            return Response("hub unreachable", status_code=503)
        for base in (hub.kb_dir, hub.federation_dir):
            if not base.is_dir():
                continue
            # content-addressed name → any hit is THE asset (natural dedupe)
            for path in base.glob(f"**/assets/{name}"):
                media = "image/png" if name.endswith(".png") else "image/webp"
                return Response(
                    path.read_bytes(),
                    media_type=media,
                    headers={"Cache-Control": "private, max-age=31536000, immutable"},
                )
        return Response("not found", status_code=404)
```

and in the returned route list:

```python
        Route("/assets/{name}", asset, methods=["GET"]),
```

Do NOT touch `EXEMPT_PATHS`/`EXEMPT_PREFIXES` in `web/auth.py` — the middleware must keep guarding `/assets/`.

- [ ] **Step 5: Run the web tests**

Run: `.venv/bin/python -m pytest tests/test_web_ui.py tests/test_web_app.py tests/test_web_auth.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/web/ui.py tests/test_web_ui.py
git commit -m "feat: authenticated /assets route serving content-addressed images"
```

---

### Task 11: CONDITIONAL — legend-grounding + in-cell icon injection

**GATE: execute this task ONLY if `docs/superpowers/plans/2026-07-16-poc-picture-findings.md` exists and records that docling emits in-cell `PictureItem`s with usable bboxes AND legend tables keep cell bboxes. Otherwise mark this task skipped (accepted coverage gap per spec §4) and move on.** The docling bbox-access details below follow docling's documented `TableItem.data.table_cells` / `prov[0].bbox` API; if the PoC findings note a different access path, adapt to the findings — they are the ground truth.

**Files:**
- Create: `src/center_kb/ingest/legend.py`
- Modify: `src/center_kb/ingest/parser.py` (`doc_to_items`, `_picture_md`)
- Test: `tests/test_legend.py`

**Interfaces:**
- Consumes: `images.LegendMap`, `images.image_ref`, `images.save_asset` (Tasks 2, 4).
- Produces: `build_legend_map(doc) -> LegendMap`; `inject_cell_icons(doc, assets_dir: Path, legend: LegendMap) -> set[int]` (returns ids of picture items consumed into table cells — `doc_to_items` skips those); `_picture_md` gains a `legend: LegendMap | None` parameter used after caption/OCR.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_legend.py` with fake docling objects (same style as Task 5's fakes, extended with bboxes):

```python
from __future__ import annotations

import pytest

PIL = pytest.importorskip("PIL")
pytest.importorskip("imagehash")
from PIL import Image, ImageDraw

from center_kb.ingest import legend as legend_mod


class _BBox:
    def __init__(self, l, t, r, b):  # noqa: E741
        self.l, self.t, self.r, self.b = l, t, r, b
        self.coord_origin = "TOPLEFT"


class _Prov:
    def __init__(self, page_no, bbox):
        self.page_no = page_no
        self.bbox = bbox


class _Cell:
    def __init__(self, text, bbox, row, col):
        self.text = text
        self.bbox = bbox
        self.start_row_offset_idx = row
        self.start_col_offset_idx = col


class _TableData:
    def __init__(self, cells):
        self.table_cells = cells


def _triangle():
    img = Image.new("RGB", (48, 48), (255, 255, 255))
    ImageDraw.Draw(img).polygon([(24, 4), (4, 44), (44, 44)], fill=(0, 0, 0))
    return img


class _Picture:
    def __init__(self, page, bbox, img):
        self.label = type("L", (), {"value": "picture"})()
        self.prov = [_Prov(page, bbox)]
        self._img = img

    def get_image(self, doc):
        return self._img

    def caption_text(self, doc):
        return ""


class _Table:
    def __init__(self, page, bbox, cells):
        self.label = type("L", (), {"value": "table"})()
        self.prov = [_Prov(page, bbox)]
        self.data = _TableData(cells)


class _Doc:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        return [(i, 0) for i in self._items]


def _legend_doc():
    """A 3-row legend table: icon cells (col 0) + meaning cells (col 1),
    with one picture geometrically inside each icon cell."""
    cells, pics = [], []
    for row in range(3):
        y = 100 + row * 30
        cells.append(_Cell("", _BBox(10, y, 40, y + 28), row, 0))
        cells.append(_Cell(f"Meaning {row}", _BBox(45, y, 200, y + 28), row, 1))
        pics.append(_Picture(5, _BBox(12, y + 2, 38, y + 26), _triangle()))
    table = _Table(5, _BBox(10, 100, 200, 190), cells)
    return _Doc([table] + pics), table, pics


def test_build_legend_map_pairs_icons_with_meanings():
    doc, _, _ = _legend_doc()
    legend = legend_mod.build_legend_map(doc)
    assert len(legend.entries) == 3
    assert legend.match(_triangle()) in {"Meaning 0", "Meaning 1", "Meaning 2"}


def test_inject_cell_icons_writes_ref_into_cell_and_consumes_pictures(tmp_path):
    doc, table, pics = _legend_doc()
    legend = legend_mod.build_legend_map(doc)
    consumed = legend_mod.inject_cell_icons(doc, tmp_path, legend)
    assert len(consumed) == 3
    icon_cells = [c for c in table.data.table_cells if c.start_col_offset_idx == 0]
    for cell in icon_cells:
        assert cell.text.startswith("![Meaning ")
        assert "](assets/" in cell.text and "|" not in cell.text.split("](")[0]
    assert len(list(tmp_path.iterdir())) >= 1  # assets written


def test_no_legend_when_too_few_pairs():
    doc = _Doc([_Table(1, _BBox(0, 0, 10, 10), [_Cell("x", _BBox(0, 0, 5, 5), 0, 0)])])
    assert legend_mod.build_legend_map(doc).entries == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_legend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.ingest.legend'`

- [ ] **Step 3: Write the implementation**

Create `src/center_kb/ingest/legend.py`:

```python
"""Legend-grounding: parse the document's own legend tables into an
icon↔meaning map (phash), and inject in-cell icons into table cells so
they survive markdown export byte-identically in L2 and L3."""
from __future__ import annotations

import logging
from pathlib import Path

from center_kb.ingest import images

logger = logging.getLogger("center_kb.ingest.legend")

MIN_LEGEND_PAIRS = 3  # fewer icon→meaning rows than this = not a legend


def _label_value(item) -> str:
    label = getattr(item, "label", "")
    return getattr(label, "value", None) or str(label)


def _norm(bbox) -> tuple[float, float, float, float] | None:
    """(left, top, right, bottom) with top < bottom regardless of origin."""
    if bbox is None:
        return None
    top, bot = sorted((float(bbox.t), float(bbox.b)))
    return float(bbox.l), top, float(bbox.r), bot


def _inside(outer, inner, pad: float = 2.0) -> bool:
    o, i = _norm(outer), _norm(inner)
    if o is None or i is None:
        return False
    return (
        i[0] >= o[0] - pad and i[2] <= o[2] + pad
        and i[1] >= o[1] - pad and i[3] <= o[3] + pad
    )


def _page_of(item) -> int | None:
    prov = getattr(item, "prov", None)
    return getattr(prov[0], "page_no", None) if prov else None


def _bbox_of(item):
    prov = getattr(item, "prov", None)
    return getattr(prov[0], "bbox", None) if prov else None


def _tables(doc):
    for item, _lvl in doc.iterate_items():
        if _label_value(item) == "table":
            yield item


def _pictures(doc):
    for item, _lvl in doc.iterate_items():
        if _label_value(item) == "picture":
            yield item


def _cell_pairs(doc, table):
    """Yield (picture, containing_cell, meaning_text) for pictures inside
    this table whose row has an adjacent non-empty text cell."""
    cells = list(getattr(getattr(table, "data", None), "table_cells", None) or [])
    tpage, tbbox = _page_of(table), _bbox_of(table)
    for pic in _pictures(doc):
        if _page_of(pic) != tpage or not _inside(tbbox, _bbox_of(pic)):
            continue
        cell = next(
            (c for c in cells if _inside(getattr(c, "bbox", None), _bbox_of(pic))),
            None,
        )
        if cell is None:
            continue
        row = cell.start_row_offset_idx
        meaning = next(
            (
                c.text.strip()
                for c in cells
                if c.start_row_offset_idx == row
                and c.start_col_offset_idx != cell.start_col_offset_idx
                and c.text and c.text.strip()
            ),
            "",
        )
        yield pic, cell, meaning


def build_legend_map(doc) -> images.LegendMap:
    legend = images.LegendMap()
    for table in _tables(doc):
        pairs = [(p, m) for p, _c, m in _cell_pairs(doc, table) if m]
        if len(pairs) < MIN_LEGEND_PAIRS:
            continue
        for pic, meaning in pairs:
            try:
                img = pic.get_image(doc)
                if img is not None:
                    legend.add(img, meaning)
            except Exception as exc:  # noqa: BLE001
                logger.warning("legend icon skipped: %s", exc)
    return legend


def inject_cell_icons(doc, assets_dir: Path, legend: images.LegendMap) -> set[int]:
    """Write each in-cell picture as an asset and put its ref into the cell
    text (identical in L2 and L3 via table copy). Returns id()s of consumed
    picture items so doc_to_items does not emit them a second time."""
    consumed: set[int] = set()
    for table in _tables(doc):
        for pic, cell, meaning in _cell_pairs(doc, table):
            try:
                img = pic.get_image(doc)
                if img is None:
                    continue
                desc = meaning or (legend.match(img) or "")
                filename = images.save_asset(img, assets_dir)
                cell.text = images.image_ref(desc, filename)
                consumed.add(id(pic))
            except Exception as exc:  # noqa: BLE001
                logger.warning("in-cell icon skipped: %s", exc)
    return consumed
```

Then wire it in `src/center_kb/ingest/parser.py` — in `doc_to_items`, when `assets_dir` is set, before the item loop:

```python
    legend = None
    consumed: set[int] = set()
    if assets_dir is not None:
        from center_kb.ingest import legend as legend_mod

        legend = legend_mod.build_legend_map(doc)
        consumed = legend_mod.inject_cell_icons(doc, assets_dir, legend)
```

In the picture branch, skip consumed items and pass the legend:

```python
        elif label == "picture":
            if assets_dir is None or id(item) in consumed:
                continue
            md = _picture_md(item, doc, assets_dir, legend)
            if md:
                items.append(DocItem("image", md, page=page))
```

And in `_picture_md`, add the legend as the third description source:

```python
def _picture_md(item, doc, assets_dir: Path, legend=None) -> str | None:
    ...
        ocr_text = "" if caption.strip() else images.ocr_image(img)
        desc = images.resolve_description(caption, ocr_text)
        if not desc and legend is not None:
            desc = legend.match(img) or ""
    ...
```

Note: the stale-asset cleanup in `doc_to_items` runs before `inject_cell_icons` writes — verify the cleanup stays first in the function.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_legend.py tests/test_parser.py -v`
Expected: PASS (all; Task 5's parser tests must still pass — the fake docs there have no tables, so `build_legend_map` returns an empty map)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/legend.py src/center_kb/ingest/parser.py tests/test_legend.py
git commit -m "feat: legend-grounding and in-cell icon injection"
```

---

### Task 12: full verification — suite, gate, docs

**Files:**
- Possibly modify: `tests-gate/golden/*` (only if the gate diff is explained by this feature), `README.md` (ingest section, one short paragraph)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Run the full unit suite**

Run: `.venv/bin/python -m pytest tests -v`
Expected: PASS. Any failure: fix the implementation, not the test (unless the test asserts pre-feature output shape — e.g. a hardcoded unit order that the page sort corrects — in which case update the test to the new, spec-correct expectation and say so in the commit).

- [ ] **Step 2: Run the regression gate**

Run: `.venv/bin/python -m pytest tests-gate -v`
Expected: PASS. If golden output differs, inspect the diff: acceptable changes are only (a) new `Figure:` lines in L2, (b) image refs in L3, (c) unit order corrected by page anchoring. Regenerate goldens only for those; anything else is a bug.

- [ ] **Step 3: Update README**

Add one short paragraph to the ingest section of `README.md`: images/icons are extracted to `.kb/<doc-id>/assets/<sha256>.<png|webp>`, described only from the source (caption → OCR → legend match, never generated), referenced relatively from L3 (and inline in tables in both layers), with description text in L2 for search.

- [ ] **Step 4: Commit**

```bash
git add README.md tests-gate
git commit -m "docs: document image and icon handling in ingest"
```

---

## Self-Review Notes

- Spec §4 (PoC gate) → Task 1 + Task 11 gate. §5 (extraction/classification/compression/sha) → Tasks 2, 5. §6 (descriptions) → Tasks 3, 4, 5, 11. §7 (placement, table-icon byte-identity) → Task 7. §8 (ordering) → Task 6 (with the documented page-anchor deviation). §9 (render/serve) → Tasks 9, 10. §11 (error handling) → Tasks 3, 5, 11 (warn+skip paths, tested). §12 (testing) → every task + Task 12.
- Determinism: same input bytes → same sha (Task 2 test); Pillow floor pinned in pyproject; encoder-version drift noted in spec §5.
- Type consistency: `DocItem(kind, text, level=0, page=None)` unchanged shape; `SectionUnit.page` added with default `None` so existing constructors keep working; `doc_to_items(doc, assets_dir=None)` backward compatible.
