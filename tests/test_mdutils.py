from strata_kb import mdutils, models

CHAPTER_MD = """## 5.1 Airport Records

Intro text for airports.

## 5.3 Restrictive Airspace

Body of restrictive airspace.

| Code | Meaning  |
|------|----------|
| P    | Prohibited |
| R    | Restricted |

## 5.4 Something Else

Tail content.
"""


def test_count_tokens_positive_and_monotonic():
    short = mdutils.count_tokens("restrictive airspace")
    long = mdutils.count_tokens("restrictive airspace " * 50)
    assert 0 < short < long


def test_slice_section_returns_only_that_section():
    block = mdutils.slice_section(CHAPTER_MD, "5.3")
    assert block is not None
    assert block.startswith("## 5.3 Restrictive Airspace")
    assert "Prohibited" in block
    assert "Airport Records" not in block
    assert "Something Else" not in block


def test_slice_section_last_section_runs_to_eof():
    block = mdutils.slice_section(CHAPTER_MD, "5.4")
    assert block is not None
    assert "Tail content." in block


def test_slice_section_missing_returns_none():
    assert mdutils.slice_section(CHAPTER_MD, "9.9") is None


def test_extract_tables_finds_table():
    tables = mdutils.extract_tables(CHAPTER_MD)
    assert len(tables) == 1
    assert "Prohibited" in tables[0]


def test_normalize_table_ignores_formatting_differences():
    a = "| Code | Meaning |\n|---|---|\n| P | Prohibited |"
    b = "| Code   | Meaning    |\n|------|----------|\n| P    | Prohibited |"
    assert mdutils.normalize_table(a) == mdutils.normalize_table(b)


def test_normalize_table_detects_value_change():
    a = "| Code | Meaning |\n|---|---|\n| P | Prohibited |"
    b = "| Code | Meaning |\n|---|---|\n| P | Permitted |"
    assert mdutils.normalize_table(a) != mdutils.normalize_table(b)


def test_slugify_id_keeps_cjk():
    assert mdutils.slugify_id("表5-6 データ概要") == "表5-6-データ概要"


def test_slugify_id_keeps_cyrillic():
    assert mdutils.slugify_id("ЧАСТЬ 1") == "часть-1"


def test_slugify_id_keeps_vietnamese_diacritics():
    assert mdutils.slugify_id("Bảng tổng hợp dữ liệu") == "bảng-tổng-hợp-dữ-liệu"


def test_slugify_id_strips_symbols_and_underscores():
    assert mdutils.slugify_id("__Table: 5-6 (final)__") == "table-5-6-final"


def test_slugify_id_empty_when_no_word_chars():
    assert mdutils.slugify_id("***") == ""


def test_slugify_id_caps_at_40_chars():
    out = mdutils.slugify_id("a" * 80)
    assert out == "a" * 40


UNIT_MD = """## 3.2 Fasteners

Intro prose of 3.2.

### 3.2.1 Torque values

Torque 12 Nm for bolt XYZ-9.

### 3.2.2 Washers

Washer spec text.

## 3.3 Next section

Other text.
"""


def test_slice_subsection_returns_folded_child():
    block = mdutils.slice_subsection(UNIT_MD, "3.2.1")
    assert block is not None
    assert block.startswith("### 3.2.1 Torque values")
    assert "Torque 12 Nm" in block
    assert "Washer spec" not in block


def test_slice_subsection_last_child_runs_to_next_h2():
    block = mdutils.slice_subsection(UNIT_MD, "3.2.2")
    assert block is not None
    assert "Washer spec text." in block
    assert "Next section" not in block


def test_slice_subsection_missing_returns_none():
    assert mdutils.slice_subsection(UNIT_MD, "9.9.9") is None


def test_extract_image_descs_standalone_only_ordered_deduped():
    from strata_kb.mdutils import extract_image_descs

    sha_a, sha_b, sha_c = "a" * 64, "b" * 64, "c" * 64
    md = "\n".join([
        f"![Holding pattern](assets/{sha_a}.webp)",
        "Some text.",
        f"| ![VOR](assets/{sha_b}.png) | VOR |",          # table icon: excluded
        f"![](assets/{sha_c}.png)",                        # empty alt: excluded
        f"![Holding pattern](assets/{sha_a}.webp)",        # duplicate: excluded
        "![not an asset](http://x/y.png)",                 # non-asset ref: excluded
    ])
    assert extract_image_descs(md) == ["Holding pattern"]


def test_slice_section_finds_heading_with_empty_title():
    md = "## 5.14 Fix Type\n\nFix body.\n\n## 5.15\n\nOrphan body.\n\n## 5.16 Real Field\n\nReal body.\n"
    assert mdutils.slice_section(md, "5.15") == "## 5.15\n\nOrphan body."
    assert mdutils.slice_section(md, "5.16") == "## 5.16 Real Field\n\nReal body."


def test_slice_subsection_finds_heading_with_empty_title():
    md = "## 5 NAV\n\nIntro.\n\n### 5.15\n\nFolded body.\n\n### 5.16 Next\n\nNext body.\n"
    assert mdutils.slice_subsection(md, "5.15") == "### 5.15\n\nFolded body."


from strata_kb.mdutils import extract_tables, heading_ids


def test_extract_tables_keeps_one_line_block():
    md = "## 1 T\n\n| only header |\n\ntext\n"
    assert extract_tables(md) == ["| only header |"]


def test_extract_tables_skips_fenced_pipe_lines():
    md = "```\n| a | b |\n```"
    assert extract_tables(md) == []


def test_extract_tables_finds_table_after_closed_fence():
    md = "```\ncode\n```\n| a | b |\n|---|---|\n| 1 | 2 |"
    assert extract_tables(md) == ["| a | b |\n|---|---|\n| 1 | 2 |"]


def test_extract_tables_unclosed_fence_swallows_rest():
    md = "```\n| a | b |\n| c | d |"
    assert extract_tables(md) == []


def test_heading_ids_in_order_ignores_subheadings():
    md = "## 1.1 A\n\n### 1.1.1 child\n\n## 1.2 B\n\n## 1.3\n"
    assert heading_ids(md) == ["1.1", "1.2", "1.3"]


DUPLICATE_ID_MD = "## 1.1 Part A\n\nBody A.\n\n## 1.1 Part B\n\nBody B.\n"


def test_slice_section_occurrence_default_matches_first():
    assert mdutils.slice_section(DUPLICATE_ID_MD, "1.1") == mdutils.slice_section(
        DUPLICATE_ID_MD, "1.1", occurrence=0
    )
    assert mdutils.slice_section(DUPLICATE_ID_MD, "1.1", occurrence=0).startswith(
        "## 1.1 Part A"
    )


def test_slice_section_occurrence_returns_nth_match():
    block = mdutils.slice_section(DUPLICATE_ID_MD, "1.1", occurrence=1)
    assert block is not None
    assert block.startswith("## 1.1 Part B")
    assert "Body A." not in block


def test_slice_section_occurrence_out_of_range_returns_none():
    assert mdutils.slice_section(DUPLICATE_ID_MD, "1.1", occurrence=2) is None


FENCED_MD = (
    "## 1.1 Real\n\nBody.\n\n"
    "```text\n## not a heading\n```\n\n"
    "## 1.2 Another\n\nMore.\n"
)


def test_heading_ids_fence_aware_skips_headings_inside_backtick_fence():
    assert heading_ids(FENCED_MD, fence_aware=True) == ["1.1", "1.2"]


def test_heading_ids_default_is_fence_naive_back_compat():
    assert heading_ids(FENCED_MD) == ["1.1", "not", "1.2"]


def test_heading_ids_fence_aware_skips_headings_inside_tilde_fence():
    md = "## 1.1 Real\n\n~~~\n## not\n~~~\n\n## 1.2 B\n"
    assert heading_ids(md, fence_aware=True) == ["1.1", "1.2"]


from strata_kb.mdutils import heading_id_titles


def test_heading_id_titles_reports_title_presence():
    md = "## 1.1 Real Title\n\nBody.\n\n## Ownership\n\nHuman note.\n"
    assert heading_id_titles(md) == [("1.1", True), ("Ownership", False)]


def test_heading_id_titles_fence_aware_skips_headings_inside_fence():
    md = "## 1.1 Real\n\n```\n## Ownership\n```\n\n## 1.2 B\n"
    assert heading_id_titles(md, fence_aware=True) == [("1.1", True), ("1.2", True)]


from strata_kb.mdutils import heading_occurrences


def test_heading_occurrences_counts_duplicate_ids_across_all_rows():
    sections = [
        models.SectionEntry(id="1.1", title="Part A", file="f", status="summarized"),
        models.SectionEntry(id="1.1", title="Part B", file="f", status="pending"),
        models.SectionEntry(id="2.1", title="Other", file="f", status="pending"),
    ]
    assert heading_occurrences(sections) == [0, 1, 0]


def test_heading_occurrences_distinguishes_by_file():
    sections = [
        models.SectionEntry(id="1.1", title="A", file="f1", status="pending"),
        models.SectionEntry(id="1.1", title="A", file="f2", status="pending"),
    ]
    assert heading_occurrences(sections) == [0, 0]
