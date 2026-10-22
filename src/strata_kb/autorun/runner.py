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

import yaml

from strata_kb import claimclient, cloud, gitio, hubapi
from strata_kb.autorun import claude, picker
from strata_kb.autorun import qa as qa_mod
from strata_kb.autorun import state as autostate
from strata_kb.autorun.claimbeat import ClaimBeat
from strata_kb.autorun.claims import RunnerClaims
from strata_kb.autorun.done import all_done
from strata_kb.autorun.lock import run_lock  # noqa: F401 -- cli uses runner.run_lock
from strata_kb.autorun.picker import Task
from strata_kb.autorun.qathread import PARKED_PREFIX, QaThread, open_question_count
from strata_kb.autorun.switch import cloud_entry_or_reason, registry_or_reason
from strata_kb.claimclient import ClaimRejectedError, ClaimRouteMissing
from strata_kb.config import AutoConfig, KBConfig, load_config, require_hub
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle, resolve_hub

logger = logging.getLogger("strata_kb.autorun.runner")

Outcome = Literal["ran", "idle", "waiting", "stopped", "done"]

MAX_ATTEMPTS = 2  # a task that ends `failed` twice stops the loop
MAX_SAME_PICK = 5  # picks of the task that just ended `done` before it is skipped
BACKOFF_START = 900
BACKOFF_MAX = 3600
EXIT_DONE = 0
AUTO_TASK_ENV = claude.AUTO_TASK_ENV  # set on every task process by run_task
EXIT_STOPPED = 2
CLAIMED_SKILLS = ("dev-implement-ticket", "dev-fix-bug")  # tasks that carry a claim
_BUILD = object()  # run_loop: no `claims` injected, build the real ones


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
    found, auto_merge, why = _registry_facts(kb_dir, cfg, hub)
    if why:
        reasons.append(f"the hub registry could not be read: {why}")
        return reasons
    if not found:
        reasons.append(f"repo_id '{cfg.repo_id}' is not in the hub registry")
    elif not auto_merge:
        reasons.append(
            f"the hub registry entry for '{cfg.repo_id}' lacks `auto_merge: true`, "
            "so intake would not merge its publish PRs"
        )
    return reasons


def _registry_facts(kb_dir: Path, cfg: KBConfig, hub: str) -> tuple[bool, bool, str]:
    """(repo is registered, its `auto_merge`, why the registry was unreadable)."""
    if cloud.is_cloud():
        facts, why = cloud_entry_or_reason(cfg.repo_id)
        return facts is not None, bool(facts and facts["auto_merge"]), why
    registry, why = registry_or_reason(kb_dir, hub or cfg.hub)
    if registry is None:
        return False, False, why
    entry = next(
        (
            e
            for k in registry.repos
            if (e := registry.resolve(k)) and e.repo_id == cfg.repo_id
        ),
        None,
    )
    return entry is not None, bool(entry and entry.auto_merge), ""


def _ticket_of(task_key: str | None) -> str | None:
    """The ticket a stored task key carries a claim for; None for other tasks."""
    skill, _, arg = (task_key or "").partition(":")
    return arg if skill in CLAIMED_SKILLS else None


def _stop(
    kb_dir: Path,
    state: autostate.AutoState,
    reason: str,
    hint: str = "Fix it, then run `kb auto run` to resume.",
    claims: RunnerClaims | None = None,
) -> Outcome:
    ticket = _ticket_of(state.task)
    if claims is not None and ticket:
        claims.stop(ticket, reason)  # stays held until the Dev resumes it
    autostate.save(kb_dir, replace(state, stop_reason=reason))
    logger.error(
        "auto mode stopped on %s: %s. %s", state.task or "no task", reason, hint
    )
    return "stopped"


def _check_done(
    cfg: KBConfig, hub: HubHandle | hubapi.HubApi, qa: qa_mod.QaClient
) -> Outcome | None:
    """`done` when every ticket is; `idle`/`waiting` when the hub or Q&A cannot
    answer yet (transient, never a task failure); None to carry on."""
    try:
        stories, unparented, _notes = picker.plan_next(hub)
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


class _Early(KbError):
    """`run_once` ends now with `outcome`, the claims having decided so. Caught
    in `run_once` before the generic KbError arm; never leaves it."""

    def __init__(self, outcome: Outcome) -> None:
        super().__init__(outcome)
        self.outcome: Outcome = outcome


def _claim_pick(
    root: Path,
    hub: HubHandle | hubapi.HubApi,
    state: autostate.AutoState,
    claims: RunnerClaims,
) -> Task | None:
    """The first candidate this Dev wins the claim on; raises `_Early("idle")`
    when other Devs hold every ready ticket."""
    held = claims.held_by_others(state.task.partition(":")[2] if state.task else None)
    candidates = picker.dev_candidates(hub, root, skip=state.skipped, held=held)
    for task in candidates:
        if task.skill not in CLAIMED_SKILLS or claims.claim(task.arg):
            return task
    if candidates:
        logger.info("every ready ticket is held by another Dev")
        raise _Early("idle")
    return None


def _task_for(
    root: Path,
    kb_dir: Path,
    cfg: KBConfig,
    hub: HubHandle | hubapi.HubApi,
    state: autostate.AutoState,
    claims: RunnerClaims | None = None,
) -> Task | None:
    """The stored task (a crash, a retry, an answered question), else a pick.
    With `claims` (dev) the task's ticket is claimed here. Raises KbError when
    the pick fails, `_Early` when another Dev holds the ticket(s)."""
    if state.task:
        skill, _, arg = state.task.partition(":")
        if claims is not None and skill in CLAIMED_SKILLS and not claims.claim(arg):
            autostate.save(kb_dir, replace(state, task=None, attempts=0))
            logger.info("%s is now held by another Dev; picking again", arg)
            raise _Early("ran")
        return Task(skill, arg)
    if cfg.kind == "ba":
        return picker.pick_ba(root, kb_dir, skip=state.skipped)
    if claims is None:
        return picker.pick_dev(hub, root, skip=state.skipped)
    return _claim_pick(root, hub, state, claims)


def _settle(
    kb_dir: Path,
    state: autostate.AutoState,
    result: claude.TaskResult,
    backoff: Backoff,
    sleep,
    claims: RunnerClaims | None = None,
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
        return _stop(
            kb_dir,
            replace(state, attempts=MAX_ATTEMPTS),
            result.reason,
            claims=claims,
        )
    state = replace(state, attempts=state.attempts + 1)
    autostate.save(kb_dir, state)
    logger.warning(
        "task failed (%d/%d): %s", state.attempts, MAX_ATTEMPTS, result.reason
    )
    if state.attempts >= MAX_ATTEMPTS:
        return _stop(kb_dir, state, result.reason, claims=claims)
    return "ran"


def _repicked(kb_dir: Path, state: autostate.AutoState, task: Task) -> Outcome:
    """The task that just ended `done` is still picked: the hub has not caught up
    with its publish yet. Wait instead of re-running it; after a few checks skip
    it (the agent cannot move it, e.g. a draft only the SA/Dev can unblock) and
    move on to the next task."""
    state = replace(state, same_pick=state.same_pick + 1)
    if state.same_pick >= MAX_SAME_PICK:
        state = replace(
            state,
            last_done=None,
            same_pick=0,
            skipped=(*state.skipped, task.key),
        )
        autostate.save(kb_dir, state)
        logger.warning(
            "%s ended done but is still picked after %d checks; skipping it",
            task.key,
            MAX_SAME_PICK,
        )
        return "ran"
    autostate.save(kb_dir, state)
    logger.info("%s ended done but is still picked; waiting for the hub", task.key)
    return "idle"


def _remember_branch(root: Path) -> str | None:
    """The branch (or, detached, the commit) `root` is on; None when unknown."""
    try:
        branch = gitio.current_branch(root)
        return gitio.head_commit(root) if branch == "HEAD" else branch
    except gitio.GitError:
        return None


def _restore_branch(root: Path, ref: str | None) -> None:
    """Put `root` back on `ref`: a task may leave it on its own branch. A failure
    is a warning, never a stop."""
    if ref is None:
        return
    try:
        branch = gitio.current_branch(root)
        if branch == ref or (branch == "HEAD" and gitio.head_commit(root) == ref):
            return
        gitio.checkout(root, ref)
    except gitio.GitError as exc:
        logger.warning("could not return %s to %s: %s", root, ref, exc)


def run_once(
    root: Path,
    kb_dir: Path,
    *,
    cfg: KBConfig,
    hub: HubHandle | hubapi.HubApi,
    qa: qa_mod.QaClient,
    run_task=claude.run_task,
    now=time.time,
    sleep=time.sleep,
    backoff: Backoff | None = None,
    qa_thread: QaThread | None = None,
    claims: RunnerClaims | None = None,
) -> Outcome:
    """One step of the loop. `cfg` is the config as just read (rule 1: a switch
    flipped between tasks stops the loop at the boundary). `claims` (dev repos
    only) makes the step claim its ticket before working it."""
    if cfg.kind != "dev":
        claims = None
    state = autostate.load(kb_dir)
    if qa_thread is not None and qa_thread.failed_twice:
        return _stop(kb_dir, state, f"qa thread: {qa_thread.stop_reason}")
    if not cfg.auto.enabled:
        return _stop(
            kb_dir,
            state,
            "switched off",
            "Run `kb auto on`, then `kb auto run`.",
            claims=claims,
        )
    finished = _check_done(cfg, hub, qa)
    if finished is not None:
        return finished
    if state.waiting_on:
        _beat_waiting(claims, state)
        state, ready = _answered(kb_dir, state, qa)
        if not ready:
            logger.info("waiting on questions %s", list(state.waiting_on))
            return "waiting"
    try:
        task = _task_for(root, kb_dir, cfg, hub, state, claims)
    except _Early as early:
        return early.outcome
    except (ClaimRouteMissing, ClaimRejectedError) as exc:
        return _stop(kb_dir, state, str(exc))  # no retry can fix either
    except KbError as exc:
        logger.error("could not pick a task: %s", exc)
        return "idle"
    if task is None:
        if qa_thread is not None and qa_thread.only_parked_left():
            parked = sorted(qa_thread.parked)
            return _stop(
                kb_dir,
                state,
                "parked: " + ", ".join(parked),
                "Drafts are on "
                + ", ".join(PARKED_PREFIX + t for t in parked)
                + ". Fix the ticket, then run `kb auto run` to resume.",
            )
        if state.skipped:
            return _stop(
                kb_dir,
                state,
                "every task left was skipped: " + ", ".join(state.skipped),
                "Each ended done but stayed picked. Fix them, then run "
                "`kb auto run` to resume.",
            )
        return "idle"
    if task.key == state.last_done:
        return _repicked(kb_dir, state, task)
    if state.task != task.key or state.last_done or state.same_pick:
        state = replace(state, task=task.key, attempts=0, last_done=None, same_pick=0)
        autostate.save(kb_dir, state)
    ticket = task.arg if task.skill in CLAIMED_SKILLS else None
    beat = None
    if claims is not None and ticket:
        if not claims.begin(ticket):
            return _claim_lost(kb_dir, state, claims, ticket)
        beat = ClaimBeat(claims, cfg.auto.claim_heartbeat)
        beat.start(ticket)
    started = now()
    ref = _remember_branch(root)
    try:
        try:
            result = run_task(
                root,
                claude.prompt_for(task.skill, task.arg, cfg.kind),
                log_dir=autostate.log_dir(kb_dir),
            )
        except Exception as exc:  # noqa: BLE001 -- must count as an attempt, not loop forever
            result = claude.TaskResult("failed", (), f"runner error: {exc}")
    finally:
        _restore_branch(root, ref)
        if beat is not None:
            beat.stop()
    logger.info("%s -> %s in %.0fs", task.key, result.kind, now() - started)
    if claims is not None and ticket:
        if beat is not None and beat.lost:
            return _claim_lost(kb_dir, state, claims, ticket)
        _after_task(claims, ticket, result)
    return _settle(kb_dir, state, result, backoff or Backoff(), sleep, claims)


def _claim_lost(
    kb_dir: Path, state: autostate.AutoState, claims: RunnerClaims, ticket: str
) -> Outcome:
    """Another Dev (or an admin) holds the ticket now: drop it, count no attempt."""
    autostate.save(kb_dir, replace(state, task=None, attempts=0, waiting_on=()))
    logger.warning("claim on %s lost: %s", ticket, claims.lost_reason(ticket))
    return "ran"


def _after_task(claims: RunnerClaims, ticket: str, result: claude.TaskResult) -> None:
    """A finished task is `publishing` (held until its PR merges); one blocked on
    questions is `waiting-qa`. Any other result leaves the phase the task set."""
    phase = {"done": "publishing", "blocked-qa": "waiting-qa"}.get(result.kind)
    if phase is None:
        return
    try:
        claims.phase(ticket, phase)
    except KbError as exc:  # transient: the result must still settle
        logger.warning("claim on %s not moved to %s: %s", ticket, phase, exc)


def _beat_waiting(claims: RunnerClaims | None, state: autostate.AutoState) -> None:
    """Keep the claim alive while the loop waits on questions."""
    ticket = _ticket_of(state.task)
    if claims is not None and ticket:
        claims.beat(ticket)


def _resolve_hub(
    cfg: KBConfig, kb_dir: Path, hub_flag: str = ""
) -> HubHandle | hubapi.HubApi:
    if cloud.is_cloud():  # read the hub live; nothing is cloned
        return hubapi.from_env()
    handle = resolve_hub(require_hub(hub_flag or cfg.hub, kb_dir))
    if handle is None:
        raise KbError("hub unreachable and not cached")
    return handle


def resume(kb_dir: Path) -> None:
    """The owner is running again after a stop: same task, fresh attempts, and
    the skipped tasks get another chance."""
    first = autostate.load(kb_dir)
    if first.stop_reason:
        autostate.save(
            kb_dir,
            replace(first, stop_reason=None, attempts=0, same_pick=0, skipped=()),
        )


def build_deps(
    kb_dir: Path, hub_flag: str = ""
) -> tuple[KBConfig, HubHandle | hubapi.HubApi, qa_mod.QaClient]:
    """The real config, hub and Q&A client for one `run_once` (`--once`).
    Raises KbError naming what is missing."""
    qa = qa_mod.from_env()
    cfg = load_config(kb_dir)
    return cfg, _resolve_hub(cfg, kb_dir, hub_flag), qa


def build_claims(root: Path, kb_dir: Path, cfg: KBConfig) -> RunnerClaims | None:
    """The claim tracker for a dev repo; None for any other kind. Raises KbError
    when the hub env is not set."""
    if cfg.kind != "dev":
        return None
    return RunnerClaims(
        root, kb_dir, claimclient.from_env(), claimclient.holder_name(root)
    )


def _release_on_exit(
    kb_dir: Path, state: autostate.AutoState, claims: RunnerClaims | None
) -> None:
    """The loop ends with a ticket still in hand: free its claim unless it is
    past the work (`publishing`, `review`) or marked `stopped`."""
    ticket = _ticket_of(state.task)
    if claims is not None and ticket:
        claims.release_if_working(ticket, "runner stopped")


def run_loop(
    root: Path, kb_dir: Path, *, sleep=time.sleep, hub_flag: str = "", **deps
) -> int:
    """Repeat `run_once` until done (0) or stopped (2). `deps` (hub, qa,
    run_task, now, claims) default to the real ones; tests inject fakes. `hub_flag` is
    the `--hub` flag (empty = config). A BA repo also runs the Q&A thread (own
    process, own worktree) for the loop's lifetime."""
    resume(kb_dir)
    qa = deps.pop("qa", None) or qa_mod.from_env()
    cfg = load_config(kb_dir)
    claims = deps.pop("claims", _BUILD)
    if claims is _BUILD:
        claims = build_claims(root, kb_dir, cfg)
    deps["claims"] = claims
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
        _release_on_exit(kb_dir, autostate.load(kb_dir), claims)


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
