"""Which skill the auto-mode loop runs next, for the BA and Dev repos."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from strata_kb import gitio, planstatus, strategyhub, teststrategy
from strata_kb.bugcandidates import Candidate
from strata_kb.claimclient import ClaimClient, LocalClaims
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from strata_kb.hubapi import HubApi
from strata_kb.missionnext import StoryStatus

logger = logging.getLogger(__name__)
MAX_STDERR = 300
PLAN_WORKTREE = Path("auto") / "worktrees" / "plan"  # under kb_dir
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


def _plan_tree(root: Path, kb_dir: Path) -> Path:
    """Where the BA plan is read: a detached worktree of origin/<default>, just
    fetched. `root`'s own branch never gets a merged ticket (a cloud session
    branch, a local default branch nobody pulls), so it reads stale (#140).
    `root` itself when there is no remote."""
    if not gitio.has_remote(root):
        return root
    gitio.default_branch(root)  # sets origin/HEAD from the remote when missing
    # origin/HEAD only: default_branch falls back to the checked-out branch,
    # which on cloud is the very session branch this read must avoid.
    ref = gitio.origin_head_ref(root)
    gitio.fetch_branch(root, ref.partition("/")[2])
    tree = kb_dir.resolve() / PLAN_WORKTREE
    gitio.worktree_remove(root, tree)
    gitio.worktree_prune(root)
    gitio.worktree_add_detached(root, tree, ref)
    return tree


def _mission_next(root: Path, tree: Path, run) -> dict:
    # cwd stays root: a relative hub path in the config resolves from there.
    proc = run(
        ["kb", "mission", "next", "--json", "--missions-dir", str(tree / "missions")],
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


def _ba_tasks(data: dict, candidates: Sequence[Candidate] = ()) -> Iterator[Task]:
    stories = data["stories"]
    rows = (*stories, *data.get("unparented", ()))
    # an unwritten child is drafted like any story (phase 3)
    for s in stories:
        if any(_MISSION_BLOCKER.match(r) for r in s["reasons"]):
            yield Task("ba-mission-plan", f"--amend {s['mission_id']}")
    for c in candidates:
        yield Task("ba-bug-report", f"--from-report {c.story} R{c.round} {c.rd_id}")
    # bugs have their own skill (ba-bug-report); the story author must not touch them
    rows = tuple(s for s in rows if not s["us_id"].startswith("BUG-"))
    for s in rows:
        if s["status"] == "draft" and not s.get("is_parent"):
            yield Task("ba-ticket-author", f"--amend {s['us_id']}")
    if data["next"]:
        yield Task("ba-ticket-author", data["next"])
    # past a skipped `next`, the later stories still to draft
    for s in rows:
        if s["status"] == "to-draft" and not s.get("is_parent"):
            yield Task("ba-ticket-author", s["us_id"])


def _first(tasks: Iterable[Task], skip: Collection[str]) -> Task | None:
    return next((t for t in tasks if t.key not in skip), None)


def pick_ba(
    root: Path,
    kb_dir: Path,
    run=subprocess.run,
    skip: Collection[str] = (),
    candidates: Sequence[Candidate] = (),
) -> Task | None:
    """Mission blocker, then a bug to draft from a regression candidate, then a
    draft ticket to amend, then the next ticket to write. First match in mission order within each rule whose key is not in
    `skip`. The plan is read from origin/<default> (`_plan_tree`)."""
    try:
        tree = _plan_tree(root, kb_dir)
    except gitio.GitError as exc:
        raise KbError(f"plan not read from the default branch: {exc}") from exc
    try:
        data = _mission_next(root, tree, run)
    finally:
        if tree != root:  # a snapshot `kb publish` would mirror it from .kb/
            gitio.worktree_remove(root, tree)
    try:
        return _first(_ba_tasks(data, candidates), skip)
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
    for_repo: str | None = None,
    require_target: bool = False,
    repo: str | None = None,
) -> tuple[list[StoryStatus], list[StoryStatus], list[str]]:
    """The hub's plan: over its API on cloud, off the cloned hub otherwise.
    With `for_repo`, only the items targeting that Dev repo; with `repo`, only
    that repo's plan."""
    if isinstance(hub, HubApi):
        return hub.plan_next(
            repo=repo, for_repo=for_repo, require_target=require_target
        )
    return planstatus.next_from_hub(hub, repo=repo, for_repo=for_repo)


def runnable_here(t: StoryStatus, repo_id: str) -> bool:
    """`t` is a ticket this Dev may build (dependencies aside): a ready row routed
    here or untargeted, or a parent bug's own fix routed here."""
    if t.own_fix_ready:
        return t.target_repo == repo_id
    return not t.is_parent and t.status == "ready" and t.target_repo in (None, repo_id)


def reopened_here(t: StoryStatus, repo_id: str) -> bool:
    """`t` failed a test round (still `done`) and this Dev owns the fix."""
    return (
        t.status == "done"
        and t.test_status == "reopened"
        and not t.is_parent
        and t.target_repo in (repo_id, None)
    )


def _dev_tasks(stories, unparented, repo_id: str) -> Iterator[Task]:
    """Reopened tickets routed here (dependencies ignored), then ready tickets
    routed to `repo_id` whose dependencies are done. `done`
    spans every repo's rows: a dependency may be built elsewhere. A ready row
    with no target only exists on a hub without dev repos (no routing): every
    runner may take it."""
    done = {t.us_id for t in (*stories, *unparented) if t.status == "done"}

    def ready(t: StoryStatus) -> bool:
        return runnable_here(t, repo_id) and all(d in done for d in t.depends_on)

    # reopened first, dependencies ignored: they were done when it first passed
    rows = (*stories, *unparented)
    for t in rows:
        if reopened_here(t, repo_id) and not t.us_id.startswith("BUG-"):
            yield Task("dev-implement-ticket", t.us_id)
    for t in rows:
        if reopened_here(t, repo_id) and t.us_id.startswith("BUG-"):
            yield Task("dev-fix-bug", t.us_id)
    for u in unparented:
        if ready(u) and u.us_id.startswith("BUG-"):
            yield Task("dev-fix-bug", u.us_id)
    for u in unparented:
        if ready(u) and not u.us_id.startswith("BUG-"):
            yield Task("dev-implement-ticket", u.us_id)
    for s in stories:
        if ready(s):
            yield Task("dev-implement-ticket", s.us_id)


def dev_candidates(
    hub: HubHandle | HubApi,
    root: Path,
    repo_id: str,
    skip: Collection[str] = (),
    held: Collection[str] = (),
) -> list[Task]:
    """Every task the Dev may take, in pick order: the CI workflow first, then
    reopened tickets (stories, then bugs), then a ready bug, a ready unparented
    ticket, each ready story, all routed to `repo_id` (ready ones with
    dependencies done). Tasks whose key is in `skip`, or whose ticket is in
    `held` (claimed by another Dev), are left out."""
    if not _has_test_workflow(root):
        tasks: Iterable[Task] = [Task("dev-test-workflow", "")]
    else:
        stories, unparented, _notes = plan_next(hub, require_target=True)
        tasks = _dev_tasks(stories, unparented, repo_id)
    return [t for t in tasks if t.key not in skip and t.arg not in held]


def pick_dev(
    hub: HubHandle | HubApi,
    root: Path,
    repo_id: str,
    skip: Collection[str] = (),
    held: Collection[str] = (),
) -> Task | None:
    """The first of `dev_candidates`."""
    return next(iter(dev_candidates(hub, root, repo_id, skip, held)), None)


STRATEGY_FILE = Path("docs") / "test-strategy.md"
_AMEND_CODES = frozenset({"broken-target", "pin-moved", "kb-context", "coverage"})
_NOT_DEPLOYED = 4  # `kb test-env deployed` exit: the story is not on the env yet


@dataclass(frozen=True)
class TesterPick:
    """`cooled`: stories the deploy check reported not deployed in this pick,
    for the runner to park in `waiting`."""

    task: Task | None
    cause: Literal["task", "nothing", "waiting"]
    cooled: tuple[str, ...] = ()


def _strategy_text(root: Path) -> str | None:
    """`docs/test-strategy.md` from a just-fetched origin/<default>; the working
    tree when there is no remote. None when the file is missing."""
    root = root.resolve()
    path = root / STRATEGY_FILE
    if not gitio.has_remote(root):
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as exc:
            raise KbError(f"{path} not read: {exc}") from exc
    try:
        gitio.default_branch(root)  # sets origin/HEAD from the remote when missing
        ref = gitio.origin_head_ref(root)
        gitio.fetch_branch(root, ref.partition("/")[2])
        return gitio.read_at(root, ref, path)
    except gitio.GitError as exc:
        raise KbError(f"test strategy not read from the default branch: {exc}") from exc


def _needs_amend(
    text: str, hub: HubHandle, strategy: teststrategy.Strategy | None
) -> bool:
    if strategy is None:
        return False
    try:
        plan = (
            strategyhub.plan_view(hub, strategy.plan)
            if strategy.plan
            else strategyhub.plan_view(hub, None, all_plans=True)
        )
        found = strategyhub.strategy_findings(text, strategy, plan, hub)
    except KbError as exc:  # incl. PlanNotOnHub
        logger.warning("test strategy not checked for amend: %s", exc)
        return False
    return any(f.code in _AMEND_CODES for f in found)


def _parse_strategy(text: str | None) -> teststrategy.Strategy | None:
    if text is None:
        return None
    try:
        return teststrategy.parse(text)
    except ValueError as exc:
        logger.warning("test strategy does not parse: %s", exc)
        return None


def _resume(kb_dir: Path, claims: list[dict]) -> Task | None:
    local = LocalClaims(kb_dir)
    for c in claims:
        saved = local.get(c["ticket"])
        if (
            saved
            and saved[0] == c["id"]
            and c.get("state") != "stopped"
            and c.get("phase") not in ("publishing", "review")
        ):
            return Task("tester-test-story", c["ticket"])
    return None


def pick_tester(
    root: Path,
    kb_dir: Path,
    hub: HubHandle,
    *,
    claims_client: ClaimClient,
    skip: Collection[str] = (),
    waiting: frozenset[str] = frozenset(),
    run=subprocess.run,
) -> TesterPick:
    """Our own working claim, then a strategy amend, then the next testable
    story that is deployed and not held by another Tester. A hub claim read
    error raises (the runner goes idle)."""
    claims = claims_client.held(role="tester")
    if task := _resume(kb_dir, claims):
        return TesterPick(task, "task")
    local = LocalClaims(kb_dir)
    other = {
        c["ticket"]
        for c in claims
        if (saved := local.get(c["ticket"])) is None or saved[0] != c["id"]
    }
    text = _strategy_text(root)
    strategy = _parse_strategy(text)
    amend = text is not None and _needs_amend(text, hub, strategy)
    amend_task = Task("tester-strategy", "--amend")
    if amend and amend_task.key not in skip:
        return TesterPick(amend_task, "task")
    try:
        stories = [p.story for p in strategyhub.next_stories(hub, strategy)]
    except strategyhub.PlanNotOnHub as exc:
        logger.warning("test order not read: %s", exc)
        stories = []
    cooled: list[str] = []
    for story in stories:
        if Task("tester-test-story", story).key in skip or story in waiting:
            continue
        if story in other:
            continue
        if not planstatus.safe_name(story):
            logger.warning("story id %r is not a safe name, skipped", story)
            continue
        proc = run(
            ["kb", "test-env", "deployed", story],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proc.returncode == 0:
            return TesterPick(Task("tester-test-story", story), "task", tuple(cooled))
        if proc.returncode != _NOT_DEPLOYED:
            raise KbError(
                f"kb test-env deployed {story} failed: {proc.stderr[:MAX_STDERR]}"
            )
        cooled.append(story)
    cause = "waiting" if stories or amend else "nothing"
    return TesterPick(None, cause, tuple(cooled))
