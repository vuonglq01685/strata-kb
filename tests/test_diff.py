import pytest
import yaml

from center_kb import models
from center_kb.diff import diff_doc, render_diff


def test_changed_summary_detected(git_kb):
    # fixture: §1.1's summary (L1) + prose (L2) change between rev1 and the worktree; L3 stays the same
    report = diff_doc(git_kb["kb"], "demo-doc", against=git_kb["rev1"])
    assert [c.section_id for c in report.changed] == ["1.1"]
    assert report.changed[0].summary_changed is True
    assert report.changed[0].content_changed is False
    assert report.changed[0].prose_changed is True
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
    kept = [s for s in manifest.sections if s.id != "1.2"]  # remove 1.2
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
    # add+remove alone must not read as a reorder (guards the `common`-id
    # restriction in diff_doc: dropping it made this pass by accident).
    assert report.order_changed is False


def test_unknown_doc_raises(git_kb):
    with pytest.raises(ValueError, match="missing-doc"):
        diff_doc(git_kb["kb"], "missing-doc", against="HEAD")


def test_render_diff_groups(git_kb):
    report = diff_doc(git_kb["kb"], "demo-doc", against=git_kb["rev1"])
    text = render_diff(report)
    assert "~ §1.1" in text
    assert "summary" in text


def test_render_diff_shows_review_record(git_kb):
    from center_kb.review import approve_sections

    approve_sections(git_kb["kb"], "demo-doc", ["1.1"], by="sme <sme@x>")
    out = render_diff(diff_doc(git_kb["kb"], "demo-doc", against=git_kb["rev1"]))
    assert "~ §1.1 Airspace Records" in out and "reviewed by sme <sme@x> at " in out


def test_render_diff_shows_review_record_on_added_section():
    """Important #3: an added ('+ §…') section that already carries a
    review record must show the sign-off, same as a changed ('~ §…')
    section does."""
    from center_kb.diff import DiffReport, SectionChange

    report = DiffReport(
        doc_id="demo-doc",
        against="HEAD",
        added=[
            SectionChange(
                "1.3", "Waypoint Records",
                reviewed_by="sme <sme@x>", reviewed_at="2026-01-01T00:00:00+00:00",
            )
        ],
    )
    text = render_diff(report)
    assert "+ §1.3 Waypoint Records — reviewed by sme <sme@x> at 2026-01-01T00:00:00+00:00" in text


def test_render_diff_added_without_review_record_unchanged():
    from center_kb.diff import DiffReport, SectionChange

    report = DiffReport(
        doc_id="demo-doc", against="HEAD",
        added=[SectionChange("1.3", "Waypoint Records")],
    )
    text = render_diff(report)
    assert text.splitlines()[1] == "+ §1.3 Waypoint Records"


def test_prose_changed_when_l2_edited(git_kb):
    # edit ONLY the L2 prose of §1.2 — summary (L1) and raw (L3) untouched
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "airway record structure, route identifiers.",
            "airway record structure, REVISED identifiers.",
        ),
        encoding="utf-8",
    )
    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")
    assert [c.section_id for c in report.changed] == ["1.2"]
    change = report.changed[0]
    assert change.prose_changed is True
    assert change.summary_changed is False
    assert change.content_changed is False
    assert "prose" in render_diff(report)


def test_title_change_in_the_manifest_only_is_reported(git_kb):
    # git_kb's worktree is clean against HEAD (see test_no_changes_against_head)
    # -- reuse it rather than hand-rolling a second repo builder.
    manifest = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        text.replace("title: Airspace Records", "title: Airspace Records and scope"),
        encoding="utf-8",
        newline="\n",
    )

    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")

    assert [c.section_id for c in report.changed] == ["1.1"]
    assert report.changed[0].title_changed is True
    assert "(title)" in render_diff(report)


def test_manifest_reorder_is_reported_once(git_kb):
    manifest = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    m = models.Manifest.model_validate(
        yaml.safe_load(manifest.read_text(encoding="utf-8"))
    )
    m.sections.reverse()
    models.save_yaml_model(manifest, m)

    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")

    assert report.order_changed is True
    assert report.has_changes is True
    assert "section order changed" in render_diff(report)


def test_renumber_stays_add_plus_remove(git_kb):
    """A section id is the citation key -- an SME must see the old one go."""
    manifest = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("id: '1.1'", "id: '1.4'"),
        encoding="utf-8",
        newline="\n",
    )

    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")

    assert [c.section_id for c in report.added] == ["1.4"]
    assert [c.section_id for c in report.removed] == ["1.1"]
    assert report.changed == []
    # add+remove (a renumber) alone must not read as a reorder -- this is
    # the guard `diff_doc` restricts order comparison to common ids for.
    assert report.order_changed is False
