# src/center_kb/ingestcmd.py
"""`kb ingest` orchestration — parse → section → scaffold.

Keeps cli.py a thin wrapper (same pattern as dockersetup/initcmd/publish):
the CLI parses flags and prints; the pipeline lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from center_kb import models
from center_kb.ingest import parser, scaffold, sectioner
from center_kb.ingest.scaffold import ScaffoldReport


@dataclass
class IngestOptions:
    pdf: Path
    doc_id: str
    tags: str = ""
    revision: str = ""
    sections: str = ""
    kb_dir: Path = Path(".kb")
    work_dir: Path = Path(".kb-work")
    chapter_pattern: str = ""
    appendix_pattern: str = ""
    attachment_pattern: str = ""
    no_bookmarks: bool = False


def run_ingest(
    opts: IngestOptions,
    echo: Callable[[str], None],
    warn: Callable[[str], None],
) -> ScaffoldReport:
    """Parse the PDF, split into sections, write the L3 + L1/L2 scaffold.

    Raises ValueError (invalid doc id / heading config) or RuntimeError
    (parse failure) — the CLI turns both into a red message + exit 1.
    """
    scaffold.validate_doc_id(opts.doc_id)  # before doc_id touches any path
    manifest_path = opts.kb_dir / opts.doc_id / "_manifest.yaml"
    previous = None
    if manifest_path.exists():
        previous = models.load_yaml_model(manifest_path, models.Manifest).ingest
    heading_config = sectioner.resolve_heading_config(
        opts.chapter_pattern, opts.appendix_pattern, opts.attachment_pattern, previous
    )

    doc = parser.load_or_parse(opts.pdf, opts.work_dir / opts.doc_id)
    items = parser.doc_to_items(
        doc, assets_dir=opts.kb_dir / opts.doc_id / "assets"
    )
    parts = (
        None if opts.no_bookmarks else parser.outline_parts(opts.pdf, heading_config)
    )
    if parts:
        echo(f"sectioning: bookmarks ({len(parts)} parts)")
    else:
        echo("sectioning: heading patterns")
    units = sectioner.build_units(items, config=heading_config, parts=parts)

    bm_ids = parser.bookmark_ids(opts.pdf, heading_config)
    if bm_ids:
        for warning in parser.crosscheck({u.id for u in units}, bm_ids):
            warn(warning)

    chapters = {s.strip() for s in opts.sections.split(",") if s.strip()} or None
    tag_list = [t.strip() for t in opts.tags.split(",") if t.strip()]
    return scaffold.scaffold_doc(
        units,
        doc_id=opts.doc_id,
        title=(
            opts.doc_id
            if not hasattr(doc, "name")
            else (getattr(doc, "name", "") or opts.doc_id)
        ),
        tags=tag_list,
        revision=opts.revision,
        source_path=opts.pdf,
        kb_dir=opts.kb_dir,
        chapters=chapters,
        heading_config=heading_config,
        part_titles={p.id: p.title for p in parts} if parts else None,
        used_bookmarks=bool(parts),
    )
