"""publishwatch — the BA loop's check on its own `kb-publish` runs (#140).

A merged ticket reaches the hub only through `kb-publish.yml`. When that run
fails, waiting on the hub can never help: the runner re-runs it once, and a
second failure stops the loop with the error, instead of reading as a hub
that has not caught up and skipping the story.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from strata_kb import ghio
from strata_kb.autorun import state as autostate

logger = logging.getLogger("strata_kb.autorun.publishwatch")

WORKFLOW = "kb-publish.yml"
# Completed without publishing. `cancelled` counts: kb-publish never cancels
# itself (its concurrency group does not cancel in progress).
FAILED = frozenset(
    {"failure", "timed_out", "startup_failure", "cancelled", "action_required", "stale"}
)
IGNORED = frozenset({"skipped", "neutral"})  # e.g. a dispatch on a branch, not a tag
LOOKBACK = 5
MAX_DETAIL = 300
_ERROR_LINE = re.compile(r"error|fatal|rejected", re.IGNORECASE)
_LOG_PREFIX = re.compile(r"^[^\t]*\t[^\t]*\t(\S+Z )?")  # "<job>\t<step>\t<stamp> "


@dataclass(frozen=True)
class PublishRun:
    run_id: int
    attempt: int
    status: str
    conclusion: str
    url: str
    head: str

    @property
    def key(self) -> str:
        return f"{self.run_id}:{self.attempt}"


def latest(root: Path) -> PublishRun | None:
    """The newest `kb-publish.yml` run that did not skip its job; None when
    there is none."""
    data = ghio.run_json(
        root,
        "run",
        "list",
        "--workflow",
        WORKFLOW,
        "--limit",
        str(LOOKBACK),
        "--json",
        "databaseId,attempt,status,conclusion,url,headBranch",
    )
    if not isinstance(data, list):
        raise ValueError(f"not a list: {str(data)[:80]}")
    r = next(
        (
            r
            for r in data
            if not (r.get("status") == "completed" and r.get("conclusion") in IGNORED)
        ),
        None,
    )
    if r is None:
        return None
    return PublishRun(
        int(r["databaseId"]),
        int(r.get("attempt") or 1),
        str(r.get("status") or ""),
        str(r.get("conclusion") or ""),
        str(r.get("url") or ""),
        str(r.get("headBranch") or ""),
    )


def _failed_step(root: Path, run: PublishRun) -> str:
    data = ghio.run_json(root, "run", "view", str(run.run_id), "--json", "jobs")
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    for job in jobs:
        for step in job.get("steps", []):
            if step.get("conclusion") == "failure":
                return f"{job.get('name', '?')} / {step.get('name', '?')}"
    return ""


def _error_line(root: Path, run: PublishRun) -> str:
    log = ghio.run_text(root, "run", "view", str(run.run_id), "--log-failed")
    lines = [_LOG_PREFIX.sub("", ln).strip() for ln in log.splitlines()]
    hits = [ln for ln in lines if _ERROR_LINE.search(ln) and "exit code" not in ln]
    return hits[0][:MAX_DETAIL] if hits else ""


def detail(root: Path, run: PublishRun) -> str:
    """`<job> / <step>: <first error line>` of a failed run; best effort."""
    try:
        step, error = _failed_step(root, run), _error_line(root, run)
    except ghio.GHError as exc:
        return f"details not read ({exc})"
    return ": ".join(p for p in (step, error) if p) or "no failed step reported"


def check(
    root: Path, kb_dir: Path, state: autostate.AutoState
) -> Literal["idle", "stopped"] | None:
    """None: carry on (no gh, no run, still running, or green). "idle": the
    failed run was just re-run; check again next round. "stopped": the re-run
    failed or never started, `stop_reason` says why."""
    if not ghio.gh_available():
        return None
    try:
        run = latest(root)
    except (ghio.GHError, KeyError, TypeError, ValueError, AttributeError) as exc:
        logger.warning("kb-publish runs not read: %s", exc)
        return None
    if run is None or run.status != "completed":
        return None
    if run.conclusion == "success":
        if state.publish_retry:
            autostate.save(kb_dir, replace(state, publish_retry=None))
        return None
    if run.conclusion not in FAILED:
        return None
    why = f"{run.head}: {detail(root, run)} ({run.url})"
    retried = (state.publish_retry or "").partition(":")[0]
    if retried != str(run.run_id):  # each run gets its own one re-run
        logger.error("kb-publish failed for %s; re-running it once", why)
        try:
            ghio.run_text(root, "run", "rerun", str(run.run_id), "--failed")
        except ghio.GHError as exc:
            return _stop(kb_dir, state, f"publish failed for {why}; re-run: {exc}")
        autostate.save(kb_dir, replace(state, publish_retry=run.key))
        return "idle"
    if state.publish_retry == run.key:
        return _stop(
            kb_dir, state, f"publish failed for {why}; the re-run never started"
        )
    return _stop(kb_dir, state, f"publish failed for {why}")


def _stop(kb_dir: Path, state: autostate.AutoState, reason: str) -> Literal["stopped"]:
    autostate.save(kb_dir, replace(state, stop_reason=reason))
    logger.error(
        "auto mode stopped: %s. Fix the publish (a green kb-publish run), "
        "then run `kb auto run` to resume.",
        reason,
    )
    return "stopped"
