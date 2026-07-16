from center_kb import mdutils

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
    from center_kb.mdutils import extract_image_descs

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
