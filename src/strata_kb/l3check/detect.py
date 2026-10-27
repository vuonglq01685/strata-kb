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
from strata_kb.ingest.sectioner import SectioningNotes
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


def _stream(
    pdf_pages: dict[int, str], furniture: dict[int, list[str]]
) -> tuple[list[str], dict[int, int]]:
    """Every page's words (furniture removed) in page order, and each page's start index."""
    words: list[str] = []
    starts: dict[int, int] = {}
    for p in sorted(pdf_pages):
        starts[p] = len(words)
        words += _page_words(pdf_pages[p], furniture.get(p, []))
    return words, starts


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


def _content_runs(
    sec: SectionInput,
    l3_neighbours: str,
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
    starts: dict[int, int],
) -> list[tuple[int | None, Finding]]:
    """Content findings, each with the document-wide word index of a missing run
    (None for an extra run in L3)."""
    pages = _span_pages(sec, pdf_pages)
    if not pages:
        return []
    # one word list over the whole span, so a run is not cut at a page break
    span_words: list[str] = []
    word_pages: list[int] = []
    word_index: list[int] = []
    for p in pages:
        words = _page_words(pdf_pages[p], furniture.get(p, []))
        span_words += words
        word_pages += [p] * len(words)
        word_index += range(starts[p], starts[p] + len(words))
    l3_words = normalize_words(strip_markdown(sec.l3))
    present = l3_words + normalize_words(strip_markdown(l3_neighbours))
    found: list[tuple[int | None, Finding]] = [
        (
            word_index[start],
            Finding(
                kind="content", page=word_pages[start], evidence={"pdf": _snippet(run)}
            ),
        )
        for start, run in _uncovered_runs(span_words, present)
    ]
    found += [
        (None, Finding(kind="content", page=sec.page, evidence={"l3": _snippet(run)}))
        for _, run in _uncovered_runs(l3_words, span_words)
    ]
    return found


def content_findings(
    sec: SectionInput,
    l3_neighbours: str,
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
) -> list[Finding]:
    """`l3_neighbours`: the L3 of every other unit whose span overlaps `sec`'s."""
    _, starts = _stream(pdf_pages, furniture)
    runs = _content_runs(sec, l3_neighbours, pdf_pages, furniture, starts)
    return [finding for _, finding in runs]


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
    """Paragraphs as blocks of pure prose lines. A blank line ends a block; a
    non-prose line (heading, table row, image, list item, fence and what it
    fences, an unclosed fence running to the end) ends it too and leaves None,
    so a pair is only ever two adjacent pure-prose blocks."""
    blocks: list[str | None] = []
    current: list[str] = []
    fenced = False
    for line in l3.splitlines():
        is_fence = _FENCE.match(line) is not None
        if is_fence:
            fenced = not fenced
        if fenced or is_fence or _NON_PROSE.match(line):
            blocks += ["\n".join(current), None] if current else [None]
            current = []
        elif line.strip():
            current.append(line.strip())
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def break_findings(sec: SectionInput, pdf_pages: dict[int, str]) -> list[Finding]:
    """Paragraph split mid-sentence in L3 where the PDF text runs on unbroken."""
    stream: list[str] = []
    for p in _span_pages(sec, pdf_pages):
        stream += normalize_words(pdf_pages[p])
    findings: list[Finding] = []
    blocks = _prose_blocks(sec.l3)
    for first, second in zip(blocks, blocks[1:], strict=False):
        if first is None or second is None:
            continue
        if strip_markdown(first).rstrip()[-1:] in {*TERMINAL, ""}:
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
    sections: list[SectionInput],
    titles: dict[str, str],
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
) -> list[tuple[str, int]]:
    """(section id, global word index of its title) for each title found from
    its start page on, in section order. Furniture is out of the stream, so a
    running header repeating a title cannot be mistaken for the heading."""
    stream, page_start = _stream(pdf_pages, furniture)
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
    furniture: dict[int, list[str]] | None = None,
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
    located = _title_positions(sections, titles, pdf_pages, furniture or {})
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
        if unit is None or chapter[unit] == "front-matter" or chapter[unit] == unit:
            continue  # front matter, or a part's root unit (its title heading)
        finding = Finding(
            kind="fallback", page=fb.page, evidence={"heading": fb.heading}
        )
        _add(out, unit, finding)
    return out


def _overlapping(
    sections: list[SectionInput], pdf_pages: dict[int, str]
) -> list[list[int]]:
    """For each section, the indexes of the other sections whose page span shares a page."""
    on_page: dict[int, list[int]] = {}
    for i, sec in enumerate(sections):
        for p in _span_pages(sec, pdf_pages):
            on_page.setdefault(p, []).append(i)
    return [
        sorted({j for p in _span_pages(sec, pdf_pages) for j in on_page[p]} - {i})
        for i, sec in enumerate(sections)
    ]


_Key = tuple[int | None, tuple[tuple[str, str], ...]]


def _owner(
    reporters: list[tuple[int, int | None]],
    sections: list[SectionInput],
    title_at: dict[str, int],
) -> int:
    """The section a gap belongs to: the last one whose title precedes the gap,
    else the first section that reported it."""
    at = next((pos for _, pos in reporters if pos is not None), None)
    best: tuple[int, int] | None = None  # (title position, section index)
    for i, _ in reporters:
        title = title_at.get(sections[i].id)
        if at is not None and title is not None and title <= at:
            best = max(best or (title, i), (title, i))
    return best[1] if best else reporters[0][0]


def check_document(
    sections: list[SectionInput],
    titles: dict[str, str],
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
    notes: SectioningNotes,
) -> list[SectionCheck]:
    order = order_findings(sections, titles, pdf_pages, notes, furniture)
    fallbacks = fallback_findings(sections, notes)
    title_at = dict(_title_positions(sections, titles, pdf_pages, furniture))
    _, starts = _stream(pdf_pages, furniture)
    overlaps = _overlapping(sections, pdf_pages)
    content: list[list[tuple[_Key, Finding]]] = []
    reporters: dict[_Key, list[tuple[int, int | None]]] = {}
    for i, sec in enumerate(sections):
        near = "\n\n".join(sections[j].l3 for j in overlaps[i])
        keyed = []
        for pos, f in _content_runs(sec, near, pdf_pages, furniture, starts):
            key = (f.page, tuple(sorted(f.evidence.items())))
            keyed.append((key, f))
            reporters.setdefault(key, []).append((i, pos))
        content.append(keyed)
    # adjacent sections share boundary pages, so the same gap shows up on several
    owner = {key: _owner(r, sections, title_at) for key, r in reporters.items()}
    checks: list[SectionCheck] = []
    for i, sec in enumerate(sections):
        unverified = unverifiable(sec, pdf_pages)
        if unverified is not None:
            findings = [unverified]
        else:
            findings = [f for key, f in content[i] if owner[key] == i]
            findings += break_findings(sec, pdf_pages)
        findings += order.get(sec.id, []) + fallbacks.get(sec.id, [])
        if findings:
            checks.append(
                SectionCheck(
                    id=sec.id, l3_sha256=quality.digest(sec.l3), findings=findings
                )
            )
    return checks
