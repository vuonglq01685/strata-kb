import pytest

from aero_kb import models
from aero_kb.review import approve_sections


def _statuses(kb, doc_id="demo-doc"):
    manifest = models.load_yaml_model(kb / doc_id / "_manifest.yaml", models.Manifest)
    return {s.id: s.status for s in manifest.sections}


def test_approve_flips_all_summarized_sections(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc")
    assert report.flipped == ["1.1", "1.2"]
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "reviewed"}


def test_approve_specific_section_only(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc", ["1.1"])
    assert report.flipped == ["1.1"]
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "summarized"}


def test_approve_skips_pending_and_reports_it(git_kb):
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].status = "pending"
    models.save_yaml_model(manifest_path, manifest)

    report = approve_sections(git_kb["kb"], "demo-doc")
    assert report.flipped == ["1.2"]
    assert report.skipped_pending == ["1.1"]
    assert _statuses(git_kb["kb"])["1.1"] == "pending"


def test_approve_is_idempotent(git_kb):
    approve_sections(git_kb["kb"], "demo-doc")
    report = approve_sections(git_kb["kb"], "demo-doc")
    assert report.flipped == []
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "reviewed"}


def test_approve_reports_missing_section(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc", ["9.9"])
    assert report.missing == ["9.9"]
    assert report.flipped == []


def test_approve_unknown_doc_raises(git_kb):
    with pytest.raises(ValueError, match="missing-doc"):
        approve_sections(git_kb["kb"], "missing-doc")
