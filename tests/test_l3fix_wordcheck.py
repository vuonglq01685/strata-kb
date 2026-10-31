from __future__ import annotations

import pytest

from strata_kb.l3check import wordcheck


def pdf_of(text: str) -> list[str]:
    return wordcheck.pdf_tokens({1: text}, {}, 1, 1)


PDF_TEXT = (
    "4.2 NGHỈ PHÉP NĂM Người lao động làm việc đủ 12 tháng được nghỉ phép năm "
    "hưởng nguyên lương theo hợp đồng"
)
PDF = pdf_of(PDF_TEXT)
ORIG = (
    "## x1 4.2 NGHỈ PHÉP NĂM\n\nNgười lao động làm việc đủ 12 tháng được nghỉ phép năm "
    "hưởng nguyên lương theo\n\nhợp đồng"
)


def test_structure_only_passes():  # re-id + join
    draft = (
        "## 4.2 NGHỈ PHÉP NĂM\n\nNgười lao động làm việc đủ 12 tháng được nghỉ phép năm "
        "hưởng nguyên lương theo hợp đồng"
    )
    assert wordcheck.check_words(ORIG, draft, PDF) is None


def test_inserted_negation_rejected():
    issue = wordcheck.check_words(
        ORIG, ORIG.replace("được nghỉ", "không được nghỉ"), PDF
    )
    assert issue is not None and issue.op == "insert"
    assert "không" in issue.draft


def test_replaced_word_rejected():
    issue = wordcheck.check_words(ORIG, ORIG.replace("12 tháng", "6 tháng"), PDF)
    assert issue is not None and issue.op == "replace"
    assert issue.original.split()[0] == "12"


def test_garbled_word_fixed_to_pdf_passes():
    garbled = ORIG.replace("nguyên lương", "nguyen luong")
    assert wordcheck.check_words(garbled, ORIG, PDF) is None


def test_dropped_sentence_rejected():
    issue = wordcheck.check_words(ORIG, "## 4.2 NGHỈ PHÉP NĂM\n", PDF)
    assert issue is not None and issue.op == "delete"


def test_duplicate_paragraph_removed_passes():
    dup = ORIG + "\n\n" + ORIG.split("\n\n", 1)[1]
    assert wordcheck.check_words(dup, ORIG, PDF) is None


def test_furniture_line_removed_passes():
    with_footer = ORIG.replace(
        "theo\n\nhợp", "theo\n\nQuy chế nhân sự Trang 12/40\n\nhợp"
    )
    assert wordcheck.check_words(with_footer, ORIG, PDF) is None


def test_trailing_paragraph_dropped_rejected():
    pdf = pdf_of(PDF_TEXT + " Đoạn cuối có thật")
    assert wordcheck.check_words(ORIG + "\n\nĐoạn cuối có thật", ORIG, pdf) is not None


def test_sentence_moved_rejected():
    moved = ORIG.replace(
        "làm việc đủ 12 tháng được nghỉ phép năm",
        "được nghỉ phép năm làm việc đủ 12 tháng",
    )
    assert moved != ORIG
    assert wordcheck.check_words(ORIG, moved, PDF) is not None


def test_empty_draft_rejected():
    issue = wordcheck.check_words(ORIG, "", PDF)
    assert issue is not None and issue.op == "delete"


def test_identical_passes():
    assert wordcheck.check_words(ORIG, ORIG, PDF) is None


def test_issue_fields_capped_at_20_tokens():
    long = " ".join(f"w{i}" for i in range(50))
    deleted = wordcheck.check_words(long, "", pdf_of(long))
    assert deleted is not None and len(deleted.original.split()) <= 20
    inserted = wordcheck.check_words(
        long, long + " " + " ".join(f"x{i}" for i in range(30)), pdf_of(long)
    )
    assert inserted is not None and 0 < len(inserted.draft.split()) <= 20


# --- review false negatives: all must be rejected ---


def test_edge_delete_of_recurring_word_rejected():
    text = "Không được hút thuốc trong phòng họp. Nhân viên không được mang thức ăn vào kho."
    issue = wordcheck.check_words(text, text.split(" ", 1)[1], pdf_of(text))
    assert issue is not None and issue.op == "delete"


def test_trailing_sentence_with_garbled_word_dropped_rejected():
    orig = "Điều 5 Nghỉ phép năm là 12 ngày.\n\nĐiều 6 Người lao động không đươc nghỉ quá 3 ngày."
    pdf = pdf_of(
        "Điều 5 Nghỉ phép năm là 12 ngày. Điều 6 Người lao động không được nghỉ quá 3 ngày."
    )
    assert (
        wordcheck.check_words(orig, "Điều 5 Nghỉ phép năm là 12 ngày.", pdf) is not None
    )


def test_leading_sentence_with_garbled_word_dropped_rejected():
    orig = "Khônq được hút thuốc trong phòng họp. Nhân viên mang thẻ."
    pdf = pdf_of("Không được hút thuốc trong phòng họp. Nhân viên mang thẻ.")
    assert wordcheck.check_words(orig, "Nhân viên mang thẻ.", pdf) is not None


def test_neighbour_text_appended_rejected():
    pdf = pdf_of("Câu một nói về lương. Câu hai nói về thưởng. Câu ba nói về phạt.")
    orig = "Câu một nói về lương. Câu hai nói về thưởng."
    neighbour = "Câu ba nói về phạt."
    issue = wordcheck.check_words(orig, orig + " " + neighbour, pdf, neighbour)
    assert issue is not None and issue.op == "insert"


def test_neighbour_text_prepended_rejected():
    pdf = pdf_of("Câu ba nói về phạt. Câu một nói về lương. Câu hai nói về thưởng.")
    orig = "Câu một nói về lương. Câu hai nói về thưởng."
    neighbour = "Câu ba nói về phạt."
    assert (
        wordcheck.check_words(orig, neighbour + " " + orig, pdf, neighbour) is not None
    )


def test_number_changed_to_one_elsewhere_in_span_rejected():
    pdf = pdf_of(
        "Mục 1. Theo quy định tại khoản 1 Điều 5 của Luật này. "
        "Theo quy định tại khoản 2 Điều 5 của Luật này."
    )
    orig = "Mục 1. Theo quy định tại khoản 1 Điều 5 của Luật này."
    assert (
        wordcheck.check_words(orig, orig.replace("khoản 1", "khoản 2"), pdf) is not None
    )


def test_mid_sentence_negation_removed_rejected():
    text = (
        "A. nhân viên thử việc không được nghỉ phép năm. "
        "B. nhân viên thử việc được nghỉ phép năm. Nhân viên không được hút thuốc."
    )
    orig = "A. nhân viên thử việc không được nghỉ phép năm. Nhân viên không được hút thuốc."
    draft = orig.replace("thử việc không được", "thử việc được")
    assert wordcheck.check_words(orig, draft, pdf_of(text)) is not None


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("nhiệt độ ≤ 5 °C", "nhiệt độ ≥ 5 °C"),
        ("nhiệt độ -5 độ", "nhiệt độ 5 độ"),
        ("mức phạt 5% giá trị", "mức phạt 5 giá trị"),
        ("lương 1.500 đồng", "lương 1,500 đồng"),
    ],
)
def test_symbol_change_rejected(before, after):
    assert wordcheck.check_words(before, after, pdf_of(before)) is not None


def test_paragraphs_reordered_out_of_pdf_order_rejected():
    pdf = pdf_of("Đoạn một nói về lương cơ bản. Đoạn hai nói về thưởng tết.")
    orig = "Đoạn một nói về lương cơ bản.\n\nĐoạn hai nói về thưởng tết."
    swapped = "Đoạn hai nói về thưởng tết.\n\nĐoạn một nói về lương cơ bản."
    assert wordcheck.check_words(orig, swapped, pdf) is not None


# --- allowed changes ---


def test_paragraphs_put_back_into_pdf_order_passes():
    pdf = pdf_of("Đoạn một nói về lương cơ bản. Đoạn hai nói về thưởng tết.")
    orig = "Đoạn hai nói về thưởng tết.\n\nĐoạn một nói về lương cơ bản."
    fixed = "Đoạn một nói về lương cơ bản.\n\nĐoạn hai nói về thưởng tết."
    assert wordcheck.check_words(orig, fixed, pdf) is None


def test_bullet_marker_style_change_passes():
    pdf = pdf_of("Danh mục:\n• mục một\n• mục hai")
    orig = "Danh mục:\n\n• mục một\n\n• mục hai"
    assert (
        wordcheck.check_words(orig, "Danh mục:\n\n- mục một\n\n- mục hai", pdf) is None
    )


def test_restoring_missing_pdf_text_passes():
    orig = ORIG.replace(" hưởng nguyên lương", "")
    assert wordcheck.check_words(orig, ORIG, PDF) is None


def test_uncovered_share():
    garbage = "xq zv bn mk lp wr ty uo ia sd fg hj kl zx cv bn"
    assert wordcheck.uncovered_share(garbage, PDF) == 1.0
    assert wordcheck.uncovered_share(ORIG, PDF) < 0.3
    assert wordcheck.uncovered_share(ORIG, []) == 1.0
    assert wordcheck.uncovered_share("", PDF) == 0.0


def test_pdf_tokens_pick_pages_and_drop_furniture():
    pages = {1: "Header A one two", 2: "three four", 3: "five", 5: "six"}
    furniture = {1: ["Header A"]}
    assert wordcheck.pdf_tokens(pages, furniture, 1, 3) == [
        "one",
        "two",
        "three",
        "four",
        "five",
    ]
    assert wordcheck.pdf_tokens(pages, furniture, 2, None) == ["three", "four"]
    assert wordcheck.pdf_tokens(pages, furniture, 4, 6) == ["six"]
    assert wordcheck.pdf_tokens(pages, furniture, None, None) == []


def test_prose_tokens_keep_symbols_and_drop_bullets():
    assert wordcheck.prose_tokens("- a ≤ -5 và 5% (1.500)\n\n• b") == [
        "a",
        "≤",
        "-5",
        "và",
        "5%",
        "(",
        "1.500",
        ")",
        "b",
    ]
    assert wordcheck.prose_tokens("## Tiêu **Đề**") == ["tiêu", "đề"]
    assert wordcheck.prose_tokens("cắt-\nđôi") == ["cắtđôi"]
