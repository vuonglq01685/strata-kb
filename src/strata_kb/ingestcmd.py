# src/center_kb/ingestcmd.py
"""`kb ingest` orchestration — parse → section → scaffold.

Keeps cli.py a thin wrapper (same pattern as dockersetup/initcmd/publish):
the CLI parses flags and prints; the pipeline lives here.
"""
from __future__ import annotations

import logging
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


_MAX_UNCOVERED_SHOWN = 10
_MAX_NOTES_SHOWN = 20
_INGEST_LOGGER = "center_kb.ingest"


class _ReportHandler(logging.Handler):
    """Routes sectioner/parser/images warnings into the ingest report.
    cli.py never configures logging, so without this they fall to Python's
    lastResort handler: a bare stderr line outside the report."""

    def __init__(self, warn: Callable[[str], None]) -> None:
        super().__init__(level=logging.WARNING)
        self._warn = warn

    def emit(self, record: logging.LogRecord) -> None:
        self._warn(record.getMessage())


def _warn_capped(lines: list[str], label: str, warn: Callable[[str], None]) -> None:
    for line in lines[:_MAX_NOTES_SHOWN]:
        warn(line)
    if len(lines) > _MAX_NOTES_SHOWN:
        warn(f"{len(lines) - _MAX_NOTES_SHOWN} more {label} not shown")


def _page(page: int | None) -> str:
    return f"page {page}" if page else "page unknown"


def _warn_uncovered(missing, warn: Callable[[str], None]) -> None:
    """L3 is the complete-content layer: anything the section tree failed to
    place is content the KB no longer has. Name it rather than lose it."""
    for item in missing[:_MAX_UNCOVERED_SHOWN]:
        warn(f"content never reached L3 ({_page(item.page)}): {item.text[:100]}")
    if len(missing) > _MAX_UNCOVERED_SHOWN:
        warn(
            f"content never reached L3: {len(missing) - _MAX_UNCOVERED_SHOWN} "
            "more item(s) not shown"
        )


def _warn_notes(notes: sectioner.SectioningNotes, warn: Callable[[str], None]) -> None:
    demoted = []
    for d in notes.demoted:
        if d.reason == "repeated":
            known_pages = [p for p in d.pages if p is not None]
            where = f"repeated on {len(known_pages)} pages: " + ", ".join(
                str(p) for p in known_pages
            )
        else:
            where = f"{d.reason}, {_page(d.pages[0] if d.pages else None)}"
        demoted.append(f"heading demoted to text ({where}): '{d.heading}'")
    _warn_capped(demoted, "demoted headings", warn)
    _warn_capped(
        [
            f"fallback id '{f.id}' for unparsed heading '{f.heading}' ({_page(f.page)})"
            for f in notes.fallbacks
        ],
        "fallback ids",
        warn,
    )
    _warn_capped(
        [
            f"heading order inverted on {_page(i.page)}: {i.first_id} before {i.second_id} — "
            + (
                "page re-ordered by layout, check both sections"
                if i.reordered
                else "no layout data, body attribution may be wrong"
            )
            for i in notes.inversions
        ],
        "page inversions",
        warn,
    )
    _warn_capped(
        [
            f"duplicate section id '{d.original}' in part {d.chapter} renamed to '{d.renamed}'"
            for d in notes.duplicates
        ],
        "duplicate ids",
        warn,
    )


def _echo_token_stats(
    report: ScaffoldReport, n_fallback: int, echo: Callable[[str], None]
) -> None:
    s = report.token_stats
    if s is None:
        return
    echo(
        f"sections: {s.n} · L3 tokens min/median/max {s.min}/{s.median}/{s.max} · "
        f"{s.below_300} below 300, {s.above_5000} above 5000 · {n_fallback} fallback ids"
    )


def run_ingest(
    opts: IngestOptions,
    echo: Callable[[str], None],
    warn: Callable[[str], None],
) -> ScaffoldReport:
    """Parse the PDF, split into sections, write the L3 + L1/L2 scaffold.

    Raises ValueError (invalid doc id / heading config) or RuntimeError
    (parse failure) — the CLI turns both into a red message + exit 1.
    """
    handler = _ReportHandler(warn)
    ingest_logger = logging.getLogger(_INGEST_LOGGER)
    ingest_logger.addHandler(handler)
    try:
        return _run_ingest(opts, echo, warn)
    finally:
        ingest_logger.removeHandler(handler)


def _run_ingest(
    opts: IngestOptions,
    echo: Callable[[str], None],
    warn: Callable[[str], None],
) -> ScaffoldReport:
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
        doc, assets_dir=opts.kb_dir / opts.doc_id / "assets", pdf_path=opts.pdf
    )
    parts = (
        None if opts.no_bookmarks else parser.outline_parts(opts.pdf, heading_config)
    )
    if parts:
        echo(f"sectioning: bookmarks ({len(parts)} parts)")
    else:
        echo("sectioning: heading patterns")
    units, notes = sectioner.build_units_with_notes(
        items, config=heading_config, parts=parts
    )

    _warn_notes(notes, warn)
    _warn_uncovered(sectioner.uncovered(items, units), warn)

    bm_ids = parser.bookmark_ids(opts.pdf, heading_config)
    if bm_ids is None:
        warn("PDF outline unreadable — bookmark cross-check skipped")
    elif bm_ids:
        for warning in parser.crosscheck({u.id for u in units}, bm_ids):
            warn(warning)

    chapters = {s.strip() for s in opts.sections.split(",") if s.strip()} or None
    if chapters and not any(u.chapter in chapters for u in units):
        # This is a delete, not a no-op, when the chapter previously
        # existed: scaffold_doc() drops any manifest entry whose stem
        # resolves to a named chapter that produced zero units this run
        # (tests/test_scaffold.py::test_sections_reingest_of_chapter_with_no_units_removes_it).
        # Say so — "nothing written" reads as "nothing happened".
        warn(
            f"--sections {opts.sections} matched no headings this run — "
            "existing files and manifest entries for those chapters were removed"
        )
    tag_list = [t.strip() for t in opts.tags.split(",") if t.strip()]
    report = scaffold.scaffold_doc(
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
    _echo_token_stats(report, len(notes.fallbacks), echo)
    return report
