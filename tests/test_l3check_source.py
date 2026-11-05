from __future__ import annotations

from strata_kb.l3check import source


def test_source_kind_defaults_to_pdf(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "_manifest.yaml").write_text(
        "id: d\ntitle: D\n", encoding="utf-8"
    )
    assert source.source_kind(tmp_path, "d") == "pdf"


def test_source_kind_reads_md(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "_manifest.yaml").write_text(
        "id: d\ntitle: D\ningest:\n  chapter_pattern: x\n"
        "  appendix_pattern: y\n  source_kind: md\n",
        encoding="utf-8",
    )
    assert source.source_kind(tmp_path, "d") == "md"


def test_load_context_md_pages_no_furniture(tmp_path):
    md = tmp_path / "a.md"
    md.write_text("## 1 Intro\n\nHello **world**.\n", encoding="utf-8")
    pages, furniture = source.load_context(md, tmp_path, "d", "md")
    assert furniture == {}
    assert pages and "Hello world." in pages[1]
