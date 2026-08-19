from importlib import resources

from center_kb.initcmd import COMMON_TEMPLATES, HUB_TEMPLATES, CHILD_TEMPLATES

WEB_TEMPLATES = [
    "base.html", "login.html", "overview.html", "search.html",
    "docs.html", "doc.html", "section.html", "error.html",
    "_partials/status.html", "_partials/left_rail.html", "_partials/cards.html",
    "static/style.css", "static/app.js",
]

# Package resources only (Task 4) — not yet wired into a *_TEMPLATES map;
# that wiring (kind `ba`) lands in Task 5.
BA_TICKET_AUTHOR_TEMPLATES = [
    "claude-skill-ba-ticket-author.md",
    "claude-command-ba-ticket-author.md",
    "copilot-ba-ticket-author.prompt.md",
    "cursor-ba-ticket-author.md",
]

BA_TICKET_AUTHOR_PIPELINE_STEPS = (
    "Intake", "Parent mission", "Ground", "Draft", "Pin", "Lint", "Review",
)


def test_all_web_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/web")
    for name in WEB_TEMPLATES:
        assert base.joinpath(name).is_file(), name


def test_all_init_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for mapping in (COMMON_TEMPLATES, HUB_TEMPLATES, CHILD_TEMPLATES):
        for resource_name in mapping.values():
            assert base.joinpath(resource_name).is_file(), resource_name


def _read_init_template(name: str) -> str:
    base = resources.files("center_kb").joinpath("templates/init")
    return base.joinpath(name).read_text(encoding="utf-8")


def test_ba_ticket_author_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for name in BA_TICKET_AUTHOR_TEMPLATES:
        assert base.joinpath(name).is_file(), name


def test_ba_ticket_author_templates_carry_the_seven_pipeline_steps():
    for name in BA_TICKET_AUTHOR_TEMPLATES:
        text = _read_init_template(name)
        for step in BA_TICKET_AUTHOR_PIPELINE_STEPS:
            assert step in text, f"{name}: missing pipeline step {step!r}"


def test_ba_ticket_author_templates_carry_the_hard_rules_markers():
    for name in BA_TICKET_AUTHOR_TEMPLATES:
        text = _read_init_template(name)
        assert "never push to jira" in text.lower(), name
        assert "never tick" in text.lower(), name
        assert "definition of ready" in text.lower(), name
        assert "kb_context_new" in text, name
        assert "kb ticket lint" in text, name
        assert "tickets/" in text, name
        assert "%%TODO: verify against codebase%%" in text, name


def test_claude_skill_ba_ticket_author_has_expected_frontmatter():
    text = _read_init_template("claude-skill-ba-ticket-author.md")
    assert "name: ba-ticket-author" in text
    expected_description = (
        "description: Draft a Dev-ready ticket (story, ACs, use cases, "
        "Mermaid diagrams) grounded in the KB with pinned citations. Use "
        "when a BA asks to write a user story / requirement / ticket, or "
        "invokes /ba-ticket-author."
    )
    assert expected_description in text


def test_copilot_ba_ticket_author_prompt_has_agent_mode():
    text = _read_init_template("copilot-ba-ticket-author.prompt.md")
    assert "mode: agent" in text


def test_ac_quality_doc_exists_and_is_wired_into_ba_kind():
    from center_kb.initcmd import BA_TEMPLATES

    base = resources.files("center_kb").joinpath("templates/init")
    assert base.joinpath("ac-quality.md").is_file()
    assert BA_TEMPLATES["docs/ac-quality.md"] == "ac-quality.md"


def test_ac_quality_doc_carries_the_banned_phrases():
    text = _read_init_template("ac-quality.md")
    for marker in (
        "configured",
        "đã cấu hình",
        "a subset",
        "responsive",
        "OPEN(<owner>)",
        "## Open questions",
    ):
        assert marker in text, marker


# The command variant is a thin pointer to the skill — v2 content markers
# only apply to the three full-content mirrors.
BA_TICKET_AUTHOR_FULL_TEMPLATES = [
    "claude-skill-ba-ticket-author.md",
    "copilot-ba-ticket-author.prompt.md",
    "cursor-ba-ticket-author.md",
]

BA_TICKET_AUTHOR_V2_MARKERS = (
    "docs/ac-quality.md",
    "OPEN(<owner>)",
    "## Dependencies",
    "## Non-functional requirements",
    "## UI / presentation spec",
    "## Out of scope",
    "## Test data & verification",
    "## Open questions",
    "canonical index",
)


def test_ba_ticket_author_templates_carry_the_v2_markers():
    for name in BA_TICKET_AUTHOR_FULL_TEMPLATES:
        text = _read_init_template(name)
        for marker in BA_TICKET_AUTHOR_V2_MARKERS:
            assert marker in text, f"{name}: missing v2 marker {marker!r}"


BA_MISSION_PLAN_TEMPLATES = [
    "claude-skill-ba-mission-plan.md",
    "claude-command-ba-mission-plan.md",
    "copilot-ba-mission-plan.prompt.md",
    "cursor-ba-mission-plan.md",
]

BA_MISSION_PLAN_V2_MARKERS = (
    "## Technology decisions",
    "## Sequencing",
    "## Open questions",
    "## Non-functional requirements",
    "split",
    "8 coded-value variants",
    "6 source entities",
)


def test_ba_mission_plan_templates_carry_the_v2_markers():
    for name in BA_MISSION_PLAN_TEMPLATES:
        text = _read_init_template(name)
        for marker in BA_MISSION_PLAN_V2_MARKERS:
            assert marker in text, f"{name}: missing v2 marker {marker!r}"


def test_weasel_phrases_all_appear_in_the_shipped_ac_quality_doc():
    from center_kb.acquality import WEASEL_PHRASES

    text = _read_init_template("ac-quality.md")
    for phrase in WEASEL_PHRASES:
        assert phrase in text, phrase


def test_every_quoted_doc_phrase_is_in_the_detector():
    import re as _re

    from center_kb.acquality import WEASEL_PHRASES

    text = _read_init_template("ac-quality.md")
    banned_col = [
        line.split("|")[1]
        for line in text.splitlines()
        if line.startswith("|") and '"' in line
    ]
    quoted = [
        phrase
        for cell in banned_col
        for phrase in _re.findall(r'"([^"]+)"', cell)
    ]
    assert quoted, "no quoted phrases parsed from the doc table"
    lowered = {p.lower() for p in WEASEL_PHRASES}
    for phrase in quoted:
        assert phrase.lower() in lowered, phrase


# --- maturity review rubric (BA review agents) ---


def test_review_rubric_doc_exists_and_is_wired_into_ba_kind():
    from center_kb.initcmd import BA_TEMPLATES

    base = resources.files("center_kb").joinpath("templates/init")
    assert base.joinpath("review-rubric.md").is_file()
    assert BA_TEMPLATES["docs/review-rubric.md"] == "review-rubric.md"


def test_review_rubric_doc_carries_both_axes_and_the_scale():
    text = _read_init_template("review-rubric.md")
    for marker in (
        "## Business coverage",
        "## Dev implementability",
        "## Maturity scale",
        "## Scoring rule",
        "OPEN(<owner>)",
        "## Review record",
        "docs/ac-quality.md",
    ):
        assert marker in text, marker


def test_both_document_templates_carry_the_review_record_section():
    for name in ("ticket-template.md", "mission-template.md"):
        text = _read_init_template(name)
        assert text.count("## Review record") == 1, name
        assert "Not yet reviewed." in text, name
        assert "docs/review-rubric.md" in text, name
        assert "| Date | Round | Business | Dev | Reviewer |" in text, name


BA_REVIEW_MARKERS = (
    "Maturity review",
    "docs/review-rubric.md",
    "## Review record",
    "Business-coverage",
    "Dev-implementability",
)


def test_ba_ticket_author_templates_carry_the_maturity_review_step():
    for name in BA_TICKET_AUTHOR_FULL_TEMPLATES:
        text = _read_init_template(name)
        for marker in BA_REVIEW_MARKERS:
            assert marker in text, f"{name}: missing {marker!r}"


# The skill mirror runs its review subagents IN PARALLEL; the cursor and
# copilot mirrors (no subagent support) fall back to sequential review
# passes run by the BA themselves. Pin that split so the two styles don't
# drift back into each other.
def test_ba_ticket_author_templates_pin_the_parallel_vs_sequential_split():
    skill_text = _read_init_template("claude-skill-ba-ticket-author.md")
    assert "IN PARALLEL" in skill_text

    for name in ("cursor-ba-ticket-author.md", "copilot-ba-ticket-author.prompt.md"):
        text = _read_init_template(name)
        assert "sequential review passes yourself" in text, name
        assert "IN PARALLEL" not in text, name


def test_ba_mission_plan_templates_carry_the_maturity_review_step():
    for name in BA_MISSION_PLAN_TEMPLATES:
        text = _read_init_template(name)
        for marker in BA_REVIEW_MARKERS:
            assert marker in text, f"{name}: missing {marker!r}"


# --- Phase 5 Stage A: the dev workflow wrappers -----------------------------

DEV_WORKFLOW_SKILLS = (
    "dev-implement-ticket",
    "dev-design",
    "dev-plan",
    "dev-execute",
    "dev-handover",
)


def _dev_wrapper_names(skill: str) -> tuple[str, ...]:
    return (
        f"claude-skill-{skill}.md",
        f"claude-command-{skill}.md",
        f"copilot-{skill}.prompt.md",
        f"cursor-{skill}.md",
    )


def test_dev_implement_ticket_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for name in _dev_wrapper_names("dev-implement-ticket"):
        assert base.joinpath(name).is_file(), name


def test_dev_implement_ticket_carries_the_five_orchestrator_steps():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        text = _read_init_template(name)
        for step in ("Intake", "Resolve", "Ground", "Placeholders", "Run the phases"):
            assert step in text, f"{name} missing step {step}"


def test_dev_implement_ticket_uses_resolve_and_get_never_diff():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        text = _read_init_template(name)
        assert "kb_resolve" in text, name          # MCP tool
        assert "kb resolve" in text, name          # CLI fallback
        assert "kb get " in text, name             # current hub version
        assert "kb diff" not in text.replace("Do NOT use `kb diff`", ""), name


def test_dev_implement_ticket_checks_ticket_dependencies():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        text = _read_init_template(name)
        assert "## Dependencies" in text, name
        assert "Sequencing" in text, name
        assert "Blocked by" in text, name


def test_dev_implement_ticket_carries_placeholder_and_ticket_ownership_rules():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        text = _read_init_template(name)
        assert "%%TODO: verify against codebase%%" in text, name
        assert "never edit the ticket" in text, name
        assert "OPEN(BA)" in text, name


def test_claude_skill_dev_implement_ticket_has_expected_frontmatter():
    text = _read_init_template("claude-skill-dev-implement-ticket.md")
    assert text.startswith("---\n")
    assert "name: dev-implement-ticket\n" in text
    assert "/dev-implement-ticket" in text


def test_copilot_dev_implement_ticket_prompt_has_agent_mode():
    text = _read_init_template("copilot-dev-implement-ticket.prompt.md")
    assert "mode: agent" in text


def test_claude_command_dev_implement_ticket_is_a_skill_invoker():
    text = _read_init_template("claude-command-dev-implement-ticket.md")
    assert "Invoke the `dev-implement-ticket` skill with the Skill tool" in text


def test_dev_design_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for name in _dev_wrapper_names("dev-design"):
        assert base.joinpath(name).is_file(), name


def test_dev_design_carries_the_three_paths_and_the_ratchet():
    for name in _dev_wrapper_names("dev-design"):
        text = _read_init_template(name)
        for path in ("spike", "bounded", "architectural"):
            assert path in text, f"{name} missing path {path}"
        assert "one-way" in text, name
        assert "take the heavier one" in text, name


def test_dev_design_writes_the_design_file_only_on_the_architectural_path():
    for name in _dev_wrapper_names("dev-design"):
        text = _read_init_template(name)
        assert "docs/impl/<ticket-id>-design.md" in text, name
        assert "architectural path only" in text, name


def test_dev_design_carries_gate_one_and_the_ac_rule():
    for name in _dev_wrapper_names("dev-design"):
        text = _read_init_template(name)
        assert "GATE 1" in text, name
        assert "OPEN(BA)" in text, name
        assert "reinterpreting an ac is forbidden" in text.lower(), name


def test_claude_skill_dev_design_has_expected_frontmatter():
    text = _read_init_template("claude-skill-dev-design.md")
    assert "name: dev-design\n" in text


def test_copilot_dev_design_prompt_has_agent_mode():
    assert "mode: agent" in _read_init_template("copilot-dev-design.prompt.md")


def test_dev_plan_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for name in _dev_wrapper_names("dev-plan"):
        assert base.joinpath(name).is_file(), name


def test_dev_plan_requires_one_task_per_ac_with_a_test():
    for name in _dev_wrapper_names("dev-plan"):
        text = _read_init_template(name)
        assert "one task per AC" in text, name
        assert "names the test that proves it" in text, name


def test_dev_plan_pins_the_plan_file_and_checkbox_shape():
    for name in _dev_wrapper_names("dev-plan"):
        text = _read_init_template(name)
        assert "docs/impl/<ticket-id>-plan.md" in text, name
        assert "- [ ]" in text, name
        for heading in ("Files", "Interfaces", "Steps"):
            assert f"**{heading}**" in text, f"{name} missing {heading}"


def test_dev_plan_first_step_is_always_the_failing_test():
    for name in _dev_wrapper_names("dev-plan"):
        text = _read_init_template(name)
        assert "step 1 always being the failing test" in text, name


def test_dev_plan_closes_with_cross_cutting_verification_from_cmd_sections():
    for name in _dev_wrapper_names("dev-plan"):
        text = _read_init_template(name)
        assert "cmd." in text, name
        assert "GATE 2" in text, name


def test_claude_skill_dev_plan_has_expected_frontmatter():
    assert "name: dev-plan\n" in _read_init_template("claude-skill-dev-plan.md")


def test_copilot_dev_plan_prompt_has_agent_mode():
    assert "mode: agent" in _read_init_template("copilot-dev-plan.prompt.md")


def test_dev_execute_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for name in _dev_wrapper_names("dev-execute"):
        assert base.joinpath(name).is_file(), name


def test_dev_execute_isolates_the_workspace_before_touching_code():
    for name in _dev_wrapper_names("dev-execute"):
        text = _read_init_template(name)
        assert "worktree" in text, name
        assert "Never work directly on the default branch" in text, name


def test_dev_execute_demands_an_observed_failing_test():
    for name in _dev_wrapper_names("dev-execute"):
        text = _read_init_template(name)
        assert "observe it fail" in text, name
        assert "never seen red proves nothing" in text, name


def test_dev_execute_has_a_review_checkpoint_and_shown_verification():
    for name in _dev_wrapper_names("dev-execute"):
        text = _read_init_template(name)
        assert "review checkpoint" in text, name
        assert "cmd.test" in text and "cmd.lint" in text, name
        assert "show the output" in text, name


def test_dev_execute_forbids_editing_tests_and_deciding_ambiguous_acs():
    for name in _dev_wrapper_names("dev-execute"):
        text = _read_init_template(name)
        assert "Never edit a test to make it green" in text, name
        assert "return to `dev-design`" in text, name


def test_dev_execute_is_resumable():
    for name in _dev_wrapper_names("dev-execute"):
        text = _read_init_template(name)
        assert "first unticked task" in text, name


def test_claude_skill_dev_execute_has_expected_frontmatter():
    assert "name: dev-execute\n" in _read_init_template("claude-skill-dev-execute.md")


def test_copilot_dev_execute_prompt_has_agent_mode():
    assert "mode: agent" in _read_init_template("copilot-dev-execute.prompt.md")
