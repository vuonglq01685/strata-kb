"""Which skill the auto-mode loop runs next, for the BA and Dev repos."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from strata_kb import planstatus
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle

MAX_STDERR = 300
TEST_WORKFLOW_MARK = "kb-test"
# Ticket-level reasons (DoR, dependencies): only the others block the mission.
_TICKET_REASON = re.compile(r"DoR |no Definition of Ready|US .* (not done|unknown)")


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
    )
    if proc.returncode != 0:
        raise KbError(f"kb mission next failed: {proc.stderr[:MAX_STDERR]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise KbError(
            f"kb mission next gave no JSON: {proc.stderr[:MAX_STDERR]}"
        ) from exc


def pick_ba(root: Path, kb_dir: Path, run=subprocess.run) -> Task | None:
    """Mission blocker, then a draft ticket to amend, then the next ticket to
    write. First match in mission order within each rule."""
    data = _mission_next(root, run)
    stories = data["stories"]
    for s in stories:
        if any(not _TICKET_REASON.match(r) for r in s["reasons"]):
            return Task("ba-mission-plan", f"--amend {s['mission_id']}")
    for s in stories:
        if s["status"] == "draft":
            return Task("ba-ticket-author", f"--amend {s['us_id']}")
    if data["next"]:
        return Task("ba-ticket-author", data["next"])
    return None


def _has_test_workflow(root: Path) -> bool:
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return False
    if (workflows / "kb-test.yml").is_file():
        return True
    return any(
        TEST_WORKFLOW_MARK in f.read_text(encoding="utf-8", errors="replace")
        for f in workflows.iterdir()
        if f.suffix in (".yml", ".yaml")
    )


def pick_dev(hub: HubHandle, root: Path) -> Task | None:
    """CI workflow first, then a ready bug, then the first ready story."""
    if not _has_test_workflow(root):
        return Task("dev-test-workflow", "")
    stories, unparented, _notes = planstatus.next_from_hub(hub)
    for u in unparented:
        if u.status == "ready" and u.us_id.startswith("BUG-"):
            return Task("dev-fix-bug", u.us_id)
    for s in stories:
        if s.status == "ready":
            return Task("dev-implement-ticket", s.us_id)
    return None
