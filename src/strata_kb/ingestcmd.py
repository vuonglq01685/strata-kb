# src/strata_kb/ingestcmd.py
"""`kb ingest` orchestration — parse → section → scaffold.

Keeps cli.py a thin wrapper (same pattern as dockersetup/initcmd/publish):
the CLI parses flags and prints; the pipeline lives here.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from strata_kb import authored, models, review
from strata_kb.ingest import parser, pdftext, scaffold, sectioner
from strata_kb.ingest.scaffold import ScaffoldReport
from strata_kb.l3check import detect, spans
from strata_kb.l3check import report as l3report


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
_INGEST_LOGGER = "strata_kb.ingest"


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


def _chapter_filter(sections: str) -> set[str] | None:
    return {s.strip() for s in sections.split(",") if s.strip()} or None


def _section_inputs(
    units: list[sectioner.SectionUnit],
    slices: dict[str, list[str | None]],
    last_page: int | None,
) -> list[detect.SectionInput]:
    """One input per unit: its page span (to the next unit's start page, or
    `last_page`) and its slice of the written L3."""
    taken: Counter[str] = Counter()
    inputs: list[detect.SectionInput] = []
    for i, unit in enumerate(units):
        end_page = None
        if unit.page is not None:
            end_page = units[i + 1].page if i + 1 < len(units) else last_page
        pieces = slices.get(unit.id, [])
        piece = pieces[taken[unit.id]] if taken[unit.id] < len(pieces) else None
        taken[unit.id] += 1
        inputs.append(
            detect.SectionInput(unit.id, unit.chapter, unit.page, end_page, piece or "")
        )
    return inputs


def _write_spans(
    opts: IngestOptions,
    units: list[sectioner.SectionUnit],
    notes: sectioner.SectioningNotes,
    slices: dict[str, list[str | None]],
    last_page: int | None,
) -> None:
    """Save every unit's page span and the fallback ids for the L3 fix."""
    manifest = models.load_yaml_model(
        opts.kb_dir / opts.doc_id / "_manifest.yaml", models.Manifest
    )
    files = {s.id: s.file for s in manifest.sections}
    inputs = _section_inputs(units, slices, last_page)
    spans.save(
        opts.work_dir,
        opts.doc_id,
        spans.SpansFile(
            doc_id=opts.doc_id,
            units=[
                spans.UnitSpan(
                    id=i.id,
                    file=files[i.id],
                    chapter=i.chapter,
                    page=i.page,
                    end_page=i.end_page,
                )
                for i in inputs
                if i.id in files
            ],
            fallback_units=sorted(detect.fallback_findings(inputs, notes)),
        ),
    )


def l3_check(
    opts: IngestOptions,
    doc,  # docling document; untyped like parser.py's
    units: list[sectioner.SectionUnit],
    notes: sectioner.SectioningNotes,
    slices: dict[str, list[str | None]],
    pdf_pages: dict[int, str],
) -> l3report.L3Check | None:
    """Check the L3 just written against the PDF's text layer (`pdf_pages`) and
    merge the result into the previous `_l3check.yaml`. `slices` is the written
    L3 (`l3report.l3_slices`). None when the PDF has no readable text layer
    (nothing to compare against). Writes nothing.

    Every unit is checked, so spans and neighbours are as in a full run; on
    `--sections` only the findings of the re-ingested chapters are kept."""
    if not pdf_pages:
        return None
    chapters = _chapter_filter(opts.sections)
    checked = {u.id for u in units if chapters is None or u.chapter in chapters}
    doc_dir = opts.kb_dir / opts.doc_id
    manifest = models.load_yaml_model(doc_dir / "_manifest.yaml", models.Manifest)
    inputs = _section_inputs(units, slices, max(pdf_pages))
    found = detect.check_document(
        inputs,
        {u.id: u.title for u in units},
        pdf_pages,
        parser.furniture_by_page(doc),
        notes,
    )
    digests = l3report.digest_slices(slices)
    fresh = l3report.L3Check(
        checked_at=review._now(),
        source_sha256=manifest.source_sha256,
        sections=[
            c.model_copy(update={"l3_sha256": digests[c.id]})
            for c in found
            if c.id in checked and c.id in digests
        ],
    )
    merged = l3report.merge(l3report.load(doc_dir), fresh, rechecked=checked)
    return merged.model_copy(
        update={"sections": [s for s in merged.sections if s.id in slices]}
    )


def _echo_l3_check(
    check: l3report.L3Check | None,
    opts: IngestOptions,
    digests: dict[str, str],
    echo: Callable[[str], None],
) -> int:
    """Save the check, echo its outcome, return the unconfirmed section count."""
    if check is None:
        echo("L3 check skipped: PDF text layer unreadable")
        return 0
    doc_dir = opts.kb_dir / opts.doc_id
    l3report.save(doc_dir, check)
    pending = l3report.unconfirmed(check, digests)
    if not pending:
        echo("L3 check: clean")
        return 0
    kinds = Counter(f.kind for s in pending for f in s.findings)
    counts = ", ".join(
        f"{kind} {kinds[kind]}"
        for kind in ("fallback", "order", "content", "break", "unverifiable")
    )
    echo(
        f"L3 check: {len(pending)} section(s) flagged ({counts}) — "
        f"review: kb l3 report {opts.doc_id}"
    )
    return len(pending)


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
    if authored.is_authored(opts.kb_dir, opts.doc_id):
        raise ValueError(authored.refusal_message(opts.doc_id))
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

    chapters = _chapter_filter(opts.sections)
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
    slices = l3report.l3_slices(opts.kb_dir, opts.doc_id)
    pdf_pages = pdftext.page_texts(opts.pdf)
    _write_spans(opts, units, notes, slices, max(pdf_pages) if pdf_pages else None)
    flagged = _echo_l3_check(
        l3_check(opts, doc, units, notes, slices, pdf_pages),
        opts,
        l3report.digest_slices(slices),
        echo,
    )
    return replace(report, l3_flagged=flagged)
