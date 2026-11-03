"""The checks `kb l3 fix apply` runs on a draft before it writes anything.

Each `_check_*` raises `_Reject` with a `<check>: <detail>` reason on the first
failure. Split out of `fix.py`, which prepares the target and writes the result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import zip_longest
from pathlib import Path

from strata_kb import models
from strata_kb.errors import KbError
from strata_kb.l3check import fixrecord, lint, report, slices, wordcheck
from strata_kb.l3check.spans import SpansFile, UnitSpan
from strata_kb.mdutils import section_map, slugify_id

FROM_IMAGE_SHARE = 0.30  # --from-image only where this much of the unit is unmatched
HEADING_MAX_TOKENS = 15  # a body line a draft turns into a heading is at most this long
_HEADING_LINE = re.compile(r"^[ \t]*#{2,4}[ \t]")
EVIDENCE_MAX = 80
_UNSAFE_ID = re.compile(r"[/\\]")
_PART_IDS = frozenset({"appendix", "attachment"})


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


# `![alt](T)` (T keeps any title); read before links so a linked image keeps its alt
_IMAGE_MD = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
# `[text](T)`, `[ref]: T` definitions, <autolinks>; run on text with images blanked
_LINK_TARGET = re.compile(
    r"\[[^\]]*\]\(([^)]*)\)"
    r"|^[ ]{0,3}\[[^\]]+\]:[ \t]*(\S+)"
    r"|<((?:https?|mailto):[^>\s]+)>",
    re.MULTILINE,
)
_NONE = ("(none)", "")


def _link_targets(text: str) -> list[tuple[str, str]]:
    """(target, alt) per image and link in text order; alt is "" for links.
    Images are `!<target>`, so `[![a](img)](url)` yields `url`, then the image."""
    found = [
        (m.start(), (("!" + m.group(2)).strip(), m.group(1).strip()))
        for m in _IMAGE_MD.finditer(text)
    ]
    blanked = _IMAGE_MD.sub(lambda m: " " * len(m[0]), text)
    found += [
        (m.start(), ((m.group(1) or m.group(2) or m.group(3) or "").strip(), ""))
        for m in _LINK_TARGET.finditer(blanked)
    ]
    return [pair for _, pair in sorted(found)]


def _without_images(md: str) -> str:
    """Image syntax out of the word check: its alt is OCR the PDF text layer
    lacks, and `_check_links` already holds each image's target and alt exact."""
    return _IMAGE_MD.sub(" ", md)


def _check_links(t: _Target, draft: str) -> None:
    """Images and links carry content the word check cannot see: the ordered
    (target, alt) pairs must be the same as in the current L3, except that a
    copy of a pair the L3 repeats may go (deleting a repeated block) while one
    stays. Images are content-addressed, so the same image is the same target."""
    old, new = _link_targets(t.run), _link_targets(draft)
    kept: list[tuple[str, str]] = []
    j = 0
    for a in old:
        if j < len(new) and new[j] == a:
            kept.append(a)
            j += 1
        elif old.count(a) < 2 or a not in new:
            kept.append(a)  # not droppable: leave it in so the mismatch below names it
    for a, b in zip_longest(kept, new, fillvalue=_NONE):
        if a == b:
            continue
        if a[0] == b[0]:
            raise _Reject(f'links: {_clip(b[0])} alt "{_clip(b[1])}"')
        raise _Reject(f"links: {_clip(b[0] if b != _NONE else a[0])}")


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


def _heading_lines(lines: list[str]) -> set[int]:
    """Indices of the `##`-`####` heading lines outside a ``` fence."""
    out: set[int] = set()
    fenced = False
    for i, line in enumerate(lines):
        if lint._BACKTICK_FENCE.match(line):
            fenced = not fenced
        elif not fenced and _HEADING_LINE.match(line):
            out.add(i)
    return out


def _garbled(line: str, pdf: list[str]) -> bool:
    """A short line the PDF text layer does not match: a heading with a broken font."""
    words = wordcheck.prose_tokens(line)
    return 0 < len(words) <= HEADING_MAX_TOKENS and (
        wordcheck.uncovered_share(line, pdf) > FROM_IMAGE_SHARE
    )


def _bodies(orig: str, draft: str, pdf: list[str]) -> tuple[str, str]:
    """Both sides without their heading lines. A garbled original body line the
    draft replaces in place with a new heading (one the ingest missed) goes too;
    each new heading takes at most one such line."""
    a, b = orig.split("\n"), draft.split("\n")
    heads_a, heads_b = _heading_lines(a), _heading_lines(b)
    drop = set(heads_a)
    for tag, i1, i2, j1, j2 in SequenceMatcher(
        None, a, b, autojunk=False
    ).get_opcodes():
        if tag != "replace":
            continue
        if any(b[j].strip() and j not in heads_b for j in range(j1, j2)):
            continue  # the draft side is not headings only
        slots = len(heads_b & set(range(j1, j2))) - len(heads_a & set(range(i1, i2)))
        old = [i for i in range(i1, i2) if a[i].strip() and i not in heads_a]
        if old and len(old) <= slots and all(_garbled(a[i], pdf) for i in old):
            drop.update(old)
    return (
        "\n".join(x for i, x in enumerate(a) if i not in drop),
        "\n".join(x for j, x in enumerate(b) if j not in heads_b),
    )


def _word_issue(
    t: _Target, orig: str, draft: str, pdf: list[str]
) -> wordcheck.WordIssue | None:
    return wordcheck.check_words(
        orig, draft, pdf, _without_images(t.neighbours), t.furniture
    )


def _describe(issue: wordcheck.WordIssue) -> str:
    return f'{issue.op}: draft "{issue.draft}" vs original "{issue.original}"'


def _check_image(
    t: _Target, draft: str, pdf_pages: dict[int, str], furniture: dict[int, list[str]]
) -> None:
    """The word check is skipped for the whole draft, so every replaced unit
    must be one the text layer cannot verify, each judged on its own. On a
    usable text layer only headings may come from the image (a broken font on
    a heading line): the draft must fail the word check and its body pass it."""
    by_id = {u.id: u for u in t.data.units}
    pieces = section_map(t.raw)
    usable = []
    for sid in t.ids:
        span = by_id[sid]
        pdf = wordcheck.pdf_tokens(pdf_pages, furniture, span.page, span.end_page)
        if not image_allowed(t.kb_dir, t.doc_id, span, pieces[sid][0], pdf):
            usable.append(sid)
    if not usable:
        return
    refused = f"words: --from-image not allowed for {usable[0]} (text layer is usable"
    pdf = wordcheck.pdf_tokens(pdf_pages, furniture, t.span.page, t.span.end_page)
    orig, new = _without_images(t.run), _without_images(draft)
    if usable != t.ids or _word_issue(t, orig, new, pdf) is None:
        raise _Reject(refused + ")")  # mixed scanned/usable units, or no image needed
    issue = _word_issue(t, *_bodies(orig, new, pdf), pdf)
    if issue is not None:
        raise _Reject(
            f"{refused}; only headings may come from the image): {_describe(issue)}"
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
        _check_image(t, draft, pdf_pages, furniture)
        return True
    pdf = wordcheck.pdf_tokens(pdf_pages, furniture, t.span.page, t.span.end_page)
    issue = _word_issue(t, _without_images(t.run), _without_images(draft), pdf)
    if issue is not None:
        raise _Reject(f"words: {_describe(issue)}")
    return False


def _check_ids(t: _Target, heads: list[tuple[str, str]]) -> None:
    """`heads` is (id, title) of every draft unit."""
    taken = {s.id: s.file for s in t.manifest.sections if s.id not in t.ids}
    for sid, title in heads:
        if sid in taken:
            raise _Reject(f"ids: {sid} is already a section of {taken[sid]}")
        if _UNSAFE_ID.search(sid) or sid in {".", ".."}:
            raise _Reject(f"ids: {sid!r} is not a usable section id")
        if sid not in t.ids and not _numbered_or_slug(sid, title):
            raise _Reject(
                f"ids: {sid!r} is not a section number — a heading the PDF does "
                "not number keeps its current id"
            )


def _numbered_or_slug(sid: str, title: str) -> bool:
    """A new id carries the PDF's numbering, is a part id (`appendix-a`), or is
    the fallback slug of its own title. A bare word is the title's first word
    read as an id."""
    if any(ch.isdigit() for ch in sid) or sid.split("-", 1)[0] in _PART_IDS:
        return True
    slug = slugify_id(title)
    return bool(slug) and (sid == slug or sid.endswith(f"-{slug}"))
