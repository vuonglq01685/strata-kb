from center_kb.ingest.sectioner import DocItem, build_units, parse_section_id


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
        assert sid == "appendix-3"

    def test_unmatched_returns_none(self):
        assert parse_section_id("FOREWORD") is None

    def test_attachment_heading(self):
        sid, title = parse_section_id("ATTACHMENT 5 PATH AND TERMINATOR")
        assert sid == "attachment-5"
        assert title == "PATH AND TERMINATOR"

    def test_attachment_heading_with_separator(self):
        assert parse_section_id("Attachment 2: Datum List")[0] == "attachment-2"

    def test_appendix_heading_with_dotted_number(self):
        sid, title = parse_section_id("Appendix 2.1 — Lights to be Displayed by Aeroplanes")
        assert sid == "appendix-2.1"
        assert title == "Lights to be Displayed by Aeroplanes"

    def test_attachment_heading_with_dotted_letter(self):
        sid, title = parse_section_id("Attachment 2.A — Carriage and Use of Oxygen")
        assert sid == "attachment-2.a"
        assert title == "Carriage and Use of Oxygen"


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

    def test_unmatched_heading_gets_slug_fallback_id(self):
        items = [
            DocItem("heading", "FOREWORD", 1),
            DocItem("text", "Foreword body. " * 60),
        ]
        units = build_units(items)
        assert len(units) == 1
        assert units[0].title == "FOREWORD"
        assert units[0].id == "foreword"  # human-readable slug, not x1

    def test_consecutive_fallback_headings_are_siblings(self):
        big = "Body text. " * 70
        items = [
            DocItem("heading", "FOREWORD", 1),
            DocItem("text", big),
            DocItem("heading", "Historical background", 1),
            DocItem("text", big),
            DocItem("heading", "Action by Contracting States", 1),
            DocItem("text", big),
        ]
        units = build_units(items)
        ids = [u.id for u in units]
        # siblings, not an x1-x2-x3 chain
        assert ids == [
            "foreword",
            "historical-background",
            "action-by-contracting-states",
        ]

    def test_fallback_with_empty_slug_uses_counter(self):
        items = [
            DocItem("heading", "______________________", 1),
            DocItem("text", "Divider page body. " * 60),
        ]
        units = build_units(items)
        assert units[0].id == "x1"

    def test_fallback_under_chapter_groups_into_chapter(self):
        big = "Body text. " * 70
        items = [
            DocItem("heading", "CHAPTER 2. GENERAL SPECIFICATIONS", 1),
            DocItem("text", big),
            DocItem("heading", "Legend of symbols", 2),  # unparsed heading
            DocItem("text", big),
        ]
        units = build_units(items)
        u = next(u for u in units if u.title == "Legend of symbols")
        assert u.id == "2-legend-of-symbols"
        assert u.chapter == "2"  # same file group as chapter 2, no own file


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
    assert "appendix-3-2.1" in ids
    u21 = next(u for u in units if u.id == "2.1")
    assert "Appendix-specific content." not in u21.body_md
    uapp = next(u for u in units if u.id == "appendix-3-2.1")
    assert "Appendix-specific content." in uapp.body_md
    assert uapp.chapter == "appendix-3"


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


def test_attachment_numeric_sections_namespaced_in_flat_mode():
    # NOTE: 80x keeps each leaf > 200 tokens (min_tokens) so it is NOT
    # folded into its parent — same convention as _items_basic's comment.
    items = [
        DocItem("heading", "ATTACHMENT 1 FLOW DIAGRAM", 1),
        DocItem("text", "Attachment intro. " * 80),
        DocItem("heading", "2.1 Diagram Conventions", 2),
        DocItem("text", "Convention body. " * 80),
    ]
    units = build_units(items)
    ids = [u.id for u in units]
    assert "attachment-1" in ids
    assert "attachment-1-2.1" in ids  # namespaced — no collision with chapter 2.1
    assert "2.1" not in ids


def test_dotted_appendix_numbers_do_not_collide():
    # Regression: "Appendix 2.1" and "Appendix 2.5" must stay distinct
    # top-level nodes. The old identifier regex ([0-9A-Za-z]+, no dot)
    # truncated both to "appendix-2", collapsing unrelated appendices
    # into one node and colliding their internal numbered sub-clauses.
    big = "Body text. " * 70
    items = [
        DocItem("heading", "Appendix 2.1 — Lights to be Displayed by Aeroplanes", 1),
        DocItem("heading", "1 TERMINOLOGY", 2),
        DocItem("text", "Lights terminology body. " + big),
        DocItem("heading", "Appendix 2.5 — Flight Recorders", 1),
        DocItem("heading", "1 TERMINOLOGY", 2),
        DocItem("text", "Flight recorder terminology body. " + big),
    ]
    units = build_units(items)
    ids = [u.id for u in units]
    # top-level appendix nodes carry no body of their own here (only a
    # single non-small child) so they fold into their child unit, same
    # convention as test_appendix_numeric_sections_namespaced.
    assert "appendix-2.1-1" in ids
    assert "appendix-2.5-1" in ids
    u1 = next(u for u in units if u.id == "appendix-2.1-1")
    u5 = next(u for u in units if u.id == "appendix-2.5-1")
    assert "Lights terminology body." in u1.body_md
    assert "Flight recorder terminology body." not in u1.body_md
    assert "Flight recorder terminology body." in u5.body_md
    assert "Lights terminology body." not in u5.body_md


def test_dotted_attachment_letters_do_not_collide():
    # Regression: "Attachment 2.A" and "Attachment 2.B" must stay distinct
    # top-level nodes, same defect as dotted appendix numbers above.
    big = "Body text. " * 70
    items = [
        DocItem("heading", "Attachment 2.A — Carriage and Use of Oxygen", 1),
        DocItem("heading", "1 OXYGEN SUPPLY", 2),
        DocItem("text", "Oxygen supply body. " + big),
        DocItem("heading", "Attachment 2.B — HUD/Vision Systems", 1),
        DocItem("heading", "1 OXYGEN SUPPLY", 2),
        DocItem("text", "Vision systems body. " + big),
    ]
    units = build_units(items)
    ids = [u.id for u in units]
    assert "attachment-2.a-1" in ids
    assert "attachment-2.b-1" in ids
    ua = next(u for u in units if u.id == "attachment-2.a-1")
    ub = next(u for u in units if u.id == "attachment-2.b-1")
    assert "Oxygen supply body." in ua.body_md
    assert "Vision systems body." not in ua.body_md
    assert "Vision systems body." in ub.body_md
    assert "Oxygen supply body." not in ub.body_md


def test_resolve_heading_config_attachment_priority():
    from center_kb import models
    from center_kb.ingest.sectioner import (
        DEFAULT_ATTACHMENT_PATTERN,
        resolve_heading_config,
    )

    cfg = resolve_heading_config("", "", "", None)
    assert cfg.attachment_pattern == DEFAULT_ATTACHMENT_PATTERN
    prev = models.IngestConfig(chapter_pattern="c", appendix_pattern="a")
    assert prev.attachment_pattern == ""      # backward-compat default
    assert prev.used_bookmarks is False
    custom = r"^annex\s+(\d+)\s*(.*)$"
    cfg2 = resolve_heading_config("", "", custom, None)
    assert cfg2.attachment_pattern == custom


def test_split_by_parts_buckets_by_page():
    from center_kb.ingest.sectioner import Part, split_by_parts

    parts = [Part("front-matter", "Front Matter", 1), Part("1", "INTRO", 21),
             Part("att1", "FLOW DIAGRAM", 331)]
    items = [
        DocItem("heading", "FOREWORD", 1, page=4),
        DocItem("text", "no page follows previous", page=None),
        DocItem("heading", "1.0 INTRO", 1, page=21),
        DocItem("text", "chapter body", page=25),
        DocItem("heading", "ATTACHMENT 1 FLOW DIAGRAM", 1, page=331),
        DocItem("text", "att body", page=340),
    ]
    result = split_by_parts(items, parts)
    by_id = {part.id: [i.text for i in bucket] for part, bucket in result}
    assert by_id["front-matter"] == ["FOREWORD", "no page follows previous"]
    assert by_id["1"] == ["1.0 INTRO", "chapter body"]
    assert by_id["att1"] == ["ATTACHMENT 1 FLOW DIAGRAM", "att body"]


def test_split_by_parts_item_before_first_part_page():
    from center_kb.ingest.sectioner import Part, split_by_parts

    parts = [Part("1", "INTRO", 21)]
    items = [DocItem("text", "stray cover text", page=1)]
    result = split_by_parts(items, parts)
    assert [i.text for i in result[0][1]] == ["stray cover text"]


def test_build_units_with_parts_assigns_part_chapter():
    from center_kb.ingest.sectioner import Part

    parts = [Part("front-matter", "Front Matter", 1), Part("1", "INTRODUCTION", 21)]
    items = [
        DocItem("heading", "FOREWORD", 1, page=4),
        DocItem("text", "Foreword body. " * 60, page=4),
        DocItem("heading", "1.0 INTRODUCTION", 1, page=21),
        DocItem("text", "Chapter one body. " * 60, page=21),
    ]
    units = build_units(items, parts=parts)
    chapters = {u.id: u.chapter for u in units}
    # FOREWORD is a fallback under the seeded front-matter node
    assert any(u.chapter == "front-matter" for u in units)
    assert chapters.get("1") == "1"
    # no top-level fake chapters
    assert not any(u.chapter.startswith("x") for u in units)


def test_build_units_with_parts_namespaces_attachment_numbering():
    from center_kb.ingest.sectioner import Part

    parts = [Part("2", "GLOSSARY", 25), Part("attachment-1", "FLOW DIAGRAM", 331)]
    items = [
        DocItem("heading", "2.0 GLOSSARY", 1, page=25),
        DocItem("text", "Glossary body. " * 60, page=25),
        DocItem("heading", "ATTACHMENT 1 FLOW DIAGRAM", 1, page=331),
        DocItem("text", "Attachment intro. " * 80, page=331),
        DocItem("heading", "2.1 Diagram Conventions", 2, page=332),
        # 80x keeps the leaf > min_tokens so it is not folded into attachment-1
        DocItem("text", "Convention body. " * 80, page=332),
    ]
    units = build_units(items, parts=parts)
    ids = {u.id for u in units}
    assert "attachment-1-2.1" in ids   # namespaced under the attachment part
    assert "2.1" not in ids            # chapter 2 never polluted
    att_units = [u for u in units if u.chapter == "attachment-1"]
    assert {u.id for u in att_units} >= {"attachment-1", "attachment-1-2.1"}


def test_build_units_without_parts_unchanged():
    units = build_units(_items_basic())
    assert [u.id for u in units] == ["5", "5.3", "5.4"]


def test_front_matter_split_before_first_chapter_heading():
    big = "Body text. " * 70
    items = [
        DocItem("heading", "FOREWORD", 1),
        DocItem("text", big),
        # numbered heading inside the foreword must NOT become chapter 1
        DocItem("heading", "1. Material comprising the Annex proper", 1),
        DocItem("text", big),
        DocItem("heading", "CHAPTER 1. DEFINITIONS", 1),
        DocItem("text", big),
        DocItem("heading", "1.1 Definitions", 2),
        DocItem("text", big),
    ]
    units = build_units(items)
    by_id = {u.id: u for u in units}
    fm = [u for u in units if u.chapter == "front-matter"]
    assert any(u.title == "FOREWORD" for u in fm)
    # foreword's "1." heading namespaced under front-matter, not chapter 1
    assert any(u.id.startswith("front-matter") and "Material" in u.title for u in fm)
    assert by_id["1"].title == "DEFINITIONS"
    assert by_id["1"].chapter == "1"
    assert "Material comprising" not in by_id["1"].body_md
    assert by_id["1.1"].chapter == "1"


def test_front_matter_split_numbered_convention_doc():
    # ARINC-style: no "Chapter N" wording, body starts at "1.0 ...", the
    # only attachment sits at the END. The body must NOT become front matter.
    big = "Body text. " * 70
    items = [
        DocItem("heading", "FOREWORD", 1),
        DocItem("text", big),
        DocItem("heading", "1.0 INTRODUCTION", 1),
        DocItem("text", big),
        DocItem("heading", "5.0 NAVIGATION DATA", 1),
        DocItem("text", big),
        DocItem("heading", "ATTACHMENT 1 FLOW DIAGRAM", 1),
        DocItem("text", big),
    ]
    units = build_units(items)
    chapters = {u.id: u.chapter for u in units}
    assert chapters["1"] == "1"
    assert chapters["5"] == "5"
    assert chapters["attachment-1"] == "attachment-1"
    fm = [u for u in units if u.chapter == "front-matter"]
    assert [u.title for u in fm] == ["FOREWORD"]


def test_numbered_heading_with_trailing_colon_demoted_to_text():
    big = "Body text. " * 70
    items = [
        DocItem("heading", "CHAPTER 1. DEFINITIONS", 1),
        DocItem("text", big),
        # list-intro line Docling mistakes for a heading — must not open node "1"
        DocItem("heading", "1.Material comprising the Annex proper:", 2),
        DocItem("text", "a) Standards and Recommended Practices."),
    ]
    units = build_units(items)
    assert [u.id for u in units] == ["1"]
    body = units[0].body_md
    assert "**1.Material comprising the Annex proper:**" in body
    assert "a) Standards and Recommended Practices." in body


def test_build_units_numeric_part_subsections_keep_flat_ids():
    from center_kb.ingest.sectioner import Part

    parts = [Part("4", "RECORD LAYOUT", 41)]
    items = [
        DocItem("heading", "4.0 RECORD LAYOUT", 1, page=41),
        DocItem("text", "Chapter body. " * 80, page=41),
        DocItem("heading", "4.1 Record Types", 2, page=42),
        DocItem("text", "Subsection body. " * 80, page=42),
    ]
    units = build_units(items, parts=parts)
    ids = {u.id for u in units}
    assert "4.1" in ids
    assert "4-4.1" not in ids
    assert all(u.chapter == "4" for u in units)
