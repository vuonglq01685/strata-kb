from __future__ import annotations

import json
import logging
from pathlib import Path

from center_kb.ingest.sectioner import (
    DocItem,
    HeadingConfig,
    Part,
    parse_section_id,
)
from center_kb.mdutils import slugify

logger = logging.getLogger("center_kb.ingest.parser")

_HEADING_LABELS = {"section_header", "title"}
_TEXT_LABELS = {"text", "paragraph", "list_item", "formula", "code", "caption"}


def _label_value(item) -> str:
    label = getattr(item, "label", "")
    return getattr(label, "value", None) or str(label)


def _page_of(item) -> int | None:
    prov = getattr(item, "prov", None)
    if prov:
        return getattr(prov[0], "page_no", None)
    return None


def load_or_parse(pdf_path: Path, work_dir: Path):
    try:
        from docling_core.types.doc import DoclingDocument
    except ImportError as exc:
        raise RuntimeError(
            "Docling is not installed. Run: pip install \"center-kb[ingest]\""
        ) from exc

    cache = work_dir / "parsed-v2.json"  # v2: includes generated picture images
    if cache.exists():
        return DoclingDocument.model_validate_json(cache.read_text(encoding="utf-8"))

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    # backend="torch" matches docling's own OCR auto-selection in this
    # install (onnxruntime/easyocr/nemotron are not installed, torch is) —
    # this pins the same engine already in use, not a new one.
    # lang=["en"]: docling's "auto" OCR mode does not forward a configured
    # language to the engine it selects, so this must be set explicitly —
    # otherwise English text is silently OCR'd with the Chinese recognition
    # model, which drops inter-word spaces on Latin-script text.
    #
    # No artifacts_path here: setting it opts the *entire* pipeline out of
    # each model's own default resolution (layout/table models already
    # resolve fine via HF Hub's ~/.cache) and requires every model to be
    # pre-baked under one folder, not just OCR's. The Docker image instead
    # pre-bakes only RapidOCR's own default asset location (see Dockerfile)
    # so this exact engine finds everything without downloading anything.
    ocr_options = RapidOcrOptions(backend="torch", lang=["en"])
    pipeline_options = PdfPipelineOptions(
        ocr_options=ocr_options,
        generate_picture_images=True,
        images_scale=2.0,
    )
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    result = converter.convert(str(pdf_path))
    doc = result.document
    work_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(doc.export_to_dict()), encoding="utf-8")
    return doc


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


def bookmark_ids(pdf_path: Path, config: HeadingConfig | None = None) -> set[str]:
    from pypdf import PdfReader

    ids: set[str] = set()

    def walk(outline) -> None:
        for entry in outline:
            if isinstance(entry, list):
                walk(entry)
            else:
                title = getattr(entry, "title", "") or ""
                parsed = parse_section_id(title, config)
                if parsed:
                    ids.add(parsed[0])

    try:
        reader = PdfReader(str(pdf_path))
        walk(reader.outline)
    except Exception:
        return set()
    return ids


def outline_parts(
    pdf_path: Path, config: HeadingConfig | None = None
) -> list[Part] | None:
    """Extract top-level document parts from the PDF outline.

    A bookmark is a part when its title parses as a chapter/attachment/
    appendix at ANY depth (some PDFs nest chapters under a "TABLE OF
    CONTENTS" entry) and its id has no sub-numbering. Unparsed TOP-LEVEL
    entries become front matter (grouped, before the first match) or
    named back-matter parts. Returns None (→ regex fallback) when there
    is no usable outline.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(pdf_path))
        outline = reader.outline
    except Exception:
        return None

    matched: list[Part] = []
    seen_ids: set[str] = set()
    top_unmatched: list[tuple[str, int]] = []

    def walk(entries, depth: int) -> None:
        for entry in entries:
            if isinstance(entry, list):
                walk(entry, depth + 1)
                continue
            title = " ".join(((getattr(entry, "title", "") or "")).split())
            try:
                page = reader.get_destination_page_number(entry) + 1
            except Exception:
                continue
            parsed = parse_section_id(title, config)
            if parsed and "." not in parsed[0]:
                if parsed[0] not in seen_ids:
                    seen_ids.add(parsed[0])
                    matched.append(Part(parsed[0], parsed[1], page))
            elif depth == 0 and not parsed:
                top_unmatched.append((title, page))

    walk(outline, 0)
    if len(matched) < 2:
        return None

    matched.sort(key=lambda p: p.page)
    first_page = matched[0].page
    front = [(t, pg) for t, pg in top_unmatched if pg < first_page]
    back = [(t, pg) for t, pg in top_unmatched if pg >= first_page]

    parts = list(matched)
    if front:
        parts.append(Part("front-matter", "Front Matter", min(pg for _, pg in front)))
        seen_ids.add("front-matter")
    for title, pg in back:
        pid = slugify(title)[:40].rstrip("-") or "part"
        base, n = pid, 2
        while pid in seen_ids:
            pid, n = f"{base}-{n}", n + 1
        seen_ids.add(pid)
        parts.append(Part(pid, title, pg))
    parts.sort(key=lambda p: p.page)
    return parts


def _is_leaf_unit(uid: str, unit_ids: set[str]) -> bool:
    """True if no other unit in unit_ids is a descendant of uid.

    A unit is a "leaf" (not split any further) when it is the last unit
    along that branch -> every bookmark that is a descendant of it is
    treated as already folded into this unit's body.
    """
    return not any(
        other != uid and other.startswith(uid + ".") for other in unit_ids
    )


def crosscheck(
    unit_ids: set[str], bm_ids: set[str], max_depth: int = 3
) -> list[str]:
    warnings: list[str] = []
    for bm in sorted(bm_ids):
        if bm[0].isdigit() and bm.count(".") + 1 > max_depth:
            continue
        covered = False
        for uid in unit_ids:
            if bm == uid:
                covered = True
            elif bm.startswith(uid + ".") and _is_leaf_unit(uid, unit_ids):
                covered = True
            elif uid.startswith(bm + "."):
                covered = True
            elif uid.startswith(bm + "-"):
                covered = True
            if covered:
                break
        if not covered:
            warnings.append(f"bookmark section '{bm}' not found in the extracted tree")
    return warnings
