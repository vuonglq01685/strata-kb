"""Image asset handling for ingest: classification, compression,
content-addressed saving, and deterministic descriptions.

Descriptions come only from the source document (caption → OCR) — never
generated. Legend-based matching (`LegendMap` below) is staged infrastructure
and not yet wired into the pipeline; it activates after a per-document PoC
validates docling's in-cell icon detection. sha256 is computed over the
stored (compressed) bytes so the filename is stable and hub verification is
byte-exact.
"""
from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("strata_kb.ingest.images")

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


INK_THRESHOLD = 200  # 8-bit grey level below which a pixel counts as ink
MIN_INK_RATIO = 0.01  # under this, the crop is paper plus scanner speckle


def is_blank(img) -> bool:
    """True when a crop carries no drawing worth keeping.

    Cell crops are taken from a page raster, so a genuinely empty cell still
    yields an image; saving those would fill the KB with white squares.
    """
    grey = img.convert("L")
    ink = sum(grey.histogram()[:INK_THRESHOLD])
    return ink < MIN_INK_RATIO * (grey.width * grey.height)


def _sanitize_alt(text: str) -> str:
    """Alt-text must not break markdown (]) or table cells (|)."""
    cleaned = text.replace("|", " ").replace("[", " ").replace("]", " ")
    return " ".join(cleaned.split())


def image_ref(desc: str, filename: str) -> str:
    return f"![{_sanitize_alt(desc)}](assets/{filename})"


_OCR_ENGINE = None  # lazily-initialized RapidOCR singleton (heavy to build)


def _engine_params() -> dict[str, object]:
    """Pin the exact engine the docling pipeline uses (parser.py:
    backend="torch", lang=["en"]). rapidocr's own default config is
    onnxruntime + Chinese — the Docker image ships torch only, so a bare
    RapidOCR() raises "onnxruntime is not installed". The version/model_type
    pins mirror docling's torch mapping, so this resolves the same weights
    the Dockerfile already pre-fetched."""
    from rapidocr import EngineType

    params: dict[str, object] = {
        "Det.engine_type": EngineType.TORCH,
        "Cls.engine_type": EngineType.TORCH,
        "Rec.engine_type": EngineType.TORCH,
    }
    try:  # older rapidocr has no typings module — keep the engine pin only
        from rapidocr.utils.typings import LangDet, LangRec, ModelType, OCRVersion
    except ImportError:
        return params
    params["Det.lang_type"] = LangDet.EN
    params["Rec.lang_type"] = LangRec.EN
    for stage in ("Det", "Cls", "Rec"):
        params[f"{stage}.ocr_version"] = OCRVersion.PPOCRV4
        params[f"{stage}.model_type"] = ModelType.MOBILE
    return params


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
    """OCR the image crop with RapidOCR, pinned to the pipeline's engine
    (torch + English — see _engine_params).
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
            _OCR_ENGINE = RapidOCR(params=_engine_params())
        out = _OCR_ENGINE(np.asarray(img.convert("RGB")))
        txts = getattr(out, "txts", None) or ()
        return " ".join(t.strip() for t in txts if t and t.strip())
    except Exception as exc:  # noqa: BLE001 — OCR must never abort an ingest
        logger.warning("OCR failed on image: %s", exc)
        return ""


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
