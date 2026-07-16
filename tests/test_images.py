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
