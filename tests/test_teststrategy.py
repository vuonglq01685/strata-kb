from importlib import resources

import pytest

from strata_kb import lintcore, teststrategy

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
