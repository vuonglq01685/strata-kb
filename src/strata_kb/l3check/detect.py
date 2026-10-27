"""L3 fidelity detection over strings: L3 text against the PDF's text layer.

Pure functions, no PDF or file I/O. Words are compared after normalisation;
a word counts as covered when any SHINGLE-word window containing it occurs on
the other side, so reordering of a few words is tolerated but dropped or
garbled stretches are not.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from strata_kb.l3check.report import Finding

SHINGLE = 4  # words per shingle
MIN_RUN = 5  # shortest missing/extra run reported
SNIPPET_WORDS = 25  # evidence cap

_HYPHEN_BREAK = re.compile(r"(\w)-[^\S\n]*\n\s*(\w)")
_WORD = re.compile(r"[^\W_]+")
_FENCE = re.compile(r"^[ \t]*(```|~~~).*$", re.MULTILINE)
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
_TABLE_SEPARATOR = re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t:|-]*$", re.MULTILINE)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
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
