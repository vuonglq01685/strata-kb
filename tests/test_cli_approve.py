from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app

runner = CliRunner()


def _statuses(kb, doc_id="demo-doc"):
    manifest = models.load_yaml_model(kb / doc_id / "_manifest.yaml", models.Manifest)
    return {s.id: s.status for s in manifest.sections}


def test_approve_doc_flips_all_summarized(git_kb):
    result = runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 0
    assert "2 section(s)" in result.output
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "reviewed"}


def test_approve_single_section(git_kb):
    result = runner.invoke(
        app,
        ["approve", "demo-doc", "--section", "1.1", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "summarized"}


def test_approve_all_changed_ci_mode(git_kb):
    result = runner.invoke(
        app,
        [
            "approve",
            "--all-changed",
            "--against",
            git_kb["rev1"],
            "--kb-dir",
            str(git_kb["kb"]),
        ],
    )
    assert result.exit_code == 0
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "summarized"}


def test_approve_all_changed_nothing_to_do_exits_0(git_kb):
    result = runner.invoke(
        app,
        ["approve", "--all-changed", "--against", "HEAD", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert "nothing to approve" in result.output


def test_approve_explicit_nothing_to_flip_exits_1(git_kb):
    runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    result = runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1


def test_approve_missing_section_exits_1(git_kb):
    result = runner.invoke(
        app,
        ["approve", "demo-doc", "--section", "9.9", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 1


def test_approve_unknown_doc_exits_1(git_kb):
    result = runner.invoke(app, ["approve", "missing-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1


def test_approve_bad_rev_exits_1(git_kb):
    result = runner.invoke(
        app,
        [
            "approve",
            "--all-changed",
            "--against",
            "deadbeef1234",
            "--kb-dir",
            str(git_kb["kb"]),
        ],
    )
    assert result.exit_code == 1


def test_all_changed_requires_against(git_kb):
    result = runner.invoke(app, ["approve", "--all-changed", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1


def test_against_requires_all_changed(git_kb):
    result = runner.invoke(
        app,
        ["approve", "demo-doc", "--against", "HEAD", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 1


def test_section_incompatible_with_all_changed(git_kb):
    result = runner.invoke(
        app,
        [
            "approve",
            "demo-doc",
            "--section",
            "1.1",
            "--all-changed",
            "--against",
            "HEAD",
            "--kb-dir",
            str(git_kb["kb"]),
        ],
    )
    assert result.exit_code == 1


def test_doc_id_required_without_all_changed(git_kb):
    result = runner.invoke(app, ["approve", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1


def test_approve_refuses_dirty_tree(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Airspace Records\n\nx\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1 and "commit .kb/demo-doc before approving" in result.output
    assert _statuses(git_kb["kb"]) == {"1.1": "summarized", "1.2": "summarized"}


def test_approve_refuses_when_strict_build_fails(git_kb, run_git):
    from tests.conftest import TABLE

    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            TABLE, TABLE + "\n\n| X | Y |\n|---|---|\n| 1 | 2 |"
        ),
        encoding="utf-8",
    )
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "fabricated table")
    result = runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1 and "table" in result.output
    assert _statuses(git_kb["kb"]) == {"1.1": "summarized", "1.2": "summarized"}


def test_approve_by_flag_is_recorded(git_kb):
    result = runner.invoke(
        app, ["approve", "demo-doc", "--by", "Ada <ada@x>", "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0, result.output
    m = models.load_yaml_model(git_kb["kb"] / "demo-doc" / "_manifest.yaml", models.Manifest)
    assert {s.reviewed.by for s in m.sections} == {"Ada <ada@x>"}


def test_approve_prints_commit_reminder_on_success(git_kb):
    result = runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 0
    assert "commit .kb/demo-doc to record the approval" in result.output


def _mark_1_2_pending(kb, run_git, root) -> None:
    """A REAL pending section — TODO marker in L2, empty summary, status
    pending — exactly as `kb ingest` leaves an unsummarized section."""
    manifest_path = kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[1].status = "pending"
    manifest.sections[1].summary = ""
    models.save_yaml_model(manifest_path, manifest)
    l2 = kb / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "Condensed: airway record structure, route identifiers.",
            "<!-- TODO:summarize 1.2 -->",
        ),
        encoding="utf-8",
    )
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "1.2 back to pending")


def test_approve_section_scoped_unblocked_by_pending_sibling(git_kb, run_git):
    """R9: `kb approve demo-doc --section 1.1` must succeed even though the
    doc's other section (1.2) is pending — a pending sibling section is not
    a reason to block approving a different, already-summarized section."""
    _mark_1_2_pending(git_kb["kb"], run_git, git_kb["root"])
    result = runner.invoke(
        app, ["approve", "demo-doc", "--section", "1.1", "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0, result.output
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "pending"}


def test_approve_whole_doc_unblocked_by_pending_section_reports_it(git_kb, run_git):
    """R9: approving the whole doc still succeeds with a pending section
    present; that section is reported as skipped (existing behavior), not
    as a blocking build error."""
    _mark_1_2_pending(git_kb["kb"], run_git, git_kb["root"])
    result = runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 0, result.output
    assert "1.2 is still pending" in result.output
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "pending"}


def test_approve_all_changed_blocked_by_unrelated_doc_error(git_kb, run_git):
    """R10: `--all-changed` keeps gating every doc with a manifest, not just
    the docs that actually changed vs `--against` — an unrelated doc with a
    genuine strict-build error blocks the whole run, and the message names
    that doc."""
    broken_dir = git_kb["kb"] / "broken-doc"
    broken_dir.mkdir()
    real_table = "| C | D |\n|---|---|\n| x | y |"
    extra_table = "| X | Y |\n|---|---|\n| 1 | 2 |"
    (broken_dir / "f.md").write_text(
        f"## 1 A\n\nProse for the broken doc.\n\n{real_table}\n\n{extra_table}\n",
        encoding="utf-8",
    )
    (broken_dir / "f.raw.md").write_text(
        f"## 1 A\n\nProse for the broken doc.\n\n{real_table}\n", encoding="utf-8"
    )
    models.save_yaml_model(
        broken_dir / "_manifest.yaml",
        models.Manifest(id="broken-doc", title="Broken", sections=[
            models.SectionEntry(id="1", title="A", summary="Broken doc section summary.",
                                 status="summarized", file="f")
        ]),
    )
    ipath = git_kb["kb"] / "index.yaml"
    idx = models.load_yaml_model(ipath, models.KBIndex)
    idx.docs.append(models.IndexEntry(id="broken-doc", title="Broken", summary="s"))
    models.save_yaml_model(ipath, idx)
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "add broken-doc")

    result = runner.invoke(
        app,
        ["approve", "--all-changed", "--against", git_kb["rev1"], "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 1
    assert "broken-doc" in result.output
    assert _statuses(git_kb["kb"]) == {"1.1": "summarized", "1.2": "summarized"}


def test_build_fails_after_l2_edit_post_approval(git_kb, run_git):
    from center_kb.build import build_kb

    assert runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])]).exit_code == 0
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("Condensed: airway", "Condensed: AIRWAY"),
        encoding="utf-8",
    )
    assert any("L2 changed after review" in e for e in build_kb(git_kb["kb"]).errors)
