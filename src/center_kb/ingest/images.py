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
