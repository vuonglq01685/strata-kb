"""L3 fidelity detection over strings: L3 text against the PDF's text layer.

Pure functions, no PDF or file I/O. Words are compared after normalisation;
a word counts as covered when any SHINGLE-word window containing it occurs on
the other side, so reordering of a few words is tolerated but dropped or
garbled stretches are not.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass

from strata_kb import quality
from strata_kb.ingest.sectioner import SectioningNotes, _is_part_root
from strata_kb.l3check.report import Finding, SectionCheck

SHINGLE = 4  # words per shingle
MIN_RUN = 5  # shortest missing/extra run reported
SNIPPET_WORDS = 25  # evidence cap
TERMINAL = '.!?:;…)"”’]'  # a paragraph ending in one of these ended on purpose
JOIN_WORDS = 4  # words taken from each side of a suspected paragraph break

_HYPHEN_BREAK = re.compile(r"(\w)-[^\S\n]*\n\s*(\w)")
_WORD = re.compile(r"[^\W_]+")
_FENCE = re.compile(r"^[ \t]*(```|~~~).*$", re.MULTILINE)
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
_TABLE_SEPARATOR = re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t:|-]*$", re.MULTILINE)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BLOCK_SPLIT = re.compile(r"\n[ \t]*\n")
_FENCED = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.MULTILINE | re.DOTALL)
_NON_PROSE = re.compile(r"[ \t]*(#|\||!\[|[-*+][ \t]|\d+[.)][ \t])")
_SUBHEADING = re.compile(r"^### (\S+)", re.MULTILINE)
_EMPHASIS = re.compile(r"\*+|(?<!\w)_+|_+(?!\w)")


@dataclass(frozen=True)
class SectionInput:
    id: str
    chapter: str
    page: int | None  # start page (SectionUnit.page)
    end_page: int | None  # last page of the span (next section's start, or doc's last)
    l3: str  # the section's L3 slice as written


def normalize_words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _WORD.findall(_HYPHEN_BREAK.sub(r"\1\2", folded))


def strip_markdown(md: str) -> str:
    md = _FENCE.sub("", md)
    md = _TABLE_SEPARATOR.sub("", md)
    md = _HEADING.sub("", md)
    md = _IMAGE.sub(r"\1", md)
    md = _LINK.sub(r"\1", md)
    return _EMPHASIS.sub("", md).replace("|", " ")


def _page_words(text: str, furniture: list[str]) -> list[str]:
    """Normalised page words with each furniture string removed once."""
    words = normalize_words(text)
    for line in furniture:
        needle = normalize_words(line)
        for i in range(len(words) - len(needle) + 1):
            if needle and words[i : i + len(needle)] == needle:
                del words[i : i + len(needle)]
                break
    return words


def _shingles(words: list[str]) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def _uncovered_runs(words: list[str], other: list[str]) -> list[tuple[int, list[str]]]:
    """(start index, words) of maximal runs of >= MIN_RUN words not covered by `other`."""
    if len(words) < SHINGLE or len(other) < SHINGLE:
        vocabulary = set(other)
        covered = [w in vocabulary for w in words]
    else:
        known = _shingles(other)
        covered = [False] * len(words)
        for i in range(len(words) - SHINGLE + 1):
            if tuple(words[i : i + SHINGLE]) in known:
                covered[i : i + SHINGLE] = [True] * SHINGLE
    runs: list[tuple[int, list[str]]] = []
    start = 0
    for i, ok in enumerate([*covered, True]):  # sentinel closes a trailing run
        if not ok:
            continue
        if i - start >= MIN_RUN:
            runs.append((start, words[start:i]))
        start = i + 1
    return runs


def _span_pages(sec: SectionInput, pdf_pages: dict[int, str]) -> list[int]:
    if sec.page is None:
        return []
    end = sec.end_page if sec.end_page is not None else sec.page
    return [p for p in range(sec.page, end + 1) if p in pdf_pages]


def _snippet(run: list[str]) -> str:
    return " ".join(run[:SNIPPET_WORDS])


def content_findings(
    sec: SectionInput,
    l3_neighbours: str,
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
) -> list[Finding]:
    pages = _span_pages(sec, pdf_pages)
    if not pages:
        return []
    # one word list over the whole span, so a run is not cut at a page break
    span_words: list[str] = []
    word_pages: list[int] = []
    for p in pages:
        words = _page_words(pdf_pages[p], furniture.get(p, []))
        span_words += words
        word_pages += [p] * len(words)
    l3_words = normalize_words(strip_markdown(sec.l3))
    present = l3_words + normalize_words(strip_markdown(l3_neighbours))
    findings = [
        Finding(kind="content", page=word_pages[start], evidence={"pdf": _snippet(run)})
        for start, run in _uncovered_runs(span_words, present)
    ]
    findings += [
        Finding(kind="content", page=sec.page, evidence={"l3": _snippet(run)})
        for _, run in _uncovered_runs(l3_words, span_words)
    ]
    return findings


def unverifiable(sec: SectionInput, pdf_pages: dict[int, str]) -> Finding | None:
    """A finding when no page of the span has a text layer (scanned pages)."""
    pages = _span_pages(sec, pdf_pages)
    if not pages or any(pdf_pages[p].strip() for p in pages):
        return None
    return Finding(kind="unverifiable", page=sec.page)


def _find_run(stream: list[str], needle: list[str], start: int = 0) -> int:
    """Index of the first contiguous occurrence of `needle` in `stream`, else -1."""
    n = len(needle)
    for i in range(start, len(stream) - n + 1):
        if stream[i : i + n] == needle:
            return i
    return -1


def _prose_blocks(l3: str) -> list[str | None]:
    """Blank-line-separated blocks; None stands for a non-prose block (heading,
    table, fence, image, list item), so a pair across it is never adjacent."""
    blocks = _BLOCK_SPLIT.split(_FENCED.sub("\n\n", l3))
    return [None if not b.strip() or _NON_PROSE.match(b) else b.strip() for b in blocks]


def break_findings(sec: SectionInput, pdf_pages: dict[int, str]) -> list[Finding]:
    """Paragraph split mid-sentence in L3 where the PDF text runs on unbroken."""
    stream: list[str] = []
    for p in _span_pages(sec, pdf_pages):
        stream += normalize_words(pdf_pages[p])
    findings: list[Finding] = []
    blocks = _prose_blocks(sec.l3)
    for first, second in zip(blocks, blocks[1:], strict=False):
        if first is None or second is None or first[-1] in TERMINAL:
            continue
        tail = normalize_words(strip_markdown(first))[-JOIN_WORDS:]
        head = normalize_words(strip_markdown(second))[:JOIN_WORDS]
        if len(tail) < 2 or len(head) < 2 or _find_run(stream, tail + head) < 0:
            continue
        evidence = {"l3": " ".join(tail), "next": " ".join(head)}
        evidence["pdf"] = " ".join(tail + head)
        findings.append(Finding(kind="break", page=sec.page, evidence=evidence))
    return findings


def enclosing_unit(sections: list[SectionInput]) -> dict[str, str]:
    """Any section id, folded `### <id>` subsections included, -> its unit id."""
    owner = {sec.id: sec.id for sec in sections}
    for sec in sections:
        for sid in _SUBHEADING.findall(sec.l3):
            owner.setdefault(sid, sec.id)
    return owner


def _add(out: dict[str, list[Finding]], sid: str, finding: Finding) -> None:
    if finding not in out.setdefault(sid, []):
        out[sid].append(finding)


def _title_positions(
    sections: list[SectionInput], titles: dict[str, str], pdf_pages: dict[int, str]
) -> list[tuple[str, int]]:
    """(section id, global word index of its title) for each title found from
    its start page on, in section order."""
    stream: list[str] = []
    page_start: dict[int, int] = {}
    for p in sorted(pdf_pages):
        page_start[p] = len(stream)
        stream += normalize_words(pdf_pages[p])
    pages = sorted(page_start)
    located: list[tuple[str, int]] = []
    for sec in sections:
        words = normalize_words(titles.get(sec.id, ""))
        if sec.page is None or len(words) < 2:
            continue
        idx = bisect_left(pages, sec.page)
        start = page_start[pages[idx]] if idx < len(pages) else len(stream)
        pos = _find_run(stream, words, start)
        if pos >= 0:
            located.append((sec.id, pos))
    return located


def order_findings(
    sections: list[SectionInput],
    titles: dict[str, str],
    pdf_pages: dict[int, str],
    notes: SectioningNotes,
) -> dict[str, list[Finding]]:
    out: dict[str, list[Finding]] = {}
    prev: SectionInput | None = None
    for sec in sections:
        if sec.page is None:
            continue
        if prev is not None and prev.page is not None and sec.page < prev.page:
            finding = Finding(kind="order", page=sec.page, evidence={"other": prev.id})
            _add(out, sec.id, finding)
        prev = sec
    by_id = {sec.id: sec for sec in sections}
    located = _title_positions(sections, titles, pdf_pages)
    for (prev_id, prev_pos), (sid, pos) in zip(located, located[1:], strict=False):
        if pos < prev_pos:
            finding = Finding(
                kind="order", page=by_id[sid].page, evidence={"other": prev_id}
            )
            _add(out, sid, finding)
    owner = enclosing_unit(sections)
    for inv in notes.inversions:
        if not inv.reordered and inv.second_id in owner:
            finding = Finding(
                kind="order", page=inv.page, evidence={"other": inv.first_id}
            )
            _add(out, owner[inv.second_id], finding)
    return out


def fallback_findings(
    sections: list[SectionInput], notes: SectioningNotes
) -> dict[str, list[Finding]]:
    """A slug-id heading is a real heading the sectioner could not parse; flag it
    on the unit that holds it, except in front matter and part-root units."""
    owner = enclosing_unit(sections)
    chapter = {sec.id: sec.chapter for sec in sections}
    out: dict[str, list[Finding]] = {}
    for fb in notes.fallbacks:
        unit = owner.get(fb.id)
        if unit is None or chapter[unit] == "front-matter" or _is_part_root(unit):
            continue
        finding = Finding(
            kind="fallback", page=fb.page, evidence={"heading": fb.heading}
        )
        _add(out, unit, finding)
    return out


def _content_and_break(
    sections: list[SectionInput],
    i: int,
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
) -> list[Finding]:
    sec = sections[i]
    unverified = unverifiable(sec, pdf_pages)
    if unverified is not None:
        return [unverified]
    near = [s.l3 for s in sections[max(i - 1, 0) : i] + sections[i + 1 : i + 2]]
    return content_findings(sec, "\n\n".join(near), pdf_pages, furniture) + (
        break_findings(sec, pdf_pages)
    )


def check_document(
    sections: list[SectionInput],
    titles: dict[str, str],
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
    notes: SectioningNotes,
) -> list[SectionCheck]:
    order = order_findings(sections, titles, pdf_pages, notes)
    fallbacks = fallback_findings(sections, notes)
    seen: set[tuple[int | None, tuple[tuple[str, str], ...]]] = set()
    checks: list[SectionCheck] = []
    for i, sec in enumerate(sections):
        own = _content_and_break(sections, i, pdf_pages, furniture)
        keys = {
            (f.page, tuple(sorted(f.evidence.items())))
            for f in own
            if f.kind == "content"
        }
        # adjacent sections share boundary pages, so the same gap shows up twice
        findings = [
            f
            for f in own
            if f.kind != "content"
            or (f.page, tuple(sorted(f.evidence.items()))) not in seen
        ]
        seen |= keys
        findings += order.get(sec.id, []) + fallbacks.get(sec.id, [])
        if findings:
            checks.append(
                SectionCheck(
                    id=sec.id, l3_sha256=quality.digest(sec.l3), findings=findings
                )
            )
    return checks
