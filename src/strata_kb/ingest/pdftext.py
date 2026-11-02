"""Text of one PDF region from its text layer, via pypdfium2.

docling flattens `code` items (line breaks become spaces, words joined by
tabs) and splits Vietnamese glyphs drawn with a fallback monospace font
into separate cells (`g ố c`). The PDF text layer has both right; this
module reads it back for a docling-provided bbox.

`mono=True` rebuilds a character grid from per-character advance boxes so
box-drawing diagrams keep their columns. Two monospace fonts on one line
(DejaVu Sans Mono + FreeMono fallback) differ by ~3 % in advance width,
so columns are placed by rounding each char's delta from its predecessor
rather than its absolute offset: no accumulated drift, no two glyphs in
one cell.
"""

from __future__ import annotations

import logging
import statistics
from pathlib import Path

logger = logging.getLogger("strata_kb.ingest.pdftext")

_LINE_END_HYPHEN = "\ufffe"  # pdfium's code for a hyphen that ends a line

Box = tuple[
    float, float, float, float
]  # (left, top, right, bottom), BOTTOMLEFT, points


def region_text(
    pdf_path: Path | None, page_no: int | None, box: Box | None, mono: bool
) -> str | None:
    """Text inside `box` on page `page_no` (1-based); None when unavailable."""
    if pdf_path is None or page_no is None or page_no < 1 or box is None:
        return None
    try:
        import pypdfium2  # pyright: ignore[reportMissingImports]

        # ponytail: this re-scans every char on the page (two FFI calls
        # each) on every call, which dominates the cost -- reopening the
        # document is comparatively cheap. Scope the char scan to the
        # region if a code-heavy PDF makes this measurably slow.
        pdf = pypdfium2.PdfDocument(str(pdf_path))
        try:
            textpage = pdf[page_no - 1].get_textpage()
            try:
                text = _mono_grid(textpage, box) if mono else _flow(textpage, box)
            finally:
                textpage.close()
        finally:
            pdf.close()
    except Exception as exc:  # noqa: BLE001 -- text layer is best-effort; caller keeps docling's text
        logger.warning("pdf text for page %s skipped: %s", page_no, exc)
        return None
    return text or None


def region_lines(
    pdf_path: Path | None, page_no: int | None, box: Box | None
) -> list[tuple[str, float]] | None:
    """Visual lines inside `box`, top to bottom, each with its largest font
    size in points; None when unavailable."""
    if pdf_path is None or page_no is None or page_no < 1 or box is None:
        return None
    try:
        import pypdfium2  # pyright: ignore[reportMissingImports]
        import pypdfium2.raw as pdfium_c  # pyright: ignore[reportMissingImports]

        pdf = pypdfium2.PdfDocument(str(pdf_path))
        try:
            textpage = pdf[page_no - 1].get_textpage()
            try:
                return _lines(textpage, box, pdfium_c.FPDFText_GetFontSize)
            finally:
                textpage.close()
        finally:
            pdf.close()
    except Exception as exc:  # noqa: BLE001 -- text layer is best-effort; caller keeps docling's text
        logger.warning("pdf lines for page %s skipped: %s", page_no, exc)
        return None


def _lines(textpage, box: Box, font_size) -> list[tuple[str, float]]:
    """Group the box's chars into rows by vertical centre; a space joins the
    row of the char before it. Row text keeps the text layer's char order."""
    left, top, right, bottom = box
    chars: list[tuple[float, int, str, float, float]] = []  # (y, index, char, size, h)
    spaces: list[int] = []
    for i in range(textpage.count_chars()):
        ch = textpage.get_text_range(i, 1).replace(_LINE_END_HYPHEN, "-")
        if not ch:
            continue
        if ch.isspace():
            spaces.append(i)
            continue
        # loose box: the font's ascent to descent, the same for every glyph of
        # a line, so accents, quotes and commas share their line's centre
        cl, cb, cr, ct = textpage.get_charbox(i, loose=True)
        cx, cy = (cl + cr) / 2, (cb + ct) / 2
        if left <= cx <= right and bottom <= cy <= top:
            size = font_size(textpage.raw, i)
            # a PDF that sets 1 pt and scales the matrix: the box height is the size
            chars.append((cy, i, ch, size if size > 1 else ct - cb, ct - cb))
    rows: list[tuple[float, float, dict[int, str]]] = []  # (centre y, size, chars)
    row_of: dict[int, int] = {}
    heights: list[float] = []
    for cy, i, ch, size, height in sorted(chars, key=lambda c: -c[0]):
        if rows and abs(rows[-1][0] - cy) <= max(heights[-1], height) / 2:
            y, big, members = rows[-1]
            rows[-1] = (y, max(big, size), members)
            heights[-1] = max(heights[-1], height)
        else:
            rows.append((cy, size, {}))
            heights.append(height)
        rows[-1][2][i] = ch
        row_of[i] = len(rows) - 1
    for i in spaces:
        if i - 1 in row_of:
            rows[row_of[i - 1]][2][i] = " "
    out: list[tuple[str, float]] = []
    for _, size, members in rows:
        text = " ".join("".join(members[i] for i in sorted(members)).split())
        if text:
            out.append((text, size))
    return out


def page_texts(pdf_path: Path) -> dict[int, str]:
    """Full text-layer text per page (1-based; "" for a page without text).

    {} when pypdfium2 is missing or the PDF is unreadable: the L3 check then
    has no reference and skips, rather than failing ingest.
    """
    try:
        import pypdfium2  # pyright: ignore[reportMissingImports]

        pdf = pypdfium2.PdfDocument(str(pdf_path))
        try:
            texts: dict[int, str] = {}
            for i in range(len(pdf)):
                textpage = pdf[i].get_textpage()
                try:
                    raw = textpage.get_text_range()
                finally:
                    textpage.close()
                texts[i + 1] = raw.replace("\r\n", "\n").replace("\r", "\n")
        finally:
            pdf.close()
    except Exception as exc:  # noqa: BLE001 -- reference text is best-effort; the check skips without it
        logger.warning("pdf page texts skipped: %s", exc)
        return {}
    return texts


def _flow(textpage, box: Box) -> str:
    left, top, right, bottom = box
    raw = textpage.get_text_bounded(left=left, bottom=bottom, right=right, top=top)
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = (" ".join(line.split()) for line in raw.split("\n"))
    return "\n".join(line for line in lines if line)


def _mono_grid(textpage, box: Box) -> str:
    left, top, right, bottom = box
    chars: list[
        tuple[float, float, float, float, str]
    ] = []  # (cy, left, width, height, ch)
    for i in range(textpage.count_chars()):
        ch = textpage.get_text_range(i, 1)
        if not ch or ch.isspace():
            continue
        l, b, r, t = textpage.get_charbox(i, loose=True)  # noqa: E741 -- pypdfium2 order
        cx, cy = (l + r) / 2, (b + t) / 2
        if left <= cx <= right and bottom <= cy <= top:
            chars.append((cy, l, r - l, t - b, ch))
    if not chars:
        return ""
    cell = statistics.median(c[2] for c in chars)
    if cell <= 0:
        return ""
    row_tol = statistics.median(c[3] for c in chars) / 2
    min_left = min(c[1] for c in chars)

    rows: list[tuple[float, list]] = []
    for c in sorted(chars, key=lambda c: -c[0]):  # PDF y grows upward: top row first
        if rows and abs(rows[-1][0] - c[0]) <= row_tol:
            rows[-1][1].append(c)
        else:
            rows.append((c[0], [c]))

    out: list[str] = []
    for _cy, row in rows:
        line: list[str] = []
        prev_left = None
        for _cy2, l, _w, _h, ch in sorted(row, key=lambda c: c[1]):  # noqa: E741
            if prev_left is None:
                col = round((l - min_left) / cell)
            else:
                col += max(1, round((l - prev_left) / cell))
            prev_left = l
            line.extend(" " * (col - len(line)))
            line.append(ch)
        out.append("".join(line).rstrip())
    return "\n".join(out)
