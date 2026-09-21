from pathlib import Path

import pytest

from strata_kb.ingest import pdftext

# Generated once with xhtml2pdf (`docs` extra) from a `<pre>` block using
# /System/Library/Fonts/SFNSMono.ttf copied next to the HTML (xhtml2pdf only
# reads fonts by relative path; Courier New and Andale Mono lack precomposed
# Vietnamese glyphs).
FIXTURE = Path(__file__).parent / "fixtures" / "mono-diagram.pdf"


def _page_box() -> tuple[float, float, float, float]:
    pypdfium2 = pytest.importorskip("pypdfium2")
    pdf = pypdfium2.PdfDocument(str(FIXTURE))
    try:
        width, height = pdf[0].get_size()
    finally:
        pdf.close()
    return (0.0, height, width, 0.0)


def test_mono_grid_keeps_columns_and_diacritics():
    out = pdftext.region_text(FIXTURE, 1, _page_box(), mono=True)
    assert out == (
        "+------+    +------+\n"
        "| Nền  |    | gốc  |\n"
        "+------+    +------+"
    )


def test_flow_text_keeps_diacritics_and_lines():
    out = pdftext.region_text(FIXTURE, 1, _page_box(), mono=False)
    assert out is not None
    lines = out.split("\n")
    assert len(lines) == 3
    assert "Nền" in lines[1] and "gốc" in lines[1]


def test_region_without_text_returns_none():
    # a 1pt sliver in the page corner holds no glyph centres
    assert pdftext.region_text(FIXTURE, 1, (0.0, 1.0, 1.0, 0.0), mono=True) is None
    assert pdftext.region_text(FIXTURE, 1, (0.0, 1.0, 1.0, 0.0), mono=False) is None


def test_missing_inputs_return_none():
    assert pdftext.region_text(None, 1, (0, 10, 10, 0), mono=True) is None
    assert pdftext.region_text(FIXTURE, None, (0, 10, 10, 0), mono=True) is None
    assert pdftext.region_text(FIXTURE, 1, None, mono=True) is None


def test_unreadable_pdf_returns_none_and_warns(tmp_path, caplog):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with caplog.at_level("WARNING", logger="strata_kb.ingest.pdftext"):
        assert pdftext.region_text(bad, 1, (0, 10, 10, 0), mono=True) is None
    assert "pdf text for page 1 skipped" in caplog.text
    assert len(caplog.records) == 1


def test_page_no_below_one_returns_none():
    assert pdftext.region_text(FIXTURE, 0, (0, 10, 10, 0), mono=True) is None
