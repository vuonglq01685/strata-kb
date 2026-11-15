"""Bug candidates: the hub's known failures, each marked logged once a published
bug cites its report defect with `> From report: <story> R<n> RD<k>` (E6)."""

from __future__ import annotations

from dataclasses import dataclass

from strata_kb import planstatus, testflow
from strata_kb.buglint import FROM_REPORT_RE
from strata_kb.hub import HubHandle
from strata_kb.hubapi import HubApi


@dataclass(frozen=True)
class Candidate:
    key: str
    story: str
    round: int
    rd_id: str
    logged: bool


def _cited(hub: HubHandle) -> set[tuple[str, int, str]]:
    """(story, round, rd_id) of every `> From report:` line of a published bug."""
    out: set[tuple[str, int, str]] = set()
    for fed, manifest in planstatus.plan_docs(hub):
        for entry in manifest.sections:
            if not entry.id.startswith("BUG-"):
                continue
            section = planstatus._l3_section(fed, manifest.id, entry)
            for m in FROM_REPORT_RE.finditer(section or ""):
                out.add((m.group(1), int(m.group(2)), m.group(3)))
    return out


def candidates(hub: HubHandle) -> list[Candidate]:
    facts = testflow.load_facts(hub)
    logged_keys = {
        d.key
        for story, n, rd in _cited(hub)
        for r in facts.reports.get(story, ())
        if r.round == n
        for d in r.regression_defects
        if d.rd_id == rd
    }
    return [
        Candidate(k.key, k.story, k.round, k.rd_id, k.key in logged_keys)
        for k in testflow.known_failures(facts).values()
    ]


def open_candidates(
    hub: HubHandle | HubApi, plan_stories: set[str] | None = None
) -> list[Candidate]:
    if isinstance(hub, HubApi):
        found = [
            Candidate(key, v["story"], v["round"], v["rd_id"], v["logged"])
            for key, v in hub.known_failures().items()
        ]
    else:
        found = candidates(hub)
    return [
        c
        for c in found
        if not c.logged
        and (plan_stories is None or c.key.split("/")[0] in plan_stories)
    ]
