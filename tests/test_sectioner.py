from aero_kb.ingest.sectioner import DocItem, build_units, parse_section_id


class TestParseSectionId:
    def test_numbered_heading(self):
        assert parse_section_id("5.3 Restrictive Airspace") == (
            "5.3",
            "Restrictive Airspace",
        )

    def test_chapter_zero_suffix_stripped(self):
        assert parse_section_id("5.0 NAVIGATION DATA") == ("5", "NAVIGATION DATA")

    def test_chapter_word_heading(self):
        assert parse_section_id("CHAPTER 2. GENERAL PROVISIONS") == (
            "2",
            "GENERAL PROVISIONS",
        )

    def test_appendix_heading(self):
        sid, _ = parse_section_id("Appendix 3 — Meteorological tables")
        assert sid == "app3"

    def test_unmatched_returns_none(self):
        assert parse_section_id("FOREWORD") is None


def _items_basic() -> list[DocItem]:
    long_text = "Restrictive airspace body text. " * 60  # > 200 tokens
    return [
        DocItem("heading", "5.0 NAVIGATION DATA", 1),
        DocItem("text", "Chapter intro. " * 60),
        DocItem("heading", "5.3 Restrictive Airspace", 2),
        DocItem("text", long_text),
        DocItem("table", "| Code | Meaning |\n|---|---|\n| P | Prohibited |"),
        DocItem("heading", "5.4 Airways", 2),
        # NOTE: 70x here (not 60x like sibling fixtures) — with 60x this
        # leaf-only body is 181 tokens (< 200 min_tokens), so it would
        # silently fold into "5" and break test_units_have_ids_and_chapter.
        # 70x brings it to ~211 tokens, matching the fixture's evident
        # intent (a section header that should NOT fold).
        DocItem("text", "Airways body. " * 70),
    ]


class TestBuildUnits:
    def test_units_have_ids_and_chapter(self):
        units = build_units(_items_basic())
        ids = [u.id for u in units]
        assert ids == ["5", "5.3", "5.4"]
        assert all(u.chapter == "5" for u in units)

    def test_tables_collected_on_unit(self):
        units = build_units(_items_basic())
        u53 = next(u for u in units if u.id == "5.3")
        assert len(u53.tables) == 1
        assert "Prohibited" in u53.tables[0]

    def test_small_leaf_merged_into_parent(self):
        items = _items_basic() + [
            DocItem("heading", "5.4.1 Tiny", 3),
            DocItem("text", "Very short."),  # < 200 tokens -> folded into 5.4
        ]
        units = build_units(items)
        assert "5.4.1" not in [u.id for u in units]
        u54 = next(u for u in units if u.id == "5.4")
        assert "Very short." in u54.body_md
        assert "### 5.4.1 Tiny" in u54.body_md

    def test_depth_beyond_max_folded(self):
        items = [
            DocItem("heading", "1.0 INTRO", 1),
            DocItem("heading", "1.1 Purpose", 2),
            DocItem("text", "Purpose body. " * 60),
            DocItem("heading", "1.1.1 Coverage", 3),
            DocItem("text", "Coverage body. " * 60),
            DocItem("heading", "1.1.1.1 Deep detail", 4),
            DocItem("text", "Deep body. " * 60),
        ]
        units = build_units(items)
        ids = [u.id for u in units]
        assert "1.1.1.1" not in ids  # deeper than 3 levels -> folded into 1.1.1
        u111 = next(u for u in units if u.id == "1.1.1")
        assert "Deep body." in u111.body_md

    def test_unmatched_heading_gets_fallback_id(self):
        items = [
            DocItem("heading", "FOREWORD", 1),
            DocItem("text", "Foreword body. " * 60),
        ]
        units = build_units(items)
        assert len(units) == 1
        assert units[0].title == "FOREWORD"
        assert units[0].id  # has a fallback id, not empty


def test_repeated_chapter_heading_reopens_node():
    big = "Body text. " * 70
    items = [
        DocItem("heading", "5.0 NAVIGATION DATA", 1),
        DocItem("text", big),
        DocItem("heading", "5.1 First Field", 2),
        DocItem("text", big),
        DocItem("heading", "5.0 NAVIGATION DATA", 1),  # running page header
        DocItem("text", "Page two chapter intro."),
        DocItem("heading", "5.2 Second Field", 2),
        DocItem("text", big),
    ]
    units = build_units(items)
    ids = [u.id for u in units]
    assert ids == ["5", "5.1", "5.2"]  # '5' is not duplicated
    # '5' is already on the stack when the running header repeats -> no-op:
    # the following content belongs to the currently open section (5.1), not '5'.
    u51 = next(u for u in units if u.id == "5.1")
    assert "Page two chapter intro." in u51.body_md


def test_running_header_does_not_steal_continuation_text():
    big = "Body text. " * 70
    items = [
        DocItem("heading", "5.0 NAVIGATION DATA", 1),
        DocItem("text", "Chapter intro."),
        DocItem("heading", "5.45 Some Field", 2),
        DocItem("text", big),
        DocItem("heading", "5.0 NAVIGATION DATA", 1),  # running header mid-page
        DocItem("text", "Continuation of 5.45 content."),
        DocItem("heading", "5.46 Next Field", 2),
        DocItem("text", big),
    ]
    units = build_units(items)
    u545 = next(u for u in units if u.id == "5.45")
    u5 = next(u for u in units if u.id == "5")
    assert "Continuation of 5.45 content." in u545.body_md
    assert "Continuation of 5.45 content." not in u5.body_md


def test_repeated_section_heading_merges_content():
    big = "Body text. " * 70
    items = [
        DocItem("heading", "5.7 Some Field", 2),
        DocItem("text", big),
        DocItem("heading", "5.7 Some Field", 2),  # page-break re-heading
        DocItem("text", "Continued content."),
    ]
    units = build_units(items)
    assert [u.id for u in units] == ["5.7"]
    assert "Continued content." in units[0].body_md


def test_label_heading_with_colon_demoted_to_text():
    big = "Body text. " * 70
    items = [
        DocItem("heading", "5.93 Facility Characteristics", 2),
        DocItem("text", big),
        DocItem("heading", "Source/Content:", 3),  # label Docling mistakes for a heading
        DocItem("text", "Derived from official sources."),
    ]
    units = build_units(items)
    assert [u.id for u in units] == ["5.93"]
    body = units[0].body_md
    assert "**Source/Content:**" in body
    assert "Derived from official sources." in body


def test_unmatched_heading_without_colon_still_fallback():
    items = [
        DocItem("heading", "FOREWORD", 1),
        DocItem("text", "Foreword body. " * 70),
    ]
    units = build_units(items)
    assert len(units) == 1
    assert units[0].title == "FOREWORD"


def test_appendix_numeric_sections_namespaced():
    big = "Body text. " * 70
    items = [
        DocItem("heading", "CHAPTER 2. GENERAL PROVISIONS", 1),
        DocItem("heading", "2.1 Objective", 2),
        DocItem("text", big),
        DocItem("heading", "Appendix 3 - Specifications", 1),
        DocItem("heading", "2.1 Appendix section", 2),
        DocItem("text", "Appendix-specific content. " + big),
    ]
    units = build_units(items)
    ids = [u.id for u in units]
    assert "2.1" in ids
    assert "app3-2.1" in ids
    u21 = next(u for u in units if u.id == "2.1")
    assert "Appendix-specific content." not in u21.body_md
    uapp = next(u for u in units if u.id == "app3-2.1")
    assert "Appendix-specific content." in uapp.body_md
    assert uapp.chapter == "app3"


def test_front_matter_fallback_does_not_namespace_chapters():
    big = "Body text. " * 70
    items = [
        DocItem("heading", "FOREWORD", 1),
        DocItem("text", "Foreword body. " * 70),
        DocItem("heading", "5.0 NAVIGATION DATA", 1),
        DocItem("text", "Chapter intro. " + big),
        DocItem("heading", "5.3 Some Field", 2),
        DocItem("text", big),
    ]
    units = build_units(items)
    ids = [u.id for u in units]
    assert "5" in ids and "5.3" in ids  # not namespaced under FOREWORD
    u53 = next(u for u in units if u.id == "5.3")
    assert u53.chapter == "5"


def test_small_leaf_folding_skipped_when_parent_would_exceed_cap():
    # 30 small children (~140 tokens each) -> total ~4200 + parent body ~700 > cap 4000
    small = "Field definition body. " * 35  # ~140 token
    items = [DocItem("heading", "5.0 NAVIGATION DATA", 1), DocItem("text", "Intro. " * 200)]
    for i in range(1, 31):
        items.append(DocItem("heading", f"5.{i} Field {i}", 2))
        items.append(DocItem("text", small))
    units = build_units(items, max_unit_tokens=4000)
    ids = [u.id for u in units]
    # all 30 children stay as their own separate units, not swallowed into '5'
    assert "5" in ids
    assert all(f"5.{i}" in ids for i in range(1, 31))
    u5 = next(u for u in units if u.id == "5")
    assert "Field definition body." not in u5.body_md


def test_small_leaf_folding_still_happens_under_cap():
    big = "Body text. " * 70
    items = [
        DocItem("heading", "5.0 NAVIGATION DATA", 1),
        DocItem("text", big),
        DocItem("heading", "5.4 Airways", 2),
        DocItem("text", big),
        DocItem("heading", "5.4.1 Tiny", 3),
        DocItem("text", "Very short."),
    ]
    units = build_units(items)  # default cap 5000, small total -> still folds
    assert "5.4.1" not in [u.id for u in units]
    u54 = next(u for u in units if u.id == "5.4")
    assert "### 5.4.1 Tiny" in u54.body_md
