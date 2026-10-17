"""Which skill the auto-mode loop runs next, for the BA and Dev repos."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from strata_kb import planstatus
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from strata_kb.hubapi import HubApi
from strata_kb.missionnext import StoryStatus

MAX_STDERR = 300
TEST_WORKFLOW_MARK = "kb-test"
# Mission blockers: an open D-row or question. Every other reason (DoR,
# dependencies, a demoted ticket) is the ticket's own to fix.
_MISSION_BLOCKER = re.compile(r"D\d+ |Q\d+ open|open question '")


@dataclass(frozen=True)
class Task:
    skill: str
    arg: str

    @property
    def key(self) -> str:
        return f"{self.skill}:{self.arg}"


def _mission_next(root: Path, run) -> dict:
    proc = run(
        ["kb", "mission", "next", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise KbError(f"kb mission next failed: {proc.stderr[:MAX_STDERR]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise KbError(
            f"kb mission next gave no JSON: {proc.stdout[:MAX_STDERR]!r}"
        ) from exc


def _ba_tasks(data: dict) -> Iterator[Task]:
    stories = data["stories"]
    for s in stories:
        if any(_MISSION_BLOCKER.match(r) for r in s["reasons"]):
            yield Task("ba-mission-plan", f"--amend {s['mission_id']}")
    for s in stories:
        if s["status"] == "draft":
            yield Task("ba-ticket-author", f"--amend {s['us_id']}")
    if data["next"]:
        yield Task("ba-ticket-author", data["next"])
    # past a skipped `next`, the later stories still to draft
    for s in stories:
        if s["status"] == "to-draft":
            yield Task("ba-ticket-author", s["us_id"])


def _first(tasks: Iterable[Task], skip: Collection[str]) -> Task | None:
    return next((t for t in tasks if t.key not in skip), None)


def pick_ba(
    root: Path, kb_dir: Path, run=subprocess.run, skip: Collection[str] = ()
) -> Task | None:
    """Mission blocker, then a draft ticket to amend, then the next ticket to
    write. First match in mission order within each rule whose key is not in
    `skip`."""
    data = _mission_next(root, run)
    try:
        return _first(_ba_tasks(data), skip)
    except (KeyError, TypeError) as exc:
        raise KbError(
            f"kb mission next gave unexpected JSON: {str(data)[:MAX_STDERR]!r}"
        ) from exc


def _has_test_workflow(root: Path) -> bool:
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return False
    return any(
        TEST_WORKFLOW_MARK in f.read_text(encoding="utf-8", errors="replace")
        for f in workflows.iterdir()
        if f.is_file() and f.suffix in (".yml", ".yaml")
    )


def plan_next(
    hub: HubHandle | HubApi,
) -> tuple[list[StoryStatus], list[StoryStatus], list[str]]:
    """The hub's plan: over its API on cloud, off the cloned hub otherwise."""
    if isinstance(hub, HubApi):
        return hub.plan_next()
    return planstatus.next_from_hub(hub)


def _dev_tasks(stories, unparented) -> Iterator[Task]:
    for u in unparented:
        if u.status == "ready" and u.us_id.startswith("BUG-"):
            yield Task("dev-fix-bug", u.us_id)
    for u in unparented:
        if u.status == "ready" and not u.us_id.startswith("BUG-"):
            yield Task("dev-implement-ticket", u.us_id)
    done = {t.us_id for t in (*stories, *unparented) if t.status == "done"}
    for s in stories:
        if s.status == "ready" and all(d in done for d in s.depends_on):
            yield Task("dev-implement-ticket", s.us_id)


def pick_dev(
    hub: HubHandle | HubApi, root: Path, skip: Collection[str] = ()
) -> Task | None:
    """CI workflow first, then a ready bug, then a ready unparented ticket,
    then the first ready story whose dependencies are done. Tasks whose key
    is in `skip` are passed over."""
    if not _has_test_workflow(root):
        return _first([Task("dev-test-workflow", "")], skip)
    stories, unparented, _notes = plan_next(hub)
    return _first(_dev_tasks(stories, unparented), skip)
