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

Box = tuple[float, float, float, float]  # (left, top, right, bottom), BOTTOMLEFT, points


def region_text(
    pdf_path: Path | None, page_no: int | None, box: Box | None, mono: bool
) -> str | None:
    """Text inside `box` on page `page_no` (1-based); None when unavailable."""
    if pdf_path is None or page_no is None or page_no < 1 or box is None:
        return None
    try:
        import pypdfium2

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


def _flow(textpage, box: Box) -> str:
    left, top, right, bottom = box
    raw = textpage.get_text_bounded(left=left, bottom=bottom, right=right, top=top)
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = (" ".join(line.split()) for line in raw.split("\n"))
    return "\n".join(line for line in lines if line)


def _mono_grid(textpage, box: Box) -> str:
    left, top, right, bottom = box
    chars: list[tuple[float, float, float, float, str]] = []  # (cy, left, width, height, ch)
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
        col = -1
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
