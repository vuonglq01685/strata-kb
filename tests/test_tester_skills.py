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
    assert idx == sorted(idx), dict(zip(order, idx, strict=True))
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


def test_branch_switch_comes_before_push_and_default_is_refused():
    t = _body("tester-test-story")
    assert t.index("git switch -c test/<story>-R<n>") < t.index("git push")
    assert "Never write, commit or push on the default branch" in t
    assert "refuse to commit or push" in t


def test_every_stop_path_releases():
    t = _body("tester-test-story")
    assert "kb claim release <story>`; exit" not in t
    # claim-taken stop unlocks
    assert "exit 3 means taken: unlock (`kb test-env unlock`)" in t
    # INCOMPLETE / BLOCKED-ENV release whatever is still held
    assert "release whatever is still held (`kb test-env unlock`," in t
    # Q1/Q2 stop rule
    stop = t.split("**Stop.**", 1)[1]
    assert "release whatever is still held" in stop
    # fallback pause keeps claim and lock
    assert "A pause is not a stop" in t and "Tester-approved" in t


def test_script_defects_end_incomplete_and_never_edit_mid_round():
    t = _body("tester-test-story")
    assert "Never edit a script during a round" in t
    assert "is left" not in t


def test_lock_refreshed_and_deploy_exit_paths():
    t = _body("tester-test-story")
    assert t.count("kb test-env lock <story>") >= 3
    assert "no version_check" in t and "Exit 1" in t


def test_regression_inputs_are_defined():
    t = _body("tester-test-story")
    for phrase in ("Verdict: PASS", "no baseline", "> Environment:", "git pull"):
        assert phrase in t, phrase
    assert "seed and reset scripts" in t


def test_env_setup_never_types_credentials_through_mcp():
    t = _body("tester-env-setup")
    assert "Never type a password" in t
    assert "tests/fixtures/login.smoke.spec.ts" in t
    assert "STRATA_KB_HTTP_TOKEN" in t and "keep every other line" in t
