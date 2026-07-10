from pathlib import Path

from aero_kb import models
from aero_kb.build import build_kb


def test_build_ok_on_valid_kb(fixture_kb: Path):
    report = build_kb(fixture_kb)
    assert report.ok, report.errors
    manifest = models.load_yaml_model(
        fixture_kb / "demo-doc" / "_manifest.yaml", models.Manifest
    )
    sec = manifest.sections[0]
    assert sec.tokens.l2 > 0
    assert sec.tokens.l3 > sec.tokens.l2


def test_build_fails_on_todo_marker(fixture_kb: Path):
    l2_path = fixture_kb / "demo-doc" / "ch1-records.md"
    text = l2_path.read_text().replace(
        "Condensed: airspace record structure with designation and type fields.",
        "<!-- TODO:summarize 1.1 -->",
    )
    l2_path.write_text(text)
    report = build_kb(fixture_kb)
    assert not report.ok
    assert any("TODO" in e for e in report.errors)


def test_build_allow_pending_downgrades_to_warning(fixture_kb: Path):
    l2_path = fixture_kb / "demo-doc" / "ch1-records.md"
    text = l2_path.read_text().replace(
        "Condensed: airspace record structure with designation and type fields.",
        "<!-- TODO:summarize 1.1 -->",
    )
    l2_path.write_text(text)
    report = build_kb(fixture_kb, allow_pending=True)
    assert report.ok
    assert any("TODO" in w for w in report.warnings)


def test_build_fails_on_empty_summary(fixture_kb: Path):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(mpath, models.Manifest)
    manifest.sections[0].summary = ""
    models.save_yaml_model(mpath, manifest)
    report = build_kb(fixture_kb)
    assert not report.ok


def test_build_fails_when_l3_table_missing_from_l2(fixture_kb: Path):
    l2_path = fixture_kb / "demo-doc" / "ch1-records.md"
    text = l2_path.read_text().replace("| P    | Prohibited |", "| P    | Permitted |")
    # edit the table in L2 -> differs from L3 -> table integrity fails
    l2_path.write_text(text.replace("| P | Prohibited |", "| P | Permitted |"))
    report = build_kb(fixture_kb)
    assert not report.ok
    assert any("table" in e.lower() for e in report.errors)


def test_build_fails_when_section_missing_in_l2(fixture_kb: Path):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(mpath, models.Manifest)
    manifest.sections.append(
        models.SectionEntry(
            id="1.9",
            title="Ghost Section",
            summary="x",
            status="summarized",
            file="ch1-records",
        )
    )
    models.save_yaml_model(mpath, manifest)
    report = build_kb(fixture_kb)
    assert not report.ok
