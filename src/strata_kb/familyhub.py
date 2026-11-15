"""Hub-backed extras of `kb ticket lint` for parent stories and children.

`lint` is `ticketlint.lint` plus checks that need the hub's other documents
(it cannot live in `ticketlint`: `planstatus` imports it through plan-ingest).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import ValidationError

from strata_kb import planrev, planstatus, ticket, ticketfetch, ticketlint
from strata_kb.doctor import Issue
from strata_kb.errors import KbError
from strata_kb.federation import load_federation
from strata_kb.hub import HubHandle
from strata_kb.lintcore import LintReport

SKIP_NOTE = "cross-repo id check skipped — pass repo_id"
_CONFIG_READ_ERRORS = (yaml.YAMLError, ValidationError, ValueError, OSError)
CLAIM_NOTE = "claim check skipped (needs the hub API)"


def _err(message: str) -> Issue:
    return Issue("error", message)


def _on_hub_as_parent_bug(hub: HubHandle, ticket_id: str) -> bool:
    """The hub already publishes `ticket_id` as a parent bug."""
    try:
        _, doc, l3 = ticketfetch.find(hub, ticket_id)
        section = ticketfetch.read_section(l3, doc, ticket_id)
    except ticketfetch.TicketFetchError:  # includes TicketNotOnHub
        return False
    return ticket.ticket_kind(ticketfetch.source_text(section)) == "parent bug"


def hub_issues(
    hub: HubHandle, ticket_id: str, own_repo: str | None, *, parent: bool
) -> list[Issue]:
    """Hub-backed checks: the id is not published by another BA repo
    (skipped when `own_repo` is None); a parent's id is not already done in
    a dev repo."""
    holders = (
        sorted(
            {
                fed.meta.repo_id
                for fed, manifest in planstatus.plan_docs(hub)
                if fed.meta.repo_id != own_repo
                and any(s.id == ticket_id for s in manifest.sections)
            }
        )
        if own_repo is not None
        else []
    )
    issues = [
        _err(f"ticket id {ticket_id} is already published by {r}") for r in holders
    ]
    # a parent bug's own fix lands in a -svc history after the parent is
    # published; only a newly made parent must not be done already
    if parent and not _on_hub_as_parent_bug(hub, ticket_id):
        cache: dict[str, set[str] | None] = {}
        if any(
            ticket_id in (planstatus.done_for(hub, fed.meta.repo_id, cache) or ())
            for fed in load_federation(hub.federation_dir)
        ):
            issues.append(
                _err(
                    f"{ticket_id} is already implemented — a done ticket "
                    "cannot become a parent story"
                )
            )
    return issues


def closed_story_issues(
    ticket_id: str, parent_id: str, local_revision: int, hub: HubHandle | None
) -> list[Issue]:
    """Refuse an amend (local revision above the published one) or a new child
    when the ticket's story is `closed` on the hub; no hub -> a warning."""
    unchecked = [Issue("warning", "story status not checked (hub unreachable)")]
    if hub is None:
        return unchecked
    story = parent_id or ticket_id
    try:
        repos, _ = planstatus.hub_plans(hub)
        rows = [s for r in repos for m in r.missions for s in m.stories]
        rows += [s for r in repos for s in r.unparented]
        if not any(s.us_id == story and s.test_status == "closed" for s in rows):
            return []
        try:
            published = planrev.parse_revision(ticketfetch.render(hub, ticket_id)) or 1
        except ticketfetch.TicketNotOnHub:
            published = None
    except KbError:
        return unchecked
    if published is None or local_revision > published:
        return [Issue("error", "story is closed — write a new story")]
    return []


def lint(
    text: str,
    hub: HubHandle | None,
    *,
    ticket_id: str | None = None,
    path: Path | None = None,
    own_repo: Callable[[], str | None] | None = None,
    **kwargs,
) -> LintReport:
    """`ticketlint.lint`, plus for a parent story or a child ticket: the id is
    not published by another BA repo, and a parent's id is not already done."""
    report = ticketlint.lint(text, hub, ticket_id=ticket_id, path=path, **kwargs)
    is_parent = (ticket.ticket_kind(text) or "").startswith("parent")
    tid = ticket_id or (path.stem if path else None)
    if hub is not None and tid and ticket.ticket_type(text) == "story":
        pin = ticket.parent_story_pin(text)
        report.issues += closed_story_issues(
            tid, pin[0] if pin else "", planrev.parse_revision(text) or 1, hub
        )
    if (
        hub is None
        or tid is None
        or not (is_parent or ticket.parent_story_pin(text) is not None)
    ):
        return report
    repo: str | None = None
    if own_repo is not None:
        try:
            repo = own_repo()
        except _CONFIG_READ_ERRORS as exc:
            report.notes.append(
                f"cross-repo id check skipped — config unreadable: {exc}"
            )
    if repo is None and own_repo is None:
        report.notes.append(SKIP_NOTE)
    report.issues += hub_issues(hub, tid, repo, parent=is_parent)
    if is_parent:
        report.notes.append(CLAIM_NOTE)
    return report


def folder_loader(path: Path) -> Callable[[str], str | None]:
    """`load_ticket` for a file on disk: a sibling `<id>.md` in its folder."""

    def load(ticket_id: str) -> str | None:
        try:
            return (path.parent / f"{ticket_id}.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    return load


def duplicate_stem(path: Path) -> Issue | None:
    """An error when another file under the same `tickets/` root has this
    file's stem (the ticket id); None when unique or outside a `tickets/`."""
    root = next((a for a in path.resolve().parents if a.name == "tickets"), None)
    if root is None:
        return None
    other = next(
        (p for p in sorted(root.rglob(path.name)) if p != path.resolve()), None
    )
    if other is None:
        return None
    return _err(f"duplicate ticket id {path.stem}: {path}, {other}")
