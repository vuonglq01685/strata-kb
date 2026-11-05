"""`kb ingest` on a Markdown source — the MD path of ingestcmd.run_ingest."""

from __future__ import annotations

import hashlib
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest
import yaml

from strata_kb import ingestcmd
from strata_kb.l3check import detect, fixrecord
from strata_kb.l3check import report as l3report

DOC = "md-doc"

SOURCE = """# Handbook

## 1 Scope

Intro text for the scope.

| a | b |
|---|---|
| 1 | 2 |

- first item
- second item

```python
x = 1
```

![logo](logo.png)

## Unnumbered part

Closing words here.
"""


def _png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = zlib.compress(b"\x00\xff\x00\x00")
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", raw)
        + chunk(b"IEND", b"")
    )


def _opts(tmp_path: Path, source: Path, **kw) -> ingestcmd.IngestOptions:
    return ingestcmd.IngestOptions(
        source=source,
        doc_id=kw.pop("doc_id", DOC),
        kb_dir=tmp_path / ".kb",
        work_dir=tmp_path / ".kb-work",
        **kw,
    )


def _run(opts: ingestcmd.IngestOptions):
    warnings: list[str] = []
    report = ingestcmd.run_ingest(opts, echo=lambda _: None, warn=warnings.append)
    return report, warnings


def _md(tmp_path: Path, text: str = SOURCE, name: str = "doc.md") -> Path:
    (tmp_path / "logo.png").write_bytes(_png())
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def test_md_ingest_writes_l3_l2_manifest_spans(tmp_path):
    src = _md(tmp_path)

    report, _ = _run(_opts(tmp_path, src))

    doc_dir = tmp_path / ".kb" / DOC
    assert report.n_sections == 2
    assert all((doc_dir / f).exists() for f in report.files)
    assert any(f.endswith(".raw.md") for f in report.files)
    manifest = yaml.safe_load((doc_dir / "_manifest.yaml").read_text())
    assert manifest["ingest"]["source_kind"] == "md"
    assert manifest["source_sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert manifest["title"] == "Handbook"
    assert (tmp_path / ".kb-work" / DOC / "sections.json").exists()
    assert len(list((doc_dir / "assets").glob("*.png"))) == 1


def test_md_ingest_every_source_word_in_l3(tmp_path):
    src = _md(tmp_path)
    report, _ = _run(_opts(tmp_path, src))
    doc_dir = tmp_path / ".kb" / DOC

    l3 = "\n".join(
        (doc_dir / f).read_text(encoding="utf-8")
        for f in sorted(report.files)
        if f.endswith(".raw.md")
    )
    # the H1 title lives in the manifest; the image target is rewritten to assets/
    body = SOURCE.removeprefix("# Handbook\n").replace("(logo.png)", "()")
    source_words = detect.normalize_words(detect.strip_markdown(body))
    l3_words = iter(detect.normalize_words(detect.strip_markdown(l3)))

    assert all(w in l3_words for w in source_words)  # ordered subsequence


def test_md_ingest_headingless_file_one_unit(tmp_path):
    src = _md(tmp_path, "Plain words only.\n\nA second paragraph.\n", "plain.md")

    report, warnings = _run(_opts(tmp_path, src))

    assert report.n_sections == 1
    assert not any("never reached L3" in w for w in warnings)
    raw = (
        tmp_path / ".kb" / DOC / [f for f in report.files if "raw" in f][0]
    ).read_text()
    assert "Plain words only." in raw and "A second paragraph." in raw


def test_md_ingest_non_utf8_refused_nothing_written(tmp_path):
    src = tmp_path / "bad.md"
    src.write_bytes("## 1 Scope\n\ncaf\xe9\n".encode("latin-1"))

    with pytest.raises(ValueError, match="bad.md is not UTF-8"):
        _run(_opts(tmp_path, src))

    assert not (tmp_path / ".kb").exists()
    assert not (tmp_path / ".kb-work").exists()


def test_md_into_pdf_doc_refused(tmp_path):
    src = _md(tmp_path)
    _run(_opts(tmp_path, src))
    manifest = tmp_path / ".kb" / DOC / "_manifest.yaml"
    data = yaml.safe_load(manifest.read_text())
    del data["ingest"]["source_kind"]  # what a PDF manifest looks like
    manifest.write_text(yaml.safe_dump(data))
    before = _snapshot(tmp_path / ".kb")

    with pytest.raises(ValueError) as err:
        _run(_opts(tmp_path, src))

    assert str(err.value) == (
        f"'{DOC}' was ingested from a PDF — ingest the Markdown under a new --id"
    )
    assert _snapshot(tmp_path / ".kb") == before


def test_pdf_into_md_doc_refused(tmp_path):
    src = _md(tmp_path)
    _run(_opts(tmp_path, src))
    before = _snapshot(tmp_path / ".kb")

    with pytest.raises(ValueError) as err:
        _run(_opts(tmp_path, tmp_path / "other.pdf"))

    assert str(err.value) == (
        f"'{DOC}' was ingested from Markdown — ingest the PDF under a new --id"
    )
    assert _snapshot(tmp_path / ".kb") == before


def test_md_reingest_resets_fix_record(tmp_path):
    src = _md(tmp_path)
    _run(_opts(tmp_path, src))
    doc_dir = tmp_path / ".kb" / DOC
    stem = yaml.safe_load((doc_dir / "_manifest.yaml").read_text())["sections"][0][
        "file"
    ]
    fixrecord.save(
        doc_dir,
        fixrecord.L3Fix(
            sections=[
                fixrecord.FixEntry(id="1", file=stem, l3_sha256="x", by="ai", at="t")
            ]
        ),
    )

    _run(_opts(tmp_path, src))

    rec = fixrecord.load(doc_dir)
    assert rec is not None and rec.sections == []  # entry forgotten
    assert (
        rec.baseline["1"].l3_sha256
        == l3report.digest_slices(l3report.l3_slices(tmp_path / ".kb", DOC))["1"]
    )


def test_md_ingest_authored_refused(tmp_path):
    src = _md(tmp_path)
    _run(_opts(tmp_path, src))
    manifest = tmp_path / ".kb" / DOC / "_manifest.yaml"
    data = yaml.safe_load(manifest.read_text())
    data["authored"] = True
    manifest.write_text(yaml.safe_dump(data))

    with pytest.raises(ValueError, match="authored"):
        _run(_opts(tmp_path, src))


def test_md_ingest_warns_no_bookmarks_and_empty_heading(tmp_path):
    src = _md(tmp_path, "## 1 Empty\n\n## 2 Full\n\ntext\n", "e.md")

    _, warnings = _run(_opts(tmp_path, src, no_bookmarks=True))

    assert "--no-bookmarks has no effect on Markdown" in warnings
    assert "heading with no text: 1" in warnings


def test_md_ingest_without_docling(tmp_path):
    src = _md(tmp_path)
    code = (
        "import sys\n"
        "for m in ('docling', 'pypdfium2', 'PIL', 'rapidocr_onnxruntime'):\n"
        "    sys.modules[m] = None\n"
        "from pathlib import Path\n"
        "from strata_kb import ingestcmd\n"
        f"o = ingestcmd.IngestOptions(source=Path({str(src)!r}), doc_id='nd',\n"
        f"    kb_dir=Path({str(tmp_path / 'kb2')!r}), work_dir=Path({str(tmp_path / 'w2')!r}))\n"
        "ingestcmd.run_ingest(o, echo=lambda _: None, warn=lambda _: None)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "kb2" / "nd" / "_manifest.yaml").exists()
