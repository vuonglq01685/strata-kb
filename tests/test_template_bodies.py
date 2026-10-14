"""Shared template bodies (1.15.2): a skill's Copilot and Cursor copies, and
for seven skills its Claude skill too, are frontmatter stubs that end in one
include directive; the text they share lives once in templates/init/bodies/.
`kb init` writes the rendered text, never a directive."""

from __future__ import annotations

import re
from importlib import resources

import pytest

from strata_kb.initcmd import KINDS, init_repo, read_template

DIRECTIVE = re.compile(r"<!-- strata-kb:include (bodies/[a-z0-9-]+\.md) -->")
BASE = resources.files("strata_kb").joinpath("templates/init")


def _templates() -> list[str]:
    return sorted(f.name for f in BASE.iterdir() if f.is_file())


def _stubs() -> dict[str, str]:
    stubs = {}
    for name in _templates():
        match = DIRECTIVE.search(BASE.joinpath(name).read_text(encoding="utf-8"))
        if match:
            stubs[name] = match.group(1)
    return stubs


def test_every_body_is_shared_by_at_least_two_stubs():
    by_body: dict[str, list[str]] = {}
    for stub, body in _stubs().items():
        by_body.setdefault(body, []).append(stub)
    bodies = sorted(f"bodies/{f.name}" for f in BASE.joinpath("bodies").iterdir())
    assert sorted(by_body) == bodies  # no orphan body, no missing one
    for body, stubs in by_body.items():
        assert len(stubs) >= 2, (body, stubs)


@pytest.mark.parametrize("name", sorted(_stubs()))
def test_a_stub_is_frontmatter_its_own_short_intro_and_the_directive(name):
    raw = BASE.joinpath(name).read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    after = raw[raw.index("\n---\n", 4) + len("\n---\n") :]
    lines = [line for line in after.splitlines() if line.strip()]
    assert DIRECTIVE.fullmatch(lines[-1])
    # Only what genuinely differs per tool stays in the stub: a heading, and
    # for some skills an intro paragraph; everything shared is in the body.
    assert len(lines) <= 20, lines
    assert raw.count("strata-kb:include") == 1


@pytest.mark.parametrize("name", _templates())
def test_no_rendered_template_carries_a_directive(name):
    assert "strata-kb:include" not in read_template(name)


def test_stubs_of_one_skill_render_one_shared_body():
    for stub, body in _stubs().items():
        shared = BASE.joinpath(body).read_text(encoding="utf-8")
        assert read_template(stub).endswith(shared), stub


@pytest.mark.parametrize("kind", KINDS)
def test_kb_init_writes_rendered_text(tmp_path, kind):
    init_repo(tmp_path, kind)
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".mdc"}:
            assert "strata-kb:include" not in path.read_text(encoding="utf-8"), path


@pytest.mark.parametrize(
    "name",
    [
        "claude-skill-dev-implement-ticket.md",
        "claude-command-dev-implement-ticket.md",
        "copilot-dev-implement-ticket.prompt.md",
        "cursor-dev-implement-ticket.md",
    ],
)
def test_dev_implement_ticket_runs_ticket_check(name):
    text = " ".join(read_template(name).split())
    assert "kb ticket check docs/impl/<id>/ticket.md" in text, name
    assert "re-run /sa-ticket-ground" in text, name


def _body(name: str) -> str:
    return " ".join(BASE.joinpath("bodies", name).read_text(encoding="utf-8").split())


@pytest.mark.parametrize("name", ["ba-mission-plan.md", "ba-ticket-author.md"])
def test_ba_bodies_search_kb_and_dev_kinds(name):
    assert "--kind kb --kind dev" in _body(name)
    assert 'kinds=["kb","dev"]' in _body(name)


def test_dev_implement_ticket_names_each_kind_it_searches():
    text = _body("dev-implement-ticket.md")
    for kind in ("--kind dev", "--kind ba", "--kind kb"):
        assert kind in text, kind


@pytest.mark.parametrize(
    "text",
    [
        _body("dev-implement-ticket.md"),
        " ".join(read_template("claude-skill-dev-implement-ticket.md").split()),
    ],
    ids=["body", "claude-skill"],
)
def test_dev_implement_ticket_restricts_dev_search_to_own_repo(text):
    for suffix in ("code", "svc"):
        assert f"--tags <repo_id>-{suffix}" in text
        assert f'tags=["<repo_id>-{suffix}"]' in text


def test_sa_ticket_ground_searches_dev_kind():
    assert "--kind dev" in _body("sa-ticket-ground.md")


def test_kb_code_sync_searches_kb_kind():
    assert "--kind kb" in _body("kb-code-sync.md")


@pytest.mark.parametrize("name", ["dev-design.md", "dev-plan.md", "dev-execute.md"])
def test_dev_flow_bodies_carry_no_kind_filter(name):
    assert "--kind" not in _body(name)


@pytest.mark.parametrize(
    "name",
    [
        "claude-skill-kb-publish.md",
        "cursor-kb-publish.md",
        "copilot-kb-publish.prompt.md",
    ],
)
def test_kb_publish_confirm_shows_hub_menu_line(name):
    text = " ".join(read_template(name).split())
    assert "hub menu" in text, name
    assert "kb init --kind" in text, name
    assert "`hub` and `child` repos → Document" in text, name
    assert "`kind:` in `.kb/config.yaml`" in text, name
    assert "`[info] kind: …` line `kb doctor` prints" in text, name


HUB_READERS = [
    "ba-mission-plan",
    "ba-ticket-author",
    "dev-design",
    "dev-execute",
    "dev-handover",
    "dev-implement-ticket",
    "dev-plan",
    "sa-ticket-ground",
]


def _rendered_copies(skill: str) -> list[str]:
    return [
        f"claude-skill-{skill}.md",
        f"claude-command-{skill}.md",
        f"cursor-{skill}.md",
        f"copilot-{skill}.prompt.md",
    ]


def _stepped_copies(skill: str) -> list[str]:
    # The claude-command copy is condensed prose with no step labels.
    return [n for n in _rendered_copies(skill) if not n.startswith("claude-command")]


@pytest.mark.parametrize("name", [n for s in HUB_READERS for n in _rendered_copies(s)])
def test_hub_reading_skills_reach_the_hub_through_mcp_first(name):
    text = " ".join(read_template(name).split())
    assert "Hub access — MCP first" in text, name
    assert "(CLI, primary)" not in text, name
    assert "`kb_ticket_lint` as a fallback" not in text, name


# Every hub-reading command a skill runs has an MCP tool: MCP first, the CLI
# only as the fallback.
_MCP_TWINS = {
    "kb mission lint": "kb_mission_lint",
    "kb ticket stale": "kb_ticket_stale",
    "kb ticket fetch": "kb_ticket_fetch",
    "kb ticket check": "kb_ticket_check",
}


def _hub_access_rule(text: str) -> str:
    start = text.index("Hub access — MCP first")
    return text[start : text.index("##", start)]


@pytest.mark.parametrize("name", [n for s in HUB_READERS for n in _rendered_copies(s)])
def test_hub_commands_name_their_mcp_tool_first(name):
    text = " ".join(read_template(name).split())
    rule = _hub_access_rule(text)
    for cli, tool in _MCP_TWINS.items():
        if cli in text:
            assert tool in rule, (name, tool)
    cli_only = [
        sentence
        for sentence in rule.split(". ")
        if "no MCP tool" in sentence
        or "CLI-first" in sentence
        or "stay CLI" in sentence
    ]
    for sentence in cli_only:
        for cli in _MCP_TWINS:
            assert f"`{cli}" not in sentence, (name, cli, sentence)
    assert "There is no MCP fallback" not in text, name


def _mcp_before_cli(text: str, step: str, tool: str, cli: str, name: str) -> None:
    at = text.index(step)
    assert text.index(tool, at) < text.index(cli, at), (name, step)


@pytest.mark.parametrize("name", _stepped_copies("ba-mission-plan"))
def test_ba_mission_plan_lints_and_sweeps_through_mcp_first(name):
    text = " ".join(read_template(name).split())
    _mcp_before_cli(text, "**Lint**", "kb_mission_lint", "kb mission lint", name)
    amend = text.index("## Amend mode")
    _mcp_before_cli(
        text[amend:], "**Read**", "kb_ticket_stale", "kb ticket stale", name
    )


@pytest.mark.parametrize("name", _stepped_copies("ba-ticket-author"))
def test_ba_ticket_author_sweeps_through_mcp_first(name):
    text = " ".join(read_template(name).split())
    amend = text.index("## Amend mode")
    _mcp_before_cli(
        text[amend:], "**Read**", "kb_ticket_stale", "kb ticket stale", name
    )


@pytest.mark.parametrize("name", _stepped_copies("dev-implement-ticket"))
def test_dev_implement_ticket_fetches_and_checks_through_mcp_first(name):
    text = " ".join(read_template(name).split())
    _mcp_before_cli(text, "get the ticket", "kb_ticket_fetch", "kb ticket fetch", name)
    _mcp_before_cli(
        text, "**Check the grounding**", "kb_ticket_check", "kb ticket check", name
    )


@pytest.mark.parametrize("name", _stepped_copies("ba-ticket-author"))
def test_ba_ticket_author_lints_through_mcp_before_the_cli(name):
    text = " ".join(read_template(name).split())
    lint = text.index("**Lint**")
    assert text.index("kb_ticket_lint", lint) < text.index("kb ticket lint", lint), name


@pytest.mark.parametrize("name", _stepped_copies("dev-implement-ticket"))
def test_dev_implement_ticket_grounds_through_mcp_before_the_cli(name):
    text = " ".join(read_template(name).split())
    ground = text.index("**Ground**")
    assert text.index("kb_search", ground) < text.index("kb query", ground), name
    assert text.index("kb_get_section", ground) < text.index("kb get", ground), name
    # #100: a push to main publishes nothing; `kb publish` does.
    assert "on merge to the default branch" not in text, name


@pytest.mark.parametrize("name", _templates())
def test_no_template_claims_a_merge_publishes(name):
    # #100: a dev repo publishes from a kb-publish/* tag (`kb publish`), never
    # on a push or merge to the default branch.
    text = " ".join(read_template(name).split())
    for claim in ("published it on merge", "on merge to the default branch"):
        assert claim not in text, name


# --- ba-answer-questions (ticket Q&A, BA side) ---------------------------------


def test_ba_answer_questions_body_pins_the_workflow_phrases():
    text = _body("ba-answer-questions.md")
    for phrase in (
        "kb_question_list",
        "kb_question_answer",
        "Trigger `question`",
        "one amendment per ticket",
        "do not record any answer for a ticket whose Definition of Ready"
        " is not fully ticked",
        "never commits, pushes or publishes",
        "answer_rev",
        "waiting for publish",
        "Q&A needs the shared hub server — point MCP at it (kb mcp-setup)",
        "kb ticket lint",
    ):
        assert phrase in text, phrase


def test_ba_answer_questions_requires_mcp_because_the_cli_has_no_twin():
    text = _body("ba-answer-questions.md")
    assert "Hub access — MCP first" in text
    assert "no CLI" in text
    assert "MCP is required" in text


def test_ba_ticket_author_amend_lists_the_question_trigger_for_qa_only():
    for name in (
        "claude-skill-ba-ticket-author.md",
        "claude-command-ba-ticket-author.md",
        "cursor-ba-ticket-author.md",
    ):
        text = " ".join(read_template(name).split())
        assert "`question`" in text, name
        assert "only for amendments made from `/ba-answer-questions`" in text, name


def test_ba_answer_questions_hub_link_comes_from_hub_url_env_not_mcp_json():
    text = _body("ba-answer-questions.md")
    assert "`STRATA_KB_HUB_URL`" in text
    assert "never show `STRATA_KB_HTTP_TOKEN`" in text
    assert "If it is unset, give the path only" in text
    assert "host in `.mcp.json`" not in text


def test_ba_answer_questions_records_none_only_when_the_hub_carries_the_answer():
    text = _body("ba-answer-questions.md")
    assert "only when the HUB revision already carries the answer" in text
    assert "hub rev" in text
    assert "local revision R higher than the hub revision" in text
    assert "never bump the revision again" in text
    assert "it already says it" not in text


def test_ba_answer_questions_records_nothing_until_lint_passes():
    text = _body("ba-answer-questions.md")
    assert "Until `kb ticket lint` passes, record nothing for that ticket" in text


def test_ba_answer_questions_names_the_answer_call_arguments_and_ticket_filter():
    text = _body("ba-answer-questions.md")
    assert "`id` (an integer: the number without the `Q`)" in text
    assert "`answer` (the BA's words)" in text
    assert "`ticket_sections` is a list of section names" in text
    assert "pass `ticket=<ticket>`" in text
    assert 'kb_question_list(repo=<repo-id>, status="waiting")' in text


def test_ba_answer_questions_claude_command_matches_the_body_rules():
    text = " ".join(read_template("claude-command-ba-answer-questions.md").split())
    assert "plus `ticket=` when a ticket is given" in text
    assert "record nothing for that ticket" in text
    assert "`STRATA_KB_HUB_URL`" in text
    assert "only when the HUB revision" in text


# --- dev skills: BA questions, resume, and dev-sa (ticket Q&A, Dev side) -------

HUB_ONLY_ERROR = "Q&A needs the shared hub server — point MCP at it (kb mcp-setup)"

_AUTHOR_BODIES = [
    ("dev-design.md", "design-author"),
    ("dev-plan.md", "plan-author"),
]


@pytest.mark.parametrize(("name", "author"), _AUTHOR_BODIES)
def test_dev_design_and_plan_route_raised_questions_through_the_orchestrator(
    name, author
):
    text = _body(name)
    for phrase in (
        f"The `{author}` subagent never calls the hub",
        "## Questions raised",
        "tagged `business` or `technical`",
        "blocks: <AC ids|none>",
        "dispatch `dev-sa`",
        "## Technical decisions",
        "- SA-<n>: <decision> — why — evidence",
        "then re-dispatch the author",
        "kb_question_ask",
        "## Open questions",
        "- Q<id> — <question> — blocks: <AC ids|none>",
        "returns `business question:`",
    ):
        assert phrase in text, (name, phrase)


@pytest.mark.parametrize(("name", "author"), _AUTHOR_BODIES)
def test_dev_design_and_plan_gate_on_blocking_questions_only(name, author):
    text = _body(name)
    for phrase in (
        "A blocking open BA question stops the gate",
        "A non-blocking open BA question does not stop the gate",
        "known open item, not a defect",
        "hub Q&A link",
    ):
        assert phrase in text, (name, phrase)


@pytest.mark.parametrize(("name", "author"), _AUTHOR_BODIES)
def test_dev_design_and_plan_stop_on_the_hub_only_error_and_guard_the_link(
    name, author
):
    text = _body(name)
    assert HUB_ONLY_ERROR in text, name
    assert 'a stop, never "no questions"' in text, name
    assert "`STRATA_KB_HUB_URL`" in text, name
    assert "never show `STRATA_KB_HTTP_TOKEN`" in text, name
    assert "give the path only" in text, name


@pytest.mark.parametrize(
    "name",
    [
        "claude-command-dev-design.md",
        "claude-command-dev-plan.md",
    ],
)
def test_dev_design_and_plan_claude_commands_carry_the_question_rules(name):
    text = " ".join(read_template(name).split())
    for phrase in (
        "never calls the hub",
        "## Questions raised",
        "dispatch `dev-sa`",
        "kb_question_ask",
        "A blocking open BA question stops the gate",
        HUB_ONLY_ERROR,
    ):
        assert phrase in text, (name, phrase)


def test_dev_execute_open_ba_returns_to_design_which_asks_through_qa():
    for text in (
        _body("dev-execute.md"),
        " ".join(read_template("claude-command-dev-execute.md").split()),
    ):
        assert "`dev-design` asks the BA through hub Q&A" in text
        assert "`OPEN(BA)`" in text


@pytest.mark.parametrize(
    "name",
    [
        "claude-skill-dev-implement-ticket.md",
        "claude-command-dev-implement-ticket.md",
        "copilot-dev-implement-ticket.prompt.md",
        "cursor-dev-implement-ticket.md",
    ],
)
def test_dev_implement_ticket_resumes_from_the_question_states(name):
    text = " ".join(read_template(name).split())
    for phrase in (
        "kb_question_list(ticket=",
        "status=all",
        "**answered**",
        "kb_ticket_fetch",
        "— answered rev N",
        "back to `dev-design`",
        "**waiting**",
        "information only",
        "**open**",
        "do not continue past the gate",
        "BA-Q: open Q<ids>",
        HUB_ONLY_ERROR,
        'never treat it as "no questions"',
    ):
        assert phrase in text, (name, phrase)


def test_dev_sa_body_pins_inputs_sources_output_and_limits():
    text = _body("dev-sa.md")
    for phrase in (
        "docs/impl/<id>/ticket.md",
        "the current design or plan draft",
        "kb_search",
        "kb_get_section",
        "decision, reasoning, rejected alternatives",
        "`path:line`",
        "`doc §section`",
        "business question: <why>",
        "what an AC means",
        "never writes to the hub",
        "- SA-<n>: <decision> — why — evidence",
    ):
        assert phrase in text, phrase
