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
