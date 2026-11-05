"""Where the text a unit is checked against comes from: the PDF text layer, or
the synthetic pages of a Markdown source. Docling stays a lazy import."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from strata_kb import models
from strata_kb.ingest import mdreader, parser, pdftext

SourceKind = Literal["pdf", "md"]


def source_kind(kb_dir: Path, doc_id: str) -> SourceKind:
    """Kind the document was ingested from; manifests without `ingest` are PDF."""
    manifest = models.load_yaml_model(
        kb_dir / doc_id / "_manifest.yaml", models.Manifest
    )
    return manifest.ingest.source_kind if manifest.ingest else "pdf"


def load_context(
    source: Path, work_dir: Path, doc_id: str, kind: SourceKind
) -> tuple[dict[int, str], dict[int, list[str]]]:
    """(text per page, furniture per page) of the source; Markdown has no furniture."""
    if kind == "md":
        return mdreader.md_pages(source.read_text(encoding="utf-8")), {}
    return pdftext.page_texts(source), parser.furniture_by_page(
        parser.load_or_parse(source, work_dir / doc_id)
    )
