"""Split a heading that swallowed several PDF lines.

docling can box a whole page-header block (title, version, status, owner,
source link, watermark) as one `title` item and join its lines with spaces,
so the KB got a one-paragraph heading. The PDF text layer still has the
lines and their font sizes: the heading keeps the title-size lines, the
smaller lines and any line with a link become body text, and lines that are
page furniture (a watermark) go, as page furniture does everywhere else.
Nothing is split unless the lines hold exactly docling's characters.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

TITLE_SIZE_RATIO = 0.9  # a line this close to the largest size is title text
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)


_WORD = re.compile(r"[^\W_]+")


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _words(text: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(_norm(text)))


def _chars(text: str) -> Counter[str]:
    return Counter(_norm(text).replace(" ", ""))


def furniture_set(by_page: dict[int, list[str]]) -> set[tuple[str, ...]]:
    """Words of each running header/footer/watermark string of the document.
    Bare numbers (page numbers) are left out: they would match real text."""
    return {
        w
        for texts in by_page.values()
        for t in texts
        if (w := _words(t)) and not "".join(w).isdigit()
    }


def _is_furniture(line: str, furniture: set[tuple[str, ...]]) -> bool:
    """True when the line's words are furniture strings back to back (one
    watermark, or the same watermark twice side by side)."""
    words = _words(line)
    reach = {0}
    for pos in range(len(words)):
        if pos in reach:
            reach |= {pos + len(f) for f in furniture if words[pos : pos + len(f)] == f}
    return bool(words) and len(words) in reach


def split_heading(
    text: str, lines: list[tuple[str, float]], furniture: set[tuple[str, ...]]
) -> tuple[str, list[str]] | None:
    """(heading, body lines), or None when the heading stays as it is.

    `lines` are the PDF lines inside the heading's box with their size.
    A title-size line is never dropped as furniture: a running header that
    repeats the document title must not take the title with it.
    """
    if len(lines) < 2:
        return None
    furn = [_is_furniture(t, furniture) for t, _ in lines]
    sizes = [
        s for (t, s), f in zip(lines, furn, strict=True) if not f and not _URL.search(t)
    ]
    if not sizes:
        return None
    floor = max(sizes) * TITLE_SIZE_RATIO
    big = [
        i
        for i, ((_, s), f) in enumerate(zip(lines, furn, strict=True))
        if f and s >= floor
    ]
    if big:
        if big != [0]:
            return None  # title-size furniture after the title: lint R9 flags it
        floor = max(floor, lines[0][1] * TITLE_SIZE_RATIO)  # the title is the header
    kept = [line for i, line in enumerate(lines) if i in big or not furn[i]]
    have = _chars(text)
    if have not in (
        _chars(" ".join(t for t, _ in lines)),
        _chars(" ".join(t for t, _ in kept)),
    ):
        return None  # the box holds other text, or docling read it differently
    is_head = [s >= floor and not _URL.search(t) for t, s in kept]
    body = [t for (t, _), h in zip(kept, is_head, strict=True) if not h]
    if not body and len(kept) == len(lines):
        return None  # a title wrapped over lines: nothing to move
    return " ".join(t for (t, _), h in zip(kept, is_head, strict=True) if h), body
