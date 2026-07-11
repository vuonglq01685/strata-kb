from pathlib import Path

from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app
from tests.test_summarize import FakeRunner, make_kb

runner = CliRunner()


def _patch_detect(monkeypatch, fake):
    import center_kb.llm as llm_mod

    # cli._run_summarize looks detect_runner up on the module at call time,
    # so patching the module attribute is enough.
    monkeypatch.setattr(llm_mod, "detect_runner", lambda choice, cfg: fake)


def test_summarize_success_exit_0(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "2 summarized" in result.output
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" for s in manifest.sections)


def test_summarize_failed_section_exit_1(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _patch_detect(monkeypatch, FakeRunner(fail_ids={"1.2"}))
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert "1 failed" in result.output
    assert "kb summarize" in result.output  # re-run hint


def test_summarize_no_runner_exit_1(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _patch_detect(monkeypatch, None)
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert "claude" in result.output and "copilot" in result.output


def test_summarize_runner_none_exit_1(tmp_path: Path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb), "--llm", "none"])
    assert result.exit_code == 1
    assert "none" in result.output


def test_summarize_bad_llm_value_exit_2(tmp_path: Path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb), "--llm", "gemini"])
    assert result.exit_code == 2


def test_summarize_nothing_pending_exit_0(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 0
    assert "0" in result.output
