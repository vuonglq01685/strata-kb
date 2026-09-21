from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from strata_kb.ingest import images, pdftext, tableimages
from strata_kb.ingest.sectioner import (
    DocItem,
    HeadingConfig,
    Part,
    _is_part_root,
    parse_section_id,
)
from strata_kb.mdutils import slugify

logger = logging.getLogger("strata_kb.ingest.parser")

_HEADING_LABELS = {"section_header", "title"}
# L3 must hold the document's complete text, so text extraction is a deny-list,
# not an allow-list: an allow-list silently drops whatever it forgot (footnotes
# carrying normative applicability dates, checkbox captions) and every label
# docling adds later. Only the running page furniture is genuinely not content.
_SKIP_LABELS = {"page_header", "page_footer"}
# Labels a picture's children must NOT be folded into its alt text: they
# keep their own normal emission path (nested picture/table) or are page
# furniture that is emitted nowhere at all.
_NON_FOLDABLE = {"picture", "table"} | _SKIP_LABELS


def _label_value(item) -> str:
    label = getattr(item, "label", "")
    return getattr(label, "value", None) or str(label)


def _page_of(item) -> int | None:
    prov = getattr(item, "prov", None)
    if prov:
        return getattr(prov[0], "page_no", None)
    return None


def _page_height(doc, page: int | None) -> float | None:
    entry = (getattr(doc, "pages", None) or {}).get(page)
    return getattr(getattr(entry, "size", None), "height", None)


def _topleft_box(bbox, page: int | None, doc) -> tableimages.Box | None:
    """Normalize a docling bbox to TOPLEFT so table provenance (BOTTOMLEFT)
    and table cells (TOPLEFT) become comparable. None when the page height
    needed to flip a BOTTOMLEFT box is unknown."""
    if bbox is None:
        return None
    origin = getattr(bbox, "coord_origin", "")
    origin = str(getattr(origin, "value", origin)).upper()
    top, bottom = bbox.t, bbox.b
    if "BOTTOM" in origin:
        height = _page_height(doc, page)
        if height is None:
            return None
        top, bottom = height - bbox.t, height - bbox.b
    if top > bottom:
        top, bottom = bottom, top
    return tableimages.Box(left=bbox.l, top=top, right=bbox.r, bottom=bottom)


def _prov_box(item, doc) -> tuple[int | None, tableimages.Box | None]:
    prov = getattr(item, "prov", None)
    if not prov:
        return None, None
    page = getattr(prov[0], "page_no", None)
    return page, _topleft_box(getattr(prov[0], "bbox", None), page, doc)


def _clean(text: str) -> str:
    """docling separates words with tabs; L3 wants single spaces."""
    return " ".join(text.split())


def _bottomleft_box(item, doc) -> tuple[int | None, pdftext.Box | None]:
    """(page, bbox) in the BOTTOMLEFT frame pypdfium2 uses — docling's own
    PDF provenance frame, so normally a pass-through."""
    prov = getattr(item, "prov", None)
    if not prov:
        return None, None
    page = getattr(prov[0], "page_no", None)
    bbox = getattr(prov[0], "bbox", None)
    if bbox is None:
        return page, None
    origin = getattr(bbox, "coord_origin", "")
    origin = str(getattr(origin, "value", origin)).upper()
    if origin.startswith("TOP"):
        height = _page_height(doc, page)
        if height is None:
            return page, None
        top, bottom = height - bbox.t, height - bbox.b
        if top < bottom:
            top, bottom = bottom, top
        return page, (bbox.l, top, bbox.r, bottom)
    top, bottom = bbox.t, bbox.b
    if top < bottom:
        top, bottom = bottom, top
    return page, (bbox.l, top, bbox.r, bottom)


# Exactly one leading marker + its trailing whitespace, or a bare marker with
# nothing after it. lstrip(chars) would strip a whole *class* of chars, so
# "-40 °C" (a negative number, not a bullet) or "- - nested" (real nesting)
# would lose content past the first marker.
_BULLET_RE = re.compile(r"^[-•*·](?:\s+|$)")


def _code_item(item, doc, pdf_path: Path | None, page, bbox) -> DocItem | None:
    # ponytail: a code line that starts with "## " would end the section in
    # mdutils.slice_section; none in the corpus. Indent fence bodies if it appears.
    raw_page, raw_box = _bottomleft_box(item, doc)
    text = getattr(item, "text", "") or ""
    body = pdftext.region_text(pdf_path, raw_page, raw_box, mono=True) or _clean(text)
    if not body.strip():
        return None
    return DocItem("code", f"```\n{body}\n```", page=page, bbox=bbox)


def _list_item(item, page, bbox) -> DocItem | None:
    text = getattr(item, "text", "") or ""
    text = _BULLET_RE.sub("", _clean(text)).strip()
    if not text:
        return None
    return DocItem("list", f"- {text}", page=page, bbox=bbox)


def _table_cells(item, doc) -> list[tableimages.Cell]:
    cells: list[tableimages.Cell] = []
    for cell in getattr(getattr(item, "data", None), "table_cells", None) or []:
        box = _topleft_box(getattr(cell, "bbox", None), _page_of(item), doc)
        if box is None:
            continue
        cells.append(
            tableimages.Cell(
                row=cell.start_row_offset_idx, col=cell.start_col_offset_idx, box=box
            )
        )
    return cells


def load_or_parse(pdf_path: Path, work_dir: Path):
    try:
        from docling_core.types.doc import DoclingDocument
    except ImportError as exc:
        raise RuntimeError(
            "Docling is not installed. Run: pip install \"strata-kb[ingest]\""
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
    # newline-exempt: docling parse cache under .kb-work, local scratch,
    # never committed or hub-synced.
    cache.write_text(json.dumps(doc.export_to_dict()), encoding="utf-8")
    return doc


def doc_to_items(
    doc, assets_dir: Path | None = None, pdf_path: Path | None = None
) -> list[DocItem]:
    if assets_dir is not None and assets_dir.exists():
        shutil.rmtree(assets_dir)  # re-ingest: assets are re-derived
        assets_dir.mkdir(parents=True)

    # traverse_pictures: docling parents figure labels (axis titles, siting
    # distances, legend text) under their picture node and its default walk
    # skips those children entirely -- 649 text items in ICAO Doc 8896 alone.
    # Folded into the picture's own alt text below rather than emitted as items.
    entries = [
        (item, _label_value(item))
        # some docling versions omit the kwarg; fall back rather than lose the walk
        for item, _level in _iterate(doc)
    ]
    nested_ids: set[int] = set()
    child_text: dict[int, str] = {}
    if assets_dir is not None:
        for item, label in entries:
            if label != "picture":
                continue
            kids = [
                k
                for k in (_resolve(c, doc) for c in (getattr(item, "children", None) or []))
                if k is not None
            ]
            # Nested pictures/tables keep their own normal emission path;
            # page furniture is neither emitted nor folded. Only text-bearing
            # children get folded into the picture's alt text.
            text_kids = [k for k in kids if _label_value(k) not in _NON_FOLDABLE]
            nested_ids.update(id(k) for k in text_kids)
            child_text[id(item)] = " ".join(
                t for t in (_clean(getattr(k, "text", "") or "") for k in text_kids) if t
            )
    tables = [(item, _table_cells(item, doc)) for item, label in entries if label == "table"]
    placements, consumed, placed_boxes = _place_glyphs(entries, tables, doc, assets_dir)
    _recover_missed_glyphs(
        tables, placements, placed_boxes, doc, assets_dir, pdf_path
    )

    items: list[DocItem] = []
    for item, label in entries:
        page, box = _prov_box(item, doc)
        bbox = (box.left, box.top, box.right, box.bottom) if box else None
        if label in _SKIP_LABELS:
            continue
        if id(item) in nested_ids:
            continue
        if label in _HEADING_LABELS:
            heading_level = getattr(item, "level", 1) if label == "section_header" else 1
            items.append(
                DocItem("heading", item.text, heading_level, page=page, bbox=bbox)
            )
        elif label == "table":
            md = item.export_to_markdown(doc=doc)
            if md and md.strip():
                md = tableimages.inject(md, placements.get(id(item), {}))
                items.append(DocItem("table", md, page=page, bbox=bbox))
        elif label == "picture":
            if assets_dir is None:
                continue
            folded = child_text.get(id(item), "")
            md = None if id(item) in consumed else _picture_md(
                item, doc, assets_dir, pdf_path, folded
            )
            if md:
                items.append(DocItem("image", md, page=page, bbox=bbox))
            elif folded:
                # No image came out of this picture (consumed into a table
                # cell, or get_image failed/returned None) but its children
                # were folded for the alt text -- that text must not vanish.
                items.append(DocItem("text", folded, page=page, bbox=bbox))
        elif label == "code":
            code = _code_item(item, doc, pdf_path, page, bbox)
            if code:
                items.append(code)
        elif label == "list_item":
            bullet = _list_item(item, page, bbox)
            if bullet:
                items.append(bullet)
        elif getattr(item, "text", "") and item.text.strip():
            items.append(DocItem("text", _clean(item.text), page=page, bbox=bbox))
    return items


def _iterate(doc):
    try:
        return list(doc.iterate_items(traverse_pictures=True))
    except TypeError:
        logger.warning("docling iterate_items has no traverse_pictures — "
                       "text drawn inside figures will be missing")
        return list(doc.iterate_items())


def _resolve(ref, doc):
    """docling children are RefItems; the stubs in tests hold the node itself.
    None on a bad ref -- a lost figure caption must never abort ingest."""
    resolve = getattr(ref, "resolve", None)
    if not callable(resolve):
        return ref
    try:
        return resolve(doc)
    except Exception as exc:  # noqa: BLE001 -- see docstring
        logger.warning("picture child ref skipped: %s", exc)
        return None


_Placements = dict[int, dict[tuple[int, int], str]]


def _place_glyphs(
    entries, tables, doc, assets_dir: Path | None
) -> tuple[_Placements, set[int], dict[int, dict[tuple[int, int], tableimages.Box]]]:
    """Assign every picture drawn inside a table to that table's cell.

    A glyph column ("Code symbol" in the ICAO SAR signal tables) holds no text
    at all, so docling leaves the column blank and emits the icons as loose
    pictures beside the table. Returns {id(table): {(row, col): markdown}}, the
    ids of the pictures consumed (which must not be emitted again on their
    own), and each placed glyph's box, which sizes the recovery crops.
    """
    placements: _Placements = {}
    consumed: set[int] = set()
    boxes: dict[int, dict[tuple[int, int], tableimages.Box]] = {}
    if assets_dir is None or not tables:
        return placements, consumed, boxes
    for item, label in entries:
        if label != "picture":
            continue
        page, box = _prov_box(item, doc)
        if box is None:
            continue
        for table, cells in tables:
            if not cells or _page_of(table) != page:
                continue
            at = tableimages.locate(box, cells)
            if at is None:
                continue
            md = _picture_md(item, doc, assets_dir)
            if not md:
                break
            slot = placements.setdefault(id(table), {})
            slot[at] = f"{slot[at]} {md}" if at in slot else md
            boxes.setdefault(id(table), {})[at] = box
            consumed.add(id(item))
            break
    return placements, consumed, boxes


def _recover_missed_glyphs(
    tables,
    placements: _Placements,
    placed_boxes: dict[int, dict[tuple[int, int], tableimages.Box]],
    doc,
    assets_dir: Path | None,
    pdf_path: Path | None,
) -> None:
    """Fill the cells of a glyph column the picture detector skipped.

    Docling files hand-drawn strokes ("LLL", "NN", arrows in the ICAO Annex 12
    signal tables) as neither picture nor text, so those cells come back empty
    while their neighbours get an icon. Cropping them out of the page raster
    is the only way L3 ends up with the whole table. Any failure leaves the
    cell empty rather than aborting the ingest.
    """
    if assets_dir is None or pdf_path is None:
        return
    for table, cells in tables:
        placed = placements.get(id(table))
        if not placed or not cells:
            continue
        page, table_box = _prov_box(table, doc)
        if page is None or table_box is None:
            continue
        missing = tableimages.empty_glyph_cells(cells, placed_boxes.get(id(table), {}), table_box)
        if not missing:
            continue
        try:
            raster = _render_page(pdf_path, page)
        except Exception as exc:  # noqa: BLE001 — a lost crop must not stop ingest
            logger.warning("page %s could not be rendered for cell crops: %s", page, exc)
            continue
        for row, col, box in missing:
            md = _crop_md(raster, box, assets_dir, page)
            if md:
                placed[(row, col)] = md


_RENDER_SCALE = 4  # ≈288 dpi: small glyphs stay legible after cropping


def _render_page(pdf_path: Path, page: int):
    import pypdfium2

    pdf = pypdfium2.PdfDocument(str(pdf_path))
    try:
        return pdf[page - 1].render(scale=_RENDER_SCALE).to_pil()
    finally:
        pdf.close()


def _crop_md(raster, box: tableimages.Box, assets_dir: Path, page: int) -> str | None:
    """Crop one cell out of the page raster; None when it holds no drawing."""
    try:
        crop = raster.crop(
            (
                int(box.left * _RENDER_SCALE),
                int(box.top * _RENDER_SCALE),
                int(box.right * _RENDER_SCALE),
                int(box.bottom * _RENDER_SCALE),
            )
        )
        if crop.width < 2 or crop.height < 2 or images.is_blank(crop):
            return None
        return images.image_ref(images.resolve_description("", images.ocr_image(crop)),
                                images.save_asset(crop, assets_dir))
    except Exception as exc:  # noqa: BLE001 -- cell crop best-effort, page rendering continues without it
        logger.warning("cell crop on page %s skipped: %s", page, exc)
        return None


def _picture_md(
    item, doc, assets_dir: Path, pdf_path: Path | None = None, child_text: str = ""
) -> str | None:
    """One picture → saved asset + markdown ref, or None on any failure.
    A lost image must never abort the ingest.

    Alt text: the caption, when there is one, always leads -- but a caption
    must not make the text drawn INSIDE the picture (axis titles, siting
    distances) disappear, since nothing else in L3 carries it and
    sectioner.uncovered() cannot see the loss. So that "inside" text is
    folded in right after the caption instead of being discarded.

    "Inside" text, first source that yields anything: the PDF text layer
    under the picture (correct diacritics and order, floored by
    MIN_OCR_CHARS so a stray one-character figure number cannot win); else
    the text cells docling nested under the picture (tabs and split
    glyphs, but still searchable). When there is neither a caption nor
    inside text, fall back to OCR of the crop.
    """
    try:
        img = item.get_image(doc)
        if img is None:
            return None
        try:
            caption = _clean(item.caption_text(doc) or "")
        except Exception:  # noqa: BLE001 -- caption best-effort, image itself is still saved
            caption = ""
        page, box = _bottomleft_box(item, doc)
        text_layer = _clean(pdftext.region_text(pdf_path, page, box, mono=False) or "")
        inside = images.resolve_description("", text_layer) or child_text
        desc = f"{caption} {inside}".strip() if inside else caption
        if not desc:
            desc = images.resolve_description("", images.ocr_image(img))
        filename = images.save_asset(img, assets_dir)
        return images.image_ref(desc, filename)
    except Exception as exc:  # noqa: BLE001 — skip the image, keep the text
        logger.warning("picture on page %s skipped: %s", _page_of(item), exc)
        return None


def bookmark_ids(pdf_path: Path, config: HeadingConfig | None = None) -> set[str] | None:
    """Section ids named by the PDF outline. None when the outline cannot be
    read at all (missing/corrupt file) — the caller must say the cross-check
    was skipped; an empty set means a readable PDF with no usable outline."""
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
    except Exception as exc:  # noqa: BLE001 -- see docstring: None means "outline unreadable", not a crash
        logger.debug("outline unreadable for %s: %s", pdf_path, exc)
        return None
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
    except Exception:  # noqa: BLE001 -- see docstring: None means "no usable outline", not a crash
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
                page_index = reader.get_destination_page_number(entry)
            except Exception as exc:  # noqa: BLE001 -- one bad bookmark must not abort the whole outline walk
                logger.debug("bookmark '%s' skipped — bad destination: %s", title, exc)
                continue
            if page_index is None:  # pypdf: destination without a page number
                logger.debug("bookmark '%s' skipped — no destination page", title)
                continue
            page = page_index + 1
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


# A numeric unit id, optionally carrying a duplicate-rename suffix ("5.3-2").
# Fallback slugs ("5.6-commentary") never match: they have their own warning.
_NUMERIC_UNIT_RE = re.compile(r"^\d+(?:\.\d+)+(?:-\d+)?$")


def _parent_id(sid: str) -> str:
    return sid.rsplit(".", 1)[0]


def _missing_bookmarks(unit_ids: set[str], bm_ids: set[str], max_depth: int) -> list[str]:
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
            elif uid.startswith(bm + "-") and _is_part_root(bm):
                # appendix-3 is covered by appendix-3-2.1; a numeric bookmark
                # is NOT covered by a fallback child like 5.6-commentary
                covered = True
            if covered:
                break
        if not covered:
            warnings.append(f"bookmark section '{bm}' not found in the extracted tree")
    return warnings


def _units_outside_outline(unit_ids: set[str], bm_ids: set[str]) -> list[str]:
    """Numeric units the outline does not name, judged only at levels the
    outline enumerates: a unit is extra when some bookmark shares its
    parent. An outline that stops at chapters says nothing about 5.x.
    A unit that is itself a strict ancestor of some bookmark is also
    exempt: bookmarks {5.1, 5.3.2} prove unit 5.3 exists even though no
    bookmark equals it — the outline just skipped a level on that branch."""
    bm_parents = {_parent_id(bm) for bm in bm_ids if _NUMERIC_UNIT_RE.match(bm)}
    return [
        f"section '{uid}' not in the PDF outline"
        for uid in sorted(unit_ids)
        if _NUMERIC_UNIT_RE.match(uid)
        and uid not in bm_ids
        and _parent_id(uid) in bm_parents
        and not any(bm.startswith(uid + ".") for bm in bm_ids)
    ]


def crosscheck(
    unit_ids: set[str], bm_ids: set[str], max_depth: int = 3
) -> list[str]:
    """Both directions of the outline cross-check (phase-1 spec §4.3:
    'section thiếu/thừa'): bookmarks no unit covers, then units the
    outline does not name."""
    return _missing_bookmarks(unit_ids, bm_ids, max_depth) + _units_outside_outline(
        unit_ids, bm_ids
    )
