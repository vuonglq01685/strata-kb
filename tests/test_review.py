import pytest

from aero_kb import gitio, models
from aero_kb.review import approve_all_changed, approve_sections, changed_section_ids


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


def test_approve_duplicate_missing_ids_reported_once(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc", ["9.9", "9.9"])
    assert report.missing == ["9.9"]


def test_approve_unknown_doc_raises(git_kb):
    with pytest.raises(ValueError, match="missing-doc"):
        approve_sections(git_kb["kb"], "missing-doc")


def _add_new_doc(kb, register_in_index: bool) -> None:
    """A doc present in the worktree but absent at every committed rev."""
    doc_dir = kb / "new-doc"
    doc_dir.mkdir()
    (doc_dir / "ch1.md").write_text("## 1.1 Intro\n\nCondensed intro.\n", encoding="utf-8")
    (doc_dir / "ch1.raw.md").write_text("## 1.1 Intro\n\nRaw intro.\n", encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="new-doc",
            title="New Doc",
            sections=[
                models.SectionEntry(
                    id="1.1",
                    title="Intro",
                    summary="Intro summary.",
                    status="summarized",
                    file="ch1",
                )
            ],
        ),
    )
    if register_in_index:
        index_path = kb / "index.yaml"
        index = models.load_yaml_model(index_path, models.KBIndex)
        index.docs.append(models.IndexEntry(id="new-doc", title="New Doc"))
        models.save_yaml_model(index_path, index)


def test_changed_ids_since_rev1(git_kb):
    # only §1.1 changed between rev1 and HEAD/worktree (see git_kb fixture)
    assert changed_section_ids(git_kb["kb"], "demo-doc", git_kb["rev1"]) == ["1.1"]


def test_changed_ids_catches_l2_only_edit(git_kb):
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "airway record structure, route identifiers.",
            "airway record structure, REVISED identifiers.",
        ),
        encoding="utf-8",
    )
    assert changed_section_ids(git_kb["kb"], "demo-doc", "HEAD") == ["1.2"]


def test_changed_ids_new_doc_returns_none(git_kb):
    _add_new_doc(git_kb["kb"], register_in_index=False)
    assert changed_section_ids(git_kb["kb"], "new-doc", "HEAD") is None


def test_all_changed_flips_only_changed_sections(git_kb):
    reports = approve_all_changed(git_kb["kb"], git_kb["rev1"])
    assert [(r.doc_id, r.flipped) for r in reports] == [("demo-doc", ["1.1"])]
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "summarized"}


def test_all_changed_nothing_changed_returns_empty(git_kb):
    assert approve_all_changed(git_kb["kb"], "HEAD") == []
    assert _statuses(git_kb["kb"]) == {"1.1": "summarized", "1.2": "summarized"}


def test_all_changed_new_doc_flips_all_its_summarized_sections(git_kb):
    _add_new_doc(git_kb["kb"], register_in_index=True)
    reports = approve_all_changed(git_kb["kb"], "HEAD")
    by_doc = {r.doc_id: r.flipped for r in reports}
    assert by_doc == {"new-doc": ["1.1"]}
    assert _statuses(git_kb["kb"], "new-doc") == {"1.1": "reviewed"}


def test_all_changed_single_doc_scope(git_kb):
    _add_new_doc(git_kb["kb"], register_in_index=True)
    reports = approve_all_changed(git_kb["kb"], git_kb["rev1"], doc_id="demo-doc")
    assert [r.doc_id for r in reports] == ["demo-doc"]
    # new-doc untouched despite being changed too
    assert _statuses(git_kb["kb"], "new-doc") == {"1.1": "summarized"}


def test_all_changed_bad_rev_raises(git_kb):
    with pytest.raises(gitio.GitError):
        approve_all_changed(git_kb["kb"], "deadbeef1234")
