from pathlib import Path

from center_kb import models
from center_kb.ingest.scaffold import chapter_stem, scaffold_doc, slugify
from center_kb.ingest.sectioner import SectionUnit

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
    assert chapter_stem("app3", "Met tables") == "app3-met-tables"


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
