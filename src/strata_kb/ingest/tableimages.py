"""Place glyph images into the table cell they were drawn in.

Docling reports a table's cells and a page's pictures as siblings: an icon
printed inside a "Code symbol" column comes back as a standalone picture and
the column comes back empty. Reuniting them needs geometry, so this module
works purely on boxes -- callers convert docling's provenance to TOPLEFT
coordinates first (see parser._topleft_box).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Box", "Cell", "inject", "locate"]

# A raw '|' inside a cell would split the row into an extra column. The HTML
# entity renders as a pipe without being one, which keeps every downstream
# pipe-counting parser (mdutils.extract_tables, the L2/L3 verbatim check)
# seeing the table's real shape.
_PIPE = "&#124;"


@dataclass(frozen=True)
class Box:
    """TOPLEFT-origin rectangle: `top` is the upper edge, so `top <= bottom`."""

    left: float
    top: float
    right: float
    bottom: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.left + self.right) / 2, (self.top + self.bottom) / 2


@dataclass(frozen=True)
class Cell:
    row: int  # 0 = header row, 1 = first body row
    col: int
    box: Box


def _bands(cells: list[Cell], key) -> dict[int, tuple[float, float]]:
    """Per row (or column) index, the union span of its cells."""
    bands: dict[int, tuple[float, float]] = {}
    for cell in cells:
        idx, lo, hi = key(cell)
        if idx in bands:
            prev_lo, prev_hi = bands[idx]
            bands[idx] = (min(prev_lo, lo), max(prev_hi, hi))
        else:
            bands[idx] = (lo, hi)
    return bands


def locate(box: Box, cells: list[Cell]) -> tuple[int, int] | None:
    """(row, col) of the cell whose bands contain `box`'s centre, else None.

    Containment only -- a nearest-band fallback would drag captions and
    footnotes that merely sit near a table into one of its cells.
    """
    if not cells:
        return None
    rows = _bands(cells, lambda c: (c.row, c.box.top, c.box.bottom))
    cols = _bands(cells, lambda c: (c.col, c.box.left, c.box.right))
    x, y = box.center
    row = next((i for i, (lo, hi) in rows.items() if lo <= y <= hi), None)
    col = next((i for i, (lo, hi) in cols.items() if lo <= x <= hi), None)
    if row is None or col is None:
        return None
    return row, col


GLYPH_PADDING = 3.0  # pt of slack around the strokes already found in a column


def _row_rects(
    rows: dict[int, tuple[float, float]], table: Box
) -> dict[int, tuple[float, float]]:
    """Text bands only cover a line of type; a glyph fills the whole row. Grow
    each band out to the midpoint of the gap to its neighbours (the table's own
    edge at the ends) so a crop catches strokes sitting above or below the
    text's baseline."""
    order = sorted(rows, key=lambda r: rows[r][0])
    rects: dict[int, tuple[float, float]] = {}
    for i, row in enumerate(order):
        top, bottom = rows[row]
        upper = table.top if i == 0 else (rows[order[i - 1]][1] + top) / 2
        lower = table.bottom if i == len(order) - 1 else (bottom + rows[order[i + 1]][0]) / 2
        rects[row] = (upper, lower)
    return rects


def empty_glyph_cells(
    cells: list[Cell], placed: dict[tuple[int, int], Box], table: Box
) -> list[tuple[int, int, Box]]:
    """Cells of a glyph column that hold neither text nor a detected picture.

    A column counts as a glyph column once at least one picture landed in it.
    Its remaining body cells are blanks the picture detector missed — ICAO
    Annex 12 p.25 draws "LLL" and arrows as strokes docling files as neither
    picture nor text — so the caller can recover them from the page raster.

    An empty cell has no bbox of its own, so the crop box is built from the
    row's full height crossed with the horizontal extent of the glyphs already
    found in that column, which is far tighter than the column's text band.
    """
    if not placed or not cells:
        return []
    rows = _row_rects(_bands(cells, lambda c: (c.row, c.box.top, c.box.bottom)), table)
    occupied = {(c.row, c.col) for c in cells} | set(placed)
    missing: list[tuple[int, int, Box]] = []
    for col in sorted({col for _, col in placed}):
        seen = [box for (_, c), box in placed.items() if c == col]
        left = min(b.left for b in seen) - GLYPH_PADDING
        right = max(b.right for b in seen) + GLYPH_PADDING
        for row in sorted(r for r in rows if r > 0):
            if (row, col) in occupied:
                continue
            top, bottom = rows[row]
            missing.append((row, col, Box(left=left, top=top, right=right, bottom=bottom)))
    return missing


def inject(table_md: str, placements: dict[tuple[int, int], str]) -> str:
    """Append each placement's markdown to its cell of a pipe table.

    Row 0 is the header, so body row N is markdown line N+1 (the separator
    sits at line 1). Placements addressing a cell the table does not have are
    dropped rather than reshaping the table.
    """
    if not placements:
        return table_md
    lines = table_md.splitlines()
    for (row, col), md in placements.items():
        line_no = row + 1 if row else 0
        if not 0 <= line_no < len(lines) or line_no == 1:
            continue
        parts = lines[line_no].split("|")
        if not 0 <= col + 1 < len(parts) - 1:
            continue
        current = parts[col + 1].strip()
        text = md.replace("|", _PIPE)
        parts[col + 1] = f" {current} {text} ".replace("  ", " ")
        lines[line_no] = "|".join(parts)
    return "\n".join(lines)
