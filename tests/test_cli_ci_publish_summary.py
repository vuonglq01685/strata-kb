# tests/test_cli_ci_publish_summary.py
from typer.testing import CliRunner

from strata_kb import cipublish
from strata_kb.cli import app

runner = CliRunner()


def _kb(tmp_path):
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text('intake: "https://kb.test"\nrepo_id: "demo"\n', encoding="utf-8")
    return kb


def test_writes_the_pr_url(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(cipublish, "run", lambda *a, **k: "https://gh/pull/8")
    result = runner.invoke(app, ["ci-publish", "--kb-dir", str(_kb(tmp_path))])
    assert result.exit_code == 0, result.output
    assert summary.read_text(encoding="utf-8") == "kb ci-publish: hub PR: https://gh/pull/8\n"


def test_writes_no_change(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(cipublish, "run", lambda *a, **k: "")
    runner.invoke(app, ["ci-publish", "--kb-dir", str(_kb(tmp_path))])
    assert summary.read_text(encoding="utf-8") == "kb ci-publish: no content change on the hub\n"


def test_writes_the_error(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def boom(*a, **k):
        raise cipublish.CIPublishError("intake rejected the publish (HTTP 403): nope")

    monkeypatch.setattr(cipublish, "run", boom)
    result = runner.invoke(app, ["ci-publish", "--kb-dir", str(_kb(tmp_path))])
    assert result.exit_code == 1
    assert "error — intake rejected" in summary.read_text(encoding="utf-8")


def test_no_summary_outside_actions(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    cipublish.write_step_summary("anything")  # must not raise or write
