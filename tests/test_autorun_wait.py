from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb.autorun import wait
from strata_kb.autorun.state import AutoState, save
from strata_kb.cli import app

cli = CliRunner()


def _state(task="dev-implement-ticket:US-1", attempts=0, waiting=(), stop=None):
    return AutoState(task, attempts, tuple(waiting), stop, "")


def _clock(step: int = 1):
    t = {"v": 0}

    def now() -> float:
        t["v"] += step
        return t["v"]

    return now


def test_wait_reports_stop(tmp_path, monkeypatch):
    save(tmp_path, _state(stop="ci-red"))
    monkeypatch.setattr(wait, "running_pid", lambda kb: None)

    got = wait.wait_for_change(tmp_path, 100, sleep=lambda s: None, now=_clock())

    assert got == "stopped: ci-red"


def test_wait_probes_the_pid_before_reading_state(tmp_path, monkeypatch):
    # loop writes stop_reason and exits between the two reads: the pid probe
    # must come first so the later state read still sees the reason.
    save(tmp_path, _state())

    def probe(kb):
        save(tmp_path, _state(stop="ci-red"))
        return None

    monkeypatch.setattr(wait, "running_pid", probe)

    got = wait.wait_for_change(tmp_path, 100, sleep=lambda s: None, now=_clock())

    assert got == "stopped: ci-red"


def test_wait_reports_not_running_without_a_reason(tmp_path, monkeypatch):
    save(tmp_path, _state())
    monkeypatch.setattr(wait, "running_pid", lambda kb: None)

    got = wait.wait_for_change(tmp_path, 100, sleep=lambda s: None, now=_clock())

    assert got == "not running — see .kb/auto/run.log"


def test_wait_reports_progress_on_task_change(tmp_path, monkeypatch):
    save(tmp_path, _state())
    monkeypatch.setattr(wait, "running_pid", lambda kb: 42)

    def sleeper(_):
        save(tmp_path, _state(task="ba-answer-questions:qa", attempts=1, waiting=(3, 4)))

    got = wait.wait_for_change(tmp_path, 100, sleep=sleeper, now=_clock())

    assert got == "progress: ba-answer-questions:qa, attempt 1, waiting on Q3,Q4"


def test_wait_progress_names_idle_without_a_task(tmp_path, monkeypatch):
    save(tmp_path, _state())
    monkeypatch.setattr(wait, "running_pid", lambda kb: 42)

    def sleeper(_):
        save(tmp_path, _state(task=None, attempts=0))

    assert (
        wait.wait_for_change(tmp_path, 100, sleep=sleeper, now=_clock())
        == "progress: idle, attempt 0"
    )


def test_wait_times_out_still_running(tmp_path, monkeypatch):
    save(tmp_path, _state())
    monkeypatch.setattr(wait, "running_pid", lambda kb: 42)

    got = wait.wait_for_change(
        tmp_path, 10, interval=5, sleep=lambda s: None, now=_clock(step=6)
    )

    assert got == "still running: dev-implement-ticket:US-1, attempt 0"


def test_wait_sleeps_the_interval_between_reads(tmp_path, monkeypatch):
    save(tmp_path, _state())
    monkeypatch.setattr(wait, "running_pid", lambda kb: 42)
    naps: list[float] = []

    wait.wait_for_change(
        tmp_path, 20, interval=7, sleep=naps.append, now=_clock(step=10)
    )

    assert naps and all(0 < n <= 7 for n in naps)


def test_wait_cli_prints_the_line(tmp_path, monkeypatch):
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text("kind: dev\n", encoding="utf-8", newline="\n")
    save(kb, _state(stop="usage-limit"))
    monkeypatch.setattr(wait, "running_pid", lambda k: None)

    result = cli.invoke(app, ["auto", "wait", "--kb-dir", str(kb), "--max", "5"])

    assert result.exit_code == 0
    assert result.output.strip() == "stopped: usage-limit"


def test_wait_refuses_inside_auto_task(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATA_KB_AUTO_TASK", "1")

    result = cli.invoke(app, ["auto", "wait", "--kb-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "refused inside an auto-mode task" in result.output
