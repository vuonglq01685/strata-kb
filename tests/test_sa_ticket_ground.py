import pytest
from importlib import resources

from tests.test_templates import SA_FULL_WRAPPERS, SA_WRAPPERS, _normalised, _read_init_template


def _after_frontmatter(text: str) -> str:
    assert text.startswith("---\n"), "no frontmatter"
    end = text.index("\n---\n", 4) + len("\n---\n")
    return text[end:]


def test_sa_ticket_ground_templates_exist_as_package_resources():
    base = resources.files("strata_kb").joinpath("templates/init")
    for name in SA_WRAPPERS:
        assert base.joinpath(name).is_file(), name


def test_sa_ticket_ground_is_wired_into_ba_only():
    from strata_kb.initcmd import BA_TEMPLATES, expected_files

    wanted = {
        ".claude/skills/sa-ticket-ground/SKILL.md": "claude-skill-sa-ticket-ground.md",
        ".claude/commands/sa-ticket-ground.md": "claude-command-sa-ticket-ground.md",
        ".github/prompts/sa-ticket-ground.prompt.md": "copilot-sa-ticket-ground.prompt.md",
        ".cursor/commands/sa-ticket-ground.md": "cursor-sa-ticket-ground.md",
    }
    for path, resource in wanted.items():
        assert BA_TEMPLATES[path] == resource, path
    for kind in ("hub", "child", "dev"):
        for path in wanted:
            assert path not in expected_files(kind), (kind, path)


def test_sa_full_wrappers_are_byte_identical_after_frontmatter():
    bodies = [_after_frontmatter(_read_init_template(n)) for n in SA_FULL_WRAPPERS]
    for name, body in zip(SA_FULL_WRAPPERS, bodies):
        assert body == bodies[0], f"{name} drifted from {SA_FULL_WRAPPERS[0]}"


def test_copilot_and_cursor_sa_wrappers_differ_only_on_frontmatter_line_2():
    copilot = _read_init_template("copilot-sa-ticket-ground.prompt.md").splitlines()
    cursor = _read_init_template("cursor-sa-ticket-ground.md").splitlines()
    assert copilot[1] == "mode: agent"
    assert cursor[1] == "name: sa-ticket-ground"
    assert copilot[:1] + copilot[2:] == cursor[:1] + cursor[2:]


def test_claude_skill_sa_ticket_ground_has_expected_frontmatter():
    text = _read_init_template("claude-skill-sa-ticket-ground.md")
    assert text.startswith("---\n")
    assert "name: sa-ticket-ground\n" in text
    assert "/sa-ticket-ground" in text


def test_claude_command_sa_ticket_ground_is_a_skill_invoker():
    text = _normalised(_read_init_template("claude-command-sa-ticket-ground.md"))
    assert "Invoke the `sa-ticket-ground` skill with the Skill tool" in text
    assert "--mission" in text


SA_HARD_RULE_NEEDLES = (
    "Grounded on:",
    "Open decisions",
    "[NEW:",
    "kb ticket check",
    "internal flow",
    "failure modes",
    "BA-owned section",
    "is not a PASS",
    "Definition of Ready",
)


@pytest.mark.parametrize("name", SA_WRAPPERS)
def test_sa_wrappers_carry_the_grounding_hard_rules(name):
    text = _normalised(_read_init_template(name))
    for needle in SA_HARD_RULE_NEEDLES:
        assert needle in text, f"{name}: missing {needle!r}"


@pytest.mark.parametrize("name", SA_FULL_WRAPPERS)
def test_sa_full_wrappers_carry_the_workflow_and_sources(name):
    text = _normalised(_read_init_template(name))
    for step in ("Intake", "Load", "Fill", "Gate", "Handover"):
        assert f"**{step}**" in text, f"{name}: missing step {step}"
    for needle in (
        "no repository access",
        "Never infer",
        "struct.tree",
        "cmd.test",
        "--mission",
        "do **not** load `db.*` or `api.*`",
        "The record has no directory field",
        "depth 4 and 600 lines",
        "Never edit a BA-owned section",
        "not a reviewer",
    ):
        assert needle in text, f"{name}: missing {needle!r}"


@pytest.mark.parametrize("name", SA_WRAPPERS)
def test_sa_wrappers_never_offer_flow_or_failure_fields(name):
    text = _read_init_template(name)
    assert "- Flow:" not in text
    assert "- Failure modes:" not in text
