from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from strata_kb import gitio
from strata_kb.autorun.claude import TaskResult
from strata_kb.autorun.qathread import PARKED_PREFIX, QaThread, open_question_count
from strata_kb.errors import KbError

WAIT = 10  # generous bound on event waits; passing runs never reach it


class FakeQa:
    def __init__(self, open_=((1, "T-1"),), fail=False):
        # an item is (id, ticket), or a ready dict (e.g. a question without a ticket)
        self.open_, self.fail, self.calls = list(open_), fail, []

    def list(self, status="open", repo="", ticket=""):
        self.calls.append((status, repo, ticket))
        if self.fail:
            raise KbError("hub answered 500")
        return [
            q if isinstance(q, dict) else {"id": q[0], "ticket": q[1]}
            for q in self.open_
        ]


class Runner:
    """Fake `run_task`: records each call, finishes when `release` is set."""

    def __init__(self, result=None, on_run=None):
        self.result = result or TaskResult("done")
        self.on_run = on_run  # called with the worktree before the result returns
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
        if self.on_run:
            self.on_run(root)
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


def _tick_and_settle(qt: QaThread) -> bool:
    launched = qt.tick()
    if launched:
        settle(qt)
    return launched


def test_two_failed_answers_in_a_row_set_failed_twice(repo):
    runner = Runner(TaskResult("failed", (), "lint broke"))
    runner.release.set()
    qt, _, _ = make(repo, runner=runner)
    assert _tick_and_settle(qt) and not qt.failed_twice
    assert _tick_and_settle(qt) and qt.failed_twice
    assert qt.stop_reason == "lint broke"
    assert qt.tick() is False  # a failed thread launches nothing more
    assert len(runner.calls) == 2


def test_done_answer_resets_the_failure_count(repo):
    runner = Runner(TaskResult("failed", (), "x"))
    runner.release.set()
    qt, _, _ = make(repo, runner=runner)
    _tick_and_settle(qt)
    runner.result = TaskResult("done")
    _tick_and_settle(qt)
    runner.result = TaskResult("failed", (), "y")
    _tick_and_settle(qt)
    assert not qt.failed_twice


def test_crashed_answers_count_as_failures(repo):
    def explode(root, prompt, *, log_dir):
        raise RuntimeError("claude missing")

    qt, _, _ = make(repo, runner=explode)
    _tick_and_settle(qt)
    _tick_and_settle(qt)
    assert qt.failed_twice and "claude missing" in qt.stop_reason


def test_usage_limit_is_not_a_failure(repo):
    runner = Runner(TaskResult("usage-limit", (), "limit hit"))
    runner.release.set()
    qt, _, _ = make(repo, runner=runner)
    for _ in range(4):
        qt.tick()
        if qt._proc_thread is not None:
            settle(qt)
    assert not qt.failed_twice


def test_loop_survives_a_tick_exception(repo, caplog):
    qt, _, _ = make(repo, interval=0)
    seen = threading.Event()
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        seen.set()
        return False

    qt.tick = flaky  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        qt.start()
        assert seen.wait(WAIT)
        qt.stop()
    assert "boom" in caplog.text


def test_worktree_bases_on_fetched_origin_when_remote_exists(repo, run_git, tmp_path):
    root, kb_dir = repo
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(root, "remote", "add", "origin", str(origin))
    run_git(root, "push", "-u", "origin", "main")
    clone = tmp_path / "clone"
    run_git(tmp_path, "clone", str(origin), str(clone))
    run_git(clone, "checkout", "-B", "main", "origin/main")
    (clone / "new.txt").write_text("n\n", encoding="utf-8", newline="\n")
    run_git(clone, "add", "new.txt")
    run_git(clone, "commit", "-m", "ahead")
    run_git(clone, "push", "origin", "main")  # origin/main now ahead of root's main
    runner = Runner()
    runner.release.set()
    qt, _, _ = make(repo, runner=runner)

    assert _tick_and_settle(qt)

    assert (kb_dir / "auto" / "worktrees" / "qa" / "new.txt").exists()


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
    qa = FakeQa(open_=((1, "T-a"), (2, "T-b"), (3, "T-b")))
    assert open_question_count(qa, "svc") == 3  # type: ignore[arg-type]
    assert qa.calls == [("open", "svc", "")]


UNTICKED = TaskResult("failed", (), "dor-unticked something-else")


def _parking(repo, open_=((2, "T-a"),), **runner_kw):
    runner = Runner(UNTICKED, **runner_kw)
    runner.release.set()
    qt, qa, _ = make(repo, qa=FakeQa(open_=open_), runner=runner)
    return qt, qa, runner


def _prompt_head(runner: Runner, n: int = -1) -> str:
    return runner.calls[n][1].splitlines()[0]


def test_tick_runs_the_oldest_unparked_ticket(repo):
    qt, _, runner = make(repo, qa=FakeQa(open_=[(3, "T-b"), (2, "T-a")]))
    runner.release.set()
    assert _tick_and_settle(qt)
    assert _prompt_head(runner) == "/ba-answer-questions T-a"


def test_dor_unticked_parks_the_launched_ticket_without_counting(repo):
    qt, _, _ = _parking(repo)
    assert _tick_and_settle(qt)
    assert qt.parked == {"T-a"} and qt.failed_twice is False
    qt._qa.open_ = [(2, "T-a"), (3, "T-b")]
    assert _tick_and_settle(qt)
    assert qt.failed_twice is False


def test_parked_ticket_is_skipped_next_tick(repo):
    qt, qa, runner = _parking(repo)
    _tick_and_settle(qt)
    qa.open_ = [(2, "T-a"), (3, "T-b")]
    assert _tick_and_settle(qt)
    assert _prompt_head(runner) == "/ba-answer-questions T-b"
    qa.open_ = [(2, "T-a")]
    assert qt.tick() is False


def test_park_saves_draft_branch(repo, run_git):
    root, _ = repo
    qt, _, _ = _parking(
        repo,
        on_run=lambda wt: (wt / "draft.txt").write_text(
            "d\n", encoding="utf-8", newline="\n"
        ),
    )
    _tick_and_settle(qt)
    branch = PARKED_PREFIX + "T-a"
    run_git(root, "rev-parse", "--verify", branch)
    assert "draft.txt" in run_git(root, "ls-tree", "-r", "--name-only", branch).split()


def test_park_with_clean_worktree_creates_no_commit(repo, run_git):
    root, _ = repo
    qt, _, _ = _parking(repo)
    _tick_and_settle(qt)
    base = run_git(qt.worktree, "rev-parse", "auto/qa")
    assert run_git(root, "rev-parse", PARKED_PREFIX + "T-a") == base
    assert qt.parked == {"T-a"}


def test_park_git_error_is_a_warning(repo, monkeypatch, caplog):
    def boom(*a, **k):
        raise gitio.GitError("boom")

    monkeypatch.setattr(gitio, "commit_all", boom)
    qt, _, _ = _parking(repo)
    with caplog.at_level(logging.WARNING):
        _tick_and_settle(qt)
    assert qt.parked == {"T-a"}
    assert any(
        r.levelno == logging.WARNING and "T-a" in r.getMessage() for r in caplog.records
    )


def test_invalid_ticket_ref_parks_with_warning(repo, caplog):
    qt, _, _ = _parking(repo, open_=((2, "bad..name"),))
    with caplog.at_level(logging.WARNING):
        _tick_and_settle(qt)
    assert qt.parked == {"bad..name"}
    assert any(
        r.levelno == logging.WARNING and "bad..name" in r.getMessage()
        for r in caplog.records
    )


def test_park_pushes_draft_when_remote_exists(repo, run_git, tmp_path):
    root, _ = repo
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(root, "remote", "add", "origin", str(origin))
    run_git(root, "push", "-u", "origin", "main")
    qt, _, _ = _parking(
        repo,
        on_run=lambda wt: (wt / "draft.txt").write_text(
            "d\n", encoding="utf-8", newline="\n"
        ),
    )
    _tick_and_settle(qt)
    run_git(origin, "rev-parse", "--verify", PARKED_PREFIX + "T-a")


def test_question_without_ticket_runs_bare_and_never_parks(repo):
    qt, _, runner = _parking(repo, open_=[{"id": 1}])
    assert _tick_and_settle(qt)
    assert _prompt_head(runner) == "/ba-answer-questions"
    assert qt.parked == frozenset() and not qt.failed_twice
    assert _tick_and_settle(qt)
    assert qt.failed_twice


def test_other_failures_still_count(repo):
    runner = Runner(TaskResult("failed", (), "ci-red http://x"))
    runner.release.set()
    qt, _, _ = make(repo, runner=runner)
    _tick_and_settle(qt)
    _tick_and_settle(qt)
    assert qt.failed_twice and qt.parked == frozenset()


def test_only_parked_left(repo):
    qt, qa, _ = _parking(repo)
    assert qt.only_parked_left() is False  # nothing parked yet
    _tick_and_settle(qt)
    qa.open_ = [(2, "T-a")]
    assert qt.only_parked_left() is True
    qa.open_ = [(2, "T-a"), (3, "T-b")]
    assert qt.only_parked_left() is False
    qa.open_ = []
    assert qt.only_parked_left() is False
    qa.open_, qa.fail = [(2, "T-a")], True
    assert qt.only_parked_left() is False


def test_only_parked_left_is_false_while_an_answer_runs(repo):
    qt, qa, runner = _parking(repo)
    qa.open_ = [(2, "T-a"), (3, "T-b")]
    _tick_and_settle(qt)  # T-a parks
    runner.release.clear()
    runner.started.clear()
    assert qt.tick() is True  # T-b answer in flight
    assert runner.started.wait(WAIT)
    qa.open_ = [(2, "T-a")]  # T-b's questions turned `waiting` during CI
    assert qt.only_parked_left() is False
    runner.release.set()
    settle(qt)
