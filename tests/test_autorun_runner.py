from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from strata_kb import gitio, planstatus
from strata_kb.autorun import lock as lock_mod
from strata_kb.autorun import picker
from strata_kb.autorun import runner as runner_mod
from strata_kb.autorun import state as autostate
from strata_kb.autorun.claims import UnknownTicketError
from strata_kb.autorun.claude import TaskResult
from strata_kb.autorun.picker import Task
from strata_kb.autorun.runner import Backoff, preflight, run_loop, run_once
from strata_kb.claimclient import (
    ClaimRejectedError,
    ClaimRouteMissing,
    ParentStoryError,
)
from strata_kb.config import AutoConfig, KBConfig
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from strata_kb.missionnext import StoryStatus
from strata_kb.models import Registry, RegistryEntry

TASK = Task("dev-implement-ticket", "M-x-US3")


def S(us_id: str, status: str) -> StoryStatus:
    return StoryStatus(us_id, "M-x", "t", status, (), (), "svc")


def cfg_of(kind: str = "dev", **auto) -> KBConfig:
    return KBConfig(
        kind=kind,  # type: ignore[arg-type]
        repo_id="svc",
        intake="http://intake",
        auto=AutoConfig(enabled=True, **auto),
    )


class FakeQa:
    def __init__(self, states=None, open_=(), fail=False):
        self._states, self._open, self._fail = states or {}, list(open_), fail

    def states(self, ids):
        if self._fail:
            raise KbError("hub answered 400")
        return {i: s for i, s in self._states.items() if i in ids}

    def list(self, status="open", repo="", ticket=""):
        if self._fail:
            raise KbError("hub answered 400")
        return [{"id": i, "state": "open"} for i in self._open]


class Script:
    """A `run_task` double: returns the scripted results in order."""

    def __init__(self, *results: TaskResult):
        self.results, self.prompts = list(results), []

    def __call__(self, root, prompt, *, log_dir):
        self.prompts.append(prompt)
        return self.results.pop(0)


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    hub = HubHandle(root=tmp_path)
    tickets = {"stories": [S("M-x-US3", "ready")]}
    monkeypatch.setattr(
        planstatus,
        "next_from_hub",
        lambda h, repo=None, for_repo=None: (tickets["stories"], [], []),
    )
    monkeypatch.setattr(picker, "pick_dev", lambda h, root, repo_id, skip=(): TASK)
    monkeypatch.setattr(picker, "pick_ba", lambda root, kb, skip=(): TASK)
    return tmp_path, kb_dir, hub, tickets


def once(env, script, cfg=None, qa=None, **kw):
    root, kb_dir, hub, _ = env
    return run_once(
        root,
        kb_dir,
        cfg=cfg or cfg_of(),
        hub=hub,
        qa=qa or FakeQa(),
        run_task=script,
        sleep=kw.pop("sleep", lambda s: None),
        **kw,
    )


def test_switch_off_stops_at_task_boundary(env):
    script = Script(TaskResult("done"))
    assert once(env, script) == "ran"
    off = KBConfig(kind="dev", auto=AutoConfig(enabled=False))
    assert once(env, script, cfg=off) == "stopped"
    assert autostate.load(env[1]).stop_reason == "switched off"
    assert len(script.prompts) == 1  # the second run never started


def test_run_once_records_run(env):
    script = Script(TaskResult("done", meta={"session_id": "s"}))
    once(env, script)
    lines = (env[1] / "auto" / "runs.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert (row["skill"], row["arg"]) == (TASK.skill, TASK.arg)
    assert (row["attempt"], row["outcome"], row["session_id"]) == (0, "done", "s")


def test_waiting_question_does_not_resume(env):
    script = Script(TaskResult("blocked-qa", (12,)))
    assert once(env, script) == "waiting"
    assert autostate.load(env[1]).waiting_on == (12,)
    assert once(env, script, qa=FakeQa({12: "waiting"})) == "waiting"
    assert len(script.prompts) == 1


def test_answered_question_reruns_same_task(env):
    script = Script(TaskResult("blocked-qa", (12, 13)), TaskResult("done"))
    once(env, script)
    assert once(env, script, qa=FakeQa({12: "answered", 13: "open"})) == "waiting"
    assert once(env, script, qa=FakeQa({12: "answered", 13: "answered"})) == "ran"
    assert script.prompts[0] == script.prompts[1]
    assert script.prompts[1].startswith("/dev-implement-ticket M-x-US3")
    state = autostate.load(env[1])
    assert (state.waiting_on, state.task) == ((), None)


def test_second_failure_stops(env):
    script = Script(TaskResult("failed", (), "lint"), TaskResult("failed", (), "lint"))
    assert once(env, script) == "ran"
    assert autostate.load(env[1]).attempts == 1
    assert once(env, script) == "stopped"
    state = autostate.load(env[1])
    assert (state.attempts, state.stop_reason) == (2, "lint")
    assert state.task == TASK.key


def test_ci_red_stops_immediately(env, caplog):
    script = Script(TaskResult("failed", (), "ci-red PR #7: unit, lint"))
    with caplog.at_level(logging.ERROR):
        assert once(env, script) == "stopped"
    assert autostate.load(env[1]).attempts == 2
    assert "ci-red PR #7" in caplog.text
    assert TASK.key in caplog.text
    assert "kb auto run" in caplog.text


def test_runner_exception_counts_as_failed_attempt(env):
    def broken(root, prompt, *, log_dir):
        raise OSError("disk full")

    assert once(env, broken) == "ran"
    assert autostate.load(env[1]).attempts == 1
    assert once(env, broken) == "stopped"
    state = autostate.load(env[1])
    assert (state.attempts, state.stop_reason) == (2, "runner error: disk full")


def test_switch_off_hint_says_kb_auto_on(env, caplog):
    off = KBConfig(kind="dev", auto=AutoConfig(enabled=False))
    with caplog.at_level(logging.ERROR):
        once(env, Script(), cfg=off)
    assert "kb auto on" in caplog.text


def test_waiting_logs_pending_question_ids(env, caplog):
    autostate.save(env[1], autostate.AutoState(TASK.key, 0, (12,), None, ""))
    with caplog.at_level(logging.INFO):
        once(env, Script(), qa=FakeQa({12: "waiting"}))
    assert "[12]" in caplog.text


def test_usage_limit_backoff_sequence(env):
    limit = TaskResult("usage-limit", (), "usage limit reached")
    script = Script(limit, limit, limit, limit, TaskResult("done"))
    sleeps: list[float] = []
    backoff = Backoff()
    for _ in range(5):
        once(env, script, sleep=sleeps.append, backoff=backoff)
    assert sleeps == [900, 1800, 3600, 3600]
    assert autostate.load(env[1]).attempts == 0
    assert backoff.next() == 900  # reset by the done result


def test_all_done_exits_zero(env, caplog):
    env[3]["stories"] = [S("US3", "done")]
    script = Script()
    with caplog.at_level(logging.INFO):
        assert once(env, script) == "done"
    assert script.prompts == []
    assert "all 1 tickets done" in caplog.text


def test_ba_open_question_blocks_done(env):
    env[3]["stories"] = [S("US3", "done")]
    script = Script(TaskResult("done"))
    assert once(env, script, cfg=cfg_of("ba"), qa=FakeQa(open_=[5])) == "ran"
    assert once(env, Script(), cfg=cfg_of("ba")) == "done"


def test_idle_when_nothing_to_pick(env, monkeypatch):
    monkeypatch.setattr(picker, "pick_dev", lambda h, root, repo_id, skip=(): None)
    assert once(env, Script()) == "idle"
    monkeypatch.setattr(
        picker,
        "pick_dev",
        lambda h, root, repo_id, skip=(): (_ for _ in ()).throw(KbError("boom")),
    )
    assert once(env, Script()) == "idle"


def test_qa_error_is_waiting_not_failure(env):
    assert once(env, Script(), qa=FakeQa(fail=True), cfg=cfg_of("ba")) == "waiting"
    autostate.save(env[1], autostate.AutoState(TASK.key, 0, (12,), None, ""))
    assert once(env, Script(), qa=FakeQa(fail=True)) == "waiting"
    state = autostate.load(env[1])
    assert (state.attempts, state.stop_reason) == (0, None)


def test_done_task_picked_again_idles_without_running(env, caplog):
    script = Script(TaskResult("done"), TaskResult("done"))
    assert once(env, script) == "ran"
    assert autostate.load(env[1]).last_done == TASK.key

    with caplog.at_level(logging.INFO):
        assert once(env, script) == "idle"

    assert len(script.prompts) == 1  # the second pick never ran
    assert f"{TASK.key} ended done but is still picked; waiting for the hub" in (
        caplog.text
    )
    assert autostate.load(env[1]).same_pick == 1


def test_fifth_repick_of_done_task_skips_it_and_moves_on(env, monkeypatch, caplog):
    other = Task("dev-implement-ticket", "M-x-US4")
    seen: list = []

    def pick(h, root, repo_id, skip=()):
        seen.append(tuple(skip))
        return other if TASK.key in skip else TASK

    monkeypatch.setattr(picker, "pick_dev", pick)
    script = Script(TaskResult("done"), TaskResult("done"))
    once(env, script)
    for _ in range(4):
        assert once(env, script) == "idle"
    with caplog.at_level(logging.WARNING):
        assert once(env, script) == "ran"
    assert f"{TASK.key} ended done but is still picked after 5 checks" in caplog.text
    state = autostate.load(env[1])
    assert (state.skipped, state.last_done, state.same_pick) == ((TASK.key,), None, 0)
    assert state.stop_reason is None

    assert once(env, script) == "ran"  # the next task runs
    assert script.prompts[1].startswith("/dev-implement-ticket M-x-US4")
    assert seen[-1] == (TASK.key,)


def test_every_task_left_skipped_stops(env, monkeypatch):
    autostate.save(
        env[1], autostate.AutoState(None, 0, (), None, "", skipped=(TASK.key,))
    )
    monkeypatch.setattr(picker, "pick_dev", lambda h, root, repo_id, skip=(): None)
    assert once(env, Script()) == "stopped"
    assert (
        autostate.load(env[1]).stop_reason == f"every task left was skipped: {TASK.key}"
    )


def test_pick_error_with_skipped_tasks_idles(env, monkeypatch):
    autostate.save(
        env[1], autostate.AutoState(None, 0, (), None, "", skipped=(TASK.key,))
    )
    monkeypatch.setattr(
        picker,
        "pick_dev",
        lambda h, root, repo_id, skip=(): (_ for _ in ()).throw(KbError("boom")),
    )
    assert once(env, Script()) == "idle"
    assert autostate.load(env[1]).stop_reason is None


def test_different_pick_resets_the_repick_guard(env, monkeypatch):
    script = Script(TaskResult("done"), TaskResult("done"))
    once(env, script)
    assert once(env, script) == "idle"
    other = Task("dev-implement-ticket", "M-x-US4")
    monkeypatch.setattr(picker, "pick_dev", lambda h, root, repo_id, skip=(): other)

    assert once(env, script) == "ran"

    state = autostate.load(env[1])
    assert (state.last_done, state.same_pick) == (other.key, 0)
    assert script.prompts[1].startswith("/dev-implement-ticket M-x-US4")


def test_resume_resets_repick_count_but_keeps_last_done(env):
    autostate.save(
        env[1], autostate.AutoState(None, 0, (), "stuck", "", TASK.key, 4, ("a:b",))
    )
    runner_mod.resume(env[1])
    state = autostate.load(env[1])
    assert (state.stop_reason, state.same_pick, state.last_done) == (None, 0, TASK.key)
    assert state.skipped == ()  # the owner fixed them: they get another chance


def test_crash_resumes_stored_task(env, monkeypatch):
    env[3]["stories"] = [S("BUG-2", "ready")]
    autostate.save(env[1], autostate.AutoState("dev-fix-bug:BUG-2", 1, (), None, ""))
    script = Script(TaskResult("done"))
    assert once(env, script) == "ran"
    assert script.prompts[0].startswith("/dev-fix-bug BUG-2")


def _loop(env, script, sleep=lambda s: None):
    root, kb_dir, hub, _ = env
    (kb_dir / "config.yaml").write_text(
        "kind: dev\nrepo_id: svc\nintake: http://intake\n"
        "auto:\n  enabled: true\n  idle_interval: 11\n  qa_interval: 7\n",
        encoding="utf-8",
        newline="\n",
    )
    return run_loop(
        root, kb_dir, sleep=sleep, hub=hub, qa=FakeQa(), run_task=script, claims=None
    )


def test_run_loop_rereads_config_so_switch_off_stops(env):
    root, kb_dir, _, _ = env
    script = Script(TaskResult("done"), TaskResult("done"))

    def run_then_switch_off(root_, prompt, *, log_dir):
        (kb_dir / "config.yaml").write_text(
            "kind: dev\nrepo_id: svc\nauto:\n  enabled: false\n",
            encoding="utf-8",
            newline="\n",
        )
        return script(root_, prompt, log_dir=log_dir)

    assert _loop(env, run_then_switch_off) == 2
    assert autostate.load(kb_dir).stop_reason == "switched off"
    assert len(script.prompts) == 1


def test_run_loop_exits_2_when_stopped(env):
    script = Script(TaskResult("failed", (), "x"), TaskResult("failed", (), "x"))
    assert _loop(env, script) == 2


def test_run_loop_exits_0_when_done_and_clears_old_stop(env):
    autostate.save(env[1], autostate.AutoState(TASK.key, 2, (), "lint", ""))
    env[3]["stories"] = [S("US3", "done")]
    assert _loop(env, Script()) == 0
    state = autostate.load(env[1])
    assert (state.stop_reason, state.attempts) == (None, 0)


def test_run_loop_resumes_after_stop_with_fresh_attempts(env):
    autostate.save(env[1], autostate.AutoState(TASK.key, 2, (), "lint", ""))
    script = Script(TaskResult("done"))

    def run_and_finish(root, prompt, *, log_dir):
        env[3]["stories"] = [S("US3", "done")]
        return script(root, prompt, log_dir=log_dir)

    assert _loop(env, run_and_finish) == 0
    assert len(script.prompts) == 1


def test_run_loop_sleeps_per_outcome_and_survives_errors(env, monkeypatch):
    sleeps: list[float] = []
    picks = iter([None, KbError("x"), RuntimeError("boom"), TASK])

    def pick(hub, root, repo_id, skip=()):
        item = next(picks)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(picker, "pick_dev", pick)
    script = Script(TaskResult("blocked-qa", (4,)))

    def record(seconds):
        sleeps.append(seconds)
        if seconds == 7:
            env[3]["stories"] = [S("US3", "done")]

    assert _loop(env, script, sleep=record) == 0
    assert sleeps == [11, 11, 11, 7]  # idle, KbError->idle, crash->idle, waiting


def _registry(**entries):
    return Registry(repos=entries)


def _write_config(kb_dir: Path, text: str) -> None:
    (kb_dir / "config.yaml").write_text(text, encoding="utf-8", newline="\n")


GOOD = "kind: dev\nrepo_id: svc\nintake: http://i\nauto:\n  enabled: true\n"


@pytest.fixture
def no_switch_check(monkeypatch):
    """These preflight tests run in a plain directory, not a git repo."""
    monkeypatch.setattr(runner_mod, "_switch_refusals", lambda root: [])


@pytest.mark.usefixtures("no_switch_check")
def test_preflight_refuses_without_auto_merge(env, monkeypatch):
    root, kb_dir, _, _ = env
    monkeypatch.setattr(
        runner_mod,
        "registry_or_reason",
        lambda kb, hub: (_registry(**{"o/r": RegistryEntry(repo_id="svc")}), ""),
    )
    _write_config(kb_dir, GOOD)
    (reason,) = preflight(root, kb_dir)
    assert "auto_merge" in reason and "svc" in reason
    monkeypatch.setattr(
        runner_mod,
        "registry_or_reason",
        lambda kb, hub: (
            _registry(**{"o/r": RegistryEntry(repo_id="svc", auto_merge=True)}),
            "",
        ),
    )
    assert preflight(root, kb_dir) == []


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("kind: dev\nrepo_id: svc\nintake: http://i\n", "switched off"),
        ("kind: hub\nrepo_id: svc\nintake: http://i\nauto:\n  enabled: true\n", "kind"),
        ("kind: dev\nrepo_id: svc\nauto:\n  enabled: true\n", "intake"),
    ],
)
@pytest.mark.usefixtures("no_switch_check")
def test_preflight_names_each_refusal(env, monkeypatch, text, needle):
    root, kb_dir, _, _ = env
    monkeypatch.setattr(
        runner_mod,
        "registry_or_reason",
        lambda kb, hub: (
            _registry(**{"o/r": RegistryEntry(repo_id="svc", auto_merge=True)}),
            "",
        ),
    )
    _write_config(kb_dir, text)
    reasons = preflight(root, kb_dir)
    assert len(reasons) == 1 and needle in reasons[0]


@pytest.mark.usefixtures("no_switch_check")
def test_preflight_reports_unreachable_hub(env, monkeypatch):
    root, kb_dir, _, _ = env
    monkeypatch.setattr(
        runner_mod,
        "registry_or_reason",
        lambda kb, hub: (None, "hub unreachable and not cached"),
    )
    _write_config(kb_dir, GOOD)
    (reason,) = preflight(root, kb_dir)
    assert "hub unreachable and not cached" in reason


class SpyQaThread:
    events: list[str] = []

    failed_twice = False
    stop_reason = ""

    def __init__(self, root, kb_dir, qa, interval, repo, run_task):
        self.args = (interval, repo)
        SpyQaThread.events = [f"init {interval} {repo}"]

    def start(self):
        SpyQaThread.events.append("start")

    def stop(self):
        SpyQaThread.events.append("stop")


def _loop_kind(env, kind, monkeypatch):
    root, kb_dir, hub, tickets = env
    tickets["stories"] = [S("US3", "done")]
    SpyQaThread.events = []
    monkeypatch.setattr(runner_mod, "QaThread", SpyQaThread)
    _write_config(
        kb_dir,
        f"kind: {kind}\nrepo_id: svc\nintake: http://i\n"
        "auto:\n  enabled: true\n  qa_interval: 7\n",
    )
    return run_loop(root, kb_dir, hub=hub, qa=FakeQa(), run_task=Script(), claims=None)


def test_run_loop_runs_qa_thread_for_ba_and_stops_it(env, monkeypatch):
    assert _loop_kind(env, "ba", monkeypatch) == 0
    assert SpyQaThread.events == ["init 7 svc", "start", "stop"]


def test_run_loop_has_no_qa_thread_for_dev(env, monkeypatch):
    assert _loop_kind(env, "dev", monkeypatch) == 0
    assert SpyQaThread.events == []


def test_build_deps_reads_config_hub_and_qa(env, monkeypatch):
    _, kb_dir, hub, _ = env
    _write_config(kb_dir, GOOD)
    qa = FakeQa()
    seen = {}
    monkeypatch.setattr(runner_mod.qa_mod, "from_env", lambda: qa)
    monkeypatch.setattr(
        runner_mod, "resolve_hub", lambda url: seen.setdefault("url", url) and hub
    )

    cfg, got_hub, got_qa = runner_mod.build_deps(kb_dir, "/flag/hub")

    assert cfg.repo_id == "svc" and cfg.auto.enabled
    assert got_hub is hub and got_qa is qa
    assert seen["url"] == "/flag/hub"  # the flag beats config


def test_build_deps_missing_env_raises_kberror_naming_var(env, monkeypatch):
    _, kb_dir, _, _ = env
    _write_config(kb_dir, GOOD)
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub")
    monkeypatch.delenv("STRATA_KB_HTTP_TOKEN", raising=False)

    with pytest.raises(KbError, match="STRATA_KB_HTTP_TOKEN"):
        runner_mod.build_deps(kb_dir)


def test_run_loop_hub_flag_overrides_config_hub(env, monkeypatch):
    root, kb_dir, hub, tickets = env
    tickets["stories"] = [S("US3", "done")]
    _write_config(kb_dir, GOOD + "hub: /cfg/hub\n")
    seen = []
    monkeypatch.setattr(runner_mod, "resolve_hub", lambda url: seen.append(url) or hub)

    code = run_loop(
        root,
        kb_dir,
        hub_flag="/flag/hub",
        qa=FakeQa(),
        run_task=Script(),
        claims=None,
    )

    assert code == 0 and seen == ["/flag/hub"]


@pytest.mark.usefixtures("no_switch_check")
def test_preflight_passes_hub_flag_to_registry(env, monkeypatch):
    root, kb_dir, _, _ = env
    _write_config(kb_dir, GOOD)
    seen = []
    monkeypatch.setattr(
        runner_mod,
        "registry_or_reason",
        lambda kb, hub: seen.append(hub) or (None, "nope"),
    )

    preflight(root, kb_dir, "/flag/hub")

    assert seen == ["/flag/hub"]


class FailedQaThread:
    failed_twice = True
    stop_reason = "lint broke"


def test_failed_qa_thread_stops_the_ba_run_without_running_a_task(env):
    script = Script(TaskResult("done"))
    outcome = once(env, script, cfg=cfg_of("ba"), qa_thread=FailedQaThread())
    assert outcome == "stopped"
    assert autostate.load(env[1]).stop_reason == "qa thread: lint broke"
    assert script.prompts == []


def test_run_loop_hands_the_qa_thread_to_run_once(env, monkeypatch):
    root, kb_dir, hub, _ = env
    monkeypatch.setattr(runner_mod, "QaThread", lambda *a: FailedQaThread_())
    (kb_dir / "config.yaml").write_text(
        GOOD.replace("kind: dev", "kind: ba"), encoding="utf-8", newline="\n"
    )
    code = run_loop(root, kb_dir, hub=hub, qa=FakeQa(), run_task=Script())
    assert code == 2
    assert autostate.load(kb_dir).stop_reason == "qa thread: lint broke"


class FailedQaThread_(FailedQaThread):
    def start(self):
        pass

    def stop(self):
        pass


@pytest.fixture
def git_repo(env, monkeypatch, run_git):
    """A real repo with the switch and the permissions committed on `main`."""
    root, kb_dir, _, _ = env
    monkeypatch.setattr(
        runner_mod,
        "registry_or_reason",
        lambda kb, hub: (
            _registry(**{"o/r": RegistryEntry(repo_id="svc", auto_merge=True)}),
            "",
        ),
    )
    _write_config(kb_dir, GOOD)
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text(
        "{}\n", encoding="utf-8", newline="\n"
    )
    run_git(root, "init", "-b", "main")
    run_git(root, "add", ".kb/config.yaml", ".claude/settings.json")
    run_git(root, "commit", "-m", "switch on")
    return root, kb_dir, run_git


def test_preflight_passes_when_switch_and_settings_are_committed(git_repo):
    root, kb_dir, _ = git_repo
    assert preflight(root, kb_dir) == []


def test_preflight_refuses_untracked_settings(git_repo):
    root, kb_dir, run_git = git_repo
    run_git(root, "rm", "--cached", "-q", ".claude/settings.json")
    (reason,) = preflight(root, kb_dir)
    assert ".claude/settings.json" in reason and "not tracked" in reason


def test_preflight_refuses_untracked_config(git_repo):
    root, kb_dir, run_git = git_repo
    run_git(root, "rm", "--cached", "-q", ".kb/config.yaml")
    reasons = preflight(root, kb_dir)
    assert any(".kb/config.yaml" in r and "not tracked" in r for r in reasons)


@pytest.mark.parametrize("rel", [".kb/config.yaml", ".claude/settings.json"])
def test_preflight_refuses_modified_file(git_repo, rel):
    root, kb_dir, _ = git_repo
    with (root / rel).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("# edited\n" if rel.endswith("yaml") else " \n")
    (reason,) = preflight(root, kb_dir)
    assert rel in reason and "uncommitted" in reason


def _default_branch_is_main_and_head_is_work(root, run_git, tmp_path):
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(root, "remote", "add", "origin", str(origin))
    run_git(root, "push", "-u", "origin", "main")
    run_git(root, "remote", "set-head", "origin", "main")
    run_git(root, "switch", "-c", "work")


def test_preflight_refuses_when_default_branch_has_switch_off(git_repo, tmp_path):
    root, kb_dir, run_git = git_repo
    _write_config(kb_dir, GOOD.replace("true", "false"))
    run_git(root, "commit", "-a", "-m", "off")
    _default_branch_is_main_and_head_is_work(root, run_git, tmp_path)
    _write_config(kb_dir, GOOD)
    run_git(root, "commit", "-a", "-m", "on, on a branch only")
    (reason,) = preflight(root, kb_dir)
    assert "on origin/main" in reason and "auto.enabled: true" in reason


def test_preflight_refuses_when_default_branch_lacks_the_config(git_repo, tmp_path):
    root, kb_dir, run_git = git_repo
    run_git(root, "rm", "-q", "--cached", ".kb/config.yaml")
    run_git(root, "commit", "-m", "no config on main")
    _default_branch_is_main_and_head_is_work(root, run_git, tmp_path)
    run_git(root, "add", ".kb/config.yaml")
    run_git(root, "commit", "-m", "config on a branch only")
    (reason,) = preflight(root, kb_dir)
    assert "on origin/main" in reason and "auto.enabled: true" in reason


def _origin(root, run_git, tmp_path):
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(root, "remote", "add", "origin", str(origin))
    return origin


def test_preflight_passes_when_the_switch_is_pushed(git_repo, tmp_path):
    root, kb_dir, run_git = git_repo
    _origin(root, run_git, tmp_path)
    run_git(root, "push", "-u", "origin", "main")
    assert preflight(root, kb_dir) == []


def test_preflight_refuses_a_switch_committed_but_not_pushed(git_repo, tmp_path):
    root, kb_dir, run_git = git_repo
    _write_config(kb_dir, GOOD.replace("true", "false"))
    run_git(root, "commit", "-a", "-m", "off")
    _origin(root, run_git, tmp_path)
    run_git(root, "push", "-u", "origin", "main")
    _write_config(kb_dir, GOOD)
    run_git(root, "commit", "-a", "-m", "on, not pushed")
    (reason,) = preflight(root, kb_dir)
    assert "origin/main" in reason and "push" in reason


def test_preflight_without_a_remote_reads_the_local_default_branch(git_repo):
    root, kb_dir, _ = git_repo
    assert preflight(root, kb_dir) == []


# --- run lock: one `kb auto run` per repo ---------------------------------


def test_run_lock_writes_pid_and_reports_running(tmp_path):
    kb_dir = tmp_path / ".kb"
    with lock_mod.run_lock(kb_dir) as path:
        assert path == kb_dir / "auto" / "run.lock"
        assert path.read_text(encoding="utf-8").strip() == str(os.getpid())
        assert lock_mod.running_pid(kb_dir) == os.getpid()
    assert lock_mod.running_pid(kb_dir) is None  # file may stay, lock is gone


def test_run_lock_refuses_while_the_lock_is_held(tmp_path):
    kb_dir = tmp_path / ".kb"
    with (
        lock_mod.run_lock(kb_dir),
        pytest.raises(KbError, match=rf"already running \(pid {os.getpid()}\)"),
        lock_mod.run_lock(kb_dir),
    ):
        pass


def test_run_lock_ignores_a_file_left_by_a_dead_process(tmp_path):
    kb_dir = tmp_path / ".kb"
    lock = kb_dir / "auto" / "run.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("424242\n", encoding="utf-8", newline="\n")  # no OS lock held
    assert lock_mod.running_pid(kb_dir) is None
    with lock_mod.run_lock(kb_dir):
        assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_run_lock_survives_garbage_content(tmp_path):
    kb_dir = tmp_path / ".kb"
    lock = kb_dir / "auto" / "run.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("not-a-pid\n", encoding="utf-8", newline="\n")
    with lock_mod.run_lock(kb_dir):
        assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_run_lock_is_released_after_an_exception(tmp_path):
    kb_dir = tmp_path / ".kb"
    with pytest.raises(RuntimeError), lock_mod.run_lock(kb_dir):
        raise RuntimeError("boom")
    assert lock_mod.running_pid(kb_dir) is None


class ParkedQaThread:
    failed_twice = False

    def __init__(self, only_parked: bool = True, parked=("T-a",)):
        self.parked = frozenset(parked)
        self._only_parked = only_parked

    def only_parked_left(self) -> bool:
        return self._only_parked


def test_parked_only_stops_the_loop(env, monkeypatch, caplog):
    monkeypatch.setattr(picker, "pick_ba", lambda root, kb, skip=(): None)
    script = Script()
    with caplog.at_level(logging.ERROR):
        outcome = once(env, script, cfg=cfg_of("ba"), qa_thread=ParkedQaThread())
    assert outcome == "stopped"
    assert autostate.load(env[1]).stop_reason == "parked: T-a"
    assert "auto/qa-parked/T-a" in caplog.text
    assert script.prompts == []


def test_parked_stop_lists_every_ticket_sorted(env, monkeypatch):
    monkeypatch.setattr(picker, "pick_ba", lambda root, kb, skip=(): None)
    parked = ParkedQaThread(parked={"T-b", "T-a"})
    assert once(env, Script(), cfg=cfg_of("ba"), qa_thread=parked) == "stopped"
    assert autostate.load(env[1]).stop_reason == "parked: T-a, T-b"


def test_parked_with_task_left_keeps_running(env):
    script = Script(TaskResult("done"))
    outcome = once(env, script, cfg=cfg_of("ba"), qa_thread=ParkedQaThread())
    assert outcome == "ran"
    assert len(script.prompts) == 1


def test_parked_with_unparked_question_idles(env, monkeypatch):
    monkeypatch.setattr(picker, "pick_ba", lambda root, kb, skip=(): None)
    outcome = once(env, Script(), cfg=cfg_of("ba"), qa_thread=ParkedQaThread(False))
    assert outcome == "idle"


def _switching(run_git, result=None, dirty=None):
    """A `run_task` double that leaves the root on `auto/US1` (and optionally
    raises, or dirties a tracked file so a checkout back conflicts)."""

    def run_task(root, prompt, *, log_dir):
        run_git(root, "switch", "-c", "auto/US1")
        if dirty:
            (root / dirty).write_text("branch\n", encoding="utf-8")
            run_git(root, "commit", "-am", "branch edit")
            (root / dirty).write_text("dirty\n", encoding="utf-8")
        if result is None:
            raise RuntimeError("boom")
        return result

    return run_task


def test_root_branch_restored_after_task(git_repo, env):
    root, _, run_git = git_repo
    outcome = once(env, _switching(run_git, TaskResult("done")))
    assert outcome == "ran"
    assert gitio.current_branch(root) == "main"


def test_root_branch_restored_after_task_exception(git_repo, env):
    root, kb_dir, run_git = git_repo
    assert once(env, _switching(run_git)) == "ran"
    assert gitio.current_branch(root) == "main"
    assert autostate.load(kb_dir).attempts == 1


def test_detached_head_restores_commit(git_repo, env):
    root, _, run_git = git_repo
    run_git(root, "checkout", "--detach")
    sha = gitio.head_commit(root)
    once(env, _switching(run_git, TaskResult("done")))
    assert gitio.current_branch(root) == "HEAD"
    assert gitio.head_commit(root) == sha


def test_restore_failure_is_a_warning(git_repo, env, caplog):
    root, _, run_git = git_repo
    (root / "f.txt").write_text("main\n", encoding="utf-8")
    run_git(root, "add", "f.txt")
    run_git(root, "commit", "-m", "f")
    script = _switching(run_git, TaskResult("done"), dirty="f.txt")
    with caplog.at_level(logging.WARNING):
        assert once(env, script) == "ran"
    assert gitio.current_branch(root) == "auto/US1"
    assert "could not return" in caplog.text


# --- ticket claims (dev kind) -------------------------------------------------


class FakeClaims:
    """A `RunnerClaims` double that records every call."""

    def __init__(self, taken=(), held=(), beat_ok=True):
        self.calls: list[tuple] = []
        self.taken, self.held, self.beat_ok = set(taken), set(held), beat_ok
        self.route_missing = False
        self.claim_error: KbError | None = None

    def held_by_others(self, mine):
        self.calls.append(("held", mine))
        if self.route_missing:
            raise ClaimRouteMissing
        return set(self.held)

    def claim(self, ticket):
        self.calls.append(("claim", ticket))
        if self.claim_error:
            raise self.claim_error
        return ticket not in self.taken

    def begin(self, ticket):
        self.calls.append(("begin", ticket))
        return True

    def phase(self, ticket, phase, pr=""):
        self.calls.append(
            ("phase", ticket, phase, pr) if pr else ("phase", ticket, phase)
        )
        return True

    def beat(self, ticket):
        self.calls.append(("beat", ticket))
        return self.beat_ok

    def stop(self, ticket, reason):
        self.calls.append(("stop", ticket, reason))

    def release_if_working(self, ticket, reason):
        self.calls.append(("release", ticket, reason))

    def forget(self, ticket):
        self.calls.append(("forget", ticket))

    def lost_reason(self, ticket):
        return "expired by hub"

    def of(self, kind):
        return [c for c in self.calls if c[0] == kind]


@pytest.fixture
def cenv(env, monkeypatch):
    """`env` with two ready tickets and a CI workflow, so the real candidate walk runs."""
    root, kb_dir, hub, tickets = env
    tickets["stories"] = [S("US1", "ready"), S("US2", "ready")]
    monkeypatch.setattr(picker, "_has_test_workflow", lambda r: True)
    return env


class FakeBeat:
    """A `ClaimBeat` double; `lost` is scripted per test."""

    lost = False
    events: list[tuple] = []

    def __init__(self, claims, interval):
        FakeBeat.events = [("init", interval)]

    def start(self, ticket):
        FakeBeat.events.append(("start", ticket))

    def stop(self):
        FakeBeat.events.append(("stop",))


def test_pick_walks_candidates_and_claims_the_first(cenv):
    claims, script = FakeClaims(), Script(TaskResult("done"))
    assert once(cenv, script, claims=claims) == "ran"
    assert script.prompts[0].startswith("/dev-implement-ticket US1")
    assert claims.of("claim") == [("claim", "US1")]
    assert claims.of("held") == [("held", None)]


def test_pick_skips_held_tickets(cenv):
    claims, script = FakeClaims(held={"US1"}), Script(TaskResult("done"))
    once(cenv, script, claims=claims)
    assert script.prompts[0].startswith("/dev-implement-ticket US2")


def test_pick_moves_on_after_lost_race(cenv):
    claims, script = FakeClaims(taken={"US1"}), Script(TaskResult("done"))
    once(cenv, script, claims=claims)
    assert claims.of("claim") == [("claim", "US1"), ("claim", "US2")]
    assert script.prompts[0].startswith("/dev-implement-ticket US2")
    assert autostate.load(cenv[1]).last_done == "dev-implement-ticket:US2"


def test_all_candidates_taken_is_idle(cenv):
    claims, script = FakeClaims(taken={"US1", "US2"}), Script()
    assert once(cenv, script, claims=claims) == "idle"
    assert script.prompts == [] and autostate.load(cenv[1]).stop_reason is None


def test_stored_task_taken_by_other_drops_task(cenv, caplog):
    cenv[3]["stories"].append(S("M-x-US3", "ready"))
    autostate.save(cenv[1], autostate.AutoState(TASK.key, 1, (), None, ""))
    claims, script = FakeClaims(taken={"M-x-US3"}), Script()
    with caplog.at_level(logging.INFO):
        assert once(cenv, script, claims=claims) == "ran"
    assert script.prompts == [] and autostate.load(cenv[1]).task is None
    assert "M-x-US3 is now held by another Dev; picking again" in caplog.text


def test_stored_task_is_reclaimed_and_mine_is_not_held(cenv):
    cenv[3]["stories"].append(S("M-x-US3", "ready"))
    autostate.save(cenv[1], autostate.AutoState(TASK.key, 1, (), None, ""))
    claims = FakeClaims()
    once(cenv, Script(TaskResult("done")), claims=claims)
    assert claims.of("claim") == [("claim", "M-x-US3")] and claims.of("held") == []


def test_done_sets_publishing_not_release(cenv):
    claims = FakeClaims()
    once(cenv, Script(TaskResult("done")), claims=claims)
    assert [c for c in claims.calls if c[0] in ("begin", "phase", "release")] == [
        ("begin", "US1"),
        ("phase", "US1", "publishing"),
    ]


def test_blocked_qa_sets_waiting_qa_and_beats_while_waiting(cenv):
    claims, script = FakeClaims(), Script(TaskResult("blocked-qa", (12,)))
    assert once(cenv, script, claims=claims) == "waiting"
    assert claims.of("phase")[-1] == ("phase", "US1", "waiting-qa")
    once(cenv, script, qa=FakeQa({12: "waiting"}), claims=claims)
    assert claims.of("beat") == [("beat", "US1")]


def test_beat_runs_around_the_task(cenv, monkeypatch):
    monkeypatch.setattr(runner_mod, "ClaimBeat", FakeBeat)
    claims = FakeClaims()
    once(
        cenv, Script(TaskResult("done")), cfg=cfg_of(claim_heartbeat=33), claims=claims
    )
    assert FakeBeat.events == [("init", 33), ("start", "US1"), ("stop",)]


def test_stop_marks_stopped(cenv):
    claims = FakeClaims()
    script = Script(TaskResult("failed", (), "ci-red http://pr/1"))
    assert once(cenv, script, claims=claims) == "stopped"
    assert claims.of("stop") == [("stop", "US1", "ci-red http://pr/1")]
    assert autostate.load(cenv[1]).task == "dev-implement-ticket:US1"  # kept


def test_second_failure_marks_stopped(cenv):
    claims = FakeClaims()
    script = Script(TaskResult("failed", (), "x"), TaskResult("failed", (), "x"))
    assert once(cenv, script, claims=claims) == "ran"
    assert claims.of("stop") == []
    assert once(cenv, script, claims=claims) == "stopped"
    assert claims.of("stop") == [("stop", "US1", "x")]


def test_route_missing_stops_run(cenv):
    claims = FakeClaims()
    claims.route_missing = True
    assert once(cenv, Script(), claims=claims) == "stopped"
    assert "upgrade it to strata-kb 1.31.0" in autostate.load(cenv[1]).stop_reason


def test_bad_request_on_take_stops_run(cenv):
    claims = FakeClaims()
    claims.claim_error = ClaimRejectedError(
        "hub /api/claims returned 400: bad_request — holder is not valid"
    )
    assert once(cenv, Script(), claims=claims) == "stopped"
    reason = autostate.load(cenv[1]).stop_reason
    assert "400: bad_request — holder is not valid" in reason


def test_transient_error_on_take_keeps_idling(cenv):
    claims = FakeClaims()
    claims.claim_error = KbError("hub unreachable: refused")
    assert once(cenv, Script(), claims=claims) == "idle"
    assert autostate.load(cenv[1]).stop_reason is None


def test_lost_during_task_counts_no_attempt(cenv, monkeypatch, caplog):
    class LostBeat(FakeBeat):
        lost = True

    monkeypatch.setattr(runner_mod, "ClaimBeat", LostBeat)
    claims = FakeClaims()
    with caplog.at_level(logging.WARNING):
        out = once(cenv, Script(TaskResult("failed", (), "x")), claims=claims)
    state = autostate.load(cenv[1])
    assert (out, state.task, state.attempts) == ("ran", None, 0)
    assert "claim on US1 lost: expired by hub" in caplog.text
    assert claims.of("stop") == []


def test_loop_exit_releases_working_claim_only(cenv):
    claims = FakeClaims()
    # a stopped run keeps its task: the loop exit hands it to release_if_working
    script = Script(TaskResult("failed", (), "ci-red x"))
    run_loop(
        *_loop_args(cenv), qa=FakeQa(), run_task=script, claims=claims, hub=cenv[2]
    )
    assert claims.of("release") == [("release", "US1", "runner stopped")]


def test_loop_exit_after_done_does_not_release(cenv):
    claims = FakeClaims()
    script = Script(TaskResult("done"))

    def run_and_finish(root, prompt, *, log_dir):
        cenv[3]["stories"] = [S("US1", "done"), S("US2", "done")]
        return script(root, prompt, log_dir=log_dir)

    code = run_loop(
        *_loop_args(cenv),
        qa=FakeQa(),
        run_task=run_and_finish,
        claims=claims,
        hub=cenv[2],
    )
    assert code == 0 and claims.of("release") == []


def _loop_args(env):
    root, kb_dir, _, _ = env
    (kb_dir / "config.yaml").write_text(
        "kind: dev\nrepo_id: svc\nintake: http://intake\nauto:\n  enabled: true\n",
        encoding="utf-8",
        newline="\n",
    )
    return root, kb_dir


def test_ba_runner_makes_no_claims(env, monkeypatch):
    ba_task = Task("ba-ticket-author", "US1")
    monkeypatch.setattr(picker, "pick_ba", lambda root, kb, skip=(): ba_task)
    claims = FakeClaims()
    assert (
        once(env, Script(TaskResult("done")), cfg=cfg_of("ba"), claims=claims) == "ran"
    )
    assert claims.calls == []


def test_test_workflow_task_makes_no_claim(cenv, monkeypatch):
    monkeypatch.setattr(picker, "_has_test_workflow", lambda r: False)
    claims, script = FakeClaims(), Script(TaskResult("done"))
    assert once(cenv, script, claims=claims) == "ran"
    assert script.prompts[0].startswith("/dev-test-workflow")
    assert [c for c in claims.calls if c[0] != "held"] == []


def test_build_claims_only_for_dev(env, monkeypatch):
    root, kb_dir, _, _ = env
    assert runner_mod.build_claims(root, kb_dir, cfg_of("ba")) is None
    monkeypatch.setattr(runner_mod.claimclient, "from_env", lambda: object())
    monkeypatch.setattr(runner_mod.claimclient, "holder_name", lambda r: "me@m1")
    assert runner_mod.build_claims(root, kb_dir, cfg_of("dev")) is not None


def test_run_loop_dev_builds_claims_from_env(env, monkeypatch):
    root, kb_dir, hub, tickets = env
    tickets["stories"] = [S("US3", "done")]
    built = []
    monkeypatch.setattr(
        runner_mod, "build_claims", lambda r, k, c: built.append(c.kind) or None
    )
    _loop_args(env)
    assert run_loop(root, kb_dir, hub=hub, qa=FakeQa(), run_task=Script()) == 0
    assert built == ["dev"]


class FlakyPhase(FakeClaims):
    """`phase` raises a transient KbError for one phase."""

    def __init__(self, failing_phase):
        super().__init__()
        self.failing_phase = failing_phase

    def phase(self, ticket, phase, pr=""):
        if phase == self.failing_phase:
            raise KbError("hub unreachable")
        return super().phase(ticket, phase, pr)


def test_transient_publishing_error_still_settles_done(cenv, caplog):
    with caplog.at_level(logging.WARNING):
        out = once(cenv, Script(TaskResult("done")), claims=FlakyPhase("publishing"))
    assert out == "ran"
    state = autostate.load(cenv[1])
    assert (state.last_done, state.task) == ("dev-implement-ticket:US1", None)
    assert "hub unreachable" in caplog.text


def test_transient_waiting_qa_error_still_saves_waiting_on(cenv):
    out = once(
        cenv, Script(TaskResult("blocked-qa", (12,))), claims=FlakyPhase("waiting-qa")
    )
    assert out == "waiting" and autostate.load(cenv[1]).waiting_on == (12,)


def _stored(env, ticket="US1"):
    autostate.save(
        env[1], autostate.AutoState(f"dev-implement-ticket:{ticket}", 1, (), None, "")
    )


@pytest.mark.parametrize(
    "stories",
    [
        [S("US2", "ready")],  # unpublished: the ticket left the plan
        [StoryStatus("US1", "M-x", "t", "ready", (), (), "other")],  # routed elsewhere
        [S("US1", "blocked"), S("US2", "ready")],  # not ready
    ],
    ids=["unpublished", "routed-elsewhere", "not-ready"],
)
def test_stored_task_no_longer_ready_here_is_dropped(cenv, stories, caplog):
    cenv[3]["stories"] = stories
    _stored(cenv)
    claims, script = FakeClaims(), Script()
    with caplog.at_level(logging.INFO):
        assert once(cenv, script, claims=claims) == "ran"
    state = autostate.load(cenv[1])
    assert (state.task, state.attempts) == (None, 0)
    assert script.prompts == [] and claims.of("claim") == []
    assert claims.of("release") == [("release", "US1", "US1 no longer ready for svc")]
    assert claims.of("forget") == [("forget", "US1")]
    assert "US1 is no longer ready for svc; picking again" in caplog.text


def test_stored_untargeted_task_is_kept_like_the_pick(cenv):
    # Same routing test as the pick: an untargeted ready row (hub with no dev repos)
    # stays this runner's task, so attempts keep counting toward MAX_ATTEMPTS.
    cenv[3]["stories"] = [StoryStatus("US1", "M-x", "t", "ready", (), (), None)]
    _stored(cenv)
    claims, script = FakeClaims(), Script(TaskResult("done"))
    assert once(cenv, script, claims=claims) == "ran"
    assert script.prompts[0].startswith("/dev-implement-ticket US1")
    assert claims.of("release") == [] and claims.of("forget") == []


def test_stored_task_unpublished_is_dropped_and_repicked(cenv):
    cenv[3]["stories"] = [S("US2", "ready")]
    _stored(cenv)
    claims, script = FakeClaims(), Script(TaskResult("done"))
    assert once(cenv, script, claims=claims) == "ran"
    assert once(cenv, script, claims=claims) == "ran"
    assert script.prompts[0].startswith("/dev-implement-ticket US2")


def test_claim_unknown_ticket_recovers(cenv, caplog):
    claims = FakeClaims()
    claims.claim_error = UnknownTicketError(
        "hub /api/claims returned 404: unknown_ticket"
    )
    _stored(cenv)
    with caplog.at_level(logging.INFO):
        assert once(cenv, Script(), claims=claims) == "ran"
    state = autostate.load(cenv[1])
    assert (state.task, state.attempts, state.stop_reason) == (None, 0, None)
    assert "unknown_ticket; picking again" in caplog.text


class _UnknownFirst(FakeClaims):
    def claim(self, ticket):
        if ticket == "US1":
            raise UnknownTicketError("hub /api/claims returned 404: unknown_ticket")
        return super().claim(ticket)


def test_pick_unknown_ticket_moves_on_to_next_candidate(cenv):
    claims, script = _UnknownFirst(), Script(TaskResult("done"))
    assert once(cenv, script, claims=claims) == "ran"
    assert script.prompts[0].startswith("/dev-implement-ticket US2")


def test_pick_only_unknown_tickets_is_idle(cenv):
    cenv[3]["stories"] = [S("US1", "ready")]
    claims, script = _UnknownFirst(), Script()
    assert once(cenv, script, claims=claims) == "idle"
    assert script.prompts == []


class _ParentFirst(FakeClaims):
    def claim(self, ticket):
        if ticket == "US1":
            raise ParentStoryError(
                "hub /api/claims returned 400: parent_story — US1 is a parent story"
            )
        return super().claim(ticket)


def test_runner_skips_parent_claim_refusal(cenv):
    claims, script = _ParentFirst(), Script(TaskResult("done"))
    assert once(cenv, script, claims=claims) == "ran"
    assert script.prompts[0].startswith("/dev-implement-ticket US2")
    assert autostate.load(cenv[1]).stop_reason is None


def test_stored_task_now_a_parent_is_dropped_not_stopped(cenv):
    claims = FakeClaims()
    claims.claim_error = ParentStoryError("hub returned 400: parent_story")
    _stored(cenv)
    assert once(cenv, Script(), claims=claims) == "ran"
    state = autostate.load(cenv[1])
    assert (state.task, state.attempts, state.stop_reason) == (None, 0, None)
    assert claims.of("forget") == [("forget", "US1")]


def test_stored_own_fix_task_survives_a_resume(cenv):
    cenv[3]["stories"] = [
        StoryStatus(
            "BUG-9", "", "t", "in progress", ("own fix pending",), (), "svc", True,
            own_fix_ready=True,
        )
    ]  # fmt: skip
    autostate.save(cenv[1], autostate.AutoState("dev-fix-bug:BUG-9", 1, (), None, ""))
    claims, script = FakeClaims(), Script(TaskResult("done"))
    assert once(cenv, script, claims=claims) == "ran"
    assert script.prompts[0].startswith("/dev-fix-bug BUG-9")
    assert claims.of("release") == [] and claims.of("forget") == []


# --- blocked-split ----------------------------------------------------------

BUG = Task("dev-fix-bug", "BUG-7")


def _bug_row(**kw) -> StoryStatus:
    return StoryStatus("BUG-7", "", "t", "ready", (), (), "svc", **kw)


def _split_env(env, monkeypatch, rows):
    seen: list = []

    def pick(h, root, repo_id, skip=()):
        seen.append(tuple(skip))
        return None if BUG.key in skip else BUG

    monkeypatch.setattr(picker, "pick_dev", pick)
    monkeypatch.setattr(
        planstatus, "next_from_hub", lambda h, repo=None, for_repo=None: ([], rows, [])
    )
    return seen


def test_blocked_split_is_not_re_picked_until_parent(env, monkeypatch):
    rows = [_bug_row()]
    seen = _split_env(env, monkeypatch, rows)
    script = Script(TaskResult("blocked-split", ("BUG-7",)), TaskResult("done"))
    assert once(env, script) == "ran"
    state = autostate.load(env[1])
    assert (state.task, state.waiting_split) == (None, ("BUG-7",))

    assert once(env, script) == "idle"  # row still a plain bug: skipped
    assert seen[-1] == (BUG.key,)
    assert len(script.prompts) == 1

    rows[:] = [_bug_row(is_parent=True, own_fix_ready=True)]
    assert once(env, script) == "ran"  # the BA split it: own fix may run
    assert seen[-1] == ()
    assert autostate.load(env[1]).waiting_split == ()
    assert script.prompts[1].startswith("/dev-fix-bug BUG-7")


def test_blocked_split_survives_restart(env, monkeypatch):
    seen = _split_env(env, monkeypatch, [_bug_row()])
    once(env, Script(TaskResult("blocked-split", ("BUG-7",))))
    raw = (env[1] / "auto" / "state.json").read_text()
    assert '"waiting_split": [\n    "BUG-7"\n  ]' in raw
    assert autostate.load(env[1]).waiting_split == ("BUG-7",)
    assert once(env, Script()) == "idle"
    assert seen[-1] == (BUG.key,)


class SplitQa(FakeQa):
    """FakeQa whose `list` returns scripted question rows."""

    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def list(self, status="open", repo="", ticket=""):
        return [q for q in self.rows if not ticket or q["ticket"] == ticket]


def _proposal(state: str, qid: int = 5) -> dict:
    return {
        "id": qid,
        "ticket": "BUG-7",
        "state": state,
        "question": "Split proposal for BUG-7: two children",
    }


def test_blocked_split_rejected_proposal_lifts_the_skip(env, monkeypatch):
    seen = _split_env(env, monkeypatch, [_bug_row()])  # the row never becomes parent
    qa = SplitQa([_proposal("waiting")])
    script = Script(TaskResult("blocked-split", ("BUG-7",)), TaskResult("done"))
    once(env, script, qa=qa)
    assert once(env, script, qa=qa) == "idle"  # still waiting for the BA
    assert seen[-1] == (BUG.key,)

    qa.rows[:] = [_proposal("answered")]
    assert once(env, script, qa=qa) == "ran"  # BA rejected: the Dev reads the answer
    assert seen[-1] == ()
    assert autostate.load(env[1]).waiting_split == ()


def test_blocked_split_newer_open_proposal_keeps_the_skip(env, monkeypatch):
    seen = _split_env(env, monkeypatch, [_bug_row()])
    qa = SplitQa([_proposal("answered", 5), _proposal("waiting", 9)])
    autostate.save(
        env[1], autostate.AutoState(None, 0, (), None, "", waiting_split=("BUG-7",))
    )
    assert once(env, Script(), qa=qa) == "idle"
    assert seen[-1] == (BUG.key,)


def test_blocked_split_child_bug_waits_on_its_own_id(env, monkeypatch):
    # a child bug proposes a sibling on its parent: never a parent row itself,
    # so only the answered proposal (listed under the child id) lifts the skip
    kid = Task("dev-fix-bug", "BUG-7.web")
    seen: list = []

    def pick(h, root, repo_id, skip=()):
        seen.append(tuple(skip))
        return None if kid.key in skip else kid

    monkeypatch.setattr(picker, "pick_dev", pick)
    monkeypatch.setattr(
        planstatus,
        "next_from_hub",
        lambda h, repo=None, for_repo=None: ([], [_bug_row()], []),
    )
    proposal = {**_proposal("waiting"), "ticket": "BUG-7.web"}
    proposal["question"] = "Split proposal for BUG-7.web: a sibling in api"
    qa = SplitQa([proposal])
    script = Script(TaskResult("blocked-split", ("BUG-7.web",)), TaskResult("done"))
    assert once(env, script, qa=qa) == "ran"
    assert autostate.load(env[1]).waiting_split == ("BUG-7.web",)
    assert once(env, script, qa=qa) == "idle"
    assert seen[-1] == (kid.key,)

    proposal["state"] = "answered"
    assert once(env, script, qa=qa) == "ran"
    assert seen[-1] == ()
    assert script.prompts[1].startswith("/dev-fix-bug BUG-7.web")


class OwnClaimClient:
    """A hub claim double: BUG-7 is the runner's own claim; it stays held once stopped."""

    def __init__(self):
        self.state, self.calls, self.taken = "active", [], False

    def _row(self):
        return {
            "id": 7,
            "ticket": "BUG-7",
            "holder": "me@m1",
            "phase": "claimed",
            "state": self.state,
            "pr": "",
        }

    def held(self, repo="", ticket=""):
        return [self._row()] if self.taken else []

    def take(self, ticket, holder, claim_token=None):
        self.calls.append(("take", ticket, claim_token))
        self.taken = True
        return self._row(), "tok"

    def update(self, claim_id, claim_token, **fields):
        self.calls.append(("update", fields))
        self.state = fields.get("state", self.state)
        return self._row()


def test_blocked_split_own_fix_retakes_the_stopped_claim(env, monkeypatch):
    from strata_kb.autorun.claims import RunnerClaims

    root, kb_dir, *_ = env
    rows = [_bug_row()]
    # the claims path runs the real `dev_candidates`, not the patched `pick_dev`
    monkeypatch.setattr(
        planstatus, "next_from_hub", lambda h, repo=None, for_repo=None: ([], rows, [])
    )
    monkeypatch.setattr(picker, "_has_test_workflow", lambda r: True)
    monkeypatch.setattr(runner_mod, "ClaimBeat", FakeBeat)
    client = OwnClaimClient()
    claims = RunnerClaims(root, kb_dir, client, "me@m1")  # type: ignore[arg-type]
    script = Script(TaskResult("blocked-split", ("BUG-7",)), TaskResult("done"))

    assert once(env, script, claims=claims) == "ran"
    client.state = "stopped"  # the skill stopped the claim; it never expires
    assert once(env, script, claims=claims) == "idle"  # plain bug: skipped

    rows[:] = [_bug_row(is_parent=True, own_fix_ready=True)]
    assert once(env, script, claims=claims) == "ran"
    assert script.prompts[1].startswith("/dev-fix-bug BUG-7")
    assert client.state == "active"  # re-taken with the saved token and resumed
    assert ("take", "BUG-7", "tok") in client.calls


# --- blocked-review -----------------------------------------------------------

PR_URL = "https://github.com/o/r/pull/42"
PARKED = f"{TASK.key} {PR_URL}"


def _park(env, *entries):
    autostate.save(
        env[1],
        autostate.AutoState(None, 0, (), None, "", waiting_review=entries or (PARKED,)),
    )


def _view(monkeypatch, state=None, error=None):
    seen: list = []

    def view_pr(root, ref):
        seen.append(ref)
        if error:
            raise error
        return {"state": state}

    monkeypatch.setattr(runner_mod.ghrest, "view_pr", view_pr)
    return seen


def test_blocked_review_parks_without_attempt(env):
    script = Script(TaskResult("blocked-review", (PR_URL,)))
    assert once(env, script) == "ran"
    state = autostate.load(env[1])
    assert (state.task, state.attempts, state.stop_reason) == (None, 0, None)
    assert state.waiting_review == (PARKED,)


def test_blocked_review_entry_is_deduped(env):
    autostate.save(
        env[1],
        autostate.AutoState(TASK.key, 0, (), None, "", waiting_review=(PARKED,)),
    )
    once(env, Script(TaskResult("blocked-review", (PR_URL,))))
    assert autostate.load(env[1]).waiting_review == (PARKED,)


def test_parked_task_is_skipped_by_pick(env, monkeypatch):
    _view(monkeypatch, "OPEN")
    skips: list = []
    monkeypatch.setattr(
        picker, "pick_dev", lambda h, root, repo_id, skip=(): skips.append(skip)
    )
    _park(env)
    assert once(env, Script()) == "idle"
    assert TASK.key in skips[-1]


def test_parked_merged_counts_done(env, monkeypatch):
    seen = _view(monkeypatch, "MERGED")
    _park(env)
    once(env, Script())
    state = autostate.load(env[1])
    assert (state.last_done, state.waiting_review) == (TASK.key, ())
    assert seen == ["42"]


def test_parked_merged_moves_claim_to_publishing(cenv, monkeypatch):
    _view(monkeypatch, "MERGED")
    _park(cenv, f"dev-implement-ticket:US1 {PR_URL}")
    claims = FakeClaims()
    # the task run afterwards is M-x-US3, so only _review_check can touch US1
    once(cenv, Script(TaskResult("done")), claims=claims)
    assert ("phase", "US1", "publishing") in claims.of("phase")


def test_parked_closed_is_dropped(env, monkeypatch, caplog):
    _view(monkeypatch, "CLOSED")
    _park(env)
    once(env, Script())
    state = autostate.load(env[1])
    assert (state.last_done, state.waiting_review) == (None, ())
    assert "closed without merging" in caplog.text


def test_parked_view_error_keeps_waiting(env, monkeypatch, caplog):
    _view(monkeypatch, error=KbError("gh down"))
    _park(env)
    once(env, Script())
    assert autostate.load(env[1]).waiting_review == (PARKED,)
    assert "gh down" in caplog.text


def test_only_parked_left_is_idle_not_stop(env, monkeypatch):
    _view(monkeypatch, "OPEN")
    monkeypatch.setattr(
        picker,
        "pick_dev",
        lambda h, root, repo_id, skip=(): None if TASK.key in skip else TASK,
    )
    _park(env)
    assert once(env, Script()) == "idle"
    assert autostate.load(env[1]).stop_reason is None


def test_blocked_review_sets_review_phase_with_pr(cenv):
    claims = FakeClaims()
    once(cenv, Script(TaskResult("blocked-review", (PR_URL,))), claims=claims)
    assert claims.of("phase")[-1] == ("phase", "US1", "review", PR_URL)


def test_parked_tickets_are_beaten_while_waiting(cenv, monkeypatch):
    _view(monkeypatch, "OPEN")
    claims = FakeClaims()
    autostate.save(
        cenv[1],
        autostate.AutoState(
            "dev-implement-ticket:US2",
            0,
            (12,),
            None,
            "",
            waiting_review=(f"dev-implement-ticket:US1 {PR_URL}",),
        ),
    )
    once(cenv, Script(), qa=FakeQa({12: "waiting"}), claims=claims)
    assert {c[1] for c in claims.of("beat")} == {"US1", "US2"}
