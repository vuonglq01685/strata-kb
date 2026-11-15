"""Bug candidates: the hub's known failures, each marked logged once a published
bug cites its report defect with `> From report: <story> R<n> RD<k>` (E6)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from strata_kb import planstatus, testflow, ticket
from strata_kb.buglint import FROM_REPORT_RE
from strata_kb.hub import HubHandle
from strata_kb.hubapi import HubApi

logger = logging.getLogger(__name__)
_RD_ID = re.compile(r"RD[1-9][0-9]*")


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
            if section is None:
                continue
            header = ticket.header_block(planstatus._restore(entry.title, section))
            for m in FROM_REPORT_RE.finditer(header):
                out.add((m.group(1), int(m.group(2)), m.group(3)))
    return out


def candidates(
    hub: HubHandle, facts: testflow.TestFacts | None = None
) -> list[Candidate]:
    facts = facts or testflow.load_facts(hub)
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
    hub: HubHandle | HubApi,
    plan_stories: set[str] | None = None,
    facts: testflow.TestFacts | None = None,
) -> list[Candidate]:
    if isinstance(hub, HubApi):
        found = [
            Candidate(key, v["story"], v["round"], v["rd_id"], v["logged"])
            for key, v in hub.known_failures().items()
        ]
    else:
        found = candidates(hub, facts)
    out = []
    for c in found:
        if c.logged or (
            plan_stories is not None and c.key.split("/")[0] not in plan_stories
        ):
            continue
        if (
            not c.rd_id
        ):  # a story defect (D<k>) reopens the ticket for the Dev, not the BA
            continue
        if not (planstatus.safe_name(c.story) and _RD_ID.fullmatch(c.rd_id)):
            logger.warning(
                "bug candidate %s has an invalid story or RD id; dropped", c.key
            )
            continue
        out.append(c)
    return out
