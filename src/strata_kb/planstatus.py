"""Plan status on the hub — read-only, derived, nothing stored.

The `M-<slug>` sections of every `<ba-repo>-plan` document are the missions;
a `M-<slug>-US<n>` section is a published ticket (its Definition of Ready
passed); `done` is the story id in a `hist.*` row of the Dev repo's `-svc`,
found from the mission's `Grounded on:` line exactly as `kb mission next`
does. The status rules are `missionnext.statuses`: the hub cannot see a
`draft`, since such a ticket is not published.

Feeds `kb mission next --from-hub` and the web UI's Plans menu.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

import yaml
from pydantic import ValidationError

from strata_kb import missionnext, models, ticketcheck
from strata_kb.federation import FederatedRepo, load_federation
from strata_kb.hub import HubHandle
from strata_kb.mdutils import slice_section
from strata_kb.planingest import TICKETS_GROUP, promote_headings
from strata_kb.ticketfetch import _safe

logger = logging.getLogger("strata_kb.planstatus")

# One ticket section = ticked Definition of Ready (plan-ingest only publishes those).
_PUBLISHED = (1, 1)


def is_plan(doc_id: str) -> bool:
    """A `<ba-repo>-plan` document: shown under Plans, never under Documents."""
    return doc_id.endswith("-plan")


@dataclass(frozen=True)
class PlanMission:
    repo: str
    doc: str
    mission_id: str
    title: str
    summary: str
    stories: list[missionnext.StoryStatus]
    tickets: frozenset[str] = field(default_factory=frozenset)  # published ticket ids

    @property
    def counts(self) -> Counter[str]:
        return Counter(s.status for s in self.stories)


@dataclass(frozen=True)
class PlanRepo:
    repo: str
    doc: str
    missions: list[PlanMission]
    unparented: list[
        tuple[str, str]
    ]  # (section id, title) of tickets without a mission


@dataclass(frozen=True)
class PlanTicket:
    title: str
    markdown: str  # the ticket L3, headings promoted back to `##`


def _plan_docs(
    hub: HubHandle, repo: str | None = None
) -> Iterator[tuple[FederatedRepo, models.Manifest]]:
    for fed in load_federation(hub.federation_dir):
        if repo is not None and fed.meta.repo_id != repo:
            continue
        for path in sorted(fed.kb_dir.glob("*-plan/_manifest.yaml")):
            try:
                yield fed, models.load_yaml_model(path, models.Manifest)
            except (
                yaml.YAMLError,
                OSError,
                UnicodeDecodeError,
                ValidationError,
            ) as exc:
                logger.warning("skipping plan manifest %s: %s", path, exc)


def _l3_section(fed: FederatedRepo, doc: str, entry: models.SectionEntry) -> str | None:
    """The `## <id> <title>` slice of a plan section's L3 group file; None
    when the group name is not a plain file name or the file does not hold it."""
    if not _safe(entry.file):
        return None
    try:
        l3 = (fed.kb_dir / doc / f"{entry.file}.raw.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return slice_section(l3, entry.id)


def _restore(title: str, section: str) -> str:
    """Source shape of a published mission or ticket: the H1 plan-ingest
    dropped, then the L3 body with its headings promoted back."""
    body = section.partition("\n")[2].strip("\n")
    return f"# {title}\n\n{promote_headings(body)}\n"


def _done_ids(
    hub: HubHandle, plan_doc: str, grounded: tuple[str | None, str] | None
) -> tuple[set[str] | None, str | None]:
    """(done ids, note). Same lookup and wording as `kb mission next`."""
    if grounded is None:
        return None, f"{plan_doc}: done: unknown (no 'Grounded on:' line in a mission)"
    rid, code_doc = grounded
    svc = missionnext.svc_doc_id(code_doc)
    try:
        doc = ticketcheck.load_from_hub(hub.federation_dir, rid, svc)
    except ticketcheck.DocLoadError as exc:
        return None, f"{plan_doc}: done: unknown ({exc})"
    if doc is None:
        return None, (
            f"{plan_doc}: done: unknown ({svc} not published — the Dev repo has "
            "not run dev-code-seed, or CI has not published yet)"
        )
    return missionnext.done_ids_from_history(doc.read_group("history")), None


def _plan_repo(
    hub: HubHandle, fed: FederatedRepo, manifest: models.Manifest, notes: list[str]
) -> PlanRepo:
    texts: dict[str, str] = {}  # mission id -> restored markdown
    titles: dict[str, tuple[str, str]] = {}  # mission id -> (title, summary)
    drafted: dict[str, tuple[int, int]] = {}
    tickets_of: dict[str, set[str]] = {}
    unparented: list[tuple[str, str]] = []
    for s in manifest.sections:
        if s.id == s.file:  # the mission is the section named like its group file
            section = _l3_section(fed, manifest.id, s)
            if section is not None:
                texts[s.id] = _restore(s.title, section)
                titles[s.id] = (s.title, s.summary)
            continue
        drafted[s.id] = _PUBLISHED
        if s.file == TICKETS_GROUP:
            unparented.append((s.id, s.title))
        else:
            tickets_of.setdefault(s.file, set()).add(s.id)

    parsed = [missionnext.parse_mission(t) for t in texts.values()]
    done, note = _done_ids(
        hub,
        manifest.id,
        next((g for g in map(missionnext.grounded_doc, texts.values()) if g), None),
    )
    if note:
        notes.append(note)
    results = missionnext.statuses(parsed, drafted, done)
    missions = [
        PlanMission(
            repo=fed.meta.repo_id,
            doc=manifest.id,
            mission_id=mid,
            title=titles[mid][0],
            summary=titles[mid][1],
            stories=[r for r in results if r.mission_id == (p[0] or mid)],
            tickets=frozenset(tickets_of.get(mid, ())),
        )
        for mid, p in zip(texts, parsed, strict=True)
    ]
    return PlanRepo(fed.meta.repo_id, manifest.id, missions, unparented)


def hub_plans(
    hub: HubHandle, repo: str | None = None
) -> tuple[list[PlanRepo], list[str]]:
    """Every BA repo's plan with per-story status, and the notes explaining
    anything the hub could not answer (never an exception for that)."""
    notes: list[str] = []
    plans = [_plan_repo(hub, fed, m, notes) for fed, m in _plan_docs(hub, repo)]
    return plans, notes


def read_ticket(
    hub: HubHandle, repo: str, group: str, ticket_id: str
) -> PlanTicket | None:
    """A published ticket of `group` (a mission id, or `tickets` for one
    without a mission); None when ids are not plain names or it is not there."""
    if not (_safe(repo) and _safe(group) and _safe(ticket_id)):
        return None
    for fed, manifest in _plan_docs(hub, repo):
        entry = next(
            (s for s in manifest.sections if s.id == ticket_id and s.file == group),
            None,
        )
        section = _l3_section(fed, manifest.id, entry) if entry else None
        if entry is not None and section is not None and entry.id != entry.file:
            return PlanTicket(
                entry.title, promote_headings(section.partition("\n")[2].strip("\n"))
            )
    return None


def section_paths(hub: HubHandle) -> dict[tuple[str, str, str], str]:
    """(repo, plan doc, section id) -> group file, for every plan section —
    the middle URL segment of its Plans page."""
    return {
        (fed.meta.repo_id, m.id, s.id): s.file
        for fed, m in _plan_docs(hub)
        for s in m.sections
    }
