from __future__ import annotations

from strata_kb.l3check import wordcheck
from strata_kb.l3check.detect import normalize_words

PDF = normalize_words(
    "4.2 NGHỈ PHÉP NĂM Người lao động làm việc đủ 12 tháng được nghỉ phép năm "
    "hưởng nguyên lương theo hợp đồng"
)
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
    assert issue.original == "12"


def test_garbled_word_fixed_to_pdf_passes():
    garbled = ORIG.replace("nguyên lương", "nguyen luong")
    assert wordcheck.check_words(garbled, ORIG, PDF) is None


def test_dropped_sentence_rejected():
    assert wordcheck.check_words(ORIG, "## 4.2 NGHỈ PHÉP NĂM\n", PDF) is not None


def test_duplicate_paragraph_removed_passes():
    dup = ORIG + "\n\n" + ORIG.split("\n\n", 1)[1]
    assert wordcheck.check_words(dup, ORIG, PDF) is None


def test_furniture_line_removed_passes():
    with_footer = ORIG.replace(
        "theo\n\nhợp", "theo\n\nQuy chế nhân sự Trang 12/40\n\nhợp"
    )
    assert wordcheck.check_words(with_footer, ORIG, PDF) is None


def test_trailing_paragraph_dropped_rejected():
    pdf = PDF + normalize_words("Đoạn cuối có thật")
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


def test_issue_windows_capped_at_20_words():
    long = " ".join(f"w{i}" for i in range(50))
    issue = wordcheck.check_words(long, "", [])
    assert issue is not None and len(issue.original.split()) <= 20


def test_uncovered_share():
    garbage = "xq zv bn mk lp wr ty uo ia sd fg hj kl zx cv bn"
    assert wordcheck.uncovered_share(garbage, PDF) == 1.0
    assert wordcheck.uncovered_share(ORIG, PDF) < 0.3
    assert wordcheck.uncovered_share(ORIG, []) == 1.0


def test_span_words_picks_pages_and_drops_furniture():
    pages = {1: "Header A one two", 2: "three four", 3: "five", 5: "six"}
    furniture = {1: ["Header A"]}
    assert wordcheck.span_words(pages, furniture, 1, 3) == [
        "one",
        "two",
        "three",
        "four",
        "five",
    ]
    assert wordcheck.span_words(pages, furniture, 2, None) == ["three", "four"]
    assert wordcheck.span_words(pages, furniture, 4, 6) == ["six"]
    assert wordcheck.span_words(pages, furniture, None, None) == []


def test_prose_words_normalises_markdown():
    assert wordcheck.prose_words("## Tiêu Đề\n\n**Đậm** [link](http://x)") == [
        "tiêu",
        "đề",
        "đậm",
        "link",
    ]
