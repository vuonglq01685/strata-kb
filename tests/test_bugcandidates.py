"""`bugcandidates` — known failures, logged once a published bug cites them."""

from __future__ import annotations

import shutil
from pathlib import Path

from strata_kb import bugcandidates, planingest
from tests.conftest import make_fed_entry
from tests.test_planingest import _bug_text, run_plan, write_repo
from tests.test_testflow import STORY, _text, publish_tests

RD = "### RD1 — filter broken   Story: ST-0 · TC-3\nSteps: open\n\n"
KW = {
    "verdict": "FAIL",
    "regression": "Run: yes\nFailed: ST-0/TC-3\nKnown: none",
    "rds": RD,
}


def fail_report(n: int, date: str = "2026-11-14") -> str:
    return _text(STORY, n, guilty=f"{STORY}.web", date=date, **KW)


def publish_bug(hub: Path, tmp_path: Path, *cites: str, body_cite: str = "") -> None:
    """A BA repo `ba-bug` whose BUG-12 carries one `> From report:` per cite."""
    root = tmp_path / "ba-bug"
    lines = "".join(f"> From report: {c}\n" for c in cites)
    text = _bug_text(()).replace(
        "> Related ticket: none\n", f"> Related ticket: none\n{lines}", 1
    )
    if body_cite:  # same line, but in the body (a comment), not the header
        text = text.replace(
            "## Summary\n", f"## Summary\n<!--\n> From report: {body_cite}\n-->\n", 1
        )
    write_repo(root, {}, {"bugs/BUG-12.md": text})
    assert run_plan(root).skipped == []
    entry = make_fed_entry(
        hub / "federation",
        "ba-bug",
        "ba-bug-plan",
        title=f"ba-bug {planingest.TITLE_SUFFIX}",
        tags=["plan", "generated"],
    )
    shutil.rmtree(entry / "ba-bug-plan")
    shutil.copytree(root / ".kb" / "demo-plan", entry / "ba-bug-plan")
    manifest = entry / "ba-bug-plan" / "_manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("demo-plan", "ba-bug-plan"),
        encoding="utf-8",
    )


def test_candidate_open_until_bug_cites_it(plan_hub, tmp_path):
    publish_tests(plan_hub.root, "tester-one", STORY, fail_report(1))
    (c,) = bugcandidates.candidates(plan_hub)
    assert (c.key, c.story, c.round, c.rd_id, c.logged) == (
        "ST-0/TC-3", STORY, 1, "RD1", False,
    )  # fmt: skip
    assert bugcandidates.open_candidates(plan_hub) == [c]
    publish_bug(plan_hub.root, tmp_path, f"{STORY} R1 RD1")
    (c,) = bugcandidates.candidates(plan_hub)
    assert c.logged
    assert bugcandidates.open_candidates(plan_hub) == []


def test_same_rd_id_other_round_stays_open(plan_hub, tmp_path):
    rd_b = "### RD1 — other broken   Story: ST-0 · TC-4\nSteps: open\n\n"
    r2 = _text(
        STORY, 2, guilty=f"{STORY}.web", date="2026-11-15", verdict="FAIL",
        regression="Run: yes\nFailed: ST-0/TC-3, ST-0/TC-4\nKnown: none", rds=rd_b,
    )  # fmt: skip
    publish_tests(plan_hub.root, "tester-one", STORY, fail_report(1), r2)
    publish_bug(plan_hub.root, tmp_path, f"{STORY} R1 RD1")
    by_key = {c.key: c for c in bugcandidates.candidates(plan_hub)}
    assert by_key["ST-0/TC-3"].logged
    assert not by_key["ST-0/TC-4"].logged
    assert [c.key for c in bugcandidates.open_candidates(plan_hub)] == ["ST-0/TC-4"]


def test_open_candidates_filters_by_plan_stories(plan_hub):
    publish_tests(plan_hub.root, "tester-one", STORY, fail_report(1))
    assert bugcandidates.open_candidates(plan_hub, {"ST-0"})
    assert bugcandidates.open_candidates(plan_hub, {"ST-9"}) == []


def test_open_candidates_over_hubapi():
    class Api(bugcandidates.HubApi):
        def __init__(self):
            pass

        def known_failures(self):
            return {
                "ST-0/TC-3": {
                    "story": "S",
                    "round": 1,
                    "rd_id": "RD1",
                    "logged": False,
                },
                "ST-0/TC-4": {"story": "S", "round": 1, "rd_id": "RD2", "logged": True},
            }

    assert [c.key for c in bugcandidates.open_candidates(Api())] == ["ST-0/TC-3"]


def test_cite_outside_the_header_does_not_log(plan_hub, tmp_path):
    publish_tests(plan_hub.root, "tester-one", STORY, fail_report(1))
    publish_bug(plan_hub.root, tmp_path, body_cite=f"{STORY} R1 RD1")
    assert [c.logged for c in bugcandidates.candidates(plan_hub)] == [False]
