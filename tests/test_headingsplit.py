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


def test_small_watermark_dropped_from_a_one_line_title():
    lines = [(TITLE, 16.0), (WM, 9.0)]
    assert split_heading(f"{TITLE} {WM}", lines, FURN) == (TITLE, [])


def test_title_size_watermark_left_for_lint_r9():
    # never drop a title-size line here; R9 flags the furniture ending the heading
    lines = [(TITLE, 16.0), (WM, 16.0)]
    assert split_heading(f"{TITLE} {WM}", lines, FURN) is None


def test_title_equal_to_running_header_is_kept():
    furn = furniture_set({2: ["Strata Architecture"], 3: ["24"], 20: ["20"]})
    lines = [("Strata Architecture", 24.0), ("Version 1.2", 10.0), ("2024", 10.0)]
    assert split_heading("Strata Architecture Version 1.2 2024", lines, furn) == (
        "Strata Architecture",
        ["Version 1.2", "2024"],
    )


def test_page_numbers_never_count_as_furniture():
    assert furniture_set({1: ["12", "Trang 12/40"]}) == {("trang", "12", "40")}
