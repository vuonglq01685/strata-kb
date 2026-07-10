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
            DocItem("text", "Very short."),  # < 200 tokens -> gop vao 5.4
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
        assert "1.1.1.1" not in ids  # sau hon 3 cap -> gap vao 1.1.1
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
        assert units[0].id  # co id fallback, khong rong
