"""`ticketlint.lint` for parent stories and their children."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_kb import kbcontext, models, ticketcheck, ticketlint
from strata_kb.familyhub import lint
from tests.test_ticketlint import (
    REFS,
    _build_ticket,
    _default_sections,
    _errors,
    _hub,
    _mission_doc,
    _warnings,
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


def bug_parent_text(pid: str = "BUG-12", rows: str | None = None) -> str:
    from tests.test_buglint import _bug

    rows = rows or (
        f"| {pid} | api | - | - | yes | first fix |\n"
        f"| {pid}.api | api | - | - | - | data |\n"
        f"| {pid}.web | web | - | {pid}.api | - | ui |\n"
    )
    split = (
        "\n\n## Split\n| Child | Repo | AC | Blocked by | Own fix | Why |\n"
        f"|---|---|---|---|---|---|\n{rows}\n"
        "## Change log\n| Rev | Date | Trigger | What changed | Affected | Review |\n"
        "|---|---|---|---|---|---|\n"
    )
    text = _bug(title=f"# {pid} — export fails") + split
    return text.replace("> Type: bug\n", "> Type: bug\n> Kind: parent bug\n", 1)


def bug_child_text(cid: str, repo: str, blocked: str = "None", pid: str = "BUG-12"):
    from tests.test_buglint import _bug

    text = _bug(
        title=f"# {cid} — export fails",
        override={"## Attachments": "N/A — see the parent"},
    )
    text = text.replace(
        "> Type: bug\n",
        f"> Type: bug\n> Parent bug: {pid} @ rev 1\n> Target repo: {repo}\n",
        1,
    )
    return text + f"\n## Dependencies\n- Blocked by: {blocked}\n"


def bug_family(pid: str = "BUG-12") -> dict[str, str]:
    api, web = f"{pid}.api", f"{pid}.web"
    return {
        pid: bug_parent_text(pid),
        api: bug_child_text(api, "api"),
        web: bug_child_text(web, "web", blocked=api),
    }


def test_parent_bug_lints_and_runs_buglint_rules(fed_hub: Path):
    texts = bug_family()
    report = lint(
        texts["BUG-12"], _hub(fed_hub), ticket_id="BUG-12", load_ticket=texts.get
    )
    assert report.passed, _errors(report)
    no_severity = texts["BUG-12"].replace("> Severity: S2\n", "")
    report = lint(no_severity, _hub(fed_hub), ticket_id="BUG-12", load_ticket=texts.get)
    assert any("Severity" in e for e in _errors(report))
    assert "parent bug is not supported yet (phase 5)" not in _errors(report)


def test_parent_bug_split_rules_flow_through_lint(fed_hub: Path):
    texts = bug_family()
    gone = {k: v for k, v in texts.items() if k != "BUG-12.web"}
    report = lint(
        texts["BUG-12"], _hub(fed_hub), ticket_id="BUG-12", load_ticket=gone.get
    )
    assert any("BUG-12.web" in e and "no ticket file" in e for e in _errors(report))
    no_own = bug_parent_text(rows="| BUG-12.api | api | - | - | - | data |\n")
    report = lint(no_own, _hub(fed_hub), ticket_id="BUG-12", load_ticket=texts.get)
    assert any("exactly one split row" in e for e in _errors(report))


def test_child_bug_lint_runs_parent_rules(fed_hub: Path):
    texts = bug_family()
    api = "BUG-12.api"
    ok = lint(texts[api], _hub(fed_hub), ticket_id=api, load_ticket=texts.get)
    assert ok.passed, _errors(ok)
    bad = bug_child_text(api, "web")
    report = lint(bad, _hub(fed_hub), ticket_id=api, load_ticket=texts.get)
    assert any("'> Target repo:' differs" in e for e in _errors(report))
    report = lint(texts[api], _hub(fed_hub), ticket_id=api, load_ticket={}.get)
    assert any("parent bug BUG-12 not found" in e for e in _errors(report))


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
    other = lint(texts[US[1]], plan_hub, own_repo=lambda: "ba-two", **args)
    assert f"ticket id {US[1]} is already published by ba-one" in _errors(other)
    own = lint(texts[US[1]], plan_hub, own_repo=lambda: "ba-one", **args)
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


def test_blocked_by_reads_split_ids_exactly(fed_hub: Path, golden_block: str):
    other = f"{MID}-US2"
    texts = family(golden_block, mission=MID)
    web = child_text(
        golden_block, WEB, "web", ("AC3", "AC4"), blocked=f"{API}, {PID}.typo, {other}"
    )
    siblings = frozenset({API, WEB})
    got = ticketlint._blocked_by_ids(web, MID, siblings, PID)
    assert got == (other,)
    report = lint(
        web,
        _hub(fed_hub),
        ticket_id=WEB,
        load_ticket=texts.get,
        load_mission={MID: _mission_doc(MID, [PID, other])}.get,
    )
    msg = " ".join(_errors(report))
    assert f"names {other}," in msg and API not in msg.split("names ")[1].split(",")[0]


def test_mission_blocked_parent_warns_but_its_children_error(
    fed_hub: Path, golden_block: str
):
    texts = family(golden_block, mission=MID)
    blocked = _mission_doc(MID, [PID]) + (
        f"\n## Open questions\n- [ ] Q1 — Which layer? — owner: Bob — blocks: {PID}\n"
    )
    load = {MID: blocked}.get
    parent = lint(
        texts[PID],
        _hub(fed_hub),
        ticket_id=PID,
        load_ticket=texts.get,
        load_mission=load,
    )
    assert parent.passed, _errors(parent)
    assert any("blocked by mission" in w for w in _warnings(parent))
    child = lint(
        texts[API],
        _hub(fed_hub),
        ticket_id=API,
        load_ticket=texts.get,
        load_mission=load,
    )
    assert any("blocked by mission" in e for e in _errors(child))


GROUNDED_TWO = "- Grounded on: demo:demo-code @ c12b24f, web:web-code @ def1234\n"
WARN_TWO = (
    "grounding touches several repos (demo, web) — split it into a parent "
    "story (BA Guide 3.10) or keep one ticket"
)


def _two_repo_ticket(block: str, extra: str = "") -> str:
    grounding = _default_sections(block)["## Technical grounding"].replace(
        "- Grounded on: demo:demo-code @ c12b24f\n", GROUNDED_TWO
    )
    title = f"# T-1 — airspace\n{extra}"
    return _build_ticket(
        block, title=title, overrides={"## Technical grounding": grounding}
    )


def test_single_ticket_grounded_on_two_repos_warns(fed_hub: Path, golden_block: str):
    report = lint(_two_repo_ticket(golden_block), _hub(fed_hub))
    assert WARN_TWO in _warnings(report)


def test_single_ticket_grounded_on_two_repos_can_pass_the_gate(
    fed_hub: Path, golden_block: str
):
    """Reject keeps one ticket: lint warns, but `kb ticket check` checks each
    line in its own repo's `-code` and can pass (BA Guide 3.10)."""
    text = _two_repo_ticket(golden_block).replace(
        "- Service: svc.airspace-service\n",
        "- Service:\n  - svc.airspace-service\n  - web:svc.web\n",
    )
    assert WARN_TWO in _warnings(lint(text, _hub(fed_hub)))

    def doc(doc_id: str, rev: str, *ids: str) -> ticketcheck.LoadedDoc:
        sections = [
            models.SectionEntry(id=i, title=i, file="g", status="reviewed") for i in ids
        ]
        manifest = models.Manifest(
            id=doc_id, title=doc_id, revision=rev, sections=sections
        )
        return ticketcheck.LoadedDoc(
            manifest, f"fake/{doc_id}", lambda g: None, lambda g: None
        )

    docs = {
        ("demo", "demo-code"): doc(
            "demo-code",
            "c12b24f",
            "svc.airspace-service",
            "db.restrictive_airspace",
            "cmd.test",
        ),
        ("web", "web-code"): doc("web-code", "def1234", "svc.web"),
    }
    report = ticketcheck.check(text, load_doc=lambda r, d: docs.get((r, d)))
    assert [i.message for i in report.issues if i.level == "error"] == []
    assert any(n.startswith("[web] ") for n in report.notes)


def test_child_grounded_on_two_repos_does_not_warn(fed_hub: Path, golden_block: str):
    text = _two_repo_ticket(
        golden_block, f"> Parent story: {PID} @ rev 1\n> Target repo: demo\n"
    )
    assert WARN_TWO not in _warnings(lint(text, _hub(fed_hub)))


def test_one_repo_grounding_does_not_warn(fed_hub: Path, golden_block: str):
    assert WARN_TWO not in _warnings(lint(_build_ticket(golden_block), _hub(fed_hub)))
