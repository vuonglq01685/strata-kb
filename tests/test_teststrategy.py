import json
from importlib import resources

import pytest
from typer.testing import CliRunner

from strata_kb import lintcore, teststrategy
from strata_kb.cli import app

STRATEGY = """\
# Test strategy — Acme

> Revision: 1
> Plan: ba-one

## Scope & objectives
Test checkout and refunds.

## Test levels & types
| Type | In scope | Tool | Runs on | Notes |
|---|---|---|---|---|
| UI | yes | playwright | staging | |
| API | yes | pytest | staging | |

## Priority order
| Rank | Target | Pin | Risk | Why | Types |
|---|---|---|---|---|---|
| 1 | M-checkout | rev 3 | High | payment path, money | UI, API |
| 1 | [acme:srs §4.2] | — | High | refunds, no mission yet | API |
| last | M-checkout-US5 | rev 2 | Low | static page | UI |

## Environments & data
See .kb/test-env.yaml.

## Entry & exit criteria
Story is ticket-ready; all P1 cases pass.

## Regression policy
Re-run P1 on every fix.

## Risks & mitigations
Payment sandbox is flaky; retry once.

## Open questions
- [ ] Q1 — none yet — owner: tester — blocks: none

## KB context
```yaml
kb-context:
  version: "abc1234"
  refs:
    - acme:srs §4.2
  tags: []
```

## Change log
| Rev | Date | Trigger | What changed | Affected | Review |
|---|---|---|---|---|---|
|   |   |   |   |   |   |

## Review record
| Date | Round | Verdict | Reviewer |
|---|---|---|---|
| 2026-11-15 | 1 | pass | opus |
"""

TICKET_WITH_CITES = """\
# Refund a payment
> Revision: 1

## Background / Business context
Refunds follow [srs §4.2].

## KB context
```yaml
kb-context:
  version: "abc1234"
  refs:
    - acme:srs §5
  tags: []
```
"""


def test_parse_three_target_forms():
    s = teststrategy.parse(STRATEGY)
    assert s.plan == "ba-one" and s.revision == 1
    assert [(r.target, r.rank, r.pin) for r in s.rows] == [
        ("M-checkout", 1, 3),
        ("[acme:srs §4.2]", 1, None),
        ("M-checkout-US5", None, 2),
    ]
    assert s.rows[1].area == teststrategy.Area("acme", "srs", "4.2")


def test_plan_dash_is_none():
    assert (
        teststrategy.parse(STRATEGY.replace("> Plan: ba-one", "> Plan: —")).plan is None
    )


def test_empty_plan_is_none_not_next_line():
    assert (
        teststrategy.parse(STRATEGY.replace("> Plan: ba-one", "> Plan:")).plan is None
    )


@pytest.mark.parametrize("rank", ["soon", "0", "²"])
def test_unparseable_rank_row_is_dropped(rank):
    bad = STRATEGY.replace("| 1 | M-checkout |", f"| {rank} | M-checkout |")
    assert [r.target for r in teststrategy.parse(bad).rows] == [
        "[acme:srs §4.2]",
        "M-checkout-US5",
    ]


def test_strategy_has_every_heading_in_order():
    lines = [ln for ln in STRATEGY.splitlines() if ln.startswith("## ")]
    assert tuple(lines) == teststrategy.HEADINGS
    assert lintcore.review_passed(STRATEGY)


def test_area_covers_ancestor_not_prefix():
    a = teststrategy.Area(None, "srs", "4")
    assert a.covers(teststrategy.Area("acme", "srs", "4.2"))
    assert a.covers(teststrategy.Area(None, "srs", "4"))
    assert not a.covers(teststrategy.Area(None, "srs", "40"))
    assert not teststrategy.Area("x", "srs", "4").covers(
        teststrategy.Area("y", "srs", "4")
    )


def test_citations_reads_body_and_kb_context():
    got = teststrategy.citations(TICKET_WITH_CITES)
    assert teststrategy.Area(None, "srs", "4.2") in got
    assert teststrategy.Area("acme", "srs", "5") in got


def test_template_parses_with_example_rows():
    text = (
        resources.files("strata_kb.templates.init")
        .joinpath("test-strategy-template.md")
        .read_text(encoding="utf-8")
    )
    assert len(teststrategy.parse(text).rows) == 3


TEMPLATE = (
    resources.files("strata_kb.templates.init")
    .joinpath("test-strategy-template.md")
    .read_text(encoding="utf-8")
)


def test_clean_strategy_passes():
    report = teststrategy.lint(STRATEGY)
    assert report.passed, report.issues


@pytest.mark.parametrize(
    "edit, code",
    [
        (("| 1 | M-checkout | rev 3 |", "| one | M-checkout | rev 3 |"), "st-row"),
        (("| M-checkout | rev 3 |", "| M-checkout | — |"), "st-row"),
        (("[acme:srs §4.2] | — |", "[acme:srs §4.2] | rev 1 |"), "st-row"),
        (("| High | payment", "| Severe | payment"), "st-row"),
        (("| rev 3 |", "| rev ٣ |"), "st-row"),
        (("M-checkout-US5 | rev 2", "M-checkout | rev 3"), "st-duplicate"),
        (("> Plan: ba-one", "> Plan: —"), "st-plan"),
        (("> Plan: ba-one\n", ""), "st-plan"),
        (("    - acme:srs §4.2\n", "    - acme:srs §9\n"), "st-kb-context"),
        (("| pass |", "| fail |"), "st-review"),
    ],
)
def test_lint_errors(edit, code):
    assert edit[0] in STRATEGY
    report = teststrategy.lint(STRATEGY.replace(*edit))
    assert not report.passed and code in {i.code for i in report.issues}


def test_plan_dash_ok_with_only_area_rows():
    text = STRATEGY.replace("> Plan: ba-one", "> Plan: —")
    text = "\n".join(ln for ln in text.splitlines() if "M-checkout" not in ln)
    assert teststrategy.lint(text).passed


def test_crlf_plan_line_parses():
    st = teststrategy.parse(STRATEGY.replace("\n", "\r\n"))
    assert st.plan == "ba-one"


def test_rounds_section_is_optional_and_template_has_it():
    assert "## Rounds" in TEMPLATE
    assert "## Rounds" not in STRATEGY and teststrategy.lint(STRATEGY).passed
    assert "missing required heading: '## Rounds'" not in {
        i.message for i in teststrategy.lint(TEMPLATE).issues
    }


def _img(src):
    return STRATEGY.replace(
        "Re-run P1 on every fix.", f"Re-run P1 on every fix.\n\n![x]({src})", 1
    )


def test_lint_image_rules_need_base_dir(tmp_path):
    docs = tmp_path / "docs"
    (docs / "assets").mkdir(parents=True)
    (docs / "assets/x.png").write_bytes(b"png")
    (docs / "other.png").write_bytes(b"png")
    assert teststrategy.lint(_img("assets/x.png"), docs).passed
    assert teststrategy.lint(_img("assets/nope.png")).passed  # no base_dir: no check
    for src in ("assets/nope.png", "other.png", "x/assets/y.png", "assets/x.gif"):
        rep = teststrategy.lint(_img(src), docs)
        assert "st-image" in {i.code for i in rep.issues}, src


def test_lint_rejects_symlinked_image(tmp_path):
    docs = tmp_path / "docs"
    (docs / "assets").mkdir(parents=True)
    (tmp_path / "real.png").write_bytes(b"png")
    (docs / "assets/x.png").symlink_to(tmp_path / "real.png")
    assert "st-image" in {
        i.code for i in teststrategy.lint(_img("assets/x.png"), docs).issues
    }


def test_lint_rejects_fenced_h2():
    text = STRATEGY.replace(
        "Re-run P1 on every fix.", "Re-run P1 on every fix.\n\n```\n## x\n```", 1
    )
    assert "st-fence" in {i.code for i in teststrategy.lint(text).issues}


def test_cli_strategy_lint_checks_images_and_reads_bytes(tmp_path):
    (tmp_path / "s.md").write_text(_img("assets/nope.png"), encoding="utf-8")
    res = CliRunner().invoke(app, ["strategy", "lint", str(tmp_path / "s.md")])
    assert res.exit_code == 1 and "nope.png" in res.output
    (tmp_path / "bin.md").write_bytes(b"\xff\xfe\x00bad")
    res = CliRunner().invoke(app, ["strategy", "lint", str(tmp_path / "bin.md")])
    assert res.exit_code == 1 and "cannot read" in res.output


def test_template_fails_on_placeholders():
    assert "st-placeholder" in {i.code for i in teststrategy.lint(TEMPLATE).issues}


def test_cli_strategy_lint_exit_codes(tmp_path):
    good, bad = tmp_path / "good.md", tmp_path / "bad.md"
    good.write_text(STRATEGY, encoding="utf-8")
    bad.write_text(TEMPLATE, encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["strategy", "lint", str(good)]).exit_code == 0
    assert runner.invoke(app, ["strategy", "lint", str(bad)]).exit_code == 1
    res = runner.invoke(app, ["strategy", "lint", str(good), "--json"])
    assert json.loads(res.output)


# ---- placement and order ----------------------------------------------------


def _a(doc, section, repo=None):
    return teststrategy.Area(repo, doc, section)


def _row(rank, target, area=None):
    return teststrategy.Row(rank, target, area, None, "High", "w", "UI")


def _strat(*rows):
    return teststrategy.Strategy("p", 1, tuple(rows))


def _info(us, mission="", deps=(), retest=False, cites=(), mcites=(), pos=0):
    return teststrategy.StoryInfo(
        us, mission, tuple(deps), retest, frozenset(cites), frozenset(mcites), pos
    )


S = _strat(
    _row(1, "M-checkout"),
    _row(None, "M-checkout-US5"),
    _row(2, "[srs §4]", _a("srs", "4")),
)
S2 = _strat(_row(2, "[srs §4]", _a("srs", "4")), _row(1, "[srs §7]", _a("srs", "7")))


def test_most_specific_match_wins():
    p = teststrategy.place(
        S, _info("M-checkout-US5", "M-checkout", cites={_a("srs", "4.1")})
    )
    assert (p.how, p.row.target, p.tier) == ("id", "M-checkout-US5", 3)
    assert teststrategy.place(S, _info("M-checkout-US1", "M-checkout")).how == "mission"


def test_area_match_uses_ticket_then_mission_cites_best_rank():
    p = teststrategy.place(
        S2, _info("M-x-US1", "M-x", mcites={_a("srs", "4.2"), _a("srs", "7")})
    )
    assert p.how == "area" and p.row.rank == 1


def test_ticket_cites_shadow_mission_cites():
    p = teststrategy.place(
        S2, _info("M-x-US1", "M-x", cites={_a("srs", "4.2")}, mcites={_a("srs", "7")})
    )
    assert p.row.rank == 2


def test_no_match_is_outside_and_no_strategy_too():
    assert teststrategy.place(S, _info("Z-US1", "Z")).how == "outside"
    p = teststrategy.place(None, _info("Z-US1", "Z"))
    assert (p.how, p.row, p.tier) == ("outside", None, 2)


def test_order_retest_ranked_unranked_last():
    st = _strat(_row(1, "R1"), _row(2, "R2"), _row(None, "LAST"), _row(None, "RETEST"))
    stories = [
        _info("R2", pos=0),
        _info("OUT", pos=1),
        _info("RETEST", retest=True, pos=2),
        _info("LAST", pos=3),
        _info("R1", pos=4),
    ]
    got = teststrategy.order(st, stories)
    assert [p.story for p in got] == ["RETEST", "R1", "R2", "OUT", "LAST"]
    assert got[0].tier == 0 and got[0].row.target == "RETEST" and got[0].how == "id"


def test_depends_on_inside_tier_only():
    st = _strat(_row(1, "A"), _row(1, "B"), _row(1, "C"), _row(3, "D"), _row(2, "E"))
    stories = [
        _info("A", deps=["B"], pos=0),
        _info("B", pos=1),
        _info("C", deps=["D"], pos=2),
        _info("D", pos=3),
        _info("E", pos=4),
    ]
    got = [p.story for p in teststrategy.order(st, stories)]
    assert got == ["B", "A", "C", "E", "D"]


def test_retests_order_by_rank_then_last_then_unmatched():
    st = _strat(_row(1, "X"), _row(None, "Y"))
    stories = [
        _info("Y", retest=True, pos=0),
        _info("Z", retest=True, pos=1),
        _info("X", retest=True, pos=2),
    ]
    got = teststrategy.order(st, stories)
    assert [p.story for p in got] == ["X", "Y", "Z"]
    assert {p.tier for p in got} == {0}


def test_dependency_cycle_terminates():
    st = _strat(_row(1, "X"), _row(1, "Y"))
    got = teststrategy.order(
        st, [_info("X", deps=["Y"], pos=0), _info("Y", deps=["X"], pos=1)]
    )
    assert sorted(p.story for p in got) == ["X", "Y"]


def test_no_strategy_is_plan_order():
    got = teststrategy.order(None, [_info("b", pos=1), _info("a", pos=0)])
    assert [p.story for p in got] == ["a", "b"]


def test_empty_rows_lists_rows_without_stories():
    assert [r.target for r in teststrategy.empty_rows(S, [])] == [
        r.target for r in S.rows
    ]
    got = teststrategy.empty_rows(S, [_info("M-checkout-US1", "M-checkout")])
    assert [r.target for r in got] == ["M-checkout-US5", "[srs §4]"]
