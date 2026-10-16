from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb.autorun import runner as runner_mod
from strata_kb.cli import app
from strata_kb.config import KBConfig
from strata_kb.hub import HubHandle

cli = CliRunner()

GOOD = "kind: dev\nrepo_id: svc\nintake: http://i\nauto:\n  enabled: true\n"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    (kb_dir / "config.yaml").write_text(GOOD, encoding="utf-8", newline="\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    monkeypatch.setattr(runner_mod, "preflight", lambda root, kb, hub="": [])
    return kb_dir


def _fake_deps(monkeypatch) -> None:
    monkeypatch.setattr(
        runner_mod,
        "build_deps",
        lambda kb, hub="": (KBConfig(), HubHandle(root=Path(".")), object()),
    )


def test_run_refuses_when_switch_off_and_shows_reason(repo, monkeypatch):
    monkeypatch.undo()  # real preflight
    monkeypatch.chdir(repo.parent)
    (repo / "config.yaml").write_text(GOOD.replace("true", "false"), encoding="utf-8")

    result = cli.invoke(app, ["auto", "run"])

    assert result.exit_code == 1
    assert "kb auto on" in result.output


def test_run_lists_every_refusal(repo, monkeypatch):
    monkeypatch.setattr(runner_mod, "preflight", lambda root, kb, hub="": ["a", "b"])

    result = cli.invoke(app, ["auto", "run"])

    assert result.exit_code == 1
    assert "a" in result.output and "b" in result.output


@pytest.mark.parametrize(
    ("outcome", "code"),
    [("ran", 0), ("idle", 0), ("waiting", 0), ("done", 0), ("stopped", 2)],
)
def test_once_prints_outcome_and_maps_exit_code(repo, monkeypatch, outcome, code):
    _fake_deps(monkeypatch)
    monkeypatch.setattr(runner_mod, "run_once", lambda *a, **kw: outcome)

    result = cli.invoke(app, ["auto", "run", "--once"])

    assert result.exit_code == code
    assert result.output.strip() == outcome


def test_once_clears_old_stop_reason(repo, monkeypatch):
    from strata_kb.autorun import state as autostate

    _fake_deps(monkeypatch)
    autostate.save(repo, autostate.AutoState(None, 2, (), "old", ""))
    monkeypatch.setattr(runner_mod, "run_once", lambda *a, **kw: "ran")

    cli.invoke(app, ["auto", "run", "--once"])

    assert autostate.load(repo).stop_reason is None


@pytest.mark.parametrize("flags", [[], ["--once"]])
def test_missing_token_is_one_red_line_not_a_traceback(repo, monkeypatch, flags):
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub")
    monkeypatch.delenv("STRATA_KB_HTTP_TOKEN", raising=False)

    result = cli.invoke(app, ["auto", "run", *flags])

    assert result.exit_code == 1
    assert "STRATA_KB_HTTP_TOKEN" in result.output
    assert "Traceback" not in result.output
    assert not isinstance(result.exception, KeyError | AttributeError)


def test_loop_exit_code_passes_through(repo, monkeypatch):
    monkeypatch.setattr(runner_mod, "run_loop", lambda *a, **kw: 2)

    result = cli.invoke(app, ["auto", "run"])

    assert result.exit_code == 2


def test_loop_done_exits_zero(repo, monkeypatch):
    monkeypatch.setattr(runner_mod, "run_loop", lambda *a, **kw: 0)

    assert cli.invoke(app, ["auto", "run"]).exit_code == 0


def test_hub_flag_reaches_the_loop(repo, monkeypatch):
    seen = {}
    monkeypatch.setattr(runner_mod, "run_loop", lambda *a, **kw: seen.update(kw) or 0)

    cli.invoke(app, ["auto", "run", "--hub", "/some/hub"])

    assert seen["hub_flag"] == "/some/hub"


def test_ctrl_c_exits_130_without_traceback(repo, monkeypatch):
    def interrupted(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner_mod, "run_loop", interrupted)

    result = cli.invoke(app, ["auto", "run"])

    assert result.exit_code == 130
    assert "stopped by user" in result.output
