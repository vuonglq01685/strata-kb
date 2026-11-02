from strata_kb.ingest.headingsplit import furniture_set, split_heading

WM = "TÀI LIỆU MẬT"
TITLE = "L2 - ACME - Phân hệ Mẫu · v2.1 · 28/10/2026"
META = ["Phiên bản v2.1 - 28/10/2026", "Trạng thái Bản Nháp", "Owner NguyenVA"]
LINK = "Bản gốc https://example.atlassian.net/wiki/x"
FURN = furniture_set({1: [WM], 2: [WM, "Trang 2/40"]})


def _lines():
    return [(TITLE, 16.0), *((m, 9.0) for m in META), (LINK, 9.0), (f"{WM} {WM}", 9.0)]


def test_header_block_split_into_title_and_body():
    text = " ".join(t for t, _ in _lines())
    assert split_heading(text, _lines(), FURN) == (TITLE, [*META, LINK])


def test_docling_text_without_the_watermark_still_splits():
    text = " ".join(t for t, _ in _lines()[:-1])
    assert split_heading(text, _lines(), FURN) == (TITLE, [*META, LINK])


def test_wrapped_title_kept():
    lines = [("Quy định chung về quản lý", 14.0), ("tài liệu kỹ thuật", 14.0)]
    assert (
        split_heading("Quy định chung về quản lý tài liệu kỹ thuật", lines, FURN)
        is None
    )


def test_single_line_kept():
    assert split_heading(TITLE, [(TITLE, 16.0)], FURN) is None


def test_other_text_in_the_box_blocks_the_split():
    lines = [(TITLE, 16.0), ("Đoạn văn bên cạnh", 9.0)]
    assert split_heading(TITLE, lines, FURN) is None


def test_link_line_is_body_even_at_title_size():
    lines = [(TITLE, 16.0), (LINK, 16.0)]
    assert split_heading(f"{TITLE} {LINK}", lines, FURN) == (TITLE, [LINK])


def test_watermark_dropped_from_a_one_line_title():
    lines = [(TITLE, 16.0), (WM, 16.0)]
    assert split_heading(f"{TITLE} {WM}", lines, FURN) == (TITLE, [])
