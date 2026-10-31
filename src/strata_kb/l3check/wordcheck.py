"""Word-level check of an AI draft against the PDF text layer (spec §9.4 check 3). Pure.

The unit's text and the draft are each aligned to the PDF tokens. A draft passes when it
loses no PDF text the original had, inserts only PDF-matched tokens, restores a missing
PDF run whole or not at all, does not copy a neighbouring unit's text, and removes
unmatched original text only when it is a heading id, a replaced garbled run, a
duplicate or furniture. Symbols are tokens, so <=/>=, signs, % and decimal separators
count. A heading's first chunk is one structural token only when it is shaped like an
id (word characters joined by - or .); otherwise it is ordinary text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from strata_kb.l3check.detect import _HYPHEN_BREAK, strip_markdown

ANCHOR = 3  # tokens of context kept before an offending position in an issue
_SHOWN = 20  # tokens kept in an issue's draft / original fields

_TOKEN = re.compile(r"[-−+]?\d+(?:[.,]\d+)*%?|[^\W_]+|[^\w\s]")
_LEADING_BULLET = re.compile(r"^[ \t]*[-*+][ \t]+", re.MULTILINE)
_BULLETS = frozenset("•◦▪‣●○■□–—-*")
_HEADING_ID = re.compile(r"^([ \t]*#{1,6}[ \t]+)(\S+)", re.MULTILINE)
_ID_SHAPE = re.compile(
    r"^[^\W_]+(?:[-.][^\W_]+)*$"
)  # an id has no punctuation but - and .
_ID_MARK = re.compile("\ue000(.*?)\ue001")
_NO_PDF = "no PDF text to verify against"
GARBLE_MIN_RATIO = 0.6  # a corrected spelling must still look like the text it replaces
DUP_MIN_TOKENS = 5  # a repeated block is at least this long; shorter runs are words


@dataclass(frozen=True)
class WordIssue:
    op: str  # "insert" | "replace" | "delete"
    draft: str
    original: str


def _tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    found = _TOKEN.findall(_HYPHEN_BREAK.sub(r"\1\2", folded))
    return [t for t in found if t not in _BULLETS]


def _prose(md: str) -> tuple[list[str], list[bool], list[int]]:
    """Tokens, a flag for heading-id tokens, and per token the title length after an id."""
    marked = _HEADING_ID.sub(
        lambda m: f"{m[1]}\ue000{m[2]}\ue001" if _ID_SHAPE.match(m[2]) else m[0], md
    )
    text = _LEADING_BULLET.sub("", strip_markdown(marked))
    tokens: list[str] = []
    structural: list[bool] = []
    title: list[int] = []
    pos = 0
    for m in _ID_MARK.finditer(text):
        plain = _tokens(text[pos : m.start()])
        tokens += [*plain, unicodedata.normalize("NFKC", m[1]).casefold()]
        structural += [False] * len(plain) + [True]
        title += [0] * len(plain) + [len(_tokens(text[m.end() :].split("\n", 1)[0]))]
        pos = m.end()
    tail = _tokens(text[pos:])
    return tokens + tail, structural + [False] * len(tail), title + [0] * len(tail)


def prose_tokens(md: str) -> list[str]:
    return _prose(md)[0]


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


@dataclass(frozen=True)
class _Side:
    tokens: list[str]
    structural: list[bool]
    title: list[int]  # tokens after a heading id on its line
    hit: dict[int, int]  # pdf index -> token index
    matched: frozenset[int]  # token indices matched to the PDF


def _side(md: str, pdf: list[str]) -> _Side:
    tokens, structural, title = _prose(md)
    hit, _ = _align(pdf, tokens)
    return _Side(tokens, structural, title, hit, frozenset(hit.values()))


def _window(tokens: list[str], pos: int) -> str:
    return " ".join(tokens[max(0, pos - ANCHOR) :][:_SHOWN])


def _runs(indices: Sequence[int]) -> list[list[int]]:
    """Maximal runs of consecutive integers in sorted `indices`."""
    runs: list[list[int]] = []
    for i in indices:
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def _after(draft: _Side, i: int) -> int:
    """Draft position just after the nearest kept PDF token before PDF index `i`."""
    before = [pos for k, pos in draft.hit.items() if k < i]
    return max(before) + 1 if before else 0


def _unmatched_inserts(draft: _Side, edit: list) -> list[int]:
    """Draft positions inside insert/replace edits the PDF does not have there."""
    return [
        j
        for tag, _, _, j1, j2 in edit
        if tag in ("insert", "replace")
        for j in range(j1, j2)
        if j not in draft.matched
    ]


def _lost(pdf: list[str], orig: _Side, draft: _Side, edit: list) -> WordIssue | None:
    """Rule 1: PDF text the original covered is gone."""
    lost = sorted(set(orig.hit) - set(draft.hit))
    if not lost:
        return None
    run = _runs(lost)[0]
    original = " ".join(pdf[i] for i in run[:_SHOWN])
    inserts = _unmatched_inserts(draft, edit)
    if inserts:
        return WordIssue("replace", _window(draft.tokens, inserts[0]), original)
    return WordIssue("delete", _window(draft.tokens, _after(draft, run[0])), original)


def _foreign_insert(draft: _Side, edit: list) -> WordIssue | None:
    """Rule 2: every inserted draft token must be what the PDF has there."""
    inserts = _unmatched_inserts(draft, edit)
    return (
        WordIssue("insert", _window(draft.tokens, inserts[0]), "") if inserts else None
    )


def _partial_restore(
    pdf: list[str], orig: _Side, draft: _Side, neigh_cov: set[int]
) -> WordIssue | None:
    """Rule 3: PDF text neither the unit nor a neighbour has comes back whole or not at all."""
    known = set(orig.hit) | neigh_cov
    for gap in _runs([i for i in range(len(pdf)) if i not in known]):
        back = [i for i in gap if i in draft.hit]
        if back and len(back) != len(gap):
            return WordIssue("insert", _window(draft.tokens, draft.hit[back[0]]), "")
    return None


def _neighbour_copy(orig: _Side, draft: _Side, neigh_cov: set[int]) -> WordIssue | None:
    """Rule 4: text a neighbouring unit holds must not appear in this one."""
    copied = sorted((set(draft.hit) - set(orig.hit)) & neigh_cov)
    if not copied:
        return None
    return WordIssue("insert", _window(draft.tokens, draft.hit[copied[0]]), "")


def _excused_block(run: list[str], orig: _Side, draft: _Side) -> bool:
    """Rule 5c: a whole unmatched segment is moved into its PDF place or a long duplicate."""
    n = len(run)
    pdf_of_pos = {pos: i for i, pos in draft.hit.items()}
    for k in range(len(draft.tokens) - n + 1):
        if draft.tokens[k : k + n] != run or any(
            m not in draft.matched for m in range(k, k + n)
        ):
            continue
        if n >= DUP_MIN_TOKENS or any(
            pdf_of_pos[m] not in orig.hit for m in range(k, k + n)
        ):
            return True
    return False


def _is_furniture(run: list[str], lines: list[list[str]]) -> bool:
    """True when `run` is a concatenation of furniture lines."""
    reach = {0}
    for pos in range(len(run)):
        if pos in reach:
            reach |= {pos + len(f) for f in lines if f and run[pos : pos + len(f)] == f}
    return len(run) in reach


def _id_removable(pdf: list[str], orig: _Side, i: int) -> bool:
    """An unmatched heading id may go only above a non-empty, fully PDF-matched title.

    Not when the id is itself PDF text sitting just before that title."""
    title = range(i + 1, i + 1 + orig.title[i])
    if not title or not all(k in orig.matched for k in title):
        return False
    first = {pos: k for k, pos in orig.hit.items()}[title[0]]
    chunk = _tokens(orig.tokens[i])
    return not (
        chunk and first >= len(chunk) and pdf[first - len(chunk) : first] == chunk
    )


def _whole_segment(run: list[int], plain_unmatched: set[int]) -> bool:
    return run[0] - 1 not in plain_unmatched and run[-1] + 1 not in plain_unmatched


def _garble_fix(
    orig: _Side, draft: _Side, run: list[int], span: tuple[int, int]
) -> bool:
    """Rule 5b: the replacement fills a PDF gap at that place and is a corrected spelling."""
    j1, j2 = span
    if j2 <= j1 or any(j not in draft.matched for j in range(j1, j2)):
        return False
    pos_to_pdf = {pos: i for i, pos in draft.hit.items()}
    before = [pos_to_pdf[k] for k in range(j1) if k in pos_to_pdf]
    after = [pos_to_pdf[k] for k in range(j2, len(draft.tokens)) if k in pos_to_pdf]
    low, high = (before[-1] if before else -1), (after[0] if after else None)
    used = [pos_to_pdf[j] for j in range(j1, j2)]
    if any(i <= low or (high is not None and i >= high) or i in orig.hit for i in used):
        return False
    removed = " ".join(orig.tokens[i] for i in run)
    replacement = " ".join(draft.tokens[j1:j2])
    return SequenceMatcher(None, removed, replacement).ratio() >= GARBLE_MIN_RATIO


def _unaccounted_removal(
    pdf: list[str], orig: _Side, draft: _Side, edit: list, furniture: Sequence[str]
) -> WordIssue | None:
    """Rule 5: removed original text the PDF lacks must be an id, a fix, a whole block or furniture."""
    lines = [_tokens(f) for f in furniture]
    unmatched = set(range(len(orig.tokens))) - orig.matched
    plain = {i for i in unmatched if not orig.structural[i]}
    for tag, i1, i2, j1, j2 in edit:
        if tag not in ("delete", "replace"):
            continue
        ids = [i for i in range(i1, i2) if i in unmatched and orig.structural[i]]
        for i in ids:
            if not _id_removable(pdf, orig, i):
                return WordIssue("delete", _window(draft.tokens, j1), orig.tokens[i])
        for run in _runs([i for i in range(i1, i2) if i in plain]):
            words = [orig.tokens[i] for i in run]
            fixed = tag == "replace" and _garble_fix(orig, draft, run, (j1, j2))
            block = _whole_segment(run, plain) and _excused_block(words, orig, draft)
            if fixed or block or _is_furniture(words, lines):
                continue
            return WordIssue(
                "delete", _window(draft.tokens, j1), " ".join(words[:_SHOWN])
            )
    return None


def check_words(
    original_md: str,
    draft_md: str,
    pdf: list[str],
    neighbour_md: str = "",
    furniture: Sequence[str] = (),
) -> WordIssue | None:
    """First change the PDF does not justify, or None."""
    orig, draft = _side(original_md, pdf), _side(draft_md, pdf)
    if not pdf:
        if orig.tokens == draft.tokens:
            return None
        return WordIssue("delete", _window(draft.tokens, 0), _NO_PDF)
    neigh_cov = set(_side(neighbour_md, pdf).hit) if neighbour_md else set()
    edit = SequenceMatcher(
        None, orig.tokens, draft.tokens, autojunk=False
    ).get_opcodes()
    return (
        _lost(pdf, orig, draft, edit)
        or _foreign_insert(draft, edit)
        or _partial_restore(pdf, orig, draft, neigh_cov)
        or _neighbour_copy(orig, draft, neigh_cov)
        or _unaccounted_removal(pdf, orig, draft, edit, furniture)
    )


def uncovered_share(md: str, pdf: list[str]) -> float:
    """Share of the markdown's tokens the PDF alignment leaves unmatched."""
    tokens = prose_tokens(md)
    if not pdf:
        return 1.0
    if not tokens:
        return 0.0
    return len(_align(pdf, tokens)[1]) / len(tokens)
