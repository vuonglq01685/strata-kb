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


def test_cli_strategy_lint_hub_reads_strata_kb_hub_env(plan_hub, tmp_path, monkeypatch):
    # CI puts the token-bearing hub URL in STRATA_KB_HUB, not in .kb/config.yaml.
    from typer.testing import CliRunner

    from strata_kb.cli import app
    from tests.test_teststrategy import STRATEGY

    file = tmp_path / "s.md"
    file.write_text(STRATEGY, encoding="utf-8")
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text("repo_id: tester-one\n", encoding="utf-8")
    monkeypatch.setenv("STRATA_KB_HUB", str(plan_hub.root))
    res = CliRunner().invoke(
        app, ["strategy", "lint", str(file), "--kb-dir", str(kb), "--hub"]
    )
    assert res.exit_code == 1 and "M-checkout" in res.output, res.output


def test_cli_testcase_lint_hub_reads_strata_kb_hub_env(tmp_path, monkeypatch):
    import typer
    from typer.testing import CliRunner

    from strata_kb import cli

    seen = []

    def fake_hub(flag, kb_dir):
        seen.append(flag)
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "_hub_or_exit", fake_hub)
    monkeypatch.setenv("STRATA_KB_HUB", "https://hub.example/x.git")
    spec = tmp_path / "test-cases.md"
    spec.write_text("# t\n> Story: S1\n", encoding="utf-8")
    CliRunner().invoke(cli.app, ["testcase", "lint", str(spec), "--hub"])
    assert seen == ["https://hub.example/x.git"]


def _stale(plan_hub, tmp_path, rows=None, *extra):
    import json

    from typer.testing import CliRunner

    from strata_kb.cli import app

    file = tmp_path / "s.md"
    if rows is not None:
        file.write_text(_doc(rows), encoding="utf-8")
    args = ["test", "stale", "--file", str(file), "--tests-dir", str(tmp_path / "t")]
    res = CliRunner().invoke(app, [*args, "--hub", str(plan_hub.root), *extra])
    return res, (json.loads(res.stdout) if "--json" in extra else None)


CLEAN = ROWS.replace("| 3 | M-nope-US1 | rev 1 | Low | gone | UI |\n", "")


def test_cli_test_stale_exit_codes(plan_hub, tmp_path):
    res, found = _stale(plan_hub, tmp_path, CLEAN, "--json")
    assert res.exit_code == 0 and found == []
    res, found = _stale(
        plan_hub, tmp_path, CLEAN.replace("rev 1 | High", "rev 2 | High"), "--json"
    )
    assert res.exit_code == 2 and [f["code"] for f in found] == ["pin-moved"]
    res, found = _stale(plan_hub, tmp_path, ROWS, "--json")
    assert res.exit_code == 1 and found[0]["code"] == "broken-target"


def test_cli_test_stale_md_and_text(plan_hub, tmp_path):
    res, _ = _stale(plan_hub, tmp_path, ROWS, "--md")
    assert res.exit_code == 1 and "| Code | Subject | Message |" in res.stdout
    res, _ = _stale(plan_hub, tmp_path, CLEAN)
    assert res.exit_code == 0 and "nothing stale" in res.output


def test_cli_test_stale_without_strategy_checks_case_revisions(plan_hub, tmp_path):
    spec = tmp_path / "t" / STORY / "test-cases.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        f"# Cases\n\n> Story: {STORY} · Children: — · Ticket revision: 7\n",
        encoding="utf-8",
    )
    res, found = _stale(plan_hub, tmp_path, None, "--json")
    assert res.exit_code == 2
    assert [(f["code"], f["subject"]) for f in found] == [("tc-revision", STORY)]


KB_CONTEXT = """
## KB context
```yaml
kb-context:
  version: "abc1234"
  refs:
    - acme:srs §4.2
  tags: []
```
"""


def test_cli_test_stale_plan_dash_still_checks_case_revisions(plan_hub, tmp_path):
    spec = tmp_path / "t" / STORY / "test-cases.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        f"# Cases\n\n> Story: {STORY} · Children: — · Ticket revision: 7\n",
        encoding="utf-8",
    )
    rows = "| 1 | [acme:srs §4.2] | — | High | refunds | API |\n"
    (tmp_path / "s.md").write_text(
        _doc(rows).replace("> Plan: ba-one", "> Plan: —"), encoding="utf-8"
    )
    res, found = _stale(plan_hub, tmp_path, None, "--json")
    assert [f["code"] for f in found if f["code"] == "tc-revision"] == ["tc-revision"]
    assert res.exit_code in (1, 2)


def test_cli_test_stale_unreadable_strategy_is_not_a_crash(plan_hub, tmp_path):
    (tmp_path / "s.md").write_bytes(b"\xff\xfe\x00bad")
    res, _ = _stale(plan_hub, tmp_path, None, "--json")
    assert res.exit_code in (0, 2) and not isinstance(res.exception, UnicodeError)


def test_hub_read_failure_gets_its_own_code(plan_hub, monkeypatch):
    from strata_kb import gitio, ticketstale

    def boom(*_a, **_k):
        raise gitio.GitError("secret path /x")

    monkeypatch.setattr(ticketstale, "resolve_refs", boom)
    found = _found(TEXT + KB_CONTEXT, plan_hub)
    assert [f.code for f in found if f.code == "hub-read"] == ["hub-read"]
