from __future__ import annotations

import json
from pathlib import Path

from aero_kb.ingest.sectioner import DocItem, parse_section_id

_HEADING_LABELS = {"section_header", "title"}
_TEXT_LABELS = {"text", "paragraph", "list_item", "formula", "code", "caption"}


def _label_value(item) -> str:
    label = getattr(item, "label", "")
    return getattr(label, "value", None) or str(label)


def load_or_parse(pdf_path: Path, work_dir: Path):
    try:
        from docling_core.types.doc import DoclingDocument
    except ImportError as exc:
        raise RuntimeError(
            "Docling chua duoc cai. Chay: pip install -e \".[ingest]\""
        ) from exc

    cache = work_dir / "parsed.json"
    if cache.exists():
        return DoclingDocument.model_validate_json(cache.read_text(encoding="utf-8"))

    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(str(pdf_path))
    doc = result.document
    work_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(doc.export_to_dict()), encoding="utf-8")
    return doc


def doc_to_items(doc) -> list[DocItem]:
    items: list[DocItem] = []
    for item, _level in doc.iterate_items():
        label = _label_value(item)
        if label in _HEADING_LABELS:
            heading_level = getattr(item, "level", 1) if label == "section_header" else 1
            items.append(DocItem("heading", item.text, heading_level))
        elif label == "table":
            md = item.export_to_markdown(doc=doc)
            if md and md.strip():
                items.append(DocItem("table", md))
        elif label in _TEXT_LABELS:
            if item.text and item.text.strip():
                items.append(DocItem("text", item.text))
    return items


def bookmark_ids(pdf_path: Path) -> set[str]:
    from pypdf import PdfReader

    ids: set[str] = set()

    def walk(outline) -> None:
        for entry in outline:
            if isinstance(entry, list):
                walk(entry)
            else:
                title = getattr(entry, "title", "") or ""
                parsed = parse_section_id(title)
                if parsed:
                    ids.add(parsed[0])

    try:
        reader = PdfReader(str(pdf_path))
        walk(reader.outline)
    except Exception:
        return set()
    return ids


def _is_leaf_unit(uid: str, unit_ids: set[str]) -> bool:
    """True neu khong co unit nao khac trong unit_ids la con chau cua uid.

    Mot unit la "leaf" (khong bi tach nho hon) khi no la unit sau cung
    trong cay cho nhanh do -> moi bookmark con chau cua no coi nhu da
    duoc gom vao body cua unit nay.
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
            if covered:
                break
        if not covered:
            warnings.append(f"bookmark section '{bm}' khong thay trong cay da trich")
    return warnings
