"""`ticketlint.lint` for parent stories and their children."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_kb import kbcontext
from strata_kb.familyhub import lint
from tests.test_ticketlint import (
    REFS,
    _build_ticket,
    _default_sections,
    _errors,
    _hub,
    _mission_doc,
)


@pytest.fixture
def golden_block(fed_hub: Path) -> str:
    return kbcontext.build_context_block(_hub(fed_hub), REFS, tags=["airspace"])[0]


MID = "M-airspace-filter"
PID = f"{MID}-US1"
API = f"{PID}.api"
WEB = f"{PID}.web"
STORY = _default_sections("")["## User Story"]
CITES = [
    "[arinc-kb:arinc-424 §5.3]",
    "[icao-kb:icao-annex-2 §1.1]",
]


def parent_text(pid: str = PID, mission: str | None = None, kind: str = "parent story"):
    mline = f"> Parent mission: {mission}\n" if mission else ""
    return (
        f"# Export {pid}\n> Kind: {kind}\n> Revision: 1\n{mline}\n"
        f"## User Story\n{STORY}\n\n"
        "## Split\n| Child | Repo | AC | Blocked by | Own fix | Why |\n"
        "|---|---|---|---|---|---|\n"
        f"| {pid}.api | api | AC1, AC2 | - | - | data |\n"
        f"| {pid}.web | web | AC3, AC4 | {pid}.api | - | ui |\n\n"
        "## Change log\n| Rev | Date | Trigger | What changed | Affected | Review |\n"
        "|---|---|---|---|---|---|\n"
    )


def child_text(
    block: str,
    cid: str,
    repo: str,
    acs: tuple[str, ...],
    blocked: str = "None",
    extra: str = "",
    pid: str = PID,
) -> str:
    items = "\n".join(
        f"- [ ] {ac}: Given a polygon, when the dispatcher clicks it, then its "
        f"details are shown per {CITES[n % 2]}"
        for n, ac in enumerate(acs)
    )
    title = (
        f"# {cid} — airspace\n\n> Parent story: {pid} @ rev 1\n"
        f"> Target repo: {repo}\n{extra}"
    )
    return _build_ticket(
        block,
        title=title,
        overrides={
            "## Acceptance Criteria": items,
            "## Dependencies": f"- Blocked by: {blocked}\n- Blocks: None",
            "## Technical grounding": _default_sections(block)[
                "## Technical grounding"
            ].replace("demo:demo-code", f"{repo}:{repo}-code"),
        },
    )


def family(block: str, pid: str = PID, mission: str | None = None):
    api, web = f"{pid}.api", f"{pid}.web"
    texts = {
        pid: parent_text(pid, mission),
        api: child_text(block, api, "api", ("AC1", "AC2"), pid=pid),
        web: child_text(block, web, "web", ("AC3", "AC4"), blocked=api, pid=pid),
    }
    return texts


def test_lint_dispatches_parent_story(fed_hub: Path, golden_block: str):
    texts = family(golden_block)
    report = lint(texts[PID], _hub(fed_hub), ticket_id=PID, load_ticket=texts.get)
    assert report.passed, _errors(report)
    gone = {k: v for k, v in texts.items() if k != WEB}
    report = lint(texts[PID], _hub(fed_hub), ticket_id=PID, load_ticket=gone.get)
    assert any(WEB in e and "no ticket file" in e for e in _errors(report))


def test_parent_bug_is_rejected(fed_hub: Path):
    report = lint(parent_text(kind="parent bug"), _hub(fed_hub), ticket_id=PID)
    assert "parent bug is not supported yet (phase 5)" in _errors(report)


def test_child_lint_runs_parent_rules(fed_hub: Path, golden_block: str):
    texts = family(golden_block)
    ok = lint(texts[API], _hub(fed_hub), ticket_id=API, load_ticket=texts.get)
    assert ok.passed, _errors(ok)
    bad = child_text(golden_block, API, "api", ("AC1", "AC3"))
    report = lint(bad, _hub(fed_hub), ticket_id=API, load_ticket=texts.get)
    assert any("differ from its split row" in e for e in _errors(report))


def test_child_with_one_ac_gets_the_at_least_two_error_once(
    fed_hub: Path, golden_block: str
):
    texts = family(golden_block)
    one = child_text(golden_block, API, "api", ("AC1",))
    report = lint(one, _hub(fed_hub), ticket_id=API, load_ticket=texts.get)
    assert sum("at least 2" in e for e in _errors(report)) == 1


def test_mission_child_backlog_checks_parent_id(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    texts = family(golden_block, mission=MID)
    load = {MID: _mission_doc(MID, [PID])}.get
    ok = lint(
        texts[API],
        _hub(fed_hub),
        ticket_id=API,
        load_ticket=texts.get,
        load_mission=load,
    )
    assert ok.passed, _errors(ok)
    # the child ids are not in the backlog, the parent id is the one checked
    other = {MID: _mission_doc(MID, [f"{MID}-US2"])}.get
    bad = lint(
        texts[API],
        _hub(fed_hub),
        ticket_id=API,
        load_ticket=texts.get,
        load_mission=other,
    )
    assert any(f"'{PID}' is not in the backlog" in e for e in _errors(bad))
    # the same through files
    missions = tmp_path / "missions"
    missions.mkdir()
    (missions / f"{MID}.md").write_text(_mission_doc(MID, [PID]), encoding="utf-8")
    by_path = lint(
        texts[API],
        _hub(fed_hub),
        path=tmp_path / "tickets" / f"{API}.md",
        missions_dir=missions,
        load_ticket=texts.get,
    )
    assert by_path.passed, _errors(by_path)


def test_mission_child_with_parent_mission_line_is_error(
    fed_hub: Path, golden_block: str
):
    texts = family(golden_block, mission=MID)
    line = child_text(
        golden_block, API, "api", ("AC1", "AC2"), extra=f"> Parent mission: {MID}\n"
    )
    report = lint(
        line,
        _hub(fed_hub),
        ticket_id=API,
        load_ticket=texts.get,
        load_mission={MID: _mission_doc(MID, [PID])}.get,
    )
    assert (
        "a child ticket inherits its parent's mission — remove '> Parent mission:'"
        in _errors(report)
    )


def test_sibling_blocked_by_not_required_in_sequencing(
    fed_hub: Path, golden_block: str
):
    texts = family(golden_block, mission=MID)
    mission = _mission_doc(MID, [PID])
    report = lint(
        texts[WEB],
        _hub(fed_hub),
        ticket_id=WEB,
        load_ticket=texts.get,
        load_mission={MID: mission}.get,
    )
    assert report.passed, _errors(report)


def test_id_published_by_other_ba_repo_is_error(plan_hub, golden_block: str):
    from tests.test_planstatus import US

    texts = family(golden_block, pid=US[1])
    args = {"ticket_id": US[1], "load_ticket": texts.get}
    other = lint(texts[US[1]], plan_hub, own_repo="ba-two", **args)
    assert f"ticket id {US[1]} is already published by ba-one" in _errors(other)
    own = lint(texts[US[1]], plan_hub, own_repo="ba-one", **args)
    assert not any("already published" in e for e in _errors(own))


def test_done_ticket_cannot_become_a_parent(plan_hub, golden_block: str):
    from tests.conftest import make_fed_entry
    from tests.test_planstatus import HISTORY, US

    svc = make_fed_entry(
        plan_hub.root / "federation", "dev-one", "dev-one-svc", sec_id="hist.x"
    )
    (svc / "dev-one-svc" / "history.md").write_text(HISTORY, encoding="utf-8")
    texts = family(golden_block, pid=US[0])
    report = lint(texts[US[0]], plan_hub, ticket_id=US[0], load_ticket=texts.get)
    assert (
        f"{US[0]} is already implemented — a done ticket cannot become a parent story"
        in _errors(report)
    )
    assert "claim check skipped (needs the hub API)" in report.notes


@pytest.mark.parametrize("with_loader", [False, True])
def test_plain_ticket_lint_unchanged(fed_hub: Path, golden_block: str, with_loader):
    text = _build_ticket(golden_block)
    base = lint(text, _hub(fed_hub))
    got = lint(
        text, _hub(fed_hub), load_ticket=(lambda _i: None) if with_loader else None
    )
    assert got.passed and got.issues == base.issues and got.notes == base.notes == []
