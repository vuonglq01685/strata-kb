from strata_kb import models, quality
from strata_kb.quality import (
    Finding,
    budget,
    check_doc,
    check_section,
    digest,
    is_brief,
    is_table_only,
    prose_only,
)

SLICE = (
    "## 5.7 Route Type\n\n"
    "Prose line one.\n\n"
    "| Code | Meaning |\n|---|---|\n| O | Official |\n\n"
    "[table omitted]\n\n"
    "Figure: Holding pattern entry sectors\n\n"
    "![Holding](assets/" + "a" * 64 + ".png)\n\n"
    "<!-- TODO:summarize 5.7 -->\n\n"
    "Prose line two.\n"
)


def test_prose_only_keeps_prose_and_drops_everything_else():
    assert prose_only(SLICE) == "Prose line one.\n\nProse line two."


def test_prose_only_collapses_blank_runs_and_strips():
    assert prose_only("\n\nA\n\n\n\nB\n\n") == "A\n\nB"


def test_prose_only_empty_for_table_only_slice():
    assert prose_only("## 2 T\n\n| h |\n|---|\n| v |\n") == ""


def test_budget_floor_and_ratio():
    assert budget(201) == 120            # floor wins
    assert budget(2000) == 700           # 0.35 ratio wins
    assert budget(342) == 120            # int(0.35*342)=119 < floor


def test_brief_and_table_only_boundaries():
    assert is_table_only(0) and not is_brief(0)
    assert is_brief(1) and is_brief(200)
    assert not is_brief(201) and not is_table_only(201)


def test_digest_is_sha256_hex_of_utf8():
    assert digest("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_finding_text_marks_quality_level():
    q = Finding("ratio", "d §1", "d §1: too long", "quality")
    e = Finding("l0-empty", "d", "d: empty", "error")
    assert q.text == "d §1: too long (quality)"
    assert e.text == "d: empty"


def test_labels_are_exact():
    assert quality.TABLE_ONLY_LABEL.format(title="X") == "Table-only section: X."
    assert quality.BRIEF_LABEL.format(title="X") == "Brief section: X."
    assert quality.TABLE_PLACEHOLDER == "[table omitted]"


LONG_PROSE = " ".join(f"Sentence number {i} explains the record layout." for i in range(12))  # > 200 chars


def _sec(summary="Covers the record layout.", title="Route Type"):
    return models.SectionEntry(id="5.7", title=title, summary=summary, status="summarized", file="ch5")


def _codes(findings):
    return sorted(f.code for f in findings)


def test_clean_section_has_no_findings():
    l3 = f"## 5.7 Route Type\n\n{LONG_PROSE}\n"
    l2 = "## 5.7 Route Type\n\nSentence number 1 explains the record layout.\n"
    assert check_section("d §5.7", _sec(), l2, l3) == []


def test_ratio_fires_when_l2_exceeds_budget():
    l3 = f"## 5.7 Route Type\n\n{LONG_PROSE}\n"
    l2 = f"## 5.7 Route Type\n\n{LONG_PROSE}\n"          # 1.0× — over 0.35
    f = check_section("d §5.7", _sec(), l2, l3)
    assert _codes(f) == ["ratio"] and f[0].level == "quality"
    assert f[0].text.endswith("(quality)")


def test_l2_empty_fires_when_prose_deleted():
    l3 = f"## 5.7 Route Type\n\n{LONG_PROSE}\n"
    l2 = "## 5.7 Route Type\n"
    assert _codes(check_section("d §5.7", _sec(), l2, l3)) == ["l2-empty"]


def test_brief_section_must_be_verbatim_and_labelled():
    l3 = "## 5.320 HAL\n\nUsed On: PA\nLength: 3\n"
    ok_l2 = "## 5.320 HAL\n\nUsed On: PA\nLength: 3\n"
    good = _sec(summary="Brief section: HAL.", title="HAL")
    assert check_section("d §5.320", good, ok_l2, l3) == []
    bad_l2 = "## 5.320 HAL\n\nThis header contains only field usage metadata.\n"
    bad = _sec(summary="Explains HAL metadata.", title="HAL")
    assert _codes(check_section("d §5.320", bad, bad_l2, l3)) == ["brief-label", "brief-verbatim"]


def test_table_only_section_label_and_empty_prose():
    l3 = "## 5.9 T\n\n| h |\n|---|\n| v |\n"
    good = _sec(summary="Table-only section: T.", title="T")
    assert check_section("d §5.9", good, "## 5.9 T\n\n| h |\n|---|\n| v |\n", l3) == []
    bad = _sec(summary="Describes the table.", title="T")
    l2 = "## 5.9 T\n\nThe table lists v.\n\n| h |\n|---|\n| v |\n"
    assert "table-only-label" in _codes(check_section("d §5.9", bad, l2, l3))


def test_table_transcription_fires_on_four_cells_in_one_sentence():
    table = (
        "| Route type | Code |\n|---|---|\n"
        "| Officially Designated Airways | O |\n| Airline Airway | A |\n"
        "| Common Portion | C |\n| Non-common Portion | N |\n"
    )
    l3 = f"## 5.7 Route Type\n\n{LONG_PROSE}\n\n{table}"
    l2 = (
        "## 5.7 Route Type\n\nOfficially Designated Airways O, Airline Airway A, "
        f"Common Portion C, Non-common Portion N.\n\n{table}"
    )
    assert "table-transcription" in _codes(check_section("d §5.7", _sec(), l2, l3))


def test_table_transcription_ignores_short_and_numeric_cells():
    table = "| A | 1 |\n|---|---|\n| B | 2 |\n| C | 3 |\n| D | 4 |\n"
    l3 = f"## 5.7 T\n\n{LONG_PROSE}\n\n{table}"
    l2 = f"## 5.7 T\n\nA B C D 1 2 3 4 in one sentence.\n\n{table}"
    assert "table-transcription" not in _codes(check_section("d §5.7", _sec(), l2, l3))


def test_invented_code_fires_for_uppercase_token_absent_from_l3():
    l3 = f"## 5.99 Marker\n\n{LONG_PROSE} Column 18 holds I and column 19 holds M.\n"
    l2 = "## 5.99 Marker\n\nThe codes IM, MM, OM and BM mark the marker type.\n"
    f = [x for x in check_section("d §5.99", _sec(), l2, l3) if x.code == "invented-code"]
    assert len(f) == 1 and "BM" in f[0].message and "IM" in f[0].message


def test_invented_code_accepts_codes_that_live_in_a_table():
    table = "| Code | Meaning |\n|---|---|\n| CTAF | common frequency |\n"
    l3 = f"## 5.101 F\n\n{LONG_PROSE}\n\n{table}"
    l2 = f"## 5.101 F\n\nCTAF is listed.\n\n{table}"
    assert "invented-code" not in _codes(check_section("d §5.101", _sec(), l2, l3))


def test_lexical_overlap_fires_on_unrelated_or_translated_prose():
    l3 = f"## 5.263 HAL\n\n{LONG_PROSE}\n"
    l2 = (
        "## 5.263 HAL\n\nPhần này chỉ chứa siêu dữ liệu về cách dùng trường, "
        "không có định nghĩa hay ghi chú nguồn nào trong văn bản trích xuất, "
        "và vì vậy không thể tóm tắt thêm được nữa ở đây.\n"
    )
    assert "lexical-overlap" in _codes(check_section("d §5.263", _sec(), l2, l3))


def test_lexical_overlap_skipped_for_short_l2():
    l3 = f"## 5.1 A\n\n{LONG_PROSE}\n"
    l2 = "## 5.1 A\n\nTotally unrelated words here.\n"   # < 20 words
    assert "lexical-overlap" not in _codes(check_section("d §5.1", _sec(), l2, l3))


def test_l1_words_fires_above_25():
    l3 = f"## 5.1 A\n\n{LONG_PROSE}\n"
    l2 = "## 5.1 A\n\nSentence number 1 explains the record layout.\n"
    sec = _sec(summary=" ".join(["word"] * 26))
    assert _codes(check_section("d §5.1", sec, l2, l3)) == ["l1-words"]


def test_check_doc_empty_summary_is_an_error_and_long_summary_is_quality():
    empty = models.IndexEntry(id="d", title="D", summary="  ")
    long = models.IndexEntry(id="d", title="D", summary=" ".join(["w"] * 31))
    ok = models.IndexEntry(id="d", title="D", summary="One sentence.")
    assert [f.code for f in check_doc(empty)] == ["l0-empty"]
    assert check_doc(empty)[0].level == "error"
    assert [f.code for f in check_doc(long)] == ["l0-words"]
    assert check_doc(ok) == []


# --- fix round 1 regression tests -----------------------------------------


def test_ratio_no_finding_when_l2_is_under_the_floor_in_the_floor_band():
    # n3=250 is in the 201..342 floor band: budget(250) = max(120, 87) = 120.
    l3 = f"## 5.7 X\n\n{'X' * 250}\n"
    l2 = f"## 5.7 X\n\n{'X' * 110}\n"
    assert check_section("d §5.7", _sec(), l2, l3) == []


def test_ratio_message_reports_the_floor_not_a_false_35_percent_of_n3():
    # Same floor band; L2 now exceeds the 120-char floor, so ratio must fire
    # and the message must show the true floor-derived budget, not "35% of 250".
    l3 = f"## 5.7 X\n\n{'X' * 250}\n"
    l2 = f"## 5.7 X\n\n{'X' * 130}\n"
    f = check_section("d §5.7", _sec(), l2, l3)
    assert _codes(f) == ["ratio"]
    assert f[0].message == "d §5.7: L2 prose 130 chars > budget 120 (max(120, 35% of 250))"


def test_invented_code_uses_word_boundary_not_substring_containment():
    # "OM" is a substring of "FROM" but never occurs as its own token in L3 —
    # a naive `t not in l3_slice` check would wrongly accept it.
    l3 = f"## 5.50 Q\n\n{LONG_PROSE} Data FROM the header appears here.\n"
    l2 = "## 5.50 Q\n\nThe code OM marks this record.\n"
    f = [x for x in check_section("d §5.50", _sec(), l2, l3) if x.code == "invented-code"]
    assert len(f) == 1 and "OM" in f[0].message


def test_table_cells_ignores_punctuated_numeric_values():
    table = "| A | B |\n|---|---|\n| 1,000 | 12% |\n| -3 | 08/24 |\n"
    assert quality._table_cells(table) == set()


# --- Ruling R17: brief/table-only short-circuit ---------------------------


def test_brief_verbatim_section_with_table_transcription_shape_is_clean():
    """(a) the reviewer's repro: L3 prose <= 200 chars containing 4
    uppercase codes that ALSO appear as table cells; a verbatim, labelled
    L2 copy must yield [] -- a verbatim copy cannot 'transcribe' a table
    it is required to carry word-for-word."""
    table = (
        "| Route type | Code |\n|---|---|\n"
        "| Officially Designated Airways | O |\n| Airline Airway | A |\n"
        "| Common Portion | C |\n| Non-common Portion | N |\n"
    )
    prose = (
        "Officially Designated Airways O, Airline Airway A, "
        "Common Portion C, Non-common Portion N."
    )
    assert len(prose) <= 200
    l3 = f"## 5.7 Route Type\n\n{prose}\n\n{table}"
    l2 = f"## 5.7 Route Type\n\n{prose}\n\n{table}"
    sec = _sec(summary="Brief section: Route Type.", title="Route Type")
    assert check_section("d §5.7", sec, l2, l3) == []


def test_table_only_section_with_label_only_l2_is_clean():
    """(b) invariant: a table-only section (zero L3 prose) whose L2 is
    the empty-prose label yields []."""
    l3 = "## 5.9 T\n\n| h |\n|---|\n| v |\n"
    l2 = "## 5.9 T\n\n| h |\n|---|\n| v |\n"
    sec = _sec(summary="Table-only section: T.", title="T")
    assert check_section("d §5.9", sec, l2, l3) == []


def test_brief_section_not_verbatim_still_flags_brief_verbatim():
    """(c) a brief section whose L2 is NOT verbatim still yields
    brief-verbatim -- the short-circuit only fires once the length/label
    check has already passed."""
    l3 = "## 5.320 HAL\n\nUsed On: PA\nLength: 3\n"
    l2 = "## 5.320 HAL\n\nThis header contains only field usage metadata.\n"
    sec = _sec(summary="Brief section: HAL.", title="HAL")
    assert "brief-verbatim" in _codes(check_section("d §5.320", sec, l2, l3))


# --- Minor A4: fixed brief/table-only labels never count as l1-words ------


def test_l1_words_exempts_brief_label_even_when_title_is_long():
    long_title = " ".join(["Word"] * 30)
    l3 = "## 5.1 A\n\nShort prose body.\n"
    l2 = "## 5.1 A\n\nShort prose body.\n"
    sec = _sec(summary=quality.BRIEF_LABEL.format(title=long_title), title=long_title)
    assert "l1-words" not in _codes(check_section("d §5.1", sec, l2, l3))


def test_l1_words_exempts_table_only_label_even_when_title_is_long():
    long_title = " ".join(["Word"] * 30)
    l3 = "## 5.9 T\n\n| h |\n|---|\n| v |\n"
    l2 = "## 5.9 T\n\n| h |\n|---|\n| v |\n"
    sec = _sec(summary=quality.TABLE_ONLY_LABEL.format(title=long_title), title=long_title)
    assert "l1-words" not in _codes(check_section("d §5.9", sec, l2, l3))
