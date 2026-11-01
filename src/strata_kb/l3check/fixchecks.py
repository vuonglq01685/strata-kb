"""The checks `kb l3 fix apply` runs on a draft before it writes anything.

Each `_check_*` raises `_Reject` with a `<check>: <detail>` reason on the first
failure. Split out of `fix.py`, which prepares the target and writes the result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path

from strata_kb import models
from strata_kb.errors import KbError
from strata_kb.l3check import fixrecord, lint, report, slices, wordcheck
from strata_kb.l3check.spans import SpansFile, UnitSpan
from strata_kb.mdutils import section_map

FROM_IMAGE_SHARE = 0.30  # --from-image only where this much of the unit is unmatched
EVIDENCE_MAX = 80
_UNSAFE_ID = re.compile(r"[/\\]")


class _Reject(KbError):
    """A check failed: the message is the `<check>: <detail>` reason."""


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


def _check_outside_edits(t: _Target) -> bool:
    """Refuse a unit changed or removed outside `apply`: its words were never
    checked, so a draft must not launder them. Return True when a replaced unit
    still holds an unconfirmed fix that was not checked against the PDF text."""
    rec = fixrecord.load(t.kb_dir / t.doc_id)
    if rec is None:
        return False
    digests = slices.current_digests(t.kb_dir, t.doc_id)
    for sid, reason in fixrecord.blocked(rec, digests):
        if sid in t.ids and reason in (fixrecord.EDITED, fixrecord.REMOVED):
            raise _Reject(
                f"status: §{sid} was {reason} — run kb l3 confirm or restore it first"
            )
    newest = {e.id: e for e in rec.sections}
    return any(
        (e := newest.get(sid)) is not None
        and not e.verified
        and (e.confirmed is None or e.confirmed.l3_sha256 != digests.get(sid))
        for sid in t.ids
    )


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


# `![alt](T)` / `[text](T)` (T keeps any title), `[ref]: T` definitions, <autolinks>
_LINK_TARGET = re.compile(
    r"(!?)\[[^\]]*\]\(([^)]*)\)"
    r"|^[ ]{0,3}\[[^\]]+\]:[ \t]*(\S+)"
    r"|<((?:https?|mailto):[^>\s]+)>",
    re.MULTILINE,
)


def _link_targets(text: str) -> list[str]:
    return [
        ((m.group(1) or "") + (m.group(2) or m.group(3) or m.group(4) or "")).strip()
        for m in _LINK_TARGET.finditer(text)
    ]


def _check_links(t: _Target, draft: str) -> None:
    """Images and links carry content the word check cannot see: the ordered
    targets must be the same as in the current L3."""
    old, new = _link_targets(t.run), _link_targets(draft)
    for a, b in zip_longest(old, new, fillvalue="(none)"):
        if a != b:
            raise _Reject(f"links: {_clip(b if b != '(none)' else a)}")


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


def _check_image(
    t: _Target, pdf_pages: dict[int, str], furniture: dict[int, list[str]]
) -> None:
    """The word check is skipped for the whole draft, so every replaced unit
    must be one the text layer cannot verify, each judged on its own."""
    by_id = {u.id: u for u in t.data.units}
    pieces = section_map(t.raw)
    for sid in t.ids:
        span = by_id[sid]
        pdf = wordcheck.pdf_tokens(pdf_pages, furniture, span.page, span.end_page)
        if not image_allowed(t.kb_dir, t.doc_id, span, pieces[sid][0], pdf):
            raise _Reject(
                f"words: --from-image not allowed for {sid} (text layer is usable)"
            )


def _check_words(
    t: _Target,
    draft: str,
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
    from_image: set[str],
) -> bool:
    """Run the word check; True when `--from-image` skipped it."""
    if t.ids[0] in from_image:
        _check_image(t, pdf_pages, furniture)
        return True
    pdf = wordcheck.pdf_tokens(pdf_pages, furniture, t.span.page, t.span.end_page)
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
