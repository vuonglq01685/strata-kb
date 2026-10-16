from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from strata_kb import gitio
from strata_kb.autorun.claude import TaskResult
from strata_kb.autorun.qathread import QaThread, open_question_count
from strata_kb.errors import KbError

WAIT = 10  # generous bound on event waits; passing runs never reach it


class FakeQa:
    def __init__(self, open_=(1,), fail=False):
        self.open_, self.fail, self.calls = list(open_), fail, []

    def list(self, status="open", repo="", ticket=""):
        self.calls.append((status, repo, ticket))
        if self.fail:
            raise KbError("hub answered 500")
        return [{"id": i} for i in self.open_]


class Runner:
    """Fake `run_task`: records each call, finishes when `release` is set."""

    def __init__(self, result=None):
        self.result = result or TaskResult("done")
        self.calls: list[tuple[Path, str]] = []
        self.branches: list[str] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def __call__(self, root, prompt, *, log_dir):
        self.calls.append((root, prompt))
        self.branches.append(gitio.current_branch(root))
        self.started.set()
        assert self.release.wait(WAIT)
        self.finished.set()
        return self.result


@pytest.fixture
def repo(tmp_path: Path, run_git) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    kb_dir = root / ".kb"
    kb_dir.mkdir(parents=True)
    run_git(root, "init", "-b", "main")
    (root / "a.txt").write_text("a\n", encoding="utf-8", newline="\n")
    run_git(root, "add", "a.txt")
    run_git(root, "commit", "-m", "init")
    return root, kb_dir


def make(repo, qa=None, runner=None, interval=5):
    root, kb_dir = repo
    qa = qa or FakeQa()
    runner = runner or Runner()
    return QaThread(root, kb_dir, qa, interval, "svc", run_task=runner), qa, runner


def settle(qt: QaThread) -> None:
    """Wait for the in-flight process thread to wind down."""
    assert qt._proc_thread is not None
    qt._proc_thread.join(WAIT)
    assert not qt._proc_thread.is_alive()


def test_tick_launches_in_worktree_on_qa_branch(repo):
    root, kb_dir = repo
    qt, qa, runner = make(repo)
    runner.release.set()
    assert qt.tick() is True
    settle(qt)
    worktree = kb_dir / "auto" / "worktrees" / "qa"
    assert runner.calls[0][0] == worktree != root
    assert runner.calls[0][1].startswith("/ba-answer-questions")
    assert runner.branches == ["auto/qa"]
    assert qa.calls == [("open", "svc", "")]


def test_tick_no_open_questions_launches_nothing(repo):
    qt, _, runner = make(repo, qa=FakeQa(open_=()))
    assert qt.tick() is False
    assert runner.calls == []


def test_tick_returns_false_while_process_runs(repo):
    qt, _, runner = make(repo)
    assert qt.tick() is True
    assert runner.started.wait(WAIT)
    assert qt.tick() is False
    assert len(runner.calls) == 1
    runner.release.set()
    settle(qt)
    assert qt.tick() is True


def test_tick_recreates_worktree_from_default_branch(repo, run_git):
    root, kb_dir = repo
    qt, _, runner = make(repo)
    runner.release.set()
    qt.tick()
    settle(qt)
    worktree = kb_dir / "auto" / "worktrees" / "qa"
    (worktree / "stale.txt").write_text("x\n", encoding="utf-8", newline="\n")
    run_git(worktree, "add", "stale.txt")
    run_git(worktree, "commit", "-m", "stale")
    qt.tick()
    settle(qt)
    assert not (worktree / "stale.txt").exists()
    assert run_git(root, "branch", "--show-current") == "main"


def test_tick_kb_error_is_a_logged_false(repo, caplog):
    qt, _, runner = make(repo, qa=FakeQa(fail=True))
    with caplog.at_level(logging.WARNING):
        assert qt.tick() is False
    assert "hub answered 500" in caplog.text
    assert runner.calls == []


def test_tick_worktree_failure_is_a_logged_false(repo, monkeypatch, caplog):
    def boom(*a, **k):
        raise gitio.GitError("no worktree")

    monkeypatch.setattr(gitio, "worktree_add", boom)
    qt, _, runner = make(repo)
    with caplog.at_level(logging.WARNING):
        assert qt.tick() is False
    assert "no worktree" in caplog.text


def test_run_task_exception_is_logged_and_frees_the_slot(repo, caplog):
    def explode(root, prompt, *, log_dir):
        raise RuntimeError("claude missing")

    qt, _, _ = make(repo, runner=explode)
    with caplog.at_level(logging.WARNING):
        assert qt.tick() is True
        settle(qt)
    assert "claude missing" in caplog.text
    assert qt.tick() is True


def test_usage_limit_skips_one_tick(repo, caplog):
    runner = Runner(TaskResult("usage-limit", (), "limit hit"))
    runner.release.set()
    qt, _, _ = make(repo, runner=runner)
    with caplog.at_level(logging.WARNING):
        assert qt.tick() is True
        settle(qt)
    assert "limit hit" in caplog.text
    assert qt.tick() is False
    assert qt.tick() is True
    settle(qt)


def test_start_ticks_then_stop_joins_loop(repo):
    runner = Runner()
    runner.release.set()
    qt, _, _ = make(repo, runner=runner, interval=3600)
    qt.start()
    assert runner.finished.wait(WAIT)
    qt.stop()
    assert qt._loop_thread is not None and not qt._loop_thread.is_alive()


def test_stop_logs_when_answer_still_running(repo, caplog):
    qt, _, runner = make(repo, interval=3600)
    qt.start()
    assert runner.started.wait(WAIT)
    with caplog.at_level(logging.INFO):
        qt.stop()
    assert "still running" in caplog.text
    runner.release.set()
    settle(qt)


def test_stop_without_start_is_safe(repo):
    qt, _, _ = make(repo)
    qt.stop()


def test_open_question_count():
    qa = FakeQa(open_=(1, 2, 3))
    assert open_question_count(qa, "svc") == 3  # type: ignore[arg-type]
    assert qa.calls == [("open", "svc", "")]
