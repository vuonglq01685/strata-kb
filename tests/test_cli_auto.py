from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb.autorun import lock as lock_mod
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


@pytest.mark.parametrize("error", [OSError("disk gone"), ValueError("bad yaml")])
def test_once_config_or_os_error_is_one_red_line(repo, monkeypatch, error):
    from strata_kb.autorun import state as autostate

    autostate.save(repo, autostate.AutoState(None, 2, (), "old", ""))

    def boom(kb, hub=""):
        raise error

    monkeypatch.setattr(runner_mod, "build_deps", boom)

    result = cli.invoke(app, ["auto", "run", "--once"])

    assert result.exit_code == 1
    assert str(error) in result.output and "Traceback" not in result.output
    assert not isinstance(result.exception, OSError | ValueError)
    assert autostate.load(repo).stop_reason == "old"  # resume ran only after build_deps


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


def test_second_run_refuses_while_the_lock_is_held(repo, monkeypatch):
    _fake_deps(monkeypatch)
    monkeypatch.setattr(runner_mod, "run_once", lambda *a, **k: "idle")
    with lock_mod.run_lock(repo):
        result = cli.invoke(app, ["auto", "run", "--once"])
    assert result.exit_code == 1
    assert "already running" in result.output
    assert lock_mod.running_pid(repo) is None  # the outer lock released


def test_run_releases_the_lock_on_exit(repo, monkeypatch):
    _fake_deps(monkeypatch)
    monkeypatch.setattr(runner_mod, "run_once", lambda *a, **k: "idle")
    result = cli.invoke(app, ["auto", "run", "--once"])
    assert result.exit_code == 0
    assert lock_mod.running_pid(repo) is None


@pytest.mark.parametrize("action", ["on", "off", "run"])
def test_auto_on_off_run_refuse_inside_an_auto_task(repo, monkeypatch, action):
    monkeypatch.setenv(runner_mod.AUTO_TASK_ENV, "1")
    result = cli.invoke(app, ["auto", action])
    assert result.exit_code == 1
    assert "refused inside an auto-mode task" in result.output
    assert "enabled: true" in (repo / "config.yaml").read_text(encoding="utf-8")


def test_auto_status_still_works_inside_an_auto_task(repo, monkeypatch):
    monkeypatch.setenv(runner_mod.AUTO_TASK_ENV, "1")
    result = cli.invoke(app, ["auto", "status", "--json"])
    assert result.exit_code == 0


def _capture_loop(monkeypatch) -> dict:
    seen: dict = {}
    monkeypatch.setattr(runner_mod, "run_loop", lambda *a, **kw: seen.update(kw) or 0)
    return seen


def test_auto_run_passes_model_and_effort(repo, monkeypatch):
    seen = _capture_loop(monkeypatch)

    cli.invoke(app, ["auto", "run", "--model", "m1", "--effort", "high"])

    assert seen["run_task"].keywords == {"model": "m1", "effort": "high"}


def test_auto_run_defaults_model_to_opus(repo, monkeypatch):
    seen = _capture_loop(monkeypatch)

    cli.invoke(app, ["auto", "run"])
    assert seen["run_task"].keywords == {"model": "opus", "effort": ""}

    cli.invoke(app, ["auto", "run", "--model", ""])
    assert seen["run_task"].keywords == {"model": "", "effort": ""}


def test_once_passes_model_and_effort(repo, monkeypatch):
    _fake_deps(monkeypatch)
    seen: dict = {}
    monkeypatch.setattr(
        runner_mod, "run_once", lambda *a, **kw: seen.update(kw) or "idle"
    )

    cli.invoke(app, ["auto", "run", "--once", "--effort", "low"])

    assert seen["run_task"].keywords == {"model": "opus", "effort": "low"}


@pytest.mark.parametrize(
    ("kind", "extra"), [("dev", []), ("ba", [Path(".kb/auto/worktrees/qa")])]
)
def test_auto_run_writes_trust_on_cloud_only(repo, monkeypatch, kind, extra):
    from strata_kb.autorun import trust

    _capture_loop(monkeypatch)
    (repo / "config.yaml").write_text(
        GOOD.replace("kind: dev", f"kind: {kind}"), encoding="utf-8"
    )
    calls: list = []
    monkeypatch.setattr(
        trust, "trust_dirs", lambda paths, config=None: calls.append(list(paths))
    )

    monkeypatch.setenv("STRATA_KB_CLOUD", "0")
    cli.invoke(app, ["auto", "run"])
    assert calls == []

    monkeypatch.setenv("STRATA_KB_CLOUD", "1")
    cli.invoke(app, ["auto", "run"])
    root = repo.parent.resolve()
    assert [[p.resolve() for p in c] for c in calls] == [
        [root, *[(root / e).resolve() for e in extra]]
    ]
