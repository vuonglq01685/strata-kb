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
