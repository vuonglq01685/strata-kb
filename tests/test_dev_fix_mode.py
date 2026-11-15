"""Dev skills fix mode: a reopened ticket is fixed from the tester's report."""

from importlib import resources

import pytest

BODIES = resources.files("strata_kb").joinpath("templates/init/bodies")
FIX_BODIES = ["dev-implement-ticket.md", "dev-fix-bug.md"]


def _body(name: str) -> str:
    return BODIES.joinpath(name).read_text(encoding="utf-8")


def _fix_section(name: str) -> str:
    text = _body(name)
    start = text.index("## Fix mode (reopened)")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None]


@pytest.mark.parametrize("name", FIX_BODIES)
def test_fix_mode_section_names_trigger_fetch_and_branch(name):
    section = _fix_section(name)
    for phrase in (
        '"test_status": "reopened"',
        "kb report fetch",
        "--child",
        "Guilty:",
        "fix/<id>-R<n>",
        "--fixes R<n>",
        "fix(<id>): R<n> defects D<k>",
    ):
        assert phrase in section, phrase


def test_implement_ticket_fix_mode_skips_design_and_plan():
    section = _fix_section("dev-implement-ticket.md")
    assert "no design or plan stage" in section.lower()


@pytest.mark.parametrize("name", FIX_BODIES)
def test_auto_mode_already_finished_checks_fix_row(name):
    text = _body(name)
    auto = text[text.index("## Auto mode") :]
    assert "fix:R<n>" in auto
    assert "Fix mode (reopened)" in auto


def test_handover_passes_fixes_and_checks_fix_row():
    text = _body("dev-handover.md")
    assert "--fixes R<n>" in text
    assert "report-R<n>.md" in text
    auto = text[text.index("## Auto mode") :]
    assert "fix:R<n>" in auto


def test_dev_auto_allowlist_permits_report_fetch():
    import json

    raw = resources.files("strata_kb").joinpath(
        "templates/init/claude-settings-auto.json"
    )
    allow = json.loads(raw.read_text(encoding="utf-8"))["permissions"]["allow"]
    assert "Bash(kb report fetch*)" in allow


@pytest.mark.parametrize("name", FIX_BODIES)
def test_fix_mode_saves_mcp_report_and_branches_first(name):
    section = _fix_section(name)
    assert "returns text only" in section
    assert "save it yourself as `docs/impl/<id>/report-R<n>.md`" in section
    assert "Fetched from hub" in section
    assert "0. Branch first" in section
    assert "git switch -c fix/<id>-R<n> FETCH_HEAD" in section
    assert (
        "`## Expected result` decides" if name == "dev-fix-bug.md" else "ACs decide"
    ) in section
    assert "`git switch fix/<id>-R<n>` instead" in section
    assert "State the mode in your first reply" in section


@pytest.mark.parametrize("name", FIX_BODIES)
def test_auto_fix_branch_replaces_reentry_branch_rules(name):
    text = _body(name)
    auto = text[text.index("## Auto mode") :]
    assert "replaces the Re-entry and branch-and-base rules" in auto


def test_handover_overrides_title_and_reads_gitignored_report():
    text = _body("dev-handover.md")
    assert "the PR title is `fix(<id>): R<n> defects D<k>[, D<k>]`, replacing" in text
    assert "git-ignored" in text
    assert "highest `R<n>`" in text


def test_dev_fix_bug_fix_mode_has_no_freshness_step_and_skips_intake_branch():
    section = _fix_section("dev-fix-bug.md")
    assert "Freshness" not in section
    assert "Intake (not its branch step" in section
