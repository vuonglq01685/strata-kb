"""The auto-mode loop: `run_once` is the unit, `run_loop` repeats it.

One call picks (or resumes) a task, runs it as a fresh `claude -p` process and
settles the result into `.kb/auto/state.json`. The loop outlives any one failed
run, like `codesync.runner`; only a stop rule, or "every ticket is done", ends it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Literal

from strata_kb import planstatus
from strata_kb.autorun import claude, picker
from strata_kb.autorun import qa as qa_mod
from strata_kb.autorun import state as autostate
from strata_kb.autorun.done import all_done
from strata_kb.autorun.picker import Task
from strata_kb.autorun.switch import registry_or_reason
from strata_kb.config import AutoConfig, KBConfig, load_config, require_hub
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle, resolve_hub

logger = logging.getLogger("strata_kb.autorun.runner")

Outcome = Literal["ran", "idle", "waiting", "stopped", "done"]

MAX_ATTEMPTS = 2  # a task that ends `failed` twice stops the loop
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


def preflight(root: Path, kb_dir: Path) -> list[str]:
    """Why `kb auto run` must refuse to start; empty = go."""
    cfg = load_config(kb_dir)
    reasons: list[str] = []
    if not cfg.auto.enabled:
        reasons.append("auto mode is switched off -- run `kb auto on`")
    if cfg.kind not in ("ba", "dev"):
        reasons.append(
            f"repo kind is '{cfg.kind or 'unset'}', auto mode needs 'ba' or 'dev'"
        )
    if not cfg.intake:
        reasons.append(
            "`intake:` is empty in .kb/config.yaml, so a merged PR would never publish"
        )
    registry, why = registry_or_reason(kb_dir, cfg.hub)
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


def _stop(kb_dir: Path, state: autostate.AutoState, reason: str) -> Outcome:
    autostate.save(kb_dir, replace(state, stop_reason=reason))
    logger.error(
        "auto mode stopped on %s: %s. Fix it, then run `kb auto run` to resume.",
        state.task or "no task",
        reason,
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
        open_questions = len(qa.list("open", repo=cfg.repo_id)) if ba else 0
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
        autostate.save(kb_dir, replace(state, task=None, attempts=0, waiting_on=()))
        return "ran"
    if result.kind == "blocked-qa":
        autostate.save(kb_dir, replace(state, waiting_on=result.ids))
        logger.info("blocked on questions %s", list(result.ids))
        return "waiting"
    if result.reason.startswith("ci-red"):
        return _stop(kb_dir, state, result.reason)
    state = replace(state, attempts=state.attempts + 1)
    autostate.save(kb_dir, state)
    logger.warning(
        "task failed (%d/%d): %s", state.attempts, MAX_ATTEMPTS, result.reason
    )
    if state.attempts >= MAX_ATTEMPTS:
        return _stop(kb_dir, state, result.reason)
    return "ran"


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
) -> Outcome:
    """One step of the loop. `cfg` is the config as just read (rule 1: a switch
    flipped between tasks stops the loop at the boundary)."""
    state = autostate.load(kb_dir)
    if not cfg.auto.enabled:
        return _stop(kb_dir, state, "switched off")
    finished = _check_done(cfg, hub, qa)
    if finished is not None:
        return finished
    if state.waiting_on:
        state, ready = _answered(kb_dir, state, qa)
        if not ready:
            return "waiting"
    task = _task_for(root, kb_dir, cfg, hub, state)
    if task is None:
        return "idle"
    if state.task != task.key:
        state = replace(state, task=task.key, attempts=0)
        autostate.save(kb_dir, state)
    started = now()
    result = run_task(
        root,
        claude.prompt_for(task.skill, task.arg, cfg.kind),
        log_dir=autostate.log_dir(kb_dir),
    )
    logger.info("%s -> %s in %.0fs", task.key, result.kind, now() - started)
    return _settle(kb_dir, state, result, backoff or Backoff(), sleep)


def _resolve_hub(cfg: KBConfig, kb_dir: Path) -> HubHandle:
    handle = resolve_hub(require_hub(cfg.hub, kb_dir))
    if handle is None:
        raise KbError("hub unreachable and not cached")
    return handle


def run_loop(root: Path, kb_dir: Path, *, sleep=time.sleep, **deps) -> int:
    """Repeat `run_once` until done (0) or stopped (2). `deps` (hub, qa,
    run_task, now) default to the real ones; tests inject fakes."""
    first = autostate.load(kb_dir)
    if first.stop_reason:  # the owner is resuming: same task, fresh attempts
        autostate.save(kb_dir, replace(first, stop_reason=None, attempts=0))
    qa = deps.pop("qa", None) or qa_mod.from_env()
    fixed_hub = deps.pop("hub", None)
    backoff = Backoff()
    while True:
        auto = AutoConfig()
        try:
            cfg = load_config(kb_dir)
            auto = cfg.auto
            hub = fixed_hub or _resolve_hub(cfg, kb_dir)
            outcome = run_once(
                root,
                kb_dir,
                cfg=cfg,
                hub=hub,
                qa=qa,
                sleep=sleep,
                backoff=backoff,
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
