"""Key phrases the tester skills must keep (task 12)."""

from importlib import resources

import pytest

BASE = resources.files("strata_kb").joinpath("templates/init")
SKILLS = ("tester-env-setup", "tester-test-story")


def _body(name: str) -> str:
    return BASE.joinpath("bodies", f"{name}.md").read_text(encoding="utf-8")


def test_test_story_body_orders_the_pipeline():
    t = _body("tester-test-story").split("## Steps", 1)[1]
    order = [
        "kb ticket fetch",
        "kb test-env deployed",
        "kb test-env lock",
        "kb claim take",
        "kb testcase lint",
        "Q1",
        "Clean retry",
        "MCP confirmation",
        "Regression run",
        "Post-check",
        "kb report lint",
        "Q2",
        "kb report-ingest",
        "kb pr open",
    ]
    idx = [t.index(p) for p in order]
    assert idx == sorted(idx), dict(zip(order, idx))
    # the claim is released after the PR is opened
    assert t.index("kb claim release", t.index("kb pr open")) > t.index("kb pr open")
    assert t.index("deployed") < t.index("lock") < t.index("Q1")
    assert t.index("regression") < t.index("Q2") < t.index("report-ingest")


def test_test_story_body_never_merges():
    t = _body("tester-test-story")
    assert "never merge" in t
    assert "kb pr merge" not in t and "gh pr merge" not in t


def test_test_story_body_pins_outcomes_and_rules():
    t = _body("tester-test-story")
    for phrase in (
        "not deployed yet",
        "/api/tests/known-failures",
        "kb test-env changed",
        "kb test-env reset",
        "kb test-env seed",
        "Playwright MCP",
        "docs/templates/test-cases.md",
        "docs/templates/test-report.md",
        "tests/<story>/ticket.md",
        "INCOMPLETE",
        "BLOCKED-ENV",
        "local run log",
        "test-case-reviewer",
        "test-report-reviewer",
        "docs/test-review-rubric.md",
        "docs/test-review-rubric.local.md",
        "| Date | Round | Verdict | Reviewer | Coverage | Open gaps |",
        "AUTO-RESULT: failed test-review",
        "Alternate flows coverage",
        "reopened",
        "known: ",
        "`retries`",
    ):
        assert phrase in t, phrase
    for phase in ("cases", "scripts", "run", "report", "review", "publishing"):
        assert f"--phase {phase}" in t, phase


def test_test_story_body_releases_on_any_stop():
    t = _body("tester-test-story")
    assert "on any stop" in t
    steps = t.split("## Steps", 1)[1]
    assert "kb test-env unlock" in steps[steps.index("Post-check") :][:300]


def test_env_setup_body_keeps_secrets_out_of_yaml():
    t = _body("tester-env-setup")
    for phrase in (
        ".env",
        "names only",
        ".kb/test-env.example.yaml",
        ".kb/test-env.yaml",
        "kb test-env check",
        "kb test-env verify",
        "tests/fixtures/login.ts",
        "Playwright MCP",
        "never echo",
        "ok",
        "FAIL",
    ):
        assert phrase in t, phrase
    assert t.index("kb test-env check") < t.index("kb test-env verify")


@pytest.mark.parametrize("name", SKILLS)
def test_bodies_have_no_auto_mode_section(name):
    # kb auto for tester is phase 3; the settings allowlist test scans these.
    assert "\n## Auto mode" not in _body(name)
