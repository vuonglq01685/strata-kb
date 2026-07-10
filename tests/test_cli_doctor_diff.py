from typer.testing import CliRunner

from aero_kb.cli import app

runner = CliRunner()


def test_diff_shows_changed_section(git_kb):
    result = runner.invoke(
        app,
        ["diff", "demo-doc", "--against", git_kb["rev1"], "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert "~ §1.1" in result.output


def test_diff_unknown_doc_exits_1(git_kb):
    result = runner.invoke(
        app, ["diff", "khong-co", "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 1


def test_doctor_clean_kb(git_kb):
    result = runner.invoke(app, ["doctor", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_doctor_broken_kb_exits_1(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.raw.md").unlink()
    result = runner.invoke(app, ["doctor", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1
    assert "[error]" in result.output


def test_doctor_context_stale_exits_2(git_kb, tmp_path_factory):
    ticket = tmp_path_factory.mktemp("t") / "tal.md"
    ticket.write_text(
        f"kb-context:\n  version: {git_kb['rev1']}\n  refs:\n    - demo-doc §1.1\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["doctor", "--context", str(ticket), "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 2
    assert "[warning]" in result.output


def test_doctor_context_broken_exits_1(git_kb, tmp_path_factory):
    ticket = tmp_path_factory.mktemp("t") / "tal.md"
    ticket.write_text(
        f"kb-context:\n  version: {git_kb['rev2']}\n  refs:\n    - demo-doc §9.9\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["doctor", "--context", str(ticket), "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 1
