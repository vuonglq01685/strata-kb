"""docs/src/build_pdf.py renders the guide PDFs from vendored fonts on any OS."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "docs/src/build_pdf.py"
FONTS = REPO_ROOT / "docs/src/fonts"
FONT_FILES = [
    "LiberationSans-Regular.ttf",
    "LiberationSans-Bold.ttf",
    "LiberationSans-Italic.ttf",
    "LiberationSans-BoldItalic.ttf",
    "LiberationMono-Regular.ttf",
    "LiberationMono-Bold.ttf",
]


def load_build_pdf():
    pytest.importorskip("xhtml2pdf")
    pytest.importorskip("markdown")
    spec = importlib.util.spec_from_file_location("build_pdf", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_sample(tmp_path, monkeypatch, text: str) -> Path:
    bp = load_build_pdf()
    (tmp_path / "sample.vi.md").write_text(text, encoding="utf-8")
    monkeypatch.setattr(bp, "SRC", tmp_path)
    monkeypatch.setattr(bp, "OUT", tmp_path)
    monkeypatch.setitem(bp.TITLES, "sample.vi", ("Mẫu", "Kiểm tra"))
    monkeypatch.chdir(tmp_path)
    return bp.render("sample.vi", "0.0.0", "2026-11-01", bp.font_css(bp.FONT_DIR))


def test_vendored_fonts_present():
    for name in FONT_FILES:
        assert (FONTS / name).is_file(), name
    licence = (FONTS / "LICENSE").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence


def test_every_font_url_is_an_existing_vendored_file():
    bp = load_build_pdf()
    urls = re.findall(r'url\("([^"]+)"\)', bp.font_css(bp.FONT_DIR))
    assert len(urls) == len(FONT_FILES)
    assert sorted(Path(u).name for u in urls) == sorted(FONT_FILES)
    assert all(Path(u).is_file() for u in urls), urls


def test_render_embeds_every_liberation_face(tmp_path, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    text = (
        "# Tiếng Việt\n\nể ả ầ ề ố ế ổ → *nghiêng ể* ***đậm nghiêng ể***"
        " `mã ể ả` **`mã đậm`**\n\n```\nkb get ể ả →\n```\n"
    )
    pdf = render_sample(tmp_path, monkeypatch, text)
    fonts = set()
    for page in pypdf.PdfReader(pdf).pages:
        for font in page["/Resources"]["/Font"].values():
            fonts.add(str(font.get_object()["/BaseFont"]))
    for face in (
        "LiberationSans",
        "LiberationSans-Bold",
        "LiberationSans-Italic",
        "LiberationSans-BoldItalic",
        "LiberationMono",
    ):
        assert any(f.split("+")[-1] == face for f in fonts), (face, fonts)


def test_render_fails_on_missing_glyph_and_keeps_old_pdf(tmp_path, monkeypatch):
    old = tmp_path / "strata-sample.vi.pdf"
    old.write_bytes(b"%PDF old")
    with pytest.raises(SystemExit, match=r"U\+1F642"):
        render_sample(tmp_path, monkeypatch, "Chào 🙂\n")
    assert old.read_bytes() == b"%PDF old"


def test_render_confines_reads_to_font_dir_not_document_path(tmp_path, monkeypatch):
    # xhtml2pdf derives its default read root from the document path through
    # urlsplit, which reads "C:\\..." as scheme "c" on Windows and falls back
    # to the cwd. An explicit policy rooted at FONT_DIR avoids that.
    bp = load_build_pdf()
    seen = {}
    real = bp.pisa.CreatePDF

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(bp.pisa, "CreatePDF", spy)
    render_sample(tmp_path, monkeypatch, "ể →\n")
    assert Path(seen["resource_policy"].base_dir) == bp.FONT_DIR
    assert "path" not in seen


def test_rewrite_links_points_sibling_docs_at_their_pdfs():
    bp = load_build_pdf()
    md = (
        "[child](guide-child.en.md#35-validate) [dev](guide-dev.vi.md) "
        "[arch](architecture.vi.md#6-citations) [same page](#3-daily-work) "
        "[deploy](../deploy-remote-mcp.md#tls) [x](https://example.com/guide-a.en.md)"
    )
    assert bp.rewrite_links(md) == (
        "[child](strata-guide-child.en.pdf) [dev](strata-guide-dev.vi.pdf) "
        "[arch](strata-architecture.vi.pdf) [same page](#3-daily-work) "
        f"[deploy]({bp.DEPLOY_URL}#tls) [x](https://example.com/guide-a.en.md)"
    )


def test_every_sibling_link_in_the_sources_has_a_matching_pdf_name():
    bp = load_build_pdf()
    for name in bp.TITLES:
        text = (REPO_ROOT / "docs/src" / f"{name}.md").read_text(encoding="utf-8")
        rewritten = bp.rewrite_links(text)
        assert not re.search(r"\]\((?:guide-|architecture\.)[^)]*\.md", rewritten), name
        assert "](../deploy-remote-mcp.md" not in rewritten, name
        for target in re.findall(r"\]\((strata-[^)]+\.pdf)\)", rewritten):
            assert target.removesuffix(".pdf").removeprefix("strata-") in bp.TITLES, (
                name,
                target,
            )
