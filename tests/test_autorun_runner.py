from __future__ import annotations

import logging
from pathlib import Path

import pytest

from strata_kb import planstatus
from strata_kb.autorun import picker
from strata_kb.autorun import runner as runner_mod
from strata_kb.autorun import state as autostate
from strata_kb.autorun.claude import TaskResult
from strata_kb.autorun.picker import Task
from strata_kb.autorun.runner import Backoff, preflight, run_loop, run_once
from strata_kb.config import AutoConfig, KBConfig
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from strata_kb.missionnext import StoryStatus
from strata_kb.models import Registry, RegistryEntry

TASK = Task("dev-implement-ticket", "M-x-US3")


def S(us_id: str, status: str) -> StoryStatus:
    return StoryStatus(us_id, "M-x", "t", status, ())


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
    tickets = {"stories": [S("US3", "ready")]}
    monkeypatch.setattr(
        planstatus, "next_from_hub", lambda h, repo=None: (tickets["stories"], [], [])
    )
    monkeypatch.setattr(picker, "pick_dev", lambda h, root: TASK)
    monkeypatch.setattr(picker, "pick_ba", lambda root, kb: TASK)
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
    monkeypatch.setattr(picker, "pick_dev", lambda h, root: None)
    assert once(env, Script()) == "idle"
    monkeypatch.setattr(
        picker, "pick_dev", lambda h, root: (_ for _ in ()).throw(KbError("boom"))
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


def test_fifth_repick_of_done_task_stops(env):
    script = Script(TaskResult("done"))
    once(env, script)
    for _ in range(4):
        assert once(env, script) == "idle"
    assert once(env, script) == "stopped"
    state = autostate.load(env[1])
    assert (
        state.stop_reason == f"{TASK.key} ended done but is still picked after 5 checks"
    )
    assert len(script.prompts) == 1


def test_different_pick_resets_the_repick_guard(env, monkeypatch):
    script = Script(TaskResult("done"), TaskResult("done"))
    once(env, script)
    assert once(env, script) == "idle"
    other = Task("dev-implement-ticket", "M-x-US4")
    monkeypatch.setattr(picker, "pick_dev", lambda h, root: other)

    assert once(env, script) == "ran"

    state = autostate.load(env[1])
    assert (state.last_done, state.same_pick) == (other.key, 0)
    assert script.prompts[1].startswith("/dev-implement-ticket M-x-US4")


def test_resume_resets_repick_count_but_keeps_last_done(env):
    autostate.save(env[1], autostate.AutoState(None, 0, (), "stuck", "", TASK.key, 4))
    runner_mod.resume(env[1])
    state = autostate.load(env[1])
    assert (state.stop_reason, state.same_pick, state.last_done) == (None, 0, TASK.key)


def test_crash_resumes_stored_task(env, monkeypatch):
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
    return run_loop(root, kb_dir, sleep=sleep, hub=hub, qa=FakeQa(), run_task=script)


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

    def pick(hub, root):
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
    return run_loop(root, kb_dir, hub=hub, qa=FakeQa(), run_task=Script())


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

    code = run_loop(root, kb_dir, hub_flag="/flag/hub", qa=FakeQa(), run_task=Script())

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
    assert "on main" in reason and "auto.enabled: true" in reason


def test_preflight_refuses_when_default_branch_lacks_the_config(git_repo, tmp_path):
    root, kb_dir, run_git = git_repo
    run_git(root, "rm", "-q", "--cached", ".kb/config.yaml")
    run_git(root, "commit", "-m", "no config on main")
    _default_branch_is_main_and_head_is_work(root, run_git, tmp_path)
    run_git(root, "add", ".kb/config.yaml")
    run_git(root, "commit", "-m", "config on a branch only")
    (reason,) = preflight(root, kb_dir)
    assert "on main" in reason and "auto.enabled: true" in reason
