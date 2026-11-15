"""`run_once` / `run_loop` for a tester repo: pick, settle, waiting, stops."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_kb.autorun import picker
from strata_kb.autorun import runner as runner_mod
from strata_kb.autorun import state as autostate
from strata_kb.autorun.claude import TaskResult
from strata_kb.autorun.picker import Task
from strata_kb.autorun.runner import run_loop, run_once
from strata_kb.config import AutoConfig, KBConfig
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from tests.test_autorun_runner import FakeQa, Script

NOW = 1_900_000_000.0
IDLE = 600
T1 = Task("tester-test-story", "M-x-US1")
T2 = Task("tester-test-story", "M-x-US2")


def cfg() -> KBConfig:
    return KBConfig(
        kind="tester",
        repo_id="svc",
        intake="http://i",
        auto=AutoConfig(enabled=True, idle_interval=IDLE),
    )


class Picks:
    """A `pick_tester` double: scripted picks; records `skip` and `waiting`."""

    def __init__(self, *picks: picker.TesterPick):
        self.picks, self.calls = list(picks), []

    def __call__(
        self, root, kb_dir, hub, *, claims_client, skip=(), waiting=frozenset()
    ):
        self.calls.append((tuple(skip), waiting))
        return self.picks.pop(0)


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    monkeypatch.setattr(autostate.time, "time", lambda: NOW)
    return tmp_path, kb_dir, HubHandle(root=tmp_path)


def step(env, script, picks, **kw):
    root, kb_dir, hub = env
    _patch[0].setattr(picker, "pick_tester", picks)
    return run_once(
        root,
        kb_dir,
        cfg=cfg(),
        hub=hub,
        qa=FakeQa(),
        run_task=script,
        now=lambda: NOW,
        sleep=lambda s: None,
        tester_claims=object(),  # type: ignore[arg-type]
        **kw,
    )


_patch: list = []


@pytest.fixture(autouse=True)
def _patcher(monkeypatch):
    _patch.clear()
    _patch.append(monkeypatch)


def task_pick(task=T1, cooled=()):
    return picker.TesterPick(task, "task", cooled)


def test_runs_tester_task_with_kind_and_next_pick_follows(env):
    script, picks = (
        Script(TaskResult("done"), TaskResult("done")),
        Picks(task_pick(T1), task_pick(T2)),
    )
    assert step(env, script, picks) == "ran"
    assert step(env, script, picks) == "ran"
    assert script.kinds == ["tester", "tester"]
    assert len(picks.calls) == 2


def test_blocked_env_parks_story_without_attempt(env):
    script = Script(TaskResult("blocked-env", ("M-x-US1", "not-deployed")))
    assert step(env, script, Picks(task_pick())) == "ran"
    st = autostate.load(env[1])
    assert st.task is None and st.attempts == 0
    assert st.waiting == (f"M-x-US1 {int(NOW) + IDLE}",)
    picks = Picks(picker.TesterPick(None, "waiting"))
    assert step(env, Script(), picks) == "idle"
    assert picks.calls[0][1] == frozenset({"M-x-US1"})


def test_env_locked_idles_until_time_passes(env):
    script = Script(TaskResult("blocked-env", ("M-x-US1", "env-locked")))
    assert step(env, script, Picks(task_pick())) == "idle"
    assert autostate.load(env[1]).env_wait_until == NOW + IDLE
    picks = Picks()  # no pick while the environment waits
    assert step(env, Script(), picks) == "idle" and picks.calls == []
    state = autostate.load(env[1])
    autostate.save(
        env[1], state.__class__(**{**state.__dict__, "env_wait_until": NOW - 1})
    )
    assert step(env, Script(TaskResult("done")), Picks(task_pick())) == "ran"


def test_incomplete_twice_skips_story_without_stopping(env):
    inc = TaskResult("incomplete", ("M-x-US1",))
    assert step(env, Script(inc), Picks(task_pick())) == "ran"
    st = autostate.load(env[1])
    assert (st.task, st.attempts, st.skipped) == (None, 1, ())
    assert st.waiting == (f"M-x-US1 {int(NOW) + IDLE}",)
    assert step(env, Script(inc), Picks(task_pick())) == "ran"
    st = autostate.load(env[1])
    assert st.skipped == (T1.key,) and st.attempts == 0 and st.stop_reason is None
    # nothing else left: every candidate skipped -> the existing stop
    assert step(env, Script(), Picks(picker.TesterPick(None, "skipped"))) == "stopped"
    assert "every task left was skipped" in (autostate.load(env[1]).stop_reason or "")


def test_failed_test_review_stops_at_once(env):
    script = Script(TaskResult("failed", (), "test-review BLOCKER stands"))
    assert step(env, script, Picks(task_pick())) == "stopped"
    assert autostate.load(env[1]).stop_reason == "test-review BLOCKER stands"


def test_nothing_is_done_and_waiting_is_idle(env):
    assert step(env, Script(), Picks(picker.TesterPick(None, "nothing"))) == "done"
    assert step(env, Script(), Picks(picker.TesterPick(None, "waiting"))) == "idle"


def test_cooled_stories_are_parked_and_survive_the_task_start(env):
    script = Script(TaskResult("done"))
    assert step(env, script, Picks(task_pick(T2, cooled=("M-x-US1",)))) == "ran"
    assert autostate.load(env[1]).waiting == (f"M-x-US1 {int(NOW) + IDLE}",)


def test_run_loop_exits_done_on_nothing(env, monkeypatch):
    root, kb_dir, hub = env
    (kb_dir / "config.yaml").write_text(
        "kind: tester\nrepo_id: svc\nintake: http://i\nauto:\n  enabled: true\n",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr(
        picker, "pick_tester", Picks(picker.TesterPick(None, "nothing"))
    )
    monkeypatch.setattr(
        runner_mod,
        "QaThread",
        lambda *a: pytest.fail("no Q&A thread for a tester"),
    )
    code = run_loop(
        root, kb_dir, hub=hub, qa=FakeQa(), run_task=Script(), tester_claims=object()
    )
    assert code == 0


def test_cloud_hub_refused_for_tester(env, monkeypatch):
    monkeypatch.setattr(runner_mod.cloud, "is_cloud", lambda: True)
    with pytest.raises(KbError, match="local hub"):
        runner_mod._resolve_hub(cfg(), env[1])


def test_dev_failed_still_counts_attempts(env):
    """BA/Dev `_settle` is untouched: a failed result counts, test-review text or not."""
    kb_dir = env[1]
    state = autostate.load(kb_dir)
    state = state.__class__(**{**state.__dict__, "task": "dev-fix-bug:B1"})
    out = runner_mod._settle(
        kb_dir,
        state,
        TaskResult("failed", (), "test-review x"),
        runner_mod.Backoff(),
        lambda s: None,
    )
    assert out == "ran" and autostate.load(kb_dir).attempts == 1
