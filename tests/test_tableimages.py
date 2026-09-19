"""Icons drawn inside a table belong in the table's cells, not beside it.

ICAO Annex 12's SAR signal tables have a "Code symbol" column whose cells hold
a glyph image, not text. Docling emits those glyphs as standalone pictures and
leaves the column empty, so the markdown loses which symbol means what. These
tests pin the geometry -> cell mapping and the markdown injection.
"""

from __future__ import annotations

from strata_kb.ingest import tableimages as ti


def _cell(row: int, col: int, left: float, top: float, right: float, bottom: float):
    return ti.Cell(row=row, col=col, box=ti.Box(left=left, top=top, right=right, bottom=bottom))


# Geometry taken from ICAO Annex 12 p.24 table (docling TOPLEFT coordinates).
HEADER = [
    _cell(0, 0, 323.8, 487.9, 336.2, 495.5),  # "No."
    _cell(0, 1, 409.8, 487.9, 442.2, 495.5),  # "Message"
    _cell(0, 2, 521.4, 484.0, 546.8, 499.6),  # "Code symbol"
]
BODY = [
    _cell(1, 0, 327.7, 517.9, 332.1, 525.6),
    _cell(1, 1, 348.0, 517.9, 415.9, 525.6),
    _cell(2, 0, 327.7, 553.9, 332.1, 561.6),
    _cell(2, 1, 348.0, 553.9, 445.6, 561.6),
]
CELLS = HEADER + BODY


def test_locate_maps_a_glyph_to_its_row_and_column():
    # picture 3 on p.24: BOTTOMLEFT t=278.4 b=259.8 -> TOPLEFT 513.6..532.2
    glyph = ti.Box(left=523.3, top=513.6, right=545.2, bottom=532.2)

    assert ti.locate(glyph, CELLS) == (1, 2)


def test_locate_maps_the_second_glyph_to_the_second_row():
    glyph = ti.Box(left=525.7, top=551.7, right=542.1, bottom=566.8)

    assert ti.locate(glyph, CELLS) == (2, 2)


def test_locate_returns_none_for_a_glyph_outside_every_column():
    glyph = ti.Box(left=50.0, top=517.9, right=70.0, bottom=525.6)

    assert ti.locate(glyph, CELLS) is None


def test_locate_returns_none_without_cells():
    assert ti.locate(ti.Box(left=1, top=1, right=2, bottom=2), []) is None


TABLE_MD = "\n".join(
    [
        "|   No. | Message                    | Code symbol   |",
        "|-------|----------------------------|---------------|",
        "|     1 | Require assistance         |               |",
        "|     2 | Require medical assistance |               |",
    ]
)


def test_inject_puts_the_image_in_the_addressed_body_cell():
    out = ti.inject(TABLE_MD, {(1, 2): "![](assets/a.png)", (2, 2): "![](assets/b.png)"})

    lines = out.splitlines()
    assert "![](assets/a.png)" in lines[2] and "Require assistance" in lines[2]
    assert "![](assets/b.png)" in lines[3]
    assert lines[1].startswith("|---")  # separator untouched


def test_inject_keeps_existing_cell_text_and_appends():
    out = ti.inject("| A | B |\n|---|---|\n| 1 | keep |", {(1, 1): "![](x.png)"})

    assert "keep ![](x.png)" in out.splitlines()[2]


def test_inject_escapes_pipes_so_the_row_keeps_its_column_count():
    out = ti.inject(TABLE_MD, {(1, 2): "![a|b](assets/a.png)"})

    assert out.splitlines()[2].count("|") == TABLE_MD.splitlines()[2].count("|")


def test_inject_ignores_placements_outside_the_table():
    out = ti.inject(TABLE_MD, {(9, 2): "![](assets/a.png)", (1, 9): "![](b.png)"})

    assert out == TABLE_MD


def test_inject_without_placements_returns_the_table_unchanged():
    assert ti.inject(TABLE_MD, {}) == TABLE_MD


TABLE_BOX = ti.Box(left=50.0, top=90.0, right=300.0, bottom=220.0)
GRID = [
    _cell(0, 0, 60.0, 100.0, 70.0, 110.0),
    _cell(0, 1, 240.0, 100.0, 290.0, 110.0),  # "Code symbol" header
    _cell(1, 0, 60.0, 150.0, 70.0, 160.0),
    _cell(2, 0, 60.0, 200.0, 70.0, 210.0),
]
GLYPH = ti.Box(left=245.0, top=145.0, right=285.0, bottom=165.0)


def test_empty_glyph_cells_lists_rows_the_detector_missed():
    # Annex 12 p.25: docling detects 4 of the 7 "Code symbol" glyphs. The
    # other three are hand-drawn letters it files as neither picture nor
    # text, so they must be recovered by cropping the page.
    missing = ti.empty_glyph_cells(GRID, placed={(1, 1): GLYPH}, table=TABLE_BOX)

    assert [(row, col) for row, col, _ in missing] == [(2, 1)]


def test_empty_glyph_cell_spans_the_whole_row_not_the_text_line():
    # A row's text bbox is one line tall; the glyph is drawn taller than that,
    # so cropping the text band alone returns a sliver of the stroke.
    (_, _, box), = ti.empty_glyph_cells(GRID, placed={(1, 1): GLYPH}, table=TABLE_BOX)

    assert (box.top, box.bottom) == (180.0, 220.0)  # midpoint of the gap -> table edge


def test_empty_glyph_cell_takes_its_width_from_the_glyphs_already_found():
    (_, _, box), = ti.empty_glyph_cells(GRID, placed={(1, 1): GLYPH}, table=TABLE_BOX)

    assert (box.left, box.right) == (245.0 - ti.GLYPH_PADDING, 285.0 + ti.GLYPH_PADDING)


def test_empty_glyph_cells_ignores_columns_with_no_glyph_at_all():
    assert ti.empty_glyph_cells(GRID, placed={}, table=TABLE_BOX) == []


def test_empty_glyph_cells_skips_rows_that_already_hold_text():
    grid = GRID + [_cell(2, 1, 240.0, 200.0, 290.0, 210.0)]

    assert ti.empty_glyph_cells(grid, placed={(1, 1): GLYPH}, table=TABLE_BOX) == []
