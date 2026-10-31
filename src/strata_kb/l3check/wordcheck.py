"""Word-level check of an AI draft against the PDF text layer (spec §9.4 check 3). Pure."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from strata_kb.l3check.detect import (
    _page_words,
    _uncovered_runs,
    normalize_words,
    strip_markdown,
)

ANCHOR = 3  # PDF-confirmed context words around every changed run
_SHOWN = 20  # words of a window/removed run kept in an issue


@dataclass(frozen=True)
class WordIssue:
    op: str  # "insert" | "replace" | "delete"
    draft: str
    original: str


def prose_words(md: str) -> list[str]:
    return normalize_words(strip_markdown(md))


def span_words(
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
    page: int | None,
    end_page: int | None,
) -> list[str]:
    """Furniture-free words of pages `page..end_page` that exist in `pdf_pages`."""
    if page is None:
        return []
    end = end_page if end_page is not None else page
    words: list[str] = []
    for p in range(page, end + 1):
        if p in pdf_pages:
            words += _page_words(pdf_pages[p], furniture.get(p, []))
    return words


def _contains(haystack: list[str], needle: list[str]) -> bool:
    return " " + " ".join(needle) + " " in " " + " ".join(haystack) + " "


def check_words(
    original_md: str, draft_md: str, pdf_words: list[str]
) -> WordIssue | None:
    """First change the PDF does not justify, or None.

    Every changed run must sit in PDF-confirmed context (ANCHOR words each side), and
    removed real PDF text must survive elsewhere in the draft (a removed duplicate).
    """
    a, b = prose_words(original_md), prose_words(draft_md)
    for tag, i1, i2, j1, j2 in SequenceMatcher(
        None, a, b, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        window = b[max(0, j1 - ANCHOR) : min(len(b), j2 + ANCHOR)]
        removed = a[i1:i2]
        if not window or not _contains(pdf_words, window):
            return _issue(tag, window, removed)
        if removed and _contains(pdf_words, removed) and not _contains(b, removed):
            return _issue(tag, window, removed)
    return None


def _issue(tag: str, window: list[str], removed: list[str]) -> WordIssue:
    return WordIssue(tag, " ".join(window[:_SHOWN]), " ".join(removed[:_SHOWN]))


def uncovered_share(md: str, pdf_words: list[str]) -> float:
    words = prose_words(md)
    if not pdf_words:
        return 1.0
    if not words:
        return 0.0
    return sum(len(run) for _, run in _uncovered_runs(words, pdf_words)) / len(words)
