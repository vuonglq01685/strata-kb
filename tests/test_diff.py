import pytest

from aero_kb import models
from aero_kb.diff import diff_doc, render_diff


def test_changed_summary_detected(git_kb):
    # fixture: §1.1 đổi summary (L1) giữa rev1 và worktree; L3 giữ nguyên
    report = diff_doc(git_kb["kb"], "demo-doc", against=git_kb["rev1"])
    assert [c.section_id for c in report.changed] == ["1.1"]
    assert report.changed[0].summary_changed is True
    assert report.changed[0].content_changed is False
    assert not report.added and not report.removed
    assert report.has_changes


def test_no_changes_against_head(git_kb):
    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")
    assert not report.has_changes


def test_content_changed_when_raw_edited(git_kb):
    raw = git_kb["kb"] / "demo-doc" / "ch1-records.raw.md"
    raw.write_text(
        raw.read_text(encoding="utf-8").replace(
            "Full raw text about airway records", "Full raw text REVISED airway"
        ),
        encoding="utf-8",
    )
    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")
    assert [c.section_id for c in report.changed] == ["1.2"]
    assert report.changed[0].content_changed is True


def test_added_and_removed_sections(git_kb):
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    kept = [s for s in manifest.sections if s.id != "1.2"]  # xóa 1.2
    kept.append(
        models.SectionEntry(id="1.3", title="Waypoint Records", file="ch1-records")
    )
    models.save_yaml_model(
        manifest_path,
        models.Manifest(
            id=manifest.id,
            title=manifest.title,
            revision=manifest.revision,
            sections=kept,
        ),
    )
    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")
    assert [c.section_id for c in report.added] == ["1.3"]
    assert [c.section_id for c in report.removed] == ["1.2"]


def test_unknown_doc_raises(git_kb):
    with pytest.raises(ValueError, match="khong-co"):
        diff_doc(git_kb["kb"], "khong-co", against="HEAD")


def test_render_diff_groups(git_kb):
    report = diff_doc(git_kb["kb"], "demo-doc", against=git_kb["rev1"])
    text = render_diff(report)
    assert "~ §1.1" in text
    assert "summary" in text
