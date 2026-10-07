from pathlib import Path

from typer.testing import CliRunner

from strata_kb.cli import app

runner = CliRunner()


def test_impl_tidy_moves_and_reports(tmp_path: Path):
    d = tmp_path / "impl"
    d.mkdir()
    (d / "ABC-12-plan.md").write_text("p", encoding="utf-8")
    result = runner.invoke(app, ["impl", "tidy", "--impl-dir", str(d)])
    assert result.exit_code == 0, result.output
    assert "moved:" in result.output
    assert (d / "ABC-12" / "plan.md").is_file()
    again = runner.invoke(app, ["impl", "tidy", "--impl-dir", str(d)])
    assert again.exit_code == 0
    assert "nothing to tidy" in again.output


def test_impl_tidy_reports_conflicts_and_exits_0(tmp_path: Path):
    d = tmp_path / "impl"
    (d / "ABC-12").mkdir(parents=True)
    (d / "ABC-12" / "plan.md").write_text("new", encoding="utf-8")
    (d / "ABC-12-plan.md").write_text("old", encoding="utf-8")
    result = runner.invoke(app, ["impl", "tidy", "--impl-dir", str(d)])
    assert result.exit_code == 0
    assert "conflict:" in result.output


def test_impl_tidy_missing_dir_is_exit_1(tmp_path: Path):
    result = runner.invoke(app, ["impl", "tidy", "--impl-dir", str(tmp_path / "nope")])
    assert result.exit_code == 1
