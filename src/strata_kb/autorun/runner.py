"""The auto-mode loop: `run_once` is the unit, `run_loop` repeats it.

One call picks (or resumes) a task, runs it as a fresh `claude -p` process and
settles the result into `.kb/auto/state.json`. The loop outlives any one failed
run, like `codesync.runner`; only a stop rule, or "every ticket is done", ends it.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Literal

import yaml

from strata_kb import gitio, planstatus
from strata_kb.autorun import claude, picker
from strata_kb.autorun import qa as qa_mod
from strata_kb.autorun import state as autostate
from strata_kb.autorun.done import all_done
from strata_kb.autorun.picker import Task
from strata_kb.autorun.qathread import QaThread, open_question_count
from strata_kb.autorun.switch import registry_or_reason
from strata_kb.config import AutoConfig, KBConfig, load_config, require_hub
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle, resolve_hub

logger = logging.getLogger("strata_kb.autorun.runner")

Outcome = Literal["ran", "idle", "waiting", "stopped", "done"]

MAX_ATTEMPTS = 2  # a task that ends `failed` twice stops the loop
MAX_SAME_PICK = 5  # picks of the task that just ended `done` before the loop stops
BACKOFF_START = 900
BACKOFF_MAX = 3600
EXIT_DONE = 0
EXIT_STOPPED = 2


class Backoff:
    """Usage-limit sleeps: 900, 1800, 3600, 3600, ... until `reset`."""

    def __init__(self) -> None:
        self._delay = BACKOFF_START

    def next(self) -> int:
        delay, self._delay = self._delay, min(self._delay * 2, BACKOFF_MAX)
        return delay

    def reset(self) -> None:
        self._delay = BACKOFF_START


SWITCH_FILES = (".kb/config.yaml", ".claude/settings.json")


def _switch_refusals(root: Path) -> list[str]:
    """The switch and the permissions must be committed: Dev's `kb publish`
    refuses a dirty `.kb/`, and the BA's Q&A worktree reads the default branch."""
    reasons = []
    for rel in SWITCH_FILES:
        if not gitio.is_tracked(root, rel):
            reasons.append(f"{rel} is not tracked by git -- commit it")
        elif gitio.is_dirty(root, root / rel):
            reasons.append(f"{rel} has uncommitted changes -- commit it")
    where, how = "the default branch", "commit it"
    enabled = False
    try:
        branch = where = gitio.default_branch(root)
        if gitio.has_remote(root):
            # The skills and the Q&A worktree work from origin, not the local branch.
            gitio.fetch_branch(root, branch)
            where, how = f"origin/{branch}", f"commit and push it to {branch}"
        committed = yaml.safe_load(
            gitio.read_at(root, where, root / SWITCH_FILES[0]) or ""
        )
        auto = committed.get("auto") if isinstance(committed, dict) else None
        enabled = isinstance(auto, dict) and auto.get("enabled") is True
    except (gitio.GitError, yaml.YAMLError) as exc:
        logger.debug("committed config not read: %s", exc)
    if not enabled:
        reasons.append(
            f"{SWITCH_FILES[0]} on {where} lacks `auto.enabled: true` -- {how}"
        )
    return reasons


def preflight(root: Path, kb_dir: Path, hub: str = "") -> list[str]:
    """Why `kb auto run` must refuse to start; empty = go. `hub` is the
    `--hub` flag (empty = config)."""
    cfg = load_config(kb_dir)
    reasons: list[str] = []
    if not cfg.auto.enabled:
        reasons.append("auto mode is switched off -- run `kb auto on`")
    if cfg.auto.enabled:
        reasons.extend(_switch_refusals(root))
    if cfg.kind not in ("ba", "dev"):
        reasons.append(
            f"repo kind is '{cfg.kind or 'unset'}', auto mode needs 'ba' or 'dev'"
        )
    if not cfg.intake:
        reasons.append(
            "`intake:` is empty in .kb/config.yaml, so a merged PR would never publish"
        )
    registry, why = registry_or_reason(kb_dir, hub or cfg.hub)
    if registry is None:
        reasons.append(f"the hub registry could not be read: {why}")
        return reasons
    entry = next(
        (
            e
            for k in registry.repos
            if (e := registry.resolve(k)) and e.repo_id == cfg.repo_id
        ),
        None,
    )
    if entry is None:
        reasons.append(f"repo_id '{cfg.repo_id}' is not in the hub registry")
    elif not entry.auto_merge:
        reasons.append(
            f"the hub registry entry for '{cfg.repo_id}' lacks `auto_merge: true`, "
            "so intake would not merge its publish PRs"
        )
    return reasons


def _stop(
    kb_dir: Path,
    state: autostate.AutoState,
    reason: str,
    hint: str = "Fix it, then run `kb auto run` to resume.",
) -> Outcome:
    autostate.save(kb_dir, replace(state, stop_reason=reason))
    logger.error(
        "auto mode stopped on %s: %s. %s", state.task or "no task", reason, hint
    )
    return "stopped"


def _check_done(cfg: KBConfig, hub: HubHandle, qa: qa_mod.QaClient) -> Outcome | None:
    """`done` when every ticket is; `idle`/`waiting` when the hub or Q&A cannot
    answer yet (transient, never a task failure); None to carry on."""
    try:
        stories, unparented, _notes = planstatus.next_from_hub(hub)
    except KbError as exc:
        logger.warning("hub plan not read: %s", exc)
        return "idle"
    ba = cfg.kind == "ba"
    try:
        open_questions = open_question_count(qa, cfg.repo_id) if ba else 0
    except KbError as exc:
        logger.warning("open questions not read: %s", exc)
        return "waiting"
    finished, why = all_done(stories, unparented, ba=ba, open_questions=open_questions)
    if finished:
        logger.info("auto mode finished: %s", why)
        return "done"
    return None


def _answered(
    kb_dir: Path, state: autostate.AutoState, qa: qa_mod.QaClient
) -> tuple[autostate.AutoState, bool]:
    """Clear `waiting_on` once every question is `answered` (not just `waiting`)."""
    try:
        states = qa.states(list(state.waiting_on))
    except KbError as exc:
        logger.warning("question states not read: %s", exc)
        return state, False
    if any(states.get(i) != "answered" for i in state.waiting_on):
        return state, False
    state = replace(state, waiting_on=())
    autostate.save(kb_dir, state)
    return state, True


def _task_for(
    root: Path,
    kb_dir: Path,
    cfg: KBConfig,
    hub: HubHandle,
    state: autostate.AutoState,
) -> Task | None:
    """The stored task (a crash, a retry, an answered question), else a pick."""
    if state.task:
        skill, _, arg = state.task.partition(":")
        return Task(skill, arg)
    try:
        if cfg.kind == "ba":
            return picker.pick_ba(root, kb_dir)
        return picker.pick_dev(hub, root)
    except KbError as exc:
        logger.error("could not pick a task: %s", exc)
        return None


def _settle(
    kb_dir: Path,
    state: autostate.AutoState,
    result: claude.TaskResult,
    backoff: Backoff,
    sleep,
) -> Outcome:
    if result.kind == "usage-limit":
        delay = backoff.next()
        logger.warning("usage limit: %s; retrying in %ds", result.reason, delay)
        sleep(delay)
        return "ran"
    backoff.reset()
    if result.kind == "done":
        done = replace(
            state,
            task=None,
            attempts=0,
            waiting_on=(),
            last_done=state.task,
            same_pick=0,
        )
        autostate.save(kb_dir, done)
        return "ran"
    if result.kind == "blocked-qa":
        autostate.save(kb_dir, replace(state, waiting_on=result.ids))
        logger.info("blocked on questions %s", list(result.ids))
        return "waiting"
    if result.reason.startswith("ci-red"):
        return _stop(kb_dir, replace(state, attempts=MAX_ATTEMPTS), result.reason)
    state = replace(state, attempts=state.attempts + 1)
    autostate.save(kb_dir, state)
    logger.warning(
        "task failed (%d/%d): %s", state.attempts, MAX_ATTEMPTS, result.reason
    )
    if state.attempts >= MAX_ATTEMPTS:
        return _stop(kb_dir, state, result.reason)
    return "ran"


def _repicked(kb_dir: Path, state: autostate.AutoState, task: Task) -> Outcome:
    """The task that just ended `done` is still picked: the hub has not caught up
    with its publish yet. Wait instead of re-running it; stop after a few checks."""
    state = replace(state, same_pick=state.same_pick + 1)
    if state.same_pick >= MAX_SAME_PICK:
        return _stop(
            kb_dir,
            state,
            f"{task.key} ended done but is still picked after {MAX_SAME_PICK} checks",
        )
    autostate.save(kb_dir, state)
    logger.info("%s ended done but is still picked; waiting for the hub", task.key)
    return "idle"


def run_once(
    root: Path,
    kb_dir: Path,
    *,
    cfg: KBConfig,
    hub: HubHandle,
    qa: qa_mod.QaClient,
    run_task=claude.run_task,
    now=time.time,
    sleep=time.sleep,
    backoff: Backoff | None = None,
    qa_thread: QaThread | None = None,
) -> Outcome:
    """One step of the loop. `cfg` is the config as just read (rule 1: a switch
    flipped between tasks stops the loop at the boundary)."""
    state = autostate.load(kb_dir)
    if qa_thread is not None and qa_thread.failed_twice:
        return _stop(kb_dir, state, f"qa thread: {qa_thread.stop_reason}")
    if not cfg.auto.enabled:
        return _stop(
            kb_dir, state, "switched off", "Run `kb auto on`, then `kb auto run`."
        )
    finished = _check_done(cfg, hub, qa)
    if finished is not None:
        return finished
    if state.waiting_on:
        state, ready = _answered(kb_dir, state, qa)
        if not ready:
            logger.info("waiting on questions %s", list(state.waiting_on))
            return "waiting"
    task = _task_for(root, kb_dir, cfg, hub, state)
    if task is None:
        return "idle"
    if task.key == state.last_done:
        return _repicked(kb_dir, state, task)
    if state.task != task.key or state.last_done or state.same_pick:
        state = replace(state, task=task.key, attempts=0, last_done=None, same_pick=0)
        autostate.save(kb_dir, state)
    started = now()
    try:
        result = run_task(
            root,
            claude.prompt_for(task.skill, task.arg, cfg.kind),
            log_dir=autostate.log_dir(kb_dir),
        )
    except Exception as exc:  # noqa: BLE001 -- must count as an attempt, not loop forever
        result = claude.TaskResult("failed", (), f"runner error: {exc}")
    logger.info("%s -> %s in %.0fs", task.key, result.kind, now() - started)
    return _settle(kb_dir, state, result, backoff or Backoff(), sleep)


LOCK_NAME = "run.lock"


def _pid_alive(pid: int) -> bool:
    """Whether `pid` is a live process. `kill(pid, 0)` sends no signal; a
    PermissionError means the process exists but is not ours."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@contextmanager
def run_lock(kb_dir: Path) -> Iterator[Path]:
    """Hold `.kb/auto/run.lock` (this pid) for the loop's lifetime: a second
    `kb auto run` in the same repo refuses with KbError while the first is
    alive, and a lock left by a dead process (crash, power loss) is replaced."""
    path = autostate.log_dir(kb_dir).parent / LOCK_NAME
    try:
        holder = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        holder = None
    if holder is not None and _pid_alive(holder):
        raise KbError(f"kb auto run is already running (pid {holder})")
    path.write_text(f"{os.getpid()}\n", encoding="utf-8", newline="\n")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _resolve_hub(cfg: KBConfig, kb_dir: Path, hub_flag: str = "") -> HubHandle:
    handle = resolve_hub(require_hub(hub_flag or cfg.hub, kb_dir))
    if handle is None:
        raise KbError("hub unreachable and not cached")
    return handle


def resume(kb_dir: Path) -> None:
    """The owner is running again after a stop: same task, fresh attempts."""
    first = autostate.load(kb_dir)
    if first.stop_reason:
        autostate.save(
            kb_dir, replace(first, stop_reason=None, attempts=0, same_pick=0)
        )


def build_deps(
    kb_dir: Path, hub_flag: str = ""
) -> tuple[KBConfig, HubHandle, qa_mod.QaClient]:
    """The real config, hub and Q&A client for one `run_once` (`--once`).
    Raises KbError naming what is missing."""
    qa = qa_mod.from_env()
    cfg = load_config(kb_dir)
    return cfg, _resolve_hub(cfg, kb_dir, hub_flag), qa


def run_loop(
    root: Path, kb_dir: Path, *, sleep=time.sleep, hub_flag: str = "", **deps
) -> int:
    """Repeat `run_once` until done (0) or stopped (2). `deps` (hub, qa,
    run_task, now) default to the real ones; tests inject fakes. `hub_flag` is
    the `--hub` flag (empty = config). A BA repo also runs the Q&A thread (own
    process, own worktree) for the loop's lifetime."""
    resume(kb_dir)
    qa = deps.pop("qa", None) or qa_mod.from_env()
    cfg = load_config(kb_dir)
    qa_thread = None
    if cfg.kind == "ba":
        run_task = deps.get("run_task", claude.run_task)
        qa_thread = QaThread(
            root, kb_dir, qa, cfg.auto.qa_interval, cfg.repo_id, run_task
        )
        qa_thread.start()
    try:
        return _repeat(root, kb_dir, sleep, qa, deps, hub_flag, qa_thread)
    finally:
        if qa_thread is not None:
            qa_thread.stop()


def _repeat(
    root: Path, kb_dir: Path, sleep, qa, deps: dict, hub_flag: str, qa_thread=None
) -> int:
    fixed_hub = deps.pop("hub", None)
    backoff = Backoff()
    while True:
        auto = AutoConfig()
        try:
            cfg = load_config(kb_dir)
            auto = cfg.auto
            hub = fixed_hub or _resolve_hub(cfg, kb_dir, hub_flag)
            outcome = run_once(
                root,
                kb_dir,
                cfg=cfg,
                hub=hub,
                qa=qa,
                sleep=sleep,
                backoff=backoff,
                qa_thread=qa_thread,
                **deps,
            )
        except Exception as exc:  # noqa: BLE001 -- the loop must outlive any one run
            logger.error("auto run failed: %s", " ".join(str(exc).split()))
            outcome = "idle"
        if outcome == "done":
            return EXIT_DONE
        if outcome == "stopped":
            return EXIT_STOPPED
        if outcome == "idle":
            sleep(auto.idle_interval)
        elif outcome == "waiting":
            sleep(auto.qa_interval)
