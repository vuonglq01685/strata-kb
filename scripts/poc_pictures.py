#!/usr/bin/env python
"""Probe docling picture extraction on a real PDF (manual PoC, not CI).

Usage:
    .venv/bin/python scripts/poc_pictures.py <pdf> [first_page] [last_page]

Prints one line per PictureItem (page, size, caption, inside-table?) and a
summary. Answers the spec §4 gate questions:
  1. large-figure coverage   2. in-cell icon detection   3. legend-table shape
Record the answers in docs/superpowers/plans/2026-07-16-poc-picture-findings.md
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    pdf = Path(sys.argv[1])
    first = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    last = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(
        ocr_options=RapidOcrOptions(backend="torch", lang=["en"]),
        generate_picture_images=True,
        images_scale=2.0,
    )
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    doc = converter.convert(str(pdf)).document

    tables = []
    pictures = []
    for item, _lvl in doc.iterate_items():
        label = getattr(getattr(item, "label", ""), "value", None) or str(
            getattr(item, "label", "")
        )
        prov = getattr(item, "prov", None)
        page = getattr(prov[0], "page_no", None) if prov else None
        if page is None or not (first <= page <= last):
            continue
        if label == "table":
            tables.append((page, getattr(prov[0], "bbox", None)))
        elif label == "picture":
            pictures.append((item, page, getattr(prov[0], "bbox", None)))

    def inside(outer, inner) -> bool:
        if outer is None or inner is None:
            return False
        return (
            inner.l >= outer.l - 2
            and inner.r <= outer.r + 2
            and min(inner.t, inner.b) >= min(outer.t, outer.b) - 2
            and max(inner.t, inner.b) <= max(outer.t, outer.b) + 2
        )

    n_in_table = 0
    for item, page, bbox in pictures:
        img = item.get_image(doc)
        size = f"{img.width}x{img.height}" if img is not None else "NO-PIXELS"
        caption = ""
        try:
            caption = item.caption_text(doc) or ""
        except Exception:  # noqa: BLE001, S110 -- best-effort caption in a manual docling exploration script
            pass
        in_table = any(tp == page and inside(tb, bbox) for tp, tb in tables)
        n_in_table += in_table
        print(f"p{page} {size} in_table={in_table} caption={caption[:60]!r}")
    print(f"\npictures={len(pictures)} in_table={n_in_table} tables={len(tables)}")
    print("cells: inspect a legend table's TableData below")
    for item, _lvl in doc.iterate_items():
        label = getattr(getattr(item, "label", ""), "value", None) or str(
            getattr(item, "label", "")
        )
        if label == "table":
            prov = getattr(item, "prov", None)
            page = getattr(prov[0], "page_no", None) if prov else None
            if page is not None and first <= page <= last:
                cells = getattr(getattr(item, "data", None), "table_cells", [])
                with_bbox = sum(1 for c in cells if getattr(c, "bbox", None))
                print(f"  table p{page}: {len(cells)} cells, {with_bbox} with bbox")


if __name__ == "__main__":
    main()
