"""Key phrases the tester skills must keep (task 12)."""

from importlib import resources
from pathlib import Path

import pytest

BASE = resources.files("strata_kb").joinpath("templates/init")
SKILLS = ("tester-env-setup", "tester-test-story", "tester-strategy")


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
    manual = t[: t.index("\n## Auto mode")]
    assert "Never merge it" in manual  # manual mode: a human merges
    assert "kb pr merge" not in manual and "gh pr merge" not in manual


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
        "`Known:` line",
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


def test_env_setup_has_no_auto_mode_section():
    assert "\n## Auto mode" not in _body("tester-env-setup")


def test_strategy_body_has_auto_mode():
    t = _body("tester-strategy")
    for p in ("\n## Auto mode", "auto/strategy", "**Auto decision:**"):
        assert p in t, p
    assert "not available yet" not in t
    assert "Auto never drops a row" in t
    assert "AUTO-RESULT: failed broken-target <target>" in t
    assert t.index("**Branch.**") < t.index("**Allowed changes.**")
    assert "replaces `--amend` step 1" in t
    assert "git switch --detach origin/<default>" in t
    assert "Never merge" in t


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
    for phrase in (
        "Verdict: PASS",
        "no baseline",
        "> Environment:",
        "git fetch origin",
    ):
        assert phrase in t, phrase
    assert "seed and reset scripts" in t


def test_env_setup_never_types_credentials_through_mcp():
    t = _body("tester-env-setup")
    assert "Never type a password" in t
    assert "tests/fixtures/login.smoke.spec.ts" in t
    assert "STRATA_KB_HTTP_TOKEN" in t and "keep every other line" in t


def test_branch_starts_from_origin_default_and_regression_reads_origin():
    t = _body("tester-test-story")
    assert "git switch -c test/<story>-R<n> origin/<default>" in t
    assert "git pull" not in t
    assert "git show origin/<default>:reports/" in t
    assert "-fsS" in t and "use exactly this shape" in t


def test_env_setup_writes_fe_url_and_role_env_convention():
    t = _body("tester-env-setup")
    assert "TEST_FE_URL" in t
    assert "TEST_<ROLE>_USER" in t and "TEST_<ROLE>_PASSWORD" in t


def test_body_uses_the_exact_allowed_curl_and_has_a_default_branch_fallback():
    from strata_kb.initcmd import TESTER_ALLOW

    t = _body("tester-test-story")
    exact = next(r for r in TESTER_ALLOW if r.startswith("Bash(curl"))[
        len("Bash(") : -1
    ]
    assert exact in t
    assert "git remote show origin" in t and "HEAD branch:" in t
    assert "when your branch lacks them" not in t
    assert "first app in `apps`" in _body("tester-env-setup")


def test_skill_regression_block_matches_the_report_parser():
    import re

    from strata_kb import testreport
    from tests.test_testreport import _report

    skill = _body("tester-test-story")
    block = re.search(r"```\n\s*(## Regression\n.*?)```", skill, re.S)
    assert block, "skill must show the `## Regression` block it writes"
    lines = [ln.strip() for ln in block.group(1).splitlines()]
    body = "\n".join(lines[1:]).strip()
    r = testreport.parse(_report(regression=body))
    assert r.regression_ran
    assert r.regression_failed == ("ST-0/TC-3", "ST-0/TC-4")
    assert r.known == ("ST-0/TC-5",)
    assert "known: <story> R<n>" not in skill


def test_skill_stops_when_the_known_failures_call_fails():
    t = _body("tester-test-story")
    assert "exits non-zero" in t and "stop the round" in t
    assert "never treat a" in t


def test_test_story_body_checks_testability_before_anything_is_held():
    t = _body("tester-test-story").split("## Steps", 1)[1]
    assert "kb mission next --from-hub" in t
    assert t.index("kb mission next --from-hub") < t.index("kb test-env lock")
    assert t.index("kb mission next --from-hub") < t.index("kb claim take")
    for phrase in ("fix-done", "`reopened`", "closed", "holding nothing"):
        assert phrase in t, phrase


def test_env_setup_never_receives_secret_values():
    t = " ".join(_body("tester-env-setup").split())
    assert "never ask for, receive or read a secret value" in t.lower()
    assert "`NAME=` placeholder" in t and "editor" in t
    assert "Never ask for the values" in t
    assert "the secret values the" not in t  # old step 4 took them in chat


def test_test_story_never_publishes_by_hand():
    t = _body("tester-test-story")
    assert "Never run `kb publish`" in t
    assert "kb publish" not in t.replace("Never run `kb publish`", "")


def test_only_no_version_check_may_be_confirmed_by_hand():
    t = " ".join(_body("tester-test-story").split())
    assert "every printed reason is `no version_check`" in t
    assert "`not in test-env apps` included" in t


def test_strategy_body_names_its_commands_and_modes():
    t = _body("tester-strategy")
    for p in (
        "kb strategy lint",
        "kb test stale --json",
        "kb context new",
        "kb report-ingest",
        "--amend",
        "kb mission next --from-hub --json",
        "`broken-target`",
        "`pin-moved`",
        "`coverage`",
        "`kb-context`",
        "`tc-revision`",
        "kb context new --refs",
        "leave it\n     for `/tester-test-story`",
        "point the Tester to New mode",
        "git switch -c strategy/rev-<N> origin/<default>",
        "docs/test-review-rubric.local.md",
        "never blocks `/tester-test-story`",
    ):
        assert p in t, p


def test_strategy_does_not_need_a_test_environment():
    # Docs-only projects write the strategy before any environment exists.
    t = _body("tester-strategy")
    assert "stop and tell" not in t
    assert "`.kb/test-env.yaml` is optional" in t
    assert "not set up yet" in t
    assert "`/tester-env-setup` before the first `/tester-test-story`" in t


def test_rubric_has_the_strategy_axes():
    r = BASE.joinpath("test-review-rubric.md").read_text(encoding="utf-8")
    assert "## Strategy axes" in r
    axes = r.split("## Strategy axes", 1)[1]
    assert len([ln for ln in axes.splitlines() if ln.startswith("- [ ]")]) == 5
    assert "when `.kb/test-env.yaml` exists" in axes
    for key in ("High", "evidence", ".kb/test-env.yaml", "silently missing", "reorder"):
        assert key in axes, key
    for key in ("High", "evidence"):
        line = next(ln for ln in axes.split("- [ ]") if key in ln)
        assert "**BLOCKER**" in line, key


def test_test_story_no_argument_proposes_next_story():
    t = _body("tester-test-story")
    head = t.split("## Steps", 1)[0]
    assert "kb test next --json" in head and "exit 3" in head
    assert "never blocks" in head


def test_changelog_mentions_test_next():
    log = (Path(__file__).parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "kb test next" in log.split("## 1.37.2", 1)[0]


def test_test_story_auto_mode_section():
    from strata_kb.autorun.claude import TESTER_RESULT_FORMS

    t = _body("tester-test-story")
    assert "\n## Auto mode\n" in t
    auto = t[t.index("\n## Auto mode\n") :]
    assert auto.index("### Result line") > auto.index("kb auto status --json")
    for form in TESTER_RESULT_FORMS:
        assert f"`{form}`" in auto, form
    for needle in (
        "kb pr merge --squash --delete-branch",
        "kb pr checks --watch",
        "kb pr view --json",
        "blocked-env <story> not-deployed",
        "blocked-env <story> env-locked",
        "blocked-env <story> claim-taken",
        "blocked-env <story> env-unhealthy",
        "failed test-review no-subagents",
        "failed test-review <id>",
        "incomplete <story>",
        "--phase review --pr <pr-url>",
        "--state all --json",
        "report-pr-closed <pr-url>",
        "kb claim take <story>",
        "do not release the claim after `kb pr open`",
    ):
        assert needle in auto, needle
    assert "reserved for the unattended runner" not in t


@pytest.mark.parametrize(
    "rel",
    (
        ".claude/skills/tester-test-story/SKILL.md",
        ".github/prompts/tester-test-story.prompt.md",
        ".cursor/commands/tester-test-story.md",
    ),
)
def test_rendered_test_story_skills_carry_the_auto_section(tmp_path, rel):
    from tests.test_init_tester import init_repo

    init_repo(tmp_path, "tester")
    text = (tmp_path / rel).read_text(encoding="utf-8")
    assert "\n## Auto mode\n" in text
    assert "kb pr merge --squash --delete-branch" in text


def test_test_story_crash_check_is_fresh_and_adopts_only_own_prs():
    auto = _body("tester-test-story").split("\n## Auto mode", 1)[1]
    check = auto.split("**Deploy check (step 2).**", 1)[0]
    assert "git switch --detach origin/<default>" in check
    assert "Let `<n>` be the row's `test_round` plus one" in check
    assert check.index("Let `<n>`") < check.index("kb pr find")
    merged = check.index("`origin/<default>` already holds `reports/<story>/R<n>.md`")
    assert merged < check.index("kb pr find")  # merged, unpublished: done
    assert "has not published it yet" in check
    assert "one more than the highest" not in check
    assert "git rev-parse --verify test/<story>-R<n>" in check
    assert "AUTO-RESULT: blocked-review <pr-url>" in check  # someone else's PR


def test_test_story_not_testable_stop_has_a_result_line():
    auto = _body("tester-test-story").split("\n## Auto mode", 1)[1]
    para = auto.split("**Not testable (step 1).**", 1)[1].split("**Deploy", 1)[0]
    assert "`closed` ends `AUTO-RESULT: done`" in para
    assert "AUTO-RESULT: blocked-env <story> claim-taken" in para


@pytest.mark.parametrize("name", ["tester-test-story", "tester-strategy"])
def test_intro_merge_ban_is_qualified_for_auto_mode(name):
    intro = _body(name).split("\n## ", 1)[0]
    assert "outside Auto mode" in intro
