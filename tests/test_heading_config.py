import pytest

from aero_kb import models
from aero_kb.ingest import sectioner
from aero_kb.ingest.scaffold import scaffold_doc
from aero_kb.ingest.sectioner import HeadingConfig, SectionUnit


def test_default_config_matches_current_behavior():
    assert sectioner.parse_section_id("Chapter 5 Navigation Data") == (
        "5", "Navigation Data",
    )
    assert sectioner.parse_section_id("APPENDIX 3. Criteria") == ("app3", "Criteria")


def test_custom_chapter_pattern():
    config = HeadingConfig(chapter_pattern=r"^section\s+(\d+)\s*[.:]?\s*(.*)$")
    assert sectioner.parse_section_id("Section 5: Data Fields", config) == (
        "5", "Data Fields",
    )
    # the default pattern no longer matches once overridden
    assert sectioner.parse_section_id("Chapter 5 Navigation", config) is None


def test_invalid_regex_raises():
    with pytest.raises(ValueError, match="regex"):
        HeadingConfig(chapter_pattern=r"^unit\s+(\d+")


def test_too_few_groups_raises():
    with pytest.raises(ValueError, match="capture group"):
        HeadingConfig(chapter_pattern=r"^unit\s+\d+$")


def test_resolve_heading_config_priority():
    prev = models.IngestConfig(
        chapter_pattern=r"^part\s+(\d+)\s+(.*)$",
        appendix_pattern=sectioner.DEFAULT_APPENDIX_PATTERN,
    )
    # explicit arg wins over the manifest
    cfg = sectioner.resolve_heading_config(r"^sec\s+(\d+)\s+(.*)$", "", prev)
    assert cfg.chapter_pattern == r"^sec\s+(\d+)\s+(.*)$"
    # no arg → taken from the manifest
    cfg = sectioner.resolve_heading_config("", "", prev)
    assert cfg.chapter_pattern == prev.chapter_pattern
    # nothing at all → default
    cfg = sectioner.resolve_heading_config("", "", None)
    assert cfg.chapter_pattern == sectioner.DEFAULT_CHAPTER_PATTERN


def test_scaffold_persists_ingest_config(tmp_path):
    units = [
        SectionUnit(id="5", title="Data", chapter="5", body_md="content", tables=[])
    ]
    config = HeadingConfig(chapter_pattern=r"^section\s+(\d+)\s*[.:]?\s*(.*)$")
    scaffold_doc(
        units, doc_id="doc-x", title="Doc X", tags=[], revision="",
        source_path=None, kb_dir=tmp_path / ".kb", heading_config=config,
    )
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "doc-x" / "_manifest.yaml", models.Manifest
    )
    assert manifest.ingest is not None
    assert manifest.ingest.chapter_pattern == config.chapter_pattern


def test_build_units_accepts_config():
    from aero_kb.ingest.sectioner import DocItem, build_units

    items = [
        DocItem("heading", "Section 1 Records", 1),
        DocItem("text", "body text"),
    ]
    config = HeadingConfig(chapter_pattern=r"^section\s+(\d+)\s*[.:]?\s*(.*)$")
    units = build_units(items, config=config)
    assert units[0].id == "1"
