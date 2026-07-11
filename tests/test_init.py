from pathlib import Path

from typer.testing import CliRunner

from aero_kb.cli import app
from aero_kb.initcmd import EXPECTED_FILES, init_repo

runner = CliRunner()


def test_init_creates_all_files(tmp_path: Path):
    report = init_repo(tmp_path)
    assert sorted(report.created) == sorted(EXPECTED_FILES)
    assert report.skipped == []
    for rel in EXPECTED_FILES:
        assert (tmp_path / rel).is_file(), rel


def test_init_is_idempotent_never_overwrites(tmp_path: Path):
    init_repo(tmp_path)
    marker = tmp_path / ".kb" / "index.yaml"
    marker.write_text("docs: [{id: keep-me, title: X}]\n", encoding="utf-8")
    report = init_repo(tmp_path)
    assert report.created == []
    assert sorted(report.skipped) == sorted(EXPECTED_FILES)
    assert "keep-me" in marker.read_text(encoding="utf-8")


def test_init_force_overwrites(tmp_path: Path):
    init_repo(tmp_path)
    marker = tmp_path / ".kb" / "index.yaml"
    marker.write_text("docs: [{id: gone, title: X}]\n", encoding="utf-8")
    report = init_repo(tmp_path, force=True)
    assert sorted(report.created) == sorted(EXPECTED_FILES)
    assert "gone" not in marker.read_text(encoding="utf-8")


def test_kb_doctor_passes_on_fresh_skeleton(tmp_path: Path):
    init_repo(tmp_path)
    result = runner.invoke(app, ["doctor", "--kb-dir", str(tmp_path / ".kb")])
    assert result.exit_code == 0
    assert "kb doctor: OK" in result.output


def test_cli_init_reports_and_next_steps(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert "created" in result.output
    assert "kb ingest" in result.output
    result2 = runner.invoke(app, ["init", str(tmp_path)])
    assert result2.exit_code == 0
    assert "skipped" in result2.output


def test_quickstart_uses_correct_ingest_flag(tmp_path: Path):
    init_repo(tmp_path)
    text = (tmp_path / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "--id" in text
    assert "--doc-id" not in text
