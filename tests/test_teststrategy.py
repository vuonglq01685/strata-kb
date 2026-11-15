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
