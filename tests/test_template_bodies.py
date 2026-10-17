"""Shared template bodies (1.15.2): a skill's Copilot and Cursor copies, and
for seven skills its Claude skill too, are frontmatter stubs that end in one
include directive; the text they share lives once in templates/init/bodies/.
`kb init` writes the rendered text, never a directive."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

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


HUB_RULE_FILES = sorted(
    p.name if p.parent == BASE else f"bodies/{p.name}"
    for p in (*BASE.iterdir(), *BASE.joinpath("bodies").iterdir())
    if p.name.endswith(".md") and "Hub access — MCP first" in p.read_text("utf-8")
)


@pytest.mark.parametrize("name", HUB_RULE_FILES)
def test_hub_access_rule_counts_a_blocked_cli_as_no_cli(name):
    text = " ".join(BASE.joinpath(name).read_text(encoding="utf-8").split())
    rule = _hub_access_rule(text)
    assert "**A blocked CLI counts as no CLI.**" in rule, name
    for cause in ("not installed", "denies it", "refuses", "cannot reach the hub"):
        assert cause in rule, (name, cause)
    assert "not a denial to report" in rule, name


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
    assert "or the question is no longer needed" in text


# --- dev skills: BA questions, resume, and dev-sa (ticket Q&A, Dev side) -------

HUB_ONLY_ERROR = "Q&A needs the shared hub server — point MCP at it (kb mcp-setup)"

_IMPLEMENT_TICKET_FORMS = [
    "claude-skill-dev-implement-ticket.md",
    "claude-command-dev-implement-ticket.md",
    "copilot-dev-implement-ticket.prompt.md",
    "cursor-dev-implement-ticket.md",
]

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
        "A blocking open BA question (a question line without `— answered rev N` "
        "whose `blocks:` names an AC) stops the gate",
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
        "BA-Q: unknown (Q&A unavailable)",
        "If every `Q<id>` line carries `— answered rev N` (or there are none), "
        "continue with `BA-Q: unknown (Q&A unavailable)`",
        "if any `Q<id>` line lacks it, STOP and tell the Dev",
        'never treating it as "no questions"'
        if name.startswith("claude-command")
        else 'never treat it as "no questions"',
        "`answer_rev`",
        "back to `status: draft`",
        "blocks no AC",
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


# --- fix round 1: author dispatch, rubric, BA-Q derivation, dev-sa limits ----

_AUTHOR_DISPATCH = [
    ("dev-design.md", "claude-command-dev-design.md"),
    ("dev-plan.md", "claude-command-dev-plan.md"),
]


@pytest.mark.parametrize(("body", "command"), _AUTHOR_DISPATCH)
def test_author_dispatch_carries_the_questions_rule(body, command):
    texts = (_body(body), " ".join(read_template(command).split()))
    for text in texts:
        for phrase in (
            "the Questions rule and preservation rule above",
            "lists what it could not decide under `## Questions raised`",
            "tags each item `business` or `technical` with `blocks: <AC ids|none>`",
            "never calls the hub or asks the BA itself",
            "After each author or fix round returns, handle its "
            "`## Questions raised` before the reviewer is dispatched",
        ):
            assert phrase in text, (body, phrase)


@pytest.mark.parametrize(("body", "command"), _AUTHOR_DISPATCH)
def test_gate_counts_only_question_lines_without_an_answered_marker(body, command):
    for text in (_body(body), " ".join(read_template(command).split())):
        assert "a question line without `— answered rev N`" in text, body
        assert "whose `blocks:` names an AC" in text, body
        assert "(the rubric's Pre-code axis says so)" in text, body
        assert "dev-sa" in text and "standard" in text and "tier" in text, body


@pytest.mark.parametrize(
    ("body", "command", "author"),
    [
        ("dev-design.md", "claude-command-dev-design.md", "design-author"),
        ("dev-plan.md", "claude-command-dev-plan.md", "plan-author"),
    ],
)
def test_only_a_re_draft_line_re_dispatches_the_author_once(body, command, author):
    for text in (_body(body), " ".join(read_template(command).split())):
        assert (
            f"once per `Q<id>` line carrying `— re-draft`, re-dispatch the `{author}` "
            "with the re-fetched ticket"
        ) in text, body
        assert "then strip that suffix" in text, body
        assert "the line keeps `— answered rev N`" in text, body
        assert "a question line without `— answered rev N`" in text, body
        assert "an answered line means re-dispatching" not in text, body


@pytest.mark.parametrize("name", _IMPLEMENT_TICKET_FORMS)
def test_implement_ticket_marks_only_new_answers_for_re_draft(name):
    text = " ".join(read_template(name).split())
    assert "`— answered rev N — re-draft`" in text, name
    assert "no `Q<id>` line without" not in text, name


@pytest.mark.parametrize("name", _IMPLEMENT_TICKET_FORMS)
def test_implement_ticket_names_the_repo_the_link_takes(name):
    text = " ".join(read_template(name).split())
    assert (
        "`?repo=<repo-id>`" not in text
    )  # the bare placeholder was ambiguous; the BA repo is named instead
    assert "the BA repo, as `kb_question_list` prints it in `<repo>:<ticket>`" in text


@pytest.mark.parametrize(("body", "command"), _AUTHOR_DISPATCH)
def test_author_and_fix_rounds_preserve_decisions_and_open_questions(body, command):
    for text in (_body(body), " ".join(read_template(command).split())):
        for phrase in (
            "Remove each handled item from `## Questions raised`.",
            "Every author and fix round keeps `## Technical decisions` and "
            "`## Open questions` verbatim and never re-raises a question already "
            "listed there.",
            "Before `kb_question_ask`, skip any item already in `## Open questions`.",
        ):
            assert phrase in text, (body, phrase)


@pytest.mark.parametrize(("body", "command"), _AUTHOR_DISPATCH)
def test_the_fix_subagent_gets_the_questions_and_preservation_rules(body, command):
    for text in (_body(body), " ".join(read_template(command).split())):
        assert (
            "The fix subagent gets the same Questions rule and preservation rule "
            "as the author."
        ) in text, body
        assert "the Questions rule and preservation rule above" in text, body


@pytest.mark.parametrize(("body", "command"), _AUTHOR_DISPATCH)
def test_unavailable_qa_stops_only_a_blocking_question(body, command):
    for text in (_body(body), " ".join(read_template(command).split())):
        for phrase in (
            "`Q&A store error — see hub log`",
            "`hub unreachable — queries need the hub federation`",
            "treat each as Q&A unavailable",
            "a `business` item with `blocks: none` falls back to the pre-1.27 "
            "behaviour",
            "`OPEN(BA)` in the draft",
            "a note in the PR description",
            "only a blocking one stops",
            "ask the Dev for a name once",
        ):
            assert phrase in text, (body, phrase)


def test_no_template_asserts_the_open_questions_line_in_the_artefact():
    for name in (
        "dev-design.md",
        "dev-plan.md",
    ):
        assert "Asked of the BA" not in _body(name), name
    for name in (
        "claude-command-dev-design.md",
        "claude-command-dev-plan.md",
    ):
        assert "Asked of the BA" not in read_template(name), name


def test_pr_review_rubric_pre_code_axis_accepts_a_hub_question_as_open_ba():
    text = " ".join(read_template("pr-review-rubric.md").split())
    assert (
        "An ambiguity is carried either as `OPEN(BA)` or as a `## Open questions` "
        "`Q<id>` asked through hub Q&A, never resolved by guessing."
    ) in text
    assert (
        "A listed question with `blocks: none` is a known open item, not a gap." in text
    )
    assert "carried as `OPEN(BA)`, never" not in text


@pytest.mark.parametrize(
    "name",
    [
        "bodies/dev-design.md",
        "bodies/dev-plan.md",
        "bodies/dev-execute.md",
        "bodies/dev-handover.md",
        "claude-command-dev-design.md",
        "claude-command-dev-plan.md",
        "claude-command-dev-execute.md",
        "claude-command-dev-handover.md",
    ],
)
def test_local_skills_derive_ba_q_from_the_local_question_lines(name):
    text = " ".join(BASE.joinpath(name).read_text(encoding="utf-8").split())
    assert "`BA-Q:` comes from the local `## Open questions` lines" in text, name
    assert "`open Q1; waiting Q2`" in text, name
    assert "`unknown (Q&A unavailable)`" in text, name


@pytest.mark.parametrize(
    "name",
    [
        "bodies/dev-implement-ticket.md",
        "claude-skill-dev-implement-ticket.md",
        "claude-command-dev-implement-ticket.md",
    ],
)
def test_implement_ticket_derives_ba_q_from_kb_question_list(name):
    text = " ".join(BASE.joinpath(name).read_text(encoding="utf-8").split())
    assert "`BA-Q:` comes from `kb_question_list`" in text, name
    assert "`open Q1; waiting Q2`" in text, name
    assert "Intake → Questions → Check" in text, name


def test_dev_sa_returns_text_only_and_names_the_business_reading():
    text = _body("dev-sa.md")
    assert "You return text only and never write the file" in text
    assert "write the file only when the Dev asks" not in text
    assert "What the AC could mean either way: <reading A> / <reading B>" in text
    assert "the standard tier, as for authors" in text
    command = " ".join(read_template("claude-command-dev-sa.md").split())
    assert "plus what the AC could mean either way" in command
    assert "It returns text only" in command


# --- full auto mode: BA skills take the auto path (Task 11) --------------------

AUTO_HEADING = "\n## Auto mode\n"
AUTO_OPENING = (
    "Run `kb auto status --json`. When `enabled` is false, this section does not "
    "apply. When true, the rules below replace the human gates named in them."
)
PRE_AUTO = Path(__file__).parent / "fixtures" / "bodies-pre-auto"

BA_AUTO_BODIES = ["ba-ticket-author", "ba-mission-plan", "ba-answer-questions"]
DEV_AUTO_BODIES = [
    "dev-implement-ticket",
    "dev-design",
    "dev-plan",
    "dev-execute",
    "dev-handover",
    "dev-fix-bug",
]
# The Dev claude skill/command files that are full copies of a body, not stubs
# over it: each carries the same section as its body.
DEV_FULL_COPIES = {
    "claude-skill-dev-implement-ticket.md": "dev-implement-ticket",
    "claude-command-dev-implement-ticket.md": "dev-implement-ticket",
    "claude-command-dev-design.md": "dev-design",
    "claude-command-dev-plan.md": "dev-plan",
    "claude-command-dev-execute.md": "dev-execute",
    "claude-command-dev-handover.md": "dev-handover",
}
KB_PUBLISH_COPIES = [
    "claude-skill-kb-publish.md",
    "copilot-kb-publish.prompt.md",
    "cursor-kb-publish.md",
]
# Template file -> fixture holding its text before this task. The Claude
# ba-ticket-author skill and ba-mission-plan command are full copies, not stubs
# over the shared body, and kb-publish is three separate files; each gets the
# same section appended.
AUTO_FILES = {
    **{f"bodies/{n}.md": f"{n}.md" for n in BA_AUTO_BODIES},
    "claude-skill-ba-ticket-author.md": "claude-skill-ba-ticket-author.md",
    "claude-command-ba-mission-plan.md": "claude-command-ba-mission-plan.md",
    **{n: n for n in KB_PUBLISH_COPIES},
    **{f"bodies/{n}.md": f"{n}.md" for n in DEV_AUTO_BODIES},
    **{n: n for n in DEV_FULL_COPIES},
}
# dev-test-workflow is new: it has no pre-auto text to snapshot.
NEW_AUTO_BODY = "bodies/dev-test-workflow.md"
ALL_AUTO_FILES = sorted([*AUTO_FILES, NEW_AUTO_BODY])


def _raw(template: str) -> str:
    return BASE.joinpath(template).read_text(encoding="utf-8")


def _auto_section(template: str) -> str:
    text = _raw(template)
    assert text.count(AUTO_HEADING) == 1, template
    return text[text.index(AUTO_HEADING) + 1 :]


def _bullets(section: str) -> list[str]:
    """Each top-level `- ` bullet of the section as one whitespace-joined line."""
    out: list[str] = []
    for line in section.splitlines():
        if line.startswith("- "):
            out.append(line[2:])
        elif out and line.startswith("  ") and line.strip():
            out[-1] += " " + line.strip()
        elif not line.strip() or line.startswith("#"):
            continue
        elif out and not line.startswith(("    ", "|")):
            out.append("")  # a paragraph ends the bullet run
    return [" ".join(b.split()) for b in out if b]


@pytest.mark.parametrize("name", BA_AUTO_BODIES)
def test_ba_body_has_auto_mode_section(name):
    section = _auto_section(f"bodies/{name}.md")
    text = " ".join(section.split())
    assert "AUTO-RESULT:" in text
    assert text.startswith(f"## Auto mode {AUTO_OPENING}")
    assert "**Auto decision:**" in text
    assert "### Result line" in section


@pytest.mark.parametrize("template", ALL_AUTO_FILES)
def test_auto_mode_is_the_last_h2_and_ends_with_the_result_line_subsection(template):
    section = _auto_section(template)
    assert section.index("### Result line") > section.index(AUTO_OPENING), template
    assert "\n## " not in section, template


@pytest.mark.parametrize("template", sorted(AUTO_FILES))
def test_off_path_text_is_unchanged(template):
    # Rule: everything before the `## Auto mode` heading, trailing blank lines
    # trimmed, equals the file as it stood before its Auto section (the fixture, same trim).
    before = _raw(template)
    before = before[: before.index(AUTO_HEADING)].rstrip("\n") + "\n"
    pre = (PRE_AUTO / AUTO_FILES[template]).read_text(encoding="utf-8")
    assert before == pre.rstrip("\n") + "\n", template


@pytest.mark.parametrize(
    "name", ["copilot-ba-ticket-author.prompt.md", "cursor-ba-ticket-author.md"]
)
def test_shared_ba_ticket_author_stubs_render_the_auto_section(name):
    assert read_template(name).endswith(_auto_section("bodies/ba-ticket-author.md"))


def test_claude_ba_ticket_author_skill_carries_the_same_auto_section():
    assert _auto_section("claude-skill-ba-ticket-author.md") == _auto_section(
        "bodies/ba-ticket-author.md"
    )


def test_claude_mission_plan_command_carries_the_same_auto_section():
    # The four ba-mission-plan wrappers are byte-identical from `## Workflow`.
    assert _auto_section("claude-command-ba-mission-plan.md") == _auto_section(
        "bodies/ba-mission-plan.md"
    )


def test_kb_publish_copies_carry_one_identical_auto_section():
    sections = {n: _auto_section(n) for n in KB_PUBLISH_COPIES}
    assert len(set(sections.values())) == 1, sections.keys()
    assert " ".join(sections[KB_PUBLISH_COPIES[0]].split()).startswith(
        f"## Auto mode {AUTO_OPENING}"
    )


def _gates(template: str) -> list[str]:
    return [b for b in _bullets(_auto_section(template)) if b.startswith("**")]


# Every gate of spec 6.7 that a BA skill names, as the body names it.
_BA_GATES = {
    "bodies/ba-ticket-author.md": [
        "Ask, don't guess",  # intake
        "never auto-pick",  # KB-ref pick
        "confirms which sections apply",  # pin
        "Every AC is Given/When/Then",  # the BA-only DoR box
        "Ask the BA for the trigger",  # amend trigger
        "never commits or pushes",  # runner-driven PR
    ],
    "bodies/ba-mission-plan.md": [
        "never auto-pick",
        "Ask the BA for the trigger",
        "You never flip a status",  # D-row OPEN -> DECIDED
        "never tick an open-question checkbox",  # open question with blocks:
        "never commits or pushes",
    ],
    "bodies/ba-answer-questions.md": [
        "never answer a question yourself",
        "ask them to re-check and re-tick",
        "never commits, pushes or publishes",
    ],
    **{n: ["go/no-go"] for n in KB_PUBLISH_COPIES},
}


# The Dev gates of spec 6.7, as the body names them (whitespace-normalised).
# Each fragment must also appear in the off path, so the Auto bullet quotes a
# gate that really exists there.
_DEV_GATES = {
    "bodies/dev-implement-ticket.md": [
        "blocked by something unmerged",
        "No `kb-context` block",
        "do not continue past the gate",
        "STOP and tell the Dev",
        "the Dev decides",
        "re-run /sa-ticket-ground",
        "humans decide",
        "after the Dev approves it",
        "ask before running `dev-plan`",
        "re-handover or reopen",
        "offer `git switch -c <ticket-id>`",
        "two tickets in flight",
        "never merge",
    ],
    "bodies/dev-design.md": [
        "GATE 1 — Dev approval before any plan is written",
        "ask the Dev for a name once",
        "stop and tell the Dev",
        "hand the Dev the trend",
        "goes to the Dev",
        "let the Dev choose",
        "the Dev's explicit go-ahead",
    ],
    "bodies/dev-plan.md": [
        "GATE 2",
        "ask the Dev once for the build/test/lint commands",
        "ask the Dev for a name once",
        "stop and tell the Dev",
        "hand the Dev the trend",
        "goes to the Dev, unfixed",
        "stops the flow and goes to the Dev",
        "let the Dev choose",
        "the Dev's explicit go-ahead",
    ],
    "bodies/dev-execute.md": [
        "a dedicated branch",
        "stop and send it back to `dev-plan`",
        "stop and return the task to `dev-plan`",
        "a plan defect: stop, do not resolve",
        "stop that task, return to `dev-design`",
        "goes to the Dev",
        "let the Dev choose",
        "the Dev's explicit go-ahead",
    ],
    "bodies/dev-handover.md": [
        "GATE 3",
        "humans decide",
        "tell the Dev to run `kb publish`",
        "goes to the Dev",
        "let the Dev choose",
        "the Dev's explicit go-ahead",
        "never merge",
    ],
    "bodies/dev-fix-bug.md": [
        "once the Dev agrees",
        "ask the Dev which production line",
        "the Dev decides",
        "Report to the BA what was tried",
        "question the architecture with the Dev",
        "The Dev opens the PR and merges",
        "ask the Dev for it first",
        "never merge",
    ],
}
_ALL_GATES = {**_BA_GATES, **_DEV_GATES}


def _normal(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("template", sorted(_DEV_GATES))
def test_every_dev_gate_fragment_is_in_the_off_path_text(template):
    raw = _raw(template)
    off = _normal(raw[: raw.index(AUTO_HEADING)])
    for fragment in _DEV_GATES[template]:
        assert fragment in off, (template, fragment)


@pytest.mark.parametrize("template", sorted(_ALL_GATES))
def test_every_replaced_gate_is_a_bullet_with_its_auto_rule(template):
    gates = _gates(template)
    for fragment in _ALL_GATES[template]:
        matching = [g for g in gates if fragment in g.split(" → ")[0]]
        assert matching, (template, fragment)
        assert all(" → " in g for g in matching), (template, fragment)


def test_ba_ticket_author_auto_ticks_dor_box():
    body = _body("ba-ticket-author.md")
    # the off path keeps the row, and points nowhere: a human ticks it
    assert (
        "| Every AC is Given/When/Then and acceptance-testable … | never — the BA's judgement |"
        in body
    )
    (gate,) = [
        g
        for g in _gates("bodies/ba-ticket-author.md")
        if "Every AC is Given/When/Then" in g
    ]
    for phrase in ("fresh-context", "tick", "docs/ac-quality.md", "rewrite"):
        assert phrase in gate, phrase
    assert "never — the BA's judgement" in gate


BRANCH_LINES = [
    "git fetch origin main && git switch -c auto/<ticket-id> FETCH_HEAD",
    "git push -u origin HEAD",
    'kb pr open --title "<ticket-id>: <short description>" --body',
    "kb pr checks --watch",
    "AUTO-RESULT: failed ci-red <pr-url>",
    "kb pr merge --squash --delete-branch",
    "kb pr merge --squash --admin --delete-branch",
    "kb pr view --json",
    "kb-publish-request.yml",
]


def test_branch_rule_is_written_once_in_ba_ticket_author():
    text = " ".join(_auto_section("bodies/ba-ticket-author.md").split())
    for line in BRANCH_LINES:
        assert line in text, line
    assert "up to 2 rounds" in text
    assert "never check out `main`" in text
    for name in ("ba-mission-plan.md", "ba-answer-questions.md"):
        other = " ".join(_auto_section(f"bodies/{name}").split())
        assert "the branch rule in ba-ticket-author's Auto mode" in other, name
        assert "git switch -c" not in other, name
    assert "auto/<mission-id>" in " ".join(
        _auto_section("bodies/ba-mission-plan.md").split()
    )
    assert "`auto/qa`" in " ".join(
        _auto_section("bodies/ba-answer-questions.md").split()
    )


@pytest.mark.parametrize("template", ALL_AUTO_FILES)
def test_result_line_contract_matches_parse_result(template):
    from strata_kb.autorun.claude import parse_result

    section = _auto_section(template)
    text = " ".join(section.split())
    assert "AUTO-RESULT: done" in text
    assert "AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]" in text
    assert "AUTO-RESULT: failed <reason>" in text
    assert "last line" in text
    assert parse_result("x\nAUTO-RESULT: done").kind == "done"
    assert parse_result("x\nAUTO-RESULT: failed ci-red https://h/pr/1").kind == "failed"
    assert parse_result("x\nAUTO-RESULT: blocked-qa Q1,Q2").ids == (1, 2)
    # `done` takes no text after it, and `failed` needs a reason
    assert "no text after `done`" in text
    assert "always give a reason" in text


def test_ba_skills_are_idempotent_on_finished_work():
    for template in (
        "bodies/ba-ticket-author.md",
        "bodies/ba-mission-plan.md",
        "bodies/ba-answer-questions.md",
        *KB_PUBLISH_COPIES,
    ):
        text = " ".join(_auto_section(template).split())
        assert "already finished" in text, template
        assert "AUTO-RESULT: done" in text, template


def test_kb_publish_auto_replaces_the_hard_rule_with_a_diff_review():
    text = " ".join(_auto_section("claude-skill-kb-publish.md").split())
    assert "NEVER run `kb publish` until the user has explicitly confirmed" in " ".join(
        _raw("claude-skill-kb-publish.md").split()
    )
    for phrase in ("reviews the diff", "kb doctor", "kb diff", "proceed"):
        assert phrase in text, phrase


def test_auto_sections_name_no_model_id():
    for template in ALL_AUTO_FILES:
        assert "claude-" not in _auto_section(template), template


@pytest.mark.parametrize("template", ALL_AUTO_FILES)
def test_no_auto_section_names_origin_main_in_a_branch_switching_command(template):
    # The deny list blocks `git switch|checkout|branch *main*`; deny beats allow.
    for line in _auto_section(template).splitlines():
        if re.search(r"git (switch|checkout|branch)", line):
            assert "origin/main" not in line, (template, line)
    assert "origin/main" not in _auto_section(template), template


def test_ticket_author_already_finished_uses_the_mission_next_status():
    text = " ".join(_auto_section("bodies/ba-ticket-author.md").split())
    assert "`ready` or `done` (not `draft` or `to-draft`)" in text
    assert "on `origin/main` with `DoR: PASS`" not in text


def test_mission_plan_separates_done_from_no_blocker():
    text = " ".join(_auto_section("bodies/ba-mission-plan.md").split())
    assert "kb pr find --state merged --head auto/<mission-id>" in text
    assert "no blocker and no such PR ever" in text


def test_answer_questions_resumes_a_crashed_run_from_the_remote_branch():
    text = " ".join(_auto_section("bodies/ba-answer-questions.md").split())
    assert "git fetch origin && git pull origin auto/qa" in text
    assert "git push -u origin HEAD" in text
    assert "answers still go through the PR and the merge" in text


def test_kb_publish_auto_leaves_publishing_to_the_merge_when_the_workflow_exists():
    text = " ".join(_auto_section("claude-skill-kb-publish.md").split())
    assert ".github/workflows/kb-publish-request.yml" in text
    assert "do not run `kb publish` by hand" in text
    assert "the merged PR that triggered it" in text


# --- Task 12: Dev skills take the auto path; dev-test-workflow ----------------

DEV_AUTO_ALL = [*DEV_AUTO_BODIES, "dev-test-workflow"]


@pytest.mark.parametrize("name", DEV_AUTO_ALL)
def test_dev_body_has_auto_mode_section(name):
    section = _auto_section(f"bodies/{name}.md")
    text = _normal(section)
    assert "AUTO-RESULT:" in text
    assert text.startswith(f"## Auto mode {AUTO_OPENING}")
    assert "**Auto decision:**" in text
    assert "### Result line" in section


@pytest.mark.parametrize("copy,body", sorted(DEV_FULL_COPIES.items()))
def test_dev_full_copies_carry_the_same_auto_section_as_their_body(copy, body):
    assert _auto_section(copy) == _auto_section(f"bodies/{body}.md")


def test_dev_stubs_render_their_auto_section():
    checked = 0
    for stub, body in _stubs().items():
        name = body.removeprefix("bodies/").removesuffix(".md")
        if name in DEV_AUTO_ALL:
            assert read_template(stub).endswith(_auto_section(body)), stub
            checked += 1
    assert checked >= len(DEV_AUTO_ALL)


def _dev_text(name: str) -> str:
    return _normal(_auto_section(f"bodies/{name}.md"))


def test_dev_handover_merges_publishes_and_names_the_admin_fallback():
    text = _dev_text("dev-handover")
    for line in DEV_BRANCH_LINES:
        assert line in text, line
    assert "kb pr merge --squash --admin --delete-branch" in text
    assert "kb publish" in text
    assert "kb svc note" in text
    assert "up to 2 rounds" in text
    assert "never merge on red or pending checks" in text.lower()
    assert "never check out `main`" not in text  # handover never creates a branch


DEV_BRANCH_LINES = [
    "git push -u origin HEAD",
    'kb pr open --title "<ticket-id>: <short description>" --body',
    "kb pr checks --watch",
    "AUTO-RESULT: failed ci-red <pr-url>",
    "kb pr merge --squash --delete-branch",
    "kb pr view --json",
    "--base <hotfix_base>",
]


def test_dev_implement_ticket_branches_at_once_and_ends_blocked_qa():
    text = _dev_text("dev-implement-ticket")
    assert "git fetch origin main && git switch -c auto/<ticket-id> FETCH_HEAD" in text
    assert "never check out `main`" in text
    assert "AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]" in text
    assert "kb_question_ask(" in text
    assert "kb_question_list" in text
    assert "git fetch origin && git switch auto/<ticket-id>" in text
    assert "git pull origin auto/<ticket-id>" in text


def test_dev_fix_bug_branches_at_once_and_reads_the_hotfix_base():
    text = _dev_text("dev-fix-bug")
    assert "hotfix_base" in text
    assert "kb auto status --json" in text
    assert "git fetch origin main && git switch -c fix/<BUG-id> FETCH_HEAD" in text
    assert "git fetch origin main && git switch -c hotfix/<BUG-id> FETCH_HEAD" in text
    assert (
        "git fetch origin <hotfix_base> && git switch -c hotfix/<BUG-id> FETCH_HEAD"
        in text
    )
    assert "--base <hotfix_base>" in text
    assert "blocked-qa" in text


@pytest.mark.parametrize(
    "name", ["dev-implement-ticket", "dev-handover", "dev-fix-bug", "dev-test-workflow"]
)
def test_dev_tasks_are_idempotent_on_finished_work(name):
    text = _dev_text(name)
    assert "already finished" in text.lower()
    assert "AUTO-RESULT: done" in text


def test_dev_resume_of_an_open_pr_pulls_the_remote_branch():
    for name in ("dev-implement-ticket", "dev-handover", "dev-fix-bug"):
        text = _dev_text(name)
        assert "git fetch origin &&" in text, name
        assert "git pull origin" in text, name
        assert "CI step" in text, name


def test_dev_phases_decide_review_gates_with_two_fix_rounds():
    for name, reason in (("dev-design", "design-review"), ("dev-plan", "plan-review")):
        text = _dev_text(name)
        assert "`status: approved`" in text, name
        assert "at most 2" in text, name
        assert f"AUTO-RESULT: failed {reason}" in text, name
        assert "fresh-context" in text or "fresh context" in text, name
        assert "blocked-qa" in text, name


def test_dev_plan_reads_commands_from_the_repo_never_asks():
    text = _dev_text("dev-plan")
    for source in (".github/workflows", "docs/conventions", "package.json"):
        assert source in text, source
    assert "never ask" in text.lower()


def test_dev_phases_only_report_to_the_orchestrator():
    for name in ("dev-design", "dev-plan", "dev-execute", "dev-handover"):
        text = _dev_text(name)
        assert "/dev-implement-ticket" in text, name
        assert "started you directly" in text, name


DEV_TEST_WORKFLOW_STUBS = [
    "claude-skill-dev-test-workflow.md",
    "claude-command-dev-test-workflow.md",
    "copilot-dev-test-workflow.prompt.md",
    "cursor-dev-test-workflow.md",
]


def test_dev_test_workflow_body_names_the_workflow_and_its_inputs():
    text = _normal(_raw("bodies/dev-test-workflow.md"))
    for needle in (
        ".github/workflows/kb-test.yml",
        "pull_request",
        "push",
        "langs:",
        "docs/conventions/<lang>/testing.md",
        "name: kb-test",
        "Run the tests locally first",
    ):
        assert needle in text, needle
    auto = _dev_text("dev-test-workflow")
    for needle in (
        "git fetch origin main && git switch -c auto/kb-test FETCH_HEAD",
        "git push -u origin HEAD",
        "kb pr checks --watch",
        "kb pr merge --squash --delete-branch",
        "kb pr merge --squash --admin --delete-branch",
        "AUTO-RESULT: failed ci-red <pr-url>",
    ):
        assert needle in auto, needle
    assert "origin/main" not in auto
    # off path: a human asked for it, the PR is left for the human to merge
    off = text[: text.index("## Auto mode")]
    assert "left for the human to merge" in off


@pytest.mark.parametrize("name", DEV_TEST_WORKFLOW_STUBS)
def test_dev_test_workflow_stubs_render_the_body(name):
    rendered = read_template(name)
    assert "strata-kb:include" not in rendered
    assert rendered.endswith(_raw("bodies/dev-test-workflow.md"))
    assert "kb-test.yml" in rendered


def test_kb_init_dev_writes_the_dev_test_workflow_wrappers_only_for_dev(tmp_path):
    for kind in ("dev", "ba"):
        target = tmp_path / kind
        target.mkdir()
        init_repo(target, kind)
        wrappers = [
            target / ".claude/skills/dev-test-workflow/SKILL.md",
            target / ".claude/commands/dev-test-workflow.md",
            target / ".github/prompts/dev-test-workflow.prompt.md",
            target / ".cursor/commands/dev-test-workflow.md",
        ]
        for path in wrappers:
            assert path.is_file() == (kind == "dev"), path
            if kind == "dev":
                text = path.read_text(encoding="utf-8")
                assert "kb-test.yml" in text and "strata-kb:include" not in text


def _allow_deny() -> tuple[list[str], list[str]]:
    import json

    perms = json.loads(_raw("claude-settings-auto.json"))["permissions"]

    def patterns(rules: list[str]) -> list[str]:
        return [r[len("Bash(") : -1] for r in rules if r.startswith("Bash(")]

    return patterns(perms["allow"]), patterns(perms["deny"])


def _permitted(command: str, allow: list[str], deny: list[str]) -> bool:
    from fnmatch import fnmatchcase

    ok = any(fnmatchcase(command, p) for p in allow)
    return ok and not any(fnmatchcase(command, p) for p in deny)


@pytest.mark.parametrize("template", ALL_AUTO_FILES)
def test_dev_auto_commands_are_inside_the_allowlist(template):
    if "dev-" not in template:
        pytest.skip("BA section")
    allow, deny = _allow_deny()
    section = _auto_section(template)
    seen = 0
    for span in re.findall(r"`([^`\n]+)`", section):
        for command in span.split(" && "):
            command = command.strip()
            if not re.match(r"(git|gh|kb) ", command):
                continue
            seen += 1
            assert _permitted(command, allow, deny), (template, command)
    assert seen, template


# --- Task 12 fix round 1 -------------------------------------------------------


@pytest.mark.parametrize("name", DEV_AUTO_ALL)
def test_dev_auto_sections_end_the_run_on_a_denied_command(name):
    text = _dev_text(name)
    assert "A command the permission system denies" in text
    assert "command-denied <command>" in text
    assert "Never work around a denial" in text


@pytest.mark.parametrize("name", DEV_AUTO_ALL)
def test_dev_auto_sections_run_mcp_for_a_denied_kb_command(name):
    text = _dev_text(name)
    assert "a denied `kb` command that has a `strata-kb` MCP tool" in text
    assert "counts as no CLI: run the MCP tool and carry on" in text


@pytest.mark.parametrize(
    "name", ["dev-design", "dev-plan", "dev-execute", "dev-handover"]
)
def test_dev_phases_report_a_denied_command_to_the_orchestrator(name):
    assert "report `command-denied <command>` to the orchestrator" in _dev_text(name)


def test_dev_plan_reads_kb_test_and_picks_lint_and_build_from_the_conventions():
    text = _dev_text("dev-plan")
    assert "`kb-test.yml` counts" in text
    assert "`cmd.lint` and `cmd.build` come only from commands" in text
    assert "`docs/conventions/<lang>.md`" in text


def test_dev_test_workflow_waits_for_the_marker_workflow_too():
    text = _dev_text("dev-test-workflow")
    assert (
        "or the workflow carrying the `# kb-test:` marker) must be among them" in text
    )
    assert "The new `kb-test` jobs" not in text


def test_dev_test_workflow_branches_before_it_writes_or_runs_anything():
    text = _dev_text("dev-test-workflow")
    assert "Before you write or run anything" in text
    assert text.index("Branch first") < text.index("The branch rule")
    assert text.count("git switch -c auto/kb-test FETCH_HEAD") == 1


def test_dev_fix_bug_checks_for_finished_work_before_it_branches():
    text = _dev_text("dev-fix-bug")
    assert text.index("Already finished") < text.index("The branch and its base")
    assert "A local `fix/<BUG-id>`" in text
    assert "`git switch fix/<BUG-id>`" in text


def test_dev_handover_reports_a_stale_blocker_to_the_orchestrator():
    text = _dev_text("dev-handover")
    assert "report the `Q<id>` to the orchestrator" in text
    assert "(on a direct run, end it yourself)" in text


@pytest.mark.parametrize(
    "name", ["dev-implement-ticket", "dev-handover", "dev-fix-bug"]
)
def test_kb_doctor_is_read_for_its_publish_advice(name):
    text = _dev_text(name)
    assert "when it advises `kb publish`" in text
    assert "says the hub lags" not in text


@pytest.mark.parametrize("name", ["dev-execute", "dev-handover"])
def test_three_round_cap_is_called_deliberate(name):
    assert "3-round cap stays as written here, on purpose" in _dev_text(name)


@pytest.mark.parametrize("kind", ["ba", "dev"])
def test_kb_auto_body_pins_its_contract(tmp_path, kind):
    init_repo(tmp_path, kind)
    text = (tmp_path / ".claude" / "skills" / "kb-auto" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for needle in (
        "kb auto status --json",
        "`running`",
        "`default_branch`",
        "git branch --show-current",
        "-- .kb/config.yaml .claude/settings.json",
        "nohup kb auto run > .kb/auto/run.log 2>&1 &",
        "mkdir -p .kb/auto",
        "STRATA_KB_AUTO_TASK=1",
        "Never pass `--dangerously-skip-permissions`",
    ):
        assert needle in text, needle
    assert "strata-kb:include" not in text


def test_kb_auto_body_has_cloud_path():
    body = BASE.joinpath("bodies", "kb-auto.md").read_text(encoding="utf-8")
    for needle in (
        "kb auto wait --max 6600",
        "auto/switch",
        "--admin",
        "`cloud`",
        "kb pr lint",
        "Blocking: No",
        "run_in_background",
        "still running",
        "git worktree remove --force .kb/auto/worktrees/switch",
    ):
        assert needle in body, needle


def test_kb_auto_cloud_switch_is_rerunnable_and_targets_the_default_branch():
    body = " ".join(
        BASE.joinpath("bodies", "kb-auto.md").read_text(encoding="utf-8").split()
    )
    for needle in (
        "git branch -D auto/switch",
        "kb pr find --head auto/switch --state open --json",
        "close that PR and delete the remote `auto/switch` branch on GitHub",
        "Run cleanup on every stop inside this step and after the merge",
        "Never force-push",
        "kb pr open --head auto/switch --base <default_branch>",
    ):
        assert needle in body, needle


def test_kb_auto_cloud_switch_flips_only_the_flag_and_watcher_outlives_default_timeout():
    body = BASE.joinpath("bodies", "kb-auto.md").read_text(encoding="utf-8")
    for needle in (
        "kb auto on --kb-dir .kb/auto/worktrees/switch/.kb",
        "git diff --no-index --quiet",
        "`timeout: 7200000`",
        "no `kb auto wait` line",
    ):
        assert needle in body, needle
    assert "Copy `.kb/config.yaml` and `.claude/settings.json`" not in body


def test_no_template_calls_gh_pr():
    # GraphQL-backed `gh pr ...` fails on Claude Code cloud; skills use `kb pr` (REST).
    call = re.compile(r"\bgh pr (list|create|checks|merge|view|edit)\b")
    hits = [
        name
        for name in _templates()
        + [f"bodies/{p.name}" for p in BASE.joinpath("bodies").iterdir()]
        if call.search(BASE.joinpath(name).read_text(encoding="utf-8"))
    ]
    assert hits == []
