"""testflow — derived test status of a story and the known-failure guard.

Read-only overlay on the hub's plan rows (spec D3, D5): `testing`, `closed`,
`reopened` and `fix-done` come from published `<repo>-test` reports, held
Tester claims and `fix:R<n>` refs in Dev histories. The row's own `status`
(done | ready | ...) is never touched. Must not import `web`; `planstatus`
imports this module, so it cannot import `planstatus` or `ticketfetch`.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from strata_kb import (
    kinds,
    missionnext,
    models,
    query,
    testcover,
    testreport,
    ticketcheck,
    ticketclaim,
)
from strata_kb.errors import KbError
from strata_kb.federation import load_federation
from strata_kb.mdutils import slice_section
from strata_kb.planingest import promote_headings

if TYPE_CHECKING:
    from strata_kb.hub import HubHandle
    from strata_kb.missionnext import StoryStatus
    from strata_kb.planstatus import PlanRepo
    from strata_kb.testreport import Report

logger = logging.getLogger("strata_kb.testflow")

STATUSES = ("testing", "closed", "reopened", "fix-done")
_ROUND_ID_RE = re.compile(r".+\.R[1-9]\d*")


@dataclass(frozen=True)
class TestFacts:
    __test__ = False  # not a pytest class
    reports: dict[str, tuple[Report, ...]] = field(default_factory=dict)
    testing: frozenset[str] = frozenset()
    fix_rounds: dict[str, frozenset[int]] = field(default_factory=dict)
    # tester repo id -> story ids its `-test` docs cover (for `duplicate_testers`)
    covered: dict[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class KnownFailure:
    key: str
    story: str
    round: int
    rd_id: str
    duplicates: tuple[str, ...] = ()


def _test_docs(hub: HubHandle) -> Iterator[tuple[str, ticketcheck.LoadedDoc]]:
    """(doc id, doc) of every readable generated test doc."""
    for fed in load_federation(hub.federation_dir):
        for entry in sorted(fed.index.docs, key=lambda d: d.id):
            if not kinds.is_test_doc(entry.title, entry.tags):
                continue
            folder = query.doc_dir(fed.kb_dir, entry.id)
            if folder is None:
                continue
            try:
                doc = ticketcheck.load_doc_dir(folder, entry.id)
            except ticketcheck.DocLoadError:
                logger.warning("skipping unreadable test doc %s", folder)
                continue
            yield entry.id, doc


def _read_report(doc: ticketcheck.LoadedDoc, sec: models.SectionEntry) -> Report | None:
    """The `<story>.R<n>` section parsed back: L3 headings were demoted at
    ingest and the H1 dropped, so both are restored first."""
    raw = doc.read_raw(sec.file)
    body = slice_section(raw, sec.id) if raw else None
    if body is None:
        return None
    inner = promote_headings(body.partition("\n")[2].strip("\n"))
    text = f"# {sec.title}\n\n{inner}\n"
    try:
        return testreport.parse(text)
    except (ValueError, KbError):
        return None


def _test_reports(hub: HubHandle) -> dict[str, list[Report]]:
    reports: dict[str, list[Report]] = {}
    for doc_id, doc in _test_docs(hub):
        for sec in doc.manifest.sections:
            if not _ROUND_ID_RE.fullmatch(sec.id):
                continue
            rep = _read_report(doc, sec)
            if rep is None:
                logger.warning("skipping unreadable report %s in %s", sec.id, doc_id)
                continue
            reports.setdefault(sec.file, []).append(rep)
    return reports


def _fix_rounds(hub: HubHandle) -> dict[str, frozenset[int]]:
    out: dict[str, frozenset[int]] = {}
    for fed in load_federation(hub.federation_dir):
        if fed.kind != kinds.DEV:
            continue
        svc = f"{fed.meta.repo_id.rpartition('/')[2]}-svc"
        try:
            doc = ticketcheck.load_from_hub(hub.federation_dir, fed.meta.repo_id, svc)
        except ticketcheck.DocLoadError:
            continue
        if doc is None:
            continue
        for ticket, rounds in missionnext.fix_rounds_from_history(
            doc.read_group("history")
        ).items():
            out[ticket] = out.get(ticket, frozenset()) | rounds
    return out


def _held_testing(hub: HubHandle) -> frozenset[str]:
    db = ticketclaim.claims_db_path(hub.root)
    if not db.exists():  # read-only: never create the store
        return frozenset()
    try:
        held = ticketclaim.ClaimStore(db).held(role="tester")
    except (sqlite3.Error, KbError, OSError):
        logger.warning("claim store unreadable", exc_info=True)
        return frozenset()
    return frozenset(c.ticket for c in held)


def load_facts(hub: HubHandle) -> TestFacts:
    reports = _test_reports(hub)
    return TestFacts(
        reports={
            s: tuple(sorted(r, key=lambda x: x.round)) for s, r in reports.items()
        },
        testing=_held_testing(hub),
        fix_rounds=_fix_rounds(hub),
        covered=testcover.tester_coverage(hub),
    )


def _latest(story: str, facts: TestFacts) -> Report | None:
    found = facts.reports.get(story)
    return found[-1] if found else None


def story_test_status(
    story: str, children: tuple[str, ...], facts: TestFacts
) -> dict[str, str]:
    """id -> test status for a story and its children (spec D3). `closed` is
    final: a held claim or a later Dev row never overrides a PASS."""
    latest = _latest(story, facts)
    if latest is not None and latest.verdict == "PASS":
        return dict.fromkeys((story, *children), "closed")
    out: dict[str, str] = {}
    if latest is not None:  # FAIL
        out[story] = "reopened"
        guilty = {d.guilty for d in latest.defects}
        for child in children:
            if child in guilty:
                fixed = latest.round in facts.fix_rounds.get(child, frozenset())
                out[child] = "fix-done" if fixed else "reopened"
    if story in facts.testing:
        out[story] = "testing"
    return out


def overlay(repo: PlanRepo, facts: TestFacts) -> PlanRepo:
    """`repo` with `test_status`, `test_round` and `regression_bug` set on
    every row a report or claim reaches; `status` stays as it was."""
    rows = [
        *(s for m in repo.missions for s in m.stories),
        *repo.unparented,
    ]
    derived: dict[str, StoryStatus] = {}
    for root in (r for r in rows if not r.parent):
        kids = tuple(r.us_id for r in rows if r.parent == root.us_id)
        statuses = story_test_status(root.us_id, kids, facts)
        latest = _latest(root.us_id, facts)
        for us_id, status in statuses.items():
            derived[us_id] = dataclasses.replace(
                next(r for r in rows if r.us_id == us_id),
                test_status=status,
                test_round=latest.round if latest else 0,
                regression_bug=bool(
                    latest and any(d.regression for d in latest.defects)
                ),
            )

    def apply(row: StoryStatus) -> StoryStatus:
        return derived.get(row.us_id, row)

    return dataclasses.replace(
        repo,
        missions=[
            dataclasses.replace(m, stories=[apply(s) for s in m.stories])
            for m in repo.missions
        ],
        unparented=[apply(u) for u in repo.unparented],
    )


def known_failures(facts: TestFacts) -> dict[str, KnownFailure]:
    """Open regression failures by key (spec D5). The first report (by date,
    story, round) owns a key; later reports inside its open window are listed
    as duplicates; a later report that ran the regression without the key
    failing closes it."""
    ordered = sorted(
        (r for rs in facts.reports.values() for r in rs),
        key=lambda r: (r.date, r.story, r.round),
    )
    open_: dict[str, KnownFailure] = {}
    for rep in ordered:
        failed = set(rep.regression_failed)
        if rep.regression_ran:
            open_ = {k: v for k, v in open_.items() if k in failed}
        rd_of = {d.key: d.rd_id for d in rep.regression_defects}
        for key in rep.regression_failed:
            current = open_.get(key)
            if current is None:
                open_[key] = KnownFailure(key, rep.story, rep.round, rd_of.get(key, ""))
            else:
                open_[key] = dataclasses.replace(
                    current,
                    duplicates=(*current.duplicates, f"{rep.story} R{rep.round}"),
                )
    return open_


def duplicate_testers(hub: HubHandle, facts: TestFacts) -> list[str]:
    """One message per BA repo covered by `-test` docs of more than one
    tester repo (spec D1); see `testcover`, which `kb doctor` shares."""
    return testcover.duplicate_testers(hub, facts.covered)
