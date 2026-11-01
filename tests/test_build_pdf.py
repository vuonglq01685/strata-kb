"""docs/src/build_pdf.py renders the guide PDFs from vendored fonts on any OS."""

from __future__ import annotations

import importlib.util
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


def test_font_dir_is_inside_repo():
    assert load_build_pdf().FONT_DIR == FONTS


def test_render_vietnamese_sample_has_no_missing_glyphs(tmp_path, monkeypatch):
    text = "# Tiếng Việt\n\nể ả ầ ề ố ế ổ → `mã ể ả`\n\n```\nkb get ể ả →\n```\n"
    pdf = render_sample(tmp_path, monkeypatch, text)
    assert pdf.read_bytes().startswith(b"%PDF")


def test_render_fails_on_missing_glyph(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match=r"U\+1F642"):
        render_sample(tmp_path, monkeypatch, "Chào 🙂\n")
