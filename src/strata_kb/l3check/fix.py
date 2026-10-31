"""`kb l3 fix apply`: verify AI drafts of L3 units against the PDF, then write.

A draft replaces one unit or a run of consecutive units of a chapter file. It is
checked in a fixed order (replaces, status, tables, contract, words, ids); the
first failure rejects it and nothing is written. Only a draft that passes all
checks touches L3, the manifest, L2, `sections.json`, `_l3check.yaml` and
`_l3fix.yaml`. The AI never confirms: the new units wait for `kb l3 confirm`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from strata_kb import models
from strata_kb.errors import KbError
from strata_kb.ingest import parser
from strata_kb.l3check import (
    detect,
    fixrecord,
    lint,
    report,
    slices,
    spans,
    wordcheck,
)
from strata_kb.l3check.fixrecord import BaselineUnit, FixEntry, L3Fix
from strata_kb.l3check.spans import SpansFile, UnitSpan
from strata_kb.mdutils import (
    HEADING_RE,
    count_tokens,
    extract_image_descs,
    extract_tables,
    section_map,
)

DRAFT_DIR = "l3fix"
FROM_IMAGE_SHARE = 0.30  # --from-image only where this much of the unit is unmatched
EVIDENCE_MAX = 80

_REPLACES = re.compile(r"^<!--\s*replaces:(.*?)-->$")
_HEADING_MARKS = re.compile(r"^(#+)[ \t]", re.MULTILINE)
_UNSAFE_ID = re.compile(r"[/\\]")

Status = Literal["applied", "unchanged", "rejected"]


@dataclass(frozen=True)
class Draft:
    name: str
    replaces: list[str]
    text: str


@dataclass(frozen=True)
class ApplyResult:
    section: str
    status: Status
    reason: str = ""
    new_ids: tuple[str, ...] = ()


class _Reject(KbError):
    """A check failed: the message is the `<check>: <detail>` reason."""


@dataclass(frozen=True)
class _Unit:
    id: str
    title: str
    body: str  # text after the `## ` line, stripped


@dataclass(frozen=True)
class _Target:
    """The replaced run and everything the later checks read about it."""

    kb_dir: Path
    work_dir: Path
    doc_id: str
    manifest: models.Manifest
    data: SpansFile
    ids: list[str]
    file: str
    raw: str
    raw_lines: tuple[int, int]  # [start, end) lines of the run in the raw file
    run: str  # the run as written, normalised
    neighbours: str  # L3 of the other units of the file
    span: UnitSpan  # union span, id = first replaced id
    furniture: list[str]


# --- normalising and loading ---


def _normalise(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip(" \t") for line in lines).strip()


def load_drafts(work_dir: Path, doc_id: str, only: set[str] | None) -> list[Draft]:
    folder = work_dir / doc_id / DRAFT_DIR
    out: list[Draft] = []
    for path in sorted(folder.glob("*.md"), key=lambda p: p.name):
        name = path.name[: -len(".md")]
        if only is not None and name not in only:
            continue
        text = _normalise(path.read_text(encoding="utf-8"))
        head, _, rest = text.partition("\n")
        header = _REPLACES.match(head.strip())
        if header is None:
            out.append(Draft(name, [name], text))
        else:
            out.append(Draft(name, header.group(1).split(), rest.strip()))
    return out


# --- units of a markdown file ---


def _marks(lines: list[str]) -> list[tuple[int, str | None]]:
    """(line index, unit id or None) of every line `section_map` treats as a heading."""
    out: list[tuple[int, str | None]] = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            m = HEADING_RE.match(line.rstrip("\r\n"))
            out.append((i, m.group("sid") if m else None))
    return out


def _units(md: str) -> list[_Unit]:
    lines = md.splitlines()
    marks = _marks(lines)
    out: list[_Unit] = []
    for k, (i, sid) in enumerate(marks):
        m = HEADING_RE.match(lines[i])
        if sid is None or m is None:
            continue
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        body = "\n".join(lines[i + 1 : end]).strip()
        out.append(_Unit(sid, (m.group("title") or "").strip(), body))
    return out


def _locate(text: str, ids: list[str]) -> tuple[int, int] | None:
    """[start, end) lines of the units `ids` when they sit one after another."""
    lines = text.splitlines(keepends=True)
    marks = _marks(lines)
    seen = [sid for _, sid in marks]
    if any(seen.count(sid) != 1 for sid in ids) or ids[0] not in seen:
        return None
    k = seen.index(ids[0])
    if seen[k : k + len(ids)] != ids:
        return None
    last = k + len(ids)
    return marks[k][0], marks[last][0] if last < len(marks) else len(lines)


def _splice(text: str, run: tuple[int, int], block: str) -> str:
    """`text` with lines [start, end) replaced by `block` (no trailing newline)."""
    lines = text.splitlines(keepends=True)
    head, tail = "".join(lines[: run[0]]), "".join(lines[run[1] :])
    return head + block + ("\n\n" + tail if tail else "\n")


# --- the checks ---


def _replaced_rows(
    draft: Draft, manifest: models.Manifest
) -> list[models.SectionEntry]:
    ids = draft.replaces
    if not ids:
        raise _Reject("replaces: no section ids in the header")
    if len(set(ids)) != len(ids):
        raise _Reject(f"replaces: {', '.join(ids)} lists a section twice")
    rows: list[models.SectionEntry] = []
    for sid in ids:
        found = [s for s in manifest.sections if s.id == sid]
        if not found:
            raise _Reject(f"replaces: no section {sid}")
        if len(found) > 1:
            raise _Reject(f"replaces: section {sid} is listed {len(found)} times")
        rows.append(found[0])
    files = {r.file for r in rows}
    if len(files) > 1:
        raise _Reject(f"replaces: {', '.join(ids)} are in different files")
    in_file = [s.id for s in manifest.sections if s.file == rows[0].file]
    at = [in_file.index(sid) for sid in ids]
    if at != list(range(at[0], at[0] + len(at))):
        raise _Reject(f"replaces: {', '.join(ids)} are not consecutive in file order")
    return rows


def _union_span(ids: list[str], file: str, data: SpansFile) -> UnitSpan:
    by_id = {u.id: u for u in data.units}
    found = [by_id.get(sid) for sid in ids]
    if None in found:
        raise _Reject(
            f"replaces: no page span for {ids[found.index(None)]} — re-ingest"
        )
    units = [u for u in found if u is not None]
    pages = [u.page for u in units if u.page is not None]
    ends = [u.end_page or u.page for u in units if (u.end_page or u.page) is not None]
    return UnitSpan(
        id=ids[0],
        file=file,
        chapter=units[0].chapter,
        page=min(pages) if pages else None,
        end_page=max(e for e in ends if e is not None) if ends else None,
    )


def _prepare(
    kb_dir: Path,
    work_dir: Path,
    doc_id: str,
    draft: Draft,
    furniture: dict[int, list[str]],
) -> _Target:
    doc_dir = kb_dir / doc_id
    manifest = models.load_yaml_model(doc_dir / "_manifest.yaml", models.Manifest)
    data = spans.load(work_dir, doc_id)
    if data is None:
        raise _Reject("replaces: no sections.json — re-ingest")
    rows = _replaced_rows(draft, manifest)
    file, ids = rows[0].file, draft.replaces
    raw_path = doc_dir / f"{file}.raw.md"
    if not raw_path.is_file():
        raise _Reject(f"replaces: {file}.raw.md is missing")
    raw = raw_path.read_text(encoding="utf-8")
    run = _locate(raw, ids)
    if run is None:
        raise _Reject(f"replaces: {', '.join(ids)} not found in {file}.raw.md")
    lines = raw.splitlines(keepends=True)
    other = [s.id for s in manifest.sections if s.file == file and s.id not in ids]
    span = _union_span(ids, file, data)
    pages = range(span.page, (span.end_page or span.page) + 1) if span.page else []
    return _Target(
        kb_dir=kb_dir,
        work_dir=work_dir,
        doc_id=doc_id,
        manifest=manifest,
        data=data,
        ids=ids,
        file=file,
        raw=raw,
        raw_lines=run,
        run=_normalise("".join(lines[run[0] : run[1]])),
        neighbours="\n\n".join(
            p for sid in other for p in section_map(raw).get(sid, ())
        ),
        span=span,
        furniture=[text for p in pages for text in furniture.get(p, [])],
    )


def _check_l2(t: _Target) -> None:
    path = t.kb_dir / t.doc_id / f"{t.file}.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if _locate(text, t.ids) is None:
        raise _Reject(f"replaces: {', '.join(t.ids)} not found in {t.file}.md")


def _check_status(t: _Target) -> None:
    busy = [
        s.id for s in t.manifest.sections if s.file == t.file and s.status != "pending"
    ]
    if busy:
        raise _Reject(f"status: {t.file} has sections past pending: {', '.join(busy)}")


def _table_blocks(text: str) -> list[tuple[str, ...]]:
    blocks: list[tuple[str, ...]] = []
    current: list[str] = []
    for line in [*text.split("\n"), ""]:
        if line.lstrip().startswith("|"):
            current.append(line)
        elif current:
            blocks.append(tuple(current))
            current = []
    return blocks


def _clip(text: str) -> str:
    one = " ".join(text.split())
    return one if len(one) <= EVIDENCE_MAX else one[: EVIDENCE_MAX - 1] + "…"


def _check_tables(t: _Target, draft: str) -> None:
    old, new = _table_blocks(t.run), _table_blocks(draft)
    if len(old) != len(new):
        raise _Reject(
            f"tables: the draft has {len(new)} table(s), the L3 has {len(old)}"
        )
    for n, (a, b) in enumerate(zip(old, new, strict=True), 1):
        if a != b:
            bad = next((y for x, y in zip(a, b, strict=False) if x != y), "row count")
            raise _Reject(f"tables: table {n} changed at {_clip(bad)}")


def _check_contract(
    t: _Target, draft: str, ids: list[str], pdf_pages: dict[int, str]
) -> None:
    if not ids:
        raise _Reject("contract: the draft has no ## unit")
    contexts = {
        sid: lint.UnitContext(
            t.span.model_copy(update={"id": sid}),
            sid in t.data.fallback_units,
            t.furniture,
            pdf_pages,
        )
        for sid in ids
    }
    issues = lint.lint_file(draft, contexts)
    if issues:
        i = issues[0]
        raise _Reject(f"contract: §{i.section} {i.rule} line {i.line}: {i.evidence}")


def image_allowed(
    kb_dir: Path, doc_id: str, span: UnitSpan, unit_md: str, pdf_words: list[str]
) -> bool:
    """`--from-image` is for units the PDF text layer cannot verify."""
    check = report.load(kb_dir / doc_id)
    if check is not None and any(
        f.kind == "unverifiable"
        for sec in check.sections
        if sec.id == span.id
        for f in sec.findings
    ):
        return True
    return wordcheck.uncovered_share(unit_md, pdf_words) > FROM_IMAGE_SHARE


def _check_words(
    t: _Target,
    draft: str,
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
    from_image: set[str],
) -> bool:
    """Run the word check; True when `--from-image` skipped it."""
    pdf = wordcheck.pdf_tokens(pdf_pages, furniture, t.span.page, t.span.end_page)
    first = t.ids[0]
    if first in from_image:
        if not image_allowed(t.kb_dir, t.doc_id, t.span, t.run, pdf):
            raise _Reject(
                f"words: --from-image not allowed for {first} (text layer is usable)"
            )
        return True
    issue = wordcheck.check_words(t.run, draft, pdf, t.neighbours, t.furniture)
    if issue is not None:
        raise _Reject(
            f'words: {issue.op}: draft "{issue.draft}" vs original "{issue.original}"'
        )
    return False


def _check_ids(t: _Target, ids: list[str]) -> None:
    taken = {s.id: s.file for s in t.manifest.sections if s.id not in t.ids}
    for sid in ids:
        if sid in taken:
            raise _Reject(f"ids: {sid} is already a section of {taken[sid]}")
        if _UNSAFE_ID.search(sid) or sid in {".", ".."}:
            raise _Reject(f"ids: {sid!r} is not a usable section id")


# --- what changed ---


def _heading_marks(md: str) -> list[int]:
    return [len(m.group(1)) for m in _HEADING_MARKS.finditer(md)]


def _prose_count(md: str) -> int:
    return sum(1 for b in detect._prose_blocks(md) if b is not None)


def _body_words(md: str) -> list[str]:
    body = "\n".join(ln for ln in md.splitlines() if not ln.lstrip().startswith("#"))
    return detect.normalize_words(detect.strip_markdown(body))


def _changes(old_ids: list[str], new_ids: list[str], old: str, new: str) -> list[str]:
    found = {
        "re-id": len(old_ids) == len(new_ids) and old_ids != new_ids,
        "split": len(new_ids) > len(old_ids),
        "merge": len(new_ids) < len(old_ids),
        "heading-level": _heading_marks(old) != _heading_marks(new),
        "join": _prose_count(new) < _prose_count(old),
        "text": _body_words(old) != _body_words(new),
    }
    return [name for name, hit in found.items() if hit]


# --- writing ---


def _atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _atomic_yaml(path: Path, model: models.Manifest) -> None:
    tmp = path.with_name(path.name + ".tmp")
    models.save_yaml_model(tmp, model)
    os.replace(tmp, path)


def _l2_block(units: list[_Unit]) -> str:
    """The L2 skeleton `scaffold_doc` writes for these units."""
    lines: list[str] = []
    for u in units:
        lines += [
            f"## {u.id} {u.title}".rstrip(),
            "",
            f"<!-- TODO:summarize {u.id} -->",
            "",
        ]
        for table in extract_tables(u.body):
            lines += [table, ""]
        for desc in extract_image_descs(u.body):
            lines += [f"Figure: {desc}", ""]
    return "\n".join(lines).rstrip("\n")


def _write_l3_l2_manifest(t: _Target, draft: str, units: list[_Unit]) -> None:
    doc_dir = t.kb_dir / t.doc_id
    _atomic(doc_dir / f"{t.file}.raw.md", _splice(t.raw, t.raw_lines, draft))
    l2_path = doc_dir / f"{t.file}.md"
    l2 = l2_path.read_text(encoding="utf-8")
    l2_run = _locate(l2, t.ids)
    assert l2_run is not None  # _check_l2 ran  # noqa: S101
    _atomic(l2_path, _splice(l2, l2_run, _l2_block(units)))
    rows = [
        models.SectionEntry(
            id=u.id,
            title=u.title,
            file=t.file,
            tokens=models.SectionTokens(l3=count_tokens(u.body)),
        )
        for u in units
    ]
    old = t.manifest.sections
    at = next(i for i, s in enumerate(old) if s.id == t.ids[0])
    kept_before = [s for s in old[:at] if s.id not in t.ids]
    kept_after = [s for s in old[at:] if s.id not in t.ids]
    manifest = t.manifest.model_copy(
        update={"sections": [*kept_before, *rows, *kept_after]}
    )
    _atomic_yaml(doc_dir / "_manifest.yaml", manifest)


def _write_spans(t: _Target, ids: list[str]) -> None:
    new = [t.span.model_copy(update={"id": sid}) for sid in ids]
    units = t.data.units
    at = next(i for i, u in enumerate(units) if u.id == t.ids[0])
    data = t.data.model_copy(
        update={
            "units": [
                *[u for u in units[:at] if u.id not in t.ids],
                *new,
                *[u for u in units[at:] if u.id not in t.ids],
            ],
            "fallback_units": [f for f in t.data.fallback_units if f not in t.ids],
        }
    )
    _atomic(t.work_dir / t.doc_id / spans.FILE_NAME, data.model_dump_json(indent=1))


def _recheck(
    t: _Target,
    ids: list[str],
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
    digests: dict[str, str],
) -> None:
    """Drop the replaced ids' findings and run the detectors on each new unit."""
    doc_dir = t.kb_dir / t.doc_id
    raw = (doc_dir / f"{t.file}.raw.md").read_text(encoding="utf-8")
    pieces = section_map(raw)
    checks: list[report.SectionCheck] = []
    for sid in ids:
        l3 = pieces[sid][0]
        near = "\n\n".join(p for o, ps in pieces.items() if o != sid for p in ps)
        sec = spans.section_input(t.span.model_copy(update={"id": sid}), l3)
        unverified = detect.unverifiable(sec, pdf_pages)
        findings = (
            [unverified]
            if unverified is not None
            else [
                *detect.content_findings(sec, near, pdf_pages, furniture),
                *detect.break_findings(sec, pdf_pages),
            ]
        )
        if findings:
            checks.append(
                report.SectionCheck(id=sid, l3_sha256=digests[sid], findings=findings)
            )
    previous = report.load(doc_dir)
    source = previous.source_sha256 if previous else t.manifest.source_sha256
    fresh = report.L3Check(
        checked_at=report._now(), source_sha256=source, sections=checks
    )
    report.save(doc_dir, report.merge(previous, fresh, {*t.ids, *ids}))


def _record(
    t: _Target,
    ids: list[str],
    changes: list[str],
    by: str,
    verified: bool,
    before: dict[str, str],
    after: dict[str, str],
) -> None:
    doc_dir = t.kb_dir / t.doc_id
    rec = fixrecord.load(doc_dir)
    if rec is None:  # switch turned on after ingest: baseline the doc as it was
        rec = L3Fix(
            baseline={
                s.id: BaselineUnit(file=s.file, l3_sha256=before[s.id])
                for s in t.manifest.sections
                if s.id in before
            }
        )
    at = report._now()
    entries = [
        FixEntry(
            id=sid,
            file=t.file,
            was=",".join(t.ids),
            l3_sha256=after[sid],
            verified=verified,
            by=by,
            at=at,
            changes=changes,
        )
        for sid in ids
    ]
    fixrecord.save(
        doc_dir,
        L3Fix(
            baseline={k: v for k, v in rec.baseline.items() if k not in t.ids},
            sections=[*[e for e in rec.sections if e.id not in t.ids], *entries],
        ),
    )


# --- apply ---


def _apply_one(
    kb_dir: Path,
    work_dir: Path,
    doc_id: str,
    draft: Draft,
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
    assistant: str,
    from_image: set[str],
) -> ApplyResult:
    try:
        t = _prepare(kb_dir, work_dir, doc_id, draft, furniture)
        if draft.text == t.run:
            _draft_file(work_dir, doc_id, draft.name).unlink(missing_ok=True)
            return ApplyResult(draft.name, "unchanged")
        _check_l2(t)
        _check_status(t)
        _check_tables(t, draft.text)
        units = _units(draft.text)
        ids = [u.id for u in units]
        _check_contract(t, draft.text, ids, pdf_pages)
        skipped = _check_words(t, draft.text, pdf_pages, furniture, from_image)
        _check_ids(t, ids)
    except _Reject as why:
        return ApplyResult(draft.name, "rejected", str(why))
    before = slices.current_digests(kb_dir, doc_id)
    _write_l3_l2_manifest(t, draft.text, units)
    _write_spans(t, ids)
    after = slices.current_digests(kb_dir, doc_id)
    _recheck(t, ids, pdf_pages, furniture, after)
    changes = _changes(t.ids, ids, t.run, draft.text)
    _record(t, ids, changes, assistant, not skipped, before, after)
    _draft_file(work_dir, doc_id, draft.name).unlink(missing_ok=True)
    return ApplyResult(draft.name, "applied", new_ids=tuple(ids))


def _draft_file(work_dir: Path, doc_id: str, name: str) -> Path:
    return work_dir / doc_id / DRAFT_DIR / f"{name}.md"


def apply_drafts(
    kb_dir: Path,
    work_dir: Path,
    doc_id: str,
    drafts: list[Draft],
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
    assistant: str,
    from_image: set[str],
) -> list[ApplyResult]:
    """Apply each draft in turn; every one sees the state the previous left."""
    return [
        _apply_one(
            kb_dir, work_dir, doc_id, d, pdf_pages, furniture, assistant, from_image
        )
        for d in drafts
    ]


def render_pages(
    pdf: Path, work_dir: Path, doc_id: str, pages: list[int]
) -> list[Path]:
    """Render PDF pages (1-based) to `<work_dir>/<doc_id>/pages/p<N>.png`."""
    out_dir = work_dir / doc_id / "pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for page in pages:
        if page < 1:
            raise ValueError(f"page {page} is not a page number")
        path = out_dir / f"p{page}.png"
        parser._render_page(pdf, page).save(path)
        paths.append(path)
    return paths
