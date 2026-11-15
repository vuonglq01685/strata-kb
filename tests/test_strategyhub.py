"""`strategyhub` — the plan as the strategy sees it, published strategies, drift."""

from __future__ import annotations

from strata_kb import strategyhub, testflow, teststrategy
from tests.test_planingest import MISSION_ID
from tests.test_testflow import STORY, publish_strategy

US1 = f"{MISSION_ID}-US1"

ROWS = f"""\
| Rank | Target | Pin | Risk | Why | Types |
|---|---|---|---|---|---|
| 1 | {MISSION_ID} | rev 1 | High | core flow | UI |
| 2 | {STORY} | rev 1 | Medium | published ticket | API |
| 3 | M-nope-US1 | rev 1 | Low | gone | UI |
"""


def _doc(rows: str) -> str:
    return (
        "# Test strategy — Acme\n\n> Revision: 1\n> Plan: ba-one\n\n"
        f"## Priority order\n{rows}\n"
    )


STRATEGY_FOR_PLAN_HUB = _doc(ROWS)
TEXT = STRATEGY_FOR_PLAN_HUB


def _found(text, hub, repo="ba-one"):
    plan = strategyhub.plan_view(hub, repo)
    return strategyhub.strategy_findings(text, teststrategy.parse(text), plan, hub)


def test_strategy_texts_reads_published_section(plan_hub):
    publish_strategy(plan_hub.root, "tester-one", STRATEGY_FOR_PLAN_HUB)
    assert "Priority order" in testflow.strategy_texts(plan_hub)["tester-one"]


def test_plan_view_has_texts_and_testable(plan_hub):
    v = strategyhub.plan_view(plan_hub, "ba-one")
    assert MISSION_ID in v.missions and STORY in v.texts
    assert US1 in v.testable  # done in dev-svc, no report
    assert v.status[US1] == "done"
    assert [s.us_id for s in v.stories][0] == US1


def test_no_plan_repo_is_empty_view(plan_hub):
    v = strategyhub.plan_view(plan_hub, None)
    assert (v.stories, v.missions, v.texts) == ([], frozenset(), {})


def test_unknown_plan_repo_makes_every_id_row_broken(plan_hub):
    broken = {
        f.subject for f in _found(TEXT, plan_hub, "nope") if f.code == "broken-target"
    }
    assert broken == {MISSION_ID, STORY, "M-nope-US1"}


def test_only_missing_id_is_broken(plan_hub):
    broken = {f.subject for f in _found(TEXT, plan_hub) if f.code == "broken-target"}
    assert broken == {"M-nope-US1"}


def test_pin_moved_when_mission_revision_differs(plan_hub):
    text = TEXT.replace(f"{MISSION_ID} | rev 1", f"{MISSION_ID} | rev 9")
    moved = [f for f in _found(text, plan_hub) if f.code == "pin-moved"]
    assert [(f.subject, f.level) for f in moved] == [(MISSION_ID, "warning")]
    assert not [f for f in _found(TEXT, plan_hub) if f.code == "pin-moved"]


def test_coverage_for_testable_story_outside_strategy(plan_hub):
    text = _doc(
        "| Rank | Target | Pin | Risk | Why | Types |\n|---|---|---|---|---|---|\n"
        "| 1 | [nope:none §9] | — | Low | x | UI |\n"
    )
    cov = {f.subject for f in _found(text, plan_hub) if f.code == "coverage"}
    assert US1 in cov
    assert not {f.subject for f in _found(TEXT, plan_hub) if f.code == "coverage"}


def test_case_findings_tc_revision(plan_hub, tmp_path):
    plan = strategyhub.plan_view(plan_hub, "ba-one")
    spec = tmp_path / STORY
    spec.mkdir()
    (spec / "test-cases.md").write_text(
        f"# Cases\n\n> Story: {STORY} · Children: — · Ticket revision: 7\n",
        encoding="utf-8",
    )
    other = tmp_path / "M-gone-US1"
    other.mkdir()
    (other / "test-cases.md").write_text(
        "# Cases\n\n> Story: M-gone-US1 · Children: — · Ticket revision: 7\n",
        encoding="utf-8",
    )
    found = strategyhub.case_findings(tmp_path, plan)
    assert [(f.code, f.subject) for f in found] == [("tc-revision", STORY)]


def test_lint_against_hub_levels(plan_hub):
    text = TEXT.replace(f"{MISSION_ID} | rev 1", f"{MISSION_ID} | rev 9")
    issues = strategyhub.lint_against_hub(text, plan_hub)
    assert {(i.code, i.level) for i in issues} == {
        ("st-broken-target", "error"),
        ("st-pin-moved", "warning"),
    }


def test_views_place_stories_and_report_rows(plan_hub):
    publish_strategy(plan_hub.root, "tester-one", STRATEGY_FOR_PLAN_HUB)
    [v] = strategyhub.views(plan_hub)
    assert v.tester_repo == "tester-one"
    assert [p.story for p in v.order] == [US1]  # only testable stories
    by_target = {r.target: placed for r, placed in v.rows}
    assert (US1, "done") in by_target[MISSION_ID]
    assert [r.target for r in v.empty_rows] == ["M-nope-US1"]
    assert v.outside == []
    assert any(f.code == "broken-target" for f in v.findings)


def test_views_skip_unparseable_strategy(plan_hub):
    publish_strategy(plan_hub.root, "tester-one", "# nothing\n")
    assert strategyhub.views(plan_hub)[0].strategy.rows == ()


def test_cli_strategy_lint_hub_flags_broken_target(plan_hub, tmp_path):
    from typer.testing import CliRunner

    from strata_kb.cli import app
    from tests.test_teststrategy import STRATEGY

    file = tmp_path / "s.md"
    file.write_text(STRATEGY, encoding="utf-8")  # plan ba-one, M-checkout not on hub
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text(f"hub: {plan_hub.root}\n", encoding="utf-8")
    args = ["strategy", "lint", str(file), "--kb-dir", str(kb)]
    runner = CliRunner()
    assert runner.invoke(app, args).exit_code == 0
    res = runner.invoke(app, [*args, "--hub"])
    assert res.exit_code == 1 and "M-checkout" in res.output
