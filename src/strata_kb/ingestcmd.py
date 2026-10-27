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

from strata_kb import authored, mdutils, models, review
from strata_kb.ingest import parser, pdftext, scaffold, sectioner
from strata_kb.ingest.scaffold import ScaffoldReport
from strata_kb.l3check import detect
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


def l3_check(
    opts: IngestOptions,
    doc,
    units: list[sectioner.SectionUnit],
    notes: sectioner.SectioningNotes,
) -> l3report.L3Check | None:
    """Check the L3 just written against the PDF's text layer and merge the
    result into the previous `_l3check.yaml`. None when the PDF has no
    readable text layer (nothing to compare against). Writes nothing."""
    pdf_pages = pdftext.page_texts(opts.pdf)
    if not pdf_pages:
        return None
    chapters = _chapter_filter(opts.sections)
    checked = [u for u in units if chapters is None or u.chapter in chapters]
    doc_dir = opts.kb_dir / opts.doc_id
    manifest = models.load_yaml_model(doc_dir / "_manifest.yaml", models.Manifest)
    # shortcut: the k-th unit of an id takes the k-th manifest row of that id;
    # an id repeated across chapters on a --sections run may pair wrongly
    slices: dict[str, list[str]] = {}
    raws: dict[str, str] = {}
    for sec, occ in zip(
        manifest.sections, mdutils.heading_occurrences(manifest.sections), strict=True
    ):
        if sec.file not in raws:
            raw = doc_dir / f"{sec.file}.raw.md"
            raws[sec.file] = raw.read_text(encoding="utf-8") if raw.exists() else ""
        slices.setdefault(sec.id, []).append(
            mdutils.slice_section(raws[sec.file], sec.id, occurrence=occ) or ""
        )
    taken: Counter[str] = Counter()
    inputs: list[detect.SectionInput] = []
    for i, unit in enumerate(checked):
        end_page = None
        if unit.page is not None:
            end_page = checked[i + 1].page if i + 1 < len(checked) else max(pdf_pages)
        l3 = slices.get(unit.id, [])
        piece = l3[taken[unit.id]] if taken[unit.id] < len(l3) else ""
        taken[unit.id] += 1
        inputs.append(
            detect.SectionInput(unit.id, unit.chapter, unit.page, end_page, piece)
        )
    found = detect.check_document(
        inputs,
        {u.id: u.title for u in checked},
        pdf_pages,
        parser.furniture_by_page(doc),
        notes,
    )
    digests = l3report.current_digests(opts.kb_dir, opts.doc_id)
    fresh = l3report.L3Check(
        checked_at=review._now(),
        source_sha256=manifest.source_sha256,
        sections=[
            c.model_copy(update={"l3_sha256": digests.get(c.id, c.l3_sha256)})
            for c in found
        ],
    )
    merged = l3report.merge(
        l3report.load(doc_dir), fresh, rechecked={u.id for u in checked}
    )
    live = {s.id for s in manifest.sections}
    return merged.model_copy(
        update={"sections": [s for s in merged.sections if s.id in live]}
    )


def _echo_l3_check(
    check: l3report.L3Check | None,
    opts: IngestOptions,
    echo: Callable[[str], None],
) -> int:
    """Save the check, echo its outcome, return the unconfirmed section count."""
    if check is None:
        echo("L3 check skipped: PDF text layer unreadable")
        return 0
    doc_dir = opts.kb_dir / opts.doc_id
    l3report.save(doc_dir, check)
    pending = l3report.unconfirmed(
        check, l3report.current_digests(opts.kb_dir, opts.doc_id)
    )
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
    flagged = _echo_l3_check(l3_check(opts, doc, units, notes), opts, echo)
    return replace(report, l3_flagged=flagged)
