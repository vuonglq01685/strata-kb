"""Word-level check of an AI draft against the PDF text layer (spec §9.4 check 3). Pure.

The unit's text and the draft are each aligned to the PDF tokens. A draft passes when it
loses no PDF text the original had, adds no token the PDF lacks at that place, and does
not copy a neighbouring unit's text. Symbols are tokens, so <=/>=, signs, % and decimal
separators count.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from strata_kb.l3check.detect import _HYPHEN_BREAK, strip_markdown

ANCHOR = 3  # tokens of context kept before an offending position in an issue
_SHOWN = 20  # tokens kept in an issue's draft / original fields

_TOKEN = re.compile(r"[-−+]?\d+(?:[.,]\d+)*%?|[^\W_]+|[^\w\s]")
_LEADING_BULLET = re.compile(r"^[ \t]*[-*+][ \t]+", re.MULTILINE)
_BULLETS = frozenset("•◦▪‣●○■□–—-*")


@dataclass(frozen=True)
class WordIssue:
    op: str  # "insert" | "replace" | "delete"
    draft: str
    original: str


def _tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    found = _TOKEN.findall(_HYPHEN_BREAK.sub(r"\1\2", folded))
    return [t for t in found if t not in _BULLETS]


def prose_tokens(md: str) -> list[str]:
    return _tokens(_LEADING_BULLET.sub("", strip_markdown(md)))


def _page_tokens(text: str, furniture: list[str]) -> list[str]:
    """Page tokens with each furniture line removed once."""
    tokens = _tokens(text)
    for line in furniture:
        needle = _tokens(line)
        for i in range(len(tokens) - len(needle) + 1):
            if needle and tokens[i : i + len(needle)] == needle:
                del tokens[i : i + len(needle)]
                break
    return tokens


def pdf_tokens(
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
    page: int | None,
    end_page: int | None,
) -> list[str]:
    """Furniture-free tokens of pages `page..end_page` that exist in `pdf_pages`."""
    if page is None:
        return []
    end = end_page if end_page is not None else page
    tokens: list[str] = []
    for p in range(page, end + 1):
        if p in pdf_pages:
            tokens += _page_tokens(pdf_pages[p], furniture.get(p, []))
    return tokens


def _align(pdf: list[str], tokens: list[str]) -> tuple[dict[int, int], list[int]]:
    """({pdf index: token index} for matched tokens, indices of unmatched tokens)."""
    hit: dict[int, int] = {}
    for a, b, n in SequenceMatcher(
        None, pdf, tokens, autojunk=False
    ).get_matching_blocks():
        hit.update({a + k: b + k for k in range(n)})
    matched = set(hit.values())
    return hit, [j for j in range(len(tokens)) if j not in matched]


def _first_run(indices: list[int]) -> list[int]:
    run = indices[:1]
    for i in indices[1:]:
        if i != run[-1] + 1:
            break
        run.append(i)
    return run


def _after(draft_hit: dict[int, int], i: int) -> int:
    """Draft position just after the nearest kept PDF token before PDF index `i`."""
    before = [draft_hit[k] for k in draft_hit if k < i]
    return max(before) + 1 if before else 0


def _window(tokens: list[str], pos: int) -> str:
    return " ".join(tokens[max(0, pos - ANCHOR) :][:_SHOWN])


def check_words(
    original_md: str, draft_md: str, pdf: list[str], neighbour_md: str = ""
) -> WordIssue | None:
    """First change the PDF does not justify, or None."""
    a, b = prose_tokens(original_md), prose_tokens(draft_md)
    orig_hit, orig_extra = _align(pdf, a)
    draft_hit, draft_extra = _align(pdf, b)
    lost = sorted(set(orig_hit) - set(draft_hit))
    new = Counter(b[j] for j in draft_extra) - Counter(a[j] for j in orig_extra)
    new_pos = next((j for j in draft_extra if new[b[j]] > 0), None)
    if lost:
        run = _first_run(lost)
        original = " ".join(pdf[i] for i in run[:_SHOWN])
        if new_pos is not None:
            return WordIssue("replace", _window(b, new_pos), original)
        return WordIssue("delete", _window(b, _after(draft_hit, run[0])), original)
    if new_pos is not None:
        return WordIssue("insert", _window(b, new_pos), "")
    if neighbour_md:
        neighbour_hit, _ = _align(pdf, prose_tokens(neighbour_md))
        copied = sorted((set(draft_hit) - set(orig_hit)) & set(neighbour_hit))
        if copied:
            return WordIssue("insert", _window(b, draft_hit[copied[0]]), "")
    return None


def uncovered_share(md: str, pdf: list[str]) -> float:
    """Share of the markdown's tokens the PDF alignment leaves unmatched."""
    tokens = prose_tokens(md)
    if not pdf:
        return 1.0
    if not tokens:
        return 0.0
    return len(_align(pdf, tokens)[1]) / len(tokens)
