"""`strategyhub.next_stories` and `kb test next`."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from strata_kb import strategyhub, teststrategy, ticketclaim
from strata_kb.cli import app
from tests.test_planstatus import HISTORY, US
from tests.test_strategyhub import STRATEGY_FOR_PLAN_HUB, US1, _doc
from tests.test_testflow import _text, publish_tests


def _two_done(hub):
    """US1 and US3 done in dev-svc: two testable stories."""
    hist = hub.federation_dir / "dev-one/dev-svc/history.md"
    hist.write_text(HISTORY + f"| {US[2]} | Story 3 | |\n", encoding="utf-8")


def _next(plan_hub, tmp_path, *extra, strategy: str | bytes | None = None):
    file = tmp_path / "s.md"
    if isinstance(strategy, bytes):
        file.write_bytes(strategy)
    elif strategy is not None:
        file.write_text(strategy, encoding="utf-8")
    kb = tmp_path / ".kb"
    kb.mkdir(exist_ok=True)
    args = ["test", "next", "--file", str(file), "--kb-dir", str(kb)]
    return CliRunner().invoke(app, [*args, "--hub", str(plan_hub.root), *extra])


def test_next_stories_testable_only_in_order(plan_hub):
    strategy = teststrategy.parse(STRATEGY_FOR_PLAN_HUB)
    assert [p.story for p in strategyhub.next_stories(plan_hub, strategy)] == [US1]


def test_next_stories_without_strategy_is_plan_order(plan_hub):
    _two_done(plan_hub)
    got = [p.story for p in strategyhub.next_stories(plan_hub, None)]
    assert got == [US[0], US[2]]


def test_next_stories_unknown_plan_raises(plan_hub):
    strategy = teststrategy.parse(STRATEGY_FOR_PLAN_HUB.replace("ba-one", "nope"))
    with pytest.raises(LookupError, match="no plan for 'nope'"):
        strategyhub.next_stories(plan_hub, strategy)


def test_next_stories_skips_testing_story(plan_hub):
    store = ticketclaim.ClaimStore(ticketclaim.claims_db_path(plan_hub.root))
    store.take("ba-one", US1, "tester-1", role="tester")
    assert strategyhub.next_stories(plan_hub, None) == []


def test_cli_test_next_first_and_all(plan_hub, tmp_path):
    res = _next(plan_hub, tmp_path, strategy=STRATEGY_FOR_PLAN_HUB)
    assert res.exit_code == 0
    lines = res.stdout.splitlines()
    assert len(lines) == 1 and lines[0].startswith(US1)
    assert "tier=1" in lines[0] and "how=" in lines[0] and "row=" in lines[0]
    _two_done(plan_hub)
    res = _next(plan_hub, tmp_path, strategy=STRATEGY_FOR_PLAN_HUB)
    assert len(res.stdout.splitlines()) == 1
    res = _next(plan_hub, tmp_path, "--all", strategy=STRATEGY_FOR_PLAN_HUB)
    got = [ln.split()[0] for ln in res.stdout.splitlines()]
    assert res.exit_code == 0 and got == [US[0], US[2]]


def test_cli_test_next_json_shape(plan_hub, tmp_path):
    res = _next(plan_hub, tmp_path, "--json", strategy=STRATEGY_FOR_PLAN_HUB)
    assert res.exit_code == 0
    (item,) = json.loads(res.stdout)
    assert set(item) == {"story", "tier", "rank", "how", "target"}
    assert item["story"] == US1


def test_cli_test_next_nothing_testable_exits_3(plan_hub, tmp_path):
    publish_tests(plan_hub.root, "qa-repo", US1, _text(US1, 1))
    res = _next(plan_hub, tmp_path, "--json", strategy=STRATEGY_FOR_PLAN_HUB)
    assert res.exit_code == 3 and json.loads(res.stdout) == []
    res = _next(plan_hub, tmp_path, strategy=STRATEGY_FOR_PLAN_HUB)
    assert res.exit_code == 3 and "nothing testable" in res.stdout


def test_cli_test_next_unreadable_strategy_warns(plan_hub, tmp_path):
    res = _next(plan_hub, tmp_path, strategy=b"\xff\xfe\x00bad")
    assert res.exit_code == 0 and res.stdout.startswith(US1)
    assert "no usable" in res.stderr


def test_cli_test_next_no_plan_strategy_warns(plan_hub, tmp_path):
    doc = _doc("").replace("> Plan: ba-one", "> Plan: —")
    res = _next(plan_hub, tmp_path, strategy=doc)
    assert res.exit_code == 0 and "names no plan" in res.stderr


def test_cli_test_next_unknown_plan_exits_1(plan_hub, tmp_path):
    res = _next(
        plan_hub, tmp_path, strategy=STRATEGY_FOR_PLAN_HUB.replace("ba-one", "nope")
    )
    assert res.exit_code == 1 and "no plan for 'nope'" in res.stderr
