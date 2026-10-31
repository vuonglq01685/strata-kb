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


FOOTER = "Quy chế nhân sự Trang 12/40"
WITH_FOOTER = ORIG.replace("theo\n\nhợp", f"theo\n\n{FOOTER}\n\nhợp")
FOOTER_PDF = wordcheck.pdf_tokens(
    {1: PDF_TEXT.replace("theo hợp", f"theo {FOOTER} hợp")}, {1: [FOOTER]}, 1, 1
)


def test_furniture_line_removed_passes():
    assert (
        wordcheck.check_words(WITH_FOOTER, ORIG, FOOTER_PDF, furniture=[FOOTER]) is None
    )


def test_furniture_line_removed_without_furniture_rejected():
    assert wordcheck.check_words(WITH_FOOTER, ORIG, FOOTER_PDF) is not None


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


# --- ruling 2: positional rules ---

P1 = "Điều 1. Nhân viên làm việc đủ một năm thì được nghỉ phép năm hưởng nguyên lương theo hợp đồng."
P2 = "Điều 2. Người thử việc không được hưởng phụ cấp ăn trưa."


def test_out_of_order_original_dropping_unmatched_paragraph_rejected():
    pdf = pdf_of(f"{P1} {P2}")
    issue = wordcheck.check_words(f"{P2}\n\n{P1}", P1, pdf)
    assert issue is not None and issue.op == "delete"


def test_out_of_order_original_restored_without_negation_rejected():
    pdf = pdf_of(f"{P1} {P2}")
    draft = f"{P1}\n\n{P2.replace('không ', '')}"
    assert wordcheck.check_words(f"{P2}\n\n{P1}", draft, pdf) is not None


def test_out_of_order_original_restored_intact_passes():
    pdf = pdf_of(f"{P1} {P2}")
    assert wordcheck.check_words(f"{P2}\n\n{P1}", f"{P1}\n\n{P2}", pdf) is None


def test_garbled_word_dropped_rejected():
    pdf = pdf_of("Không được hút thuốc.")
    issue = wordcheck.check_words("Khônq được hút thuốc.", "Được hút thuốc.", pdf)
    assert issue is not None and issue.op == "delete"


def test_garbled_number_dropped_rejected():
    pdf = pdf_of("Mức phạt là 500.000 đồng.")
    assert (
        wordcheck.check_words("Mức phạt là 5O0.000 đồng.", "Mức phạt là đồng.", pdf)
        is not None
    )


def test_garbled_word_fixed_to_pdf_word_in_place_passes():
    pdf = pdf_of("Không được hút thuốc.")
    assert (
        wordcheck.check_words("Khônq được hút thuốc.", "Không được hút thuốc.", pdf)
        is None
    )


def test_stray_word_moved_to_new_place_rejected():
    pdf = pdf_of("Nhân viên được nghỉ phép năm. Nhân viên được hút thuốc ở sân.")
    orig = "Nhân viên được nghỉ phép năm. không\n\nNhân viên được hút thuốc ở sân."
    draft = "Nhân viên được nghỉ phép năm.\n\nNhân viên không được hút thuốc ở sân."
    issue = wordcheck.check_words(orig, draft, pdf)
    assert issue is not None and issue.op == "insert"


def test_stray_page_number_moved_into_number_rejected():
    pdf = pdf_of("Thưởng 2 triệu.")
    assert (
        wordcheck.check_words("Thưởng 2 triệu.\n\n10", "Thưởng 2 10 triệu.", pdf)
        is not None
    )


def test_stray_page_number_dropped_with_furniture_passes():
    pdf = wordcheck.pdf_tokens({1: "Thưởng 2 triệu. 10"}, {1: ["10"]}, 1, 1)
    assert (
        wordcheck.check_words(
            "Thưởng 2 triệu.\n\n10", "Thưởng 2 triệu.", pdf, furniture=["10"]
        )
        is None
    )


def test_partial_restore_rejected():
    pdf = pdf_of("Nhân viên không được hút thuốc trong phòng họp.")
    orig = "Nhân viên trong phòng họp."
    issue = wordcheck.check_words(
        orig, "Nhân viên được hút thuốc trong phòng họp.", pdf
    )
    assert issue is not None and issue.op == "insert"


def test_whole_restore_passes():
    pdf = pdf_of("Nhân viên không được hút thuốc trong phòng họp.")
    draft = "Nhân viên không được hút thuốc trong phòng họp."
    assert wordcheck.check_words("Nhân viên trong phòng họp.", draft, pdf) is None


NO_PDF_ORIG = "Điều 1. Nhân viên không được hút thuốc. Điều 2. Lương 12 tháng."


@pytest.mark.parametrize(
    "draft",
    [
        "Điều 1. Nhân viên không được hút thuốc.",
        "Điều 1. Nhân viên được hút thuốc. Điều 2. Lương 12 tháng.",
        "Điều 1. Nhân viên không được hút thuốc. Điều 2. Lương 21 tháng.",
        "Điều 2. Lương 12 tháng. Điều 1. Nhân viên không được hút thuốc.",
        "",
    ],
)
def test_no_pdf_text_changes_rejected(draft):
    issue = wordcheck.check_words(NO_PDF_ORIG, draft, [])
    assert issue is not None and issue.op == "delete"


def test_no_pdf_text_identical_passes():
    assert wordcheck.check_words(NO_PDF_ORIG, NO_PDF_ORIG, []) is None


def test_fallback_heading_id_replaced_passes():
    draft = ORIG.replace("## x1 4.2", "## 4.2")
    assert wordcheck.check_words(ORIG, draft, PDF) is None


def test_heading_id_swapped_for_other_id_rejected():  # ids are only ever deleted
    draft = ORIG.replace("## x1 4.2", "## nghi-phep-nam 4.2")
    assert wordcheck.check_words(ORIG, draft, PDF) is not None


def test_heading_text_word_inserted_rejected():
    draft = ORIG.replace("4.2 NGHỈ PHÉP NĂM", "4.2 KHÔNG NGHỈ PHÉP NĂM")
    assert wordcheck.check_words(ORIG, draft, PDF) is not None


# --- ruling 3: no loopholes in the exemptions ---


def test_heading_word_inserted_rejected():
    pdf = pdf_of("LƯU Ý Nhân viên được hút thuốc.")
    assert wordcheck.check_words("### LƯU Ý", "### KHÔNG LƯU Ý", pdf) is not None


def test_fake_heading_inserting_word_rejected():
    pdf = pdf_of("Nhân viên được hút thuốc.")
    draft = "Nhân viên\n## không\nđược hút thuốc."
    assert wordcheck.check_words("Nhân viên\nđược hút thuốc.", draft, pdf) is not None


def test_fake_heading_inserting_number_rejected():
    pdf = pdf_of("Phạt 5 triệu")
    assert (
        wordcheck.check_words("Phạt\n5 triệu", "Phạt\n## 10\n5 triệu", pdf) is not None
    )


def test_heading_word_dropped_when_heading_not_in_pdf_rejected():
    pdf = pdf_of("Nhân viên được hút thuốc.")
    orig = "## KHÔNG ÁP DỤNG\n\nNhân viên được hút thuốc."
    assert (
        wordcheck.check_words(orig, "## ÁP DỤNG\n\nNhân viên được hút thuốc.", pdf)
        is not None
    )


def test_slug_id_dropped_from_matched_heading_passes():
    pdf = pdf_of("LƯU Ý VỀ PHÉP TỒN Nhân viên được nghỉ phép.")
    orig = "## luu-y-ve-phep-ton LƯU Ý VỀ PHÉP TỒN\n\nNhân viên được nghỉ phép."
    draft = "### LƯU Ý VỀ PHÉP TỒN\n\nNhân viên được nghỉ phép."
    assert wordcheck.check_words(orig, draft, pdf) is None


def test_unicode_slug_id_dropped_from_matched_heading_passes():
    pdf = pdf_of("NGHỈ PHÉP NĂM Nhân viên được nghỉ phép.")
    orig = "## nghỉ-phép-năm NGHỈ PHÉP NĂM\n\nNhân viên được nghỉ phép."
    assert wordcheck.check_words(orig, orig.replace("nghỉ-phép-năm ", ""), pdf) is None


def test_paragraph_line_split_into_heading_passes():
    pdf = pdf_of("4.3 Thủ tục Nhân viên nộp đơn.")
    orig = "4.3 Thủ tục\n\nNhân viên nộp đơn."
    assert (
        wordcheck.check_words(orig, "## 4.3 Thủ tục\n\nNhân viên nộp đơn.", pdf) is None
    )


def test_misplaced_paragraph_negation_dropped_in_place_rejected():
    pdf = pdf_of(f"{P1} {P2}")
    draft = f"{P2.replace('không ', '')}\n\n{P1}"
    assert wordcheck.check_words(f"{P2}\n\n{P1}", draft, pdf) is not None


def test_misplaced_paragraph_negation_dropped_with_matched_negation_elsewhere_rejected():
    p1 = P1 + " Người lao động không được tự ý nghỉ."
    pdf = pdf_of(f"{p1} {P2}")
    draft = f"{P2.replace('không ', '')}\n\n{p1}"
    assert wordcheck.check_words(f"{P2}\n\n{p1}", draft, pdf) is not None


def test_duplicate_paragraph_negation_dropped_rejected():
    d = "Nhân viên không được nghỉ 12 ngày."
    assert wordcheck.check_words(
        f"{d}\n\n{d}", f"{d}\n\n{d.replace('không ', '')}", pdf_of(d)
    )


def test_misplaced_paragraph_replaced_by_pdf_gap_text_rejected():
    pdf = pdf_of(f"Mục A. {P1} {P2}")
    assert wordcheck.check_words(f"{P2}\n\n{P1}", f"Mục A.\n\n{P1}", pdf) is not None


def test_negation_sentence_replaced_by_other_pdf_text_rejected():
    pdf = pdf_of("Ghi chú. Nhân viên được nghỉ phép năm.")
    orig = "Phụ cấp không áp dụng cho thử việc.\n\nNhân viên được nghỉ phép năm."
    draft = "Ghi chú.\n\nNhân viên được nghỉ phép năm."
    assert wordcheck.check_words(orig, draft, pdf) is not None


def test_word_replaced_by_footer_word_rejected():
    pdf = pdf_of("Nhân viên không được hút thuốc. Trang 3")
    orig = "Nhân viên không được hút thuốc."
    assert wordcheck.check_words(orig, orig.replace("không", "Trang"), pdf) is not None


def test_garble_fix_in_place_with_digits_passes():
    pdf = pdf_of("Mức phạt là 500.000 đồng.")
    assert (
        wordcheck.check_words(
            "Mức phạt là 5O0.000 đồng.", "Mức phạt là 500.000 đồng.", pdf
        )
        is None
    )


# --- ruling 4: moved text vs duplicates, id-shaped heading ids only ---

MOVED_PDF = "Nhân viên mới không được nghỉ phép. Khách không được vào kho."
MOVED_ORIG = "Nhân viên không mới được nghỉ phép. Khách không được vào kho."


def test_misplaced_word_dropped_while_same_word_elsewhere_rejected():
    draft = "Nhân viên mới được nghỉ phép. Khách không được vào kho."
    assert wordcheck.check_words(MOVED_ORIG, draft, pdf_of(MOVED_PDF)) is not None


def test_misplaced_word_moved_into_pdf_place_passes():
    assert wordcheck.check_words(MOVED_ORIG, MOVED_PDF, pdf_of(MOVED_PDF)) is None


def test_misplaced_number_dropped_while_same_number_elsewhere_rejected():
    pdf = pdf_of("Mức phạt tối đa 5 triệu đồng. Thời hạn nộp 5 ngày.")
    orig = "Mức phạt 5 tối đa triệu đồng. Thời hạn nộp 5 ngày."
    draft = "Mức phạt tối đa triệu đồng. Thời hạn nộp 5 ngày."
    assert wordcheck.check_words(orig, draft, pdf) is not None


def test_glued_punctuation_heading_chunk_dropped_rejected():
    pdf = pdf_of("Cấm: hút thuốc trong kho. Nhân viên vi phạm bị phạt.")
    orig = "### Cấm: hút thuốc trong kho.\n\nNhân viên vi phạm bị phạt."
    draft = "### hút thuốc trong kho.\n\nNhân viên vi phạm bị phạt."
    assert wordcheck.check_words(orig, draft, pdf) is not None


@pytest.mark.parametrize("chunk", ["500.000đ", "KHÔNG:", "≤5"])
def test_heading_first_chunk_removed_rejected(chunk):
    pdf = pdf_of(f"{chunk} PHỤ CẤP ĂN TRƯA Nhân viên được hưởng.")
    orig = f"## {chunk} PHỤ CẤP ĂN TRƯA\n\nNhân viên được hưởng."
    draft = "## PHỤ CẤP ĂN TRƯA\n\nNhân viên được hưởng."
    assert wordcheck.check_words(orig, draft, pdf) is not None


# --- ruling 5: move and duplicate excuses tied to the PDF ---

MOVED_RESTORE = "Nhân viên mới được nghỉ phép. Khách không được vào kho."
S = "Mức phạt là 5 triệu đồng."
DUP_PDF = f"Điều 1. Đi muộn nhiều lần. {S} Điều 2. Hút thuốc trong kho. {S}"
DUP_ORIG = f"Điều 1. Đi muộn nhiều lần. {S}\n\n{S}\n\nĐiều 2. Hút thuốc trong kho."


def test_move_excuse_needs_whole_gap_restore_elsewhere_rejected():
    pdf = pdf_of(MOVED_PDF)
    orig = "Nhân viên không mới được nghỉ phép."
    assert wordcheck.check_words(orig, MOVED_RESTORE, pdf) is not None


def test_move_excuse_needs_whole_gap_number_restore_rejected():
    pdf = pdf_of("Mức phạt tối đa 5 triệu đồng. Thời hạn nộp 5 ngày.")
    orig = "Mức phạt 5 tối đa triệu đồng."
    draft = "Mức phạt tối đa triệu đồng. Thời hạn nộp 5 ngày."
    assert wordcheck.check_words(orig, draft, pdf) is not None


def test_duplicate_excuse_pdf_repeats_sentence_deduped_rejected():
    draft = f"Điều 1. Đi muộn nhiều lần. {S}\n\nĐiều 2. Hút thuốc trong kho."
    assert wordcheck.check_words(DUP_ORIG, draft, pdf_of(DUP_PDF)) is not None


def test_duplicate_excuse_pdf_repeats_sentence_moved_passes():
    draft = f"Điều 1. Đi muộn nhiều lần. {S}\n\nĐiều 2. Hút thuốc trong kho. {S}"
    assert wordcheck.check_words(DUP_ORIG, draft, pdf_of(DUP_PDF)) is None
