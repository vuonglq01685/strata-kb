from pathlib import Path

import pytest

from center_kb import models
from center_kb.ingest.scaffold import chapter_stem, scaffold_doc, slugify
from center_kb.ingest.sectioner import SectionUnit
from center_kb.mdutils import slice_section

TABLE = "| Code | Meaning |\n|---|---|\n| P | Prohibited |"


def _units() -> list[SectionUnit]:
    return [
        SectionUnit("5", "NAVIGATION DATA", "5", "Chapter intro.", []),
        SectionUnit(
            "5.3",
            "Restrictive Airspace",
            "5",
            f"Airspace body.\n\n{TABLE}",
            [TABLE],
        ),
        SectionUnit("6", "OTHER CHAPTER", "6", "Other body.", []),
    ]


def test_slugify():
    assert slugify("NAVIGATION DATA — Field/Spec") == "navigation-data-field-spec"


def test_chapter_stem():
    assert chapter_stem("5", "NAVIGATION DATA") == "ch5-navigation-data"
    assert chapter_stem("appendix-3", "Met tables") == "appendix-3-met-tables"


@pytest.mark.parametrize("bad_id", ["../evil", "a/b", "..", ".", "", ".hidden"])
def test_scaffold_rejects_doc_id_with_path_separators(tmp_path: Path, bad_id: str):
    """doc_id becomes a directory name under .kb/ — never a path."""
    with pytest.raises(ValueError, match="doc"):
        scaffold_doc(
            _units(),
            doc_id=bad_id,
            title="X",
            tags=[],
            revision="r",
            source_path=None,
            kb_dir=tmp_path / ".kb",
        )
    assert not (tmp_path / "evil").exists()


def test_scaffold_writes_l3_l2_manifest_index(tmp_path: Path):
    kb = tmp_path / ".kb"
    report = scaffold_doc(
        _units(),
        doc_id="arinc-424",
        title="ARINC 424",
        tags=["arinc424", "navdata"],
        revision="Supplement 22",
        source_path=None,
        kb_dir=kb,
    )
    assert report.n_sections == 3

    l3 = (kb / "arinc-424" / "ch5-navigation-data.raw.md").read_text()
    assert "## 5.3 Restrictive Airspace" in l3
    assert "Prohibited" in l3

    l2 = (kb / "arinc-424" / "ch5-navigation-data.md").read_text()
    assert "<!-- TODO:summarize 5.3 -->" in l2
    assert "Prohibited" in l2  # table is copied verbatim into L2 by code
    assert "Airspace body." not in l2  # prose is NOT included in the L2 scaffold

    manifest = models.load_yaml_model(
        kb / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert [s.id for s in manifest.sections] == ["5", "5.3", "6"]
    sec53 = next(s for s in manifest.sections if s.id == "5.3")
    assert sec53.status == "pending"
    assert sec53.file == "ch5-navigation-data"
    assert sec53.tokens.l3 > 0

    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].id == "arinc-424"
    assert "arinc424" in index.docs[0].tags


def test_scaffold_chapter_filter(tmp_path: Path):
    kb = tmp_path / ".kb"
    report = scaffold_doc(
        _units(),
        doc_id="arinc-424",
        title="ARINC 424",
        tags=[],
        revision="",
        source_path=None,
        kb_dir=kb,
        chapters={"5"},
    )
    assert report.n_sections == 2
    assert not (kb / "arinc-424" / "ch6-other-chapter.md").exists()


def test_scaffold_reingest_replaces_index_entry(tmp_path: Path):
    kb = tmp_path / ".kb"
    for _ in range(2):
        scaffold_doc(
            _units(),
            doc_id="arinc-424",
            title="ARINC 424",
            tags=["arinc424"],
            revision="",
            source_path=None,
            kb_dir=kb,
        )
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert len(index.docs) == 1


def test_chapter_stem_no_duplicate_when_slug_equals_prefix():
    assert chapter_stem("errata", "ERRATA") == "errata"
    assert chapter_stem("front-matter", "Front Matter") == "front-matter"
    assert chapter_stem("attachment-1", "FLOW DIAGRAM") == "attachment-1-flow-diagram"


def test_scaffold_reingest_removes_stale_files(tmp_path: Path):
    kb = tmp_path / ".kb"
    doc_dir = kb / "doc1"
    doc_dir.mkdir(parents=True)
    (doc_dir / "ch9-fake-chapter.md").write_text("stale", encoding="utf-8")
    (doc_dir / "ch9-fake-chapter.raw.md").write_text("stale", encoding="utf-8")
    units = [
        SectionUnit(
            id="1", title="INTRO", chapter="1",
            body_md="Body. " * 60, tables=[],
        )
    ]
    scaffold_doc(
        units, doc_id="doc1", title="Doc", tags=[], revision="",
        source_path=None, kb_dir=kb,
    )
    names = {p.name for p in doc_dir.iterdir()}
    assert "ch9-fake-chapter.md" not in names
    assert "ch9-fake-chapter.raw.md" not in names
    assert "ch1-intro.md" in names


def test_scaffold_stem_prefers_part_title(tmp_path: Path):
    kb = tmp_path / ".kb"
    units = [
        SectionUnit(
            id="4.1", title="General", chapter="4",
            body_md="Body. " * 60, tables=[],
        )
    ]
    report = scaffold_doc(
        units, doc_id="doc1", title="Doc", tags=[], revision="",
        source_path=None, kb_dir=kb,
        part_titles={"4": "NAVIGATION DATA - RECORD LAYOUT"},
    )
    assert "ch4-navigation-data-record-layout.md" in report.files


def test_scaffold_stem_falls_back_without_part_titles(tmp_path: Path):
    kb = tmp_path / ".kb"
    units = [
        SectionUnit(
            id="4.1", title="General", chapter="4",
            body_md="Body. " * 60, tables=[],
        )
    ]
    report = scaffold_doc(
        units, doc_id="doc1", title="Doc", tags=[], revision="",
        source_path=None, kb_dir=kb,
    )
    assert "ch4-general.md" in report.files


def test_l2_gets_figure_description_text(tmp_path: Path):
    sha = "d" * 64
    unit = SectionUnit(
        id="5.1",
        title="Symbols",
        chapter="5",
        body_md=f"Intro.\n\n![Holding pattern](assets/{sha}.webp)",
        tables=[],
        page=12,
    )
    scaffold_doc(
        [unit], doc_id="doc", title="T", tags=[], revision="r1",
        source_path=None, kb_dir=tmp_path,
    )
    l2 = (tmp_path / "doc" / "ch5-symbols.md").read_text(encoding="utf-8")
    l3 = (tmp_path / "doc" / "ch5-symbols.raw.md").read_text(encoding="utf-8")
    assert "Figure: Holding pattern" in l2
    assert f"![Holding pattern](assets/{sha}.webp)" in l3
    assert f"![Holding pattern](assets/{sha}.webp)" not in l2  # figures stay text-only in L2


def test_table_icon_cell_identical_in_l2_and_l3(tmp_path: Path):
    sha = "e" * 64
    row = f"| ![VOR](assets/{sha}.png) | VOR station |"
    table = "| Symbol | Meaning |\n| --- | --- |\n" + row
    unit = SectionUnit(
        id="5.2", title="Legend", chapter="5",
        body_md=f"See legend.\n\n{table}", tables=[table], page=13,
    )
    scaffold_doc(
        [unit], doc_id="doc", title="T", tags=[], revision="r1",
        source_path=None, kb_dir=tmp_path,
    )
    l2 = (tmp_path / "doc" / "ch5-legend.md").read_text(encoding="utf-8")
    l3 = (tmp_path / "doc" / "ch5-legend.raw.md").read_text(encoding="utf-8")
    assert row in l2 and row in l3        # byte-identical cell in both layers
    assert "Figure: VOR" not in l2        # table icons are not figure lines


def test_scaffold_writes_bare_heading_for_empty_title_and_it_slices(tmp_path: Path):
    kb = tmp_path / ".kb"
    units = [
        SectionUnit("5", "NAV", "5", "Chapter intro.", []),
        SectionUnit("5.15", "", "5", "Orphan body.", []),
    ]
    scaffold_doc(
        units, doc_id="d", title="D", tags=[], revision="",
        source_path=None, kb_dir=kb,
    )
    raw = (kb / "d" / "ch5-nav.raw.md").read_text(encoding="utf-8")
    l2 = (kb / "d" / "ch5-nav.md").read_text(encoding="utf-8")
    assert "## 5.15\n" in raw and "## 5.15 \n" not in raw
    assert "## 5.15\n" in l2 and "## 5.15 \n" not in l2
    assert slice_section(raw, "5.15") == "## 5.15\n\nOrphan body."
    manifest = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert manifest.sections[1].title == ""


def test_scaffold_rejects_section_id_with_whitespace_before_writing(tmp_path: Path):
    units = [SectionUnit("Part A", "Definitions", "Part A", "Body.", [])]
    with pytest.raises(ValueError, match="'Part A'"):
        scaffold_doc(
            units, doc_id="d", title="D", tags=[], revision="",
            source_path=None, kb_dir=tmp_path / ".kb",
        )
    assert not (tmp_path / ".kb" / "d").exists()


def test_scaffold_rejects_empty_section_id(tmp_path: Path):
    units = [SectionUnit("", "Nameless", "5", "Body.", [])]
    with pytest.raises(ValueError, match="empty"):
        scaffold_doc(
            units, doc_id="d", title="D", tags=[], revision="",
            source_path=None, kb_dir=tmp_path / ".kb",
        )


@pytest.mark.parametrize("bad_id", ["../../pwn", "a/b", "a\\b", "..", "."])
def test_scaffold_rejects_section_id_with_path_traversal_before_writing(
    tmp_path: Path, bad_id: str
):
    """A custom --chapter-pattern whose identifier group captures a path
    separator or '..' must not be allowed to escape the document
    directory when chapter_stem() turns the id into a file stem."""
    units = [SectionUnit(bad_id, "Title", bad_id, "Body.", [])]
    with pytest.raises(ValueError) as exc_info:
        scaffold_doc(
            units, doc_id="d", title="D", tags=[], revision="",
            source_path=None, kb_dir=tmp_path / ".kb",
        )
    assert repr(bad_id) in str(exc_info.value)
    assert not (tmp_path / ".kb").exists()


def test_scaffold_report_carries_token_stats(tmp_path: Path):
    from center_kb.ingest.scaffold import TokenStats

    report = scaffold_doc(
        _units(), doc_id="d", title="D", tags=[], revision="",
        source_path=None, kb_dir=tmp_path / ".kb",
    )
    stats = report.token_stats
    assert isinstance(stats, TokenStats)
    assert stats.n == 3
    assert stats.below_300 == 3 and stats.above_5000 == 0
    assert 0 < stats.min <= stats.median <= stats.max


def test_scaffold_report_token_stats_none_without_sections(tmp_path: Path):
    report = scaffold_doc(
        [], doc_id="d", title="D", tags=[], revision="",
        source_path=None, kb_dir=tmp_path / ".kb",
    )
    assert report.token_stats is None


def _three_chapter_units() -> list[SectionUnit]:
    return [
        SectionUnit("5", "NAV", "5", "Nav intro.", []),
        SectionUnit("5.3", "Airspace", "5", "Airspace body.", []),
        SectionUnit("6", "PROC", "6", "Proc intro.", []),
        SectionUnit("7", "COMMS", "7", "Comms intro.", []),
    ]


def _scaffold(units, kb: Path, chapters=None):
    return scaffold_doc(
        units, doc_id="d", title="D", tags=[], revision="",
        source_path=None, kb_dir=kb, chapters=chapters,
    )


def _snapshot(doc: Path, *prefixes: str) -> dict[str, bytes]:
    return {
        p.name: p.read_bytes()
        for p in doc.iterdir()
        if any(p.name.startswith(pre) for pre in prefixes)
    }


def test_sections_reingest_keeps_other_chapters_and_their_review_state(tmp_path: Path):
    kb = tmp_path / ".kb"
    _scaffold(_three_chapter_units(), kb)
    doc = kb / "d"
    manifest_path = doc / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    reviewed = manifest.sections[1].model_copy(
        update={"status": "reviewed", "summary": "Approved summary."}
    )
    models.save_yaml_model(
        manifest_path,
        manifest.model_copy(update={"sections": [manifest.sections[0], reviewed, *manifest.sections[2:]]}),
    )
    (doc / "ch5-nav.md").write_text("## 5.3 Airspace\n\nApproved L2 text.\n", encoding="utf-8")
    before = _snapshot(doc, "ch5-", "ch7-")

    new6 = [
        SectionUnit("6", "PROCEDURES", "6", "Proc intro rewritten.", []),
        SectionUnit("6.1", "Steps", "6", "Steps body.", []),
    ]
    report = _scaffold(new6, kb, chapters={"6"})

    assert _snapshot(doc, "ch5-", "ch7-") == before
    merged = models.load_yaml_model(manifest_path, models.Manifest)
    assert [s.id for s in merged.sections] == ["5", "5.3", "6", "6.1", "7"]
    assert merged.sections[1].status == "reviewed"
    assert merged.sections[1].summary == "Approved summary."
    assert merged.sections[2].file == "ch6-procedures"
    assert not (doc / "ch6-proc.md").exists()        # old stem of the rewritten chapter is gone
    assert not (doc / "ch6-proc.raw.md").exists()
    assert "Proc intro rewritten." in (doc / "ch6-procedures.raw.md").read_text(encoding="utf-8")
    assert report.n_sections == 2
    assert report.files == ["ch6-procedures.md", "ch6-procedures.raw.md"]


def test_sections_reingest_of_a_new_chapter_appends(tmp_path: Path):
    kb = tmp_path / ".kb"
    _scaffold(_three_chapter_units(), kb)
    _scaffold([SectionUnit("8", "GLOSSARY", "8", "Gloss.", [])], kb, chapters={"8"})
    merged = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert [s.id for s in merged.sections] == ["5", "5.3", "6", "7", "8"]
    assert (kb / "d" / "ch5-nav.raw.md").exists()


def test_sections_reingest_of_two_nonadjacent_chapters_keeps_manifest_order(
    tmp_path: Path,
):
    """--sections 5,7 must splice each targeted chapter's new entries at
    its OWN former position, not both at the position of the first
    chapter dropped — a single shared insertion point would push the
    untouched chapter 6 to the end (['5','5.3','7','6'])."""
    kb = tmp_path / ".kb"
    _scaffold(_three_chapter_units(), kb)
    doc = kb / "d"
    before = _snapshot(doc, "ch6-")

    new_5_and_7 = [
        SectionUnit("5", "NAV", "5", "Nav rewritten.", []),
        SectionUnit("5.3", "Airspace", "5", "Airspace rewritten.", []),
        SectionUnit("7", "COMMS", "7", "Comms rewritten.", []),
    ]
    report = _scaffold(new_5_and_7, kb, chapters={"5", "7"})

    assert _snapshot(doc, "ch6-") == before
    merged = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    assert [s.id for s in merged.sections] == ["5", "5.3", "6", "7"]
    assert report.n_sections == 3


def test_sections_without_previous_manifest_writes_only_named_chapters(tmp_path: Path):
    kb = tmp_path / ".kb"
    report = _scaffold(_three_chapter_units(), kb, chapters={"6"})
    assert [s.id for s in models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest).sections] == ["6"]
    assert report.n_sections == 1


def test_full_reingest_still_replaces_everything(tmp_path: Path):
    kb = tmp_path / ".kb"
    _scaffold(_three_chapter_units(), kb)
    _scaffold([SectionUnit("5", "NAV", "5", "Only nav now.", [])], kb)
    doc = kb / "d"
    assert {p.name for p in doc.glob("*.md")} == {"ch5-nav.md", "ch5-nav.raw.md"}
    assert [s.id for s in models.load_yaml_model(doc / "_manifest.yaml", models.Manifest).sections] == ["5"]


def _appendix_units() -> list[SectionUnit]:
    return [
        SectionUnit("appendix", "SIGNALS", "appendix", "Signals body.", []),
        SectionUnit("appendix-a", "ALPHA", "appendix-a", "Alpha body.", []),
    ]


def test_sections_reingest_refuses_ambiguous_chapter_stem(tmp_path: Path):
    """The stem for chapter "appendix-a" also starts with the prefix for
    chapter "appendix" — refuse rather than guess which one to replace,
    and touch nothing."""
    kb = tmp_path / ".kb"
    _scaffold(_appendix_units(), kb)
    doc = kb / "d"
    before = _snapshot(doc, "appendix")
    manifest_before = (doc / "_manifest.yaml").read_bytes()

    with pytest.raises(ValueError, match="'appendix'"):
        _scaffold(
            [SectionUnit("appendix", "SIGNALS V2", "appendix", "New body.", [])],
            kb, chapters={"appendix"},
        )

    assert _snapshot(doc, "appendix") == before
    assert (doc / "_manifest.yaml").read_bytes() == manifest_before


def test_sections_reingest_of_unambiguous_sibling_chapter_succeeds(tmp_path: Path):
    kb = tmp_path / ".kb"
    _scaffold(_appendix_units(), kb)
    doc = kb / "d"
    before = _snapshot(doc, "appendix-signals")

    report = _scaffold(
        [SectionUnit("appendix-a", "ALPHA V2", "appendix-a", "New alpha body.", [])],
        kb, chapters={"appendix-a"},
    )

    assert _snapshot(doc, "appendix-signals") == before
    assert report.n_sections == 1
    merged = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    assert [s.id for s in merged.sections] == ["appendix", "appendix-a"]


def test_sections_reingest_refuses_when_merge_would_duplicate_an_id(tmp_path: Path):
    kb = tmp_path / ".kb"
    units = [
        SectionUnit("5", "NAV", "5", "Nav intro.", []),
        SectionUnit("6.1", "Misfiled", "5", "Misfiled body.", []),  # chapter mis-classified
        SectionUnit("6", "PROC", "6", "Proc intro.", []),
    ]
    _scaffold(units, kb)
    doc = kb / "d"
    before = _snapshot(doc, "ch5-", "ch6-")

    new6 = [
        SectionUnit("6", "PROCEDURES", "6", "Proc rewritten.", []),
        SectionUnit("6.1", "Steps", "6", "Steps body.", []),
    ]
    with pytest.raises(ValueError, match="'6.1'"):
        _scaffold(new6, kb, chapters={"6"})

    assert _snapshot(doc, "ch5-", "ch6-") == before
    assert (doc / "ch5-nav.md").exists()


def test_sections_reingest_distinguishes_chapter_5_from_50(tmp_path: Path):
    kb = tmp_path / ".kb"
    units = [
        SectionUnit("5", "NAV", "5", "Nav intro.", []),
        SectionUnit("50", "FIFTY", "50", "Fifty body.", []),
    ]
    _scaffold(units, kb)
    doc = kb / "d"
    before = _snapshot(doc, "ch50-")

    _scaffold([SectionUnit("5", "NAVIGATION", "5", "Nav rewritten.", [])], kb, chapters={"5"})

    assert _snapshot(doc, "ch50-") == before
    merged = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    assert [s.id for s in merged.sections] == ["5", "50"]
    assert merged.sections[1].file == "ch50-fifty"


def test_sections_reingest_of_chapter_with_no_units_removes_it(tmp_path: Path):
    """--sections doubles as a chapter delete when the named chapter no
    longer produces any units — current, now-documented behaviour."""
    kb = tmp_path / ".kb"
    _scaffold(_three_chapter_units(), kb)
    doc = kb / "d"

    report = _scaffold([], kb, chapters={"6"})

    assert not (doc / "ch6-proc.md").exists()
    assert not (doc / "ch6-proc.raw.md").exists()
    merged = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    assert [s.id for s in merged.sections] == ["5", "5.3", "7"]
    assert report.n_sections == 0


def test_sections_reingest_refuses_lone_candidate_stem_from_a_different_chapter(
    tmp_path: Path,
):
    """A prefix can resolve to exactly one existing stem that in fact
    belongs to a DIFFERENT chapter — here chapter 'appendix' was never
    ingested, but its prefix matches chapter 'appendix-a''s only stem
    ('appendix-a-alpha'). Trusting a lone candidate blindly would destroy
    'appendix-a'; refuse instead, and touch nothing."""
    kb = tmp_path / ".kb"
    _scaffold(
        [SectionUnit("appendix-a", "ALPHA", "appendix-a", "Alpha body.", [])], kb
    )
    doc = kb / "d"
    before = _snapshot(doc, "appendix-a-alpha")
    manifest_before = (doc / "_manifest.yaml").read_bytes()

    with pytest.raises(ValueError, match="'appendix'"):
        _scaffold(
            [SectionUnit("appendix", "SIGNALS", "appendix", "Signals body.", [])],
            kb, chapters={"appendix"},
        )

    assert _snapshot(doc, "appendix-a-alpha") == before
    assert (doc / "_manifest.yaml").read_bytes() == manifest_before


def test_sections_reingest_resolves_a_chapter_with_many_entries_under_one_stem(
    tmp_path: Path,
):
    """Five entries share one stem for chapter 5 — _resolve_stems must
    collapse them to the single distinct stem, not refuse as ambiguous."""
    kb = tmp_path / ".kb"
    units = [
        SectionUnit("5", "NAV", "5", "Nav intro.", []),
        SectionUnit("5.1", "One", "5", "One body.", []),
        SectionUnit("5.2", "Two", "5", "Two body.", []),
        SectionUnit("5.3", "Three", "5", "Three body.", []),
        SectionUnit("5.4", "Four", "5", "Four body.", []),
        SectionUnit("6", "PROC", "6", "Proc intro.", []),
    ]
    _scaffold(units, kb)
    doc = kb / "d"
    before = _snapshot(doc, "ch6-")

    report = _scaffold(
        [SectionUnit("5", "NAVIGATION", "5", "Nav rewritten.", [])], kb, chapters={"5"}
    )

    assert _snapshot(doc, "ch6-") == before
    merged = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    assert [s.id for s in merged.sections] == ["5", "6"]
    assert report.n_sections == 1


def test_sections_reingest_confirms_headless_chapter_by_shared_unit_ids(tmp_path: Path):
    """build_units() probe (CHAPTER 5 + "APPENDIX A. ALPHA" whose first
    content is "1. Purpose" / "2. Scope", no body of its own) never emits a
    unit whose id equals the chapter id "appendix-a" — only the namespaced
    ids "appendix-a-1", "appendix-a-2" (see sectioner._TreeBuilder). Round
    2's id-only confirmation would refuse this chapter forever. The new
    shared-id arm must confirm it instead, since re-ingesting the same
    headings produces the same ids."""
    kb = tmp_path / ".kb"
    units = [
        SectionUnit("appendix-a-1", "Purpose", "appendix-a", "Purpose body.", []),
        SectionUnit("appendix-a-2", "Scope", "appendix-a", "Scope body.", []),
        SectionUnit("5", "NAV", "5", "Nav intro.", []),
    ]
    _scaffold(units, kb)
    doc = kb / "d"
    before = _snapshot(doc, "ch5-")

    new_appendix = [
        SectionUnit("appendix-a-1", "Purpose", "appendix-a", "Purpose rewritten.", []),
        SectionUnit("appendix-a-2", "Scope", "appendix-a", "Scope rewritten.", []),
    ]
    report = _scaffold(new_appendix, kb, chapters={"appendix-a"})

    assert _snapshot(doc, "ch5-") == before
    merged = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    assert [s.id for s in merged.sections] == ["appendix-a-1", "appendix-a-2", "5"]
    assert report.n_sections == 2
    assert "Purpose rewritten." in (doc / "appendix-a-purpose.raw.md").read_text(
        encoding="utf-8"
    )


def test_sections_reingest_shared_id_confirmation_is_scoped_to_the_named_chapter(
    tmp_path: Path,
):
    """The shared-id confirmation arm (_confirms_chapter's `entry.id in
    run_ids`) must be built from THIS RUN's units for the chapter being
    resolved only — not from every chapter named in --sections. Previous
    manifest holds a lone entry id 'appendix-a' under stem
    'appendix-a-alpha'. Chapter 'appendix' resolves to that stem as its
    only candidate; chapter 'zulu' — also named this run — happens to
    emit a unit whose id is also 'appendix-a'. If run_ids leaked zulu's
    ids into chapter 'appendix''s confirmation, that shared id would
    wrongly confirm 'appendix' and silently delete appendix-a's reviewed
    work. It must still refuse."""
    kb = tmp_path / ".kb"
    _scaffold(
        [SectionUnit("appendix-a", "ALPHA", "appendix-a", "Alpha body.", [])], kb
    )
    doc = kb / "d"
    before = _snapshot(doc, "appendix-a-alpha")
    manifest_before = (doc / "_manifest.yaml").read_bytes()

    with pytest.raises(ValueError, match="'appendix'"):
        _scaffold(
            [SectionUnit("appendix-a", "ZULU HEADING", "zulu", "Zulu body.", [])],
            kb, chapters={"appendix", "zulu"},
        )

    assert _snapshot(doc, "appendix-a-alpha") == before
    assert (doc / "_manifest.yaml").read_bytes() == manifest_before
