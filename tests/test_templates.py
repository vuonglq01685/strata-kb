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

# Every dev workflow skill has landed as of Task A5, so this is the same
# five-skill list. It stays a distinct name because it is what the
# byte-identity test enumerates. Note the cross-wrapper tests below read
# wrapper files while iterating DEV_WORKFLOW_SKILLS, so a stage that adds a
# sixth skill must land its four wrappers in the same task that names it.
LANDED_DEV_WORKFLOW_SKILLS = DEV_WORKFLOW_SKILLS

# The three blocks reproduced verbatim in every dev wrapper — canon in
# docs/superpowers/plans/2026-08-19-dev-agent-stage-a.md (SHARED-FRESHNESS,
# SHARED-HARD-RULES, SHARED-NEXT-STEP). Each is keyed by its first and last
# line rather than sliced "heading → next heading": the command wrappers put
# their compressed procedure paragraph between the freshness block and the next
# heading, and the dev-design wrappers close with a sentence after the hard
# rules, so a heading-to-heading slice would swallow skill-specific prose and
# make the body assertions below vacuous all over again.
SHARED_BLOCKS = {
    "SHARED-FRESHNESS": (
        "## Freshness re-check (run this FIRST, every time)\n",
        "- **ok** → continue.\n",
    ),
    "SHARED-HARD-RULES": (
        "## Hard rules\n",
        "- KB feedback items found during implementation go in the PR"
        " description — dropping them silently violates DoD.\n",
    ),
    "SHARED-NEXT-STEP": (
        "## Next step — ALWAYS end your response with this block\n",
        "  Flow order never hides a blocker.\n",
    ),
}

# Canon text for each SHARED-* block, extracted verbatim (via repr()) from a
# landed wrapper — never hand-retyped. Comparing every copy against this
# canon, rather than only against each other, means a fleet-wide edit that
# deletes or rewords a hard rule now fails here, where the pairwise-only
# version did not.
SHARED_BLOCK_TEXT = {
    'SHARED-FRESHNESS': "## Freshness re-check (run this FIRST, every time)\n\nBefore anything else, re-resolve the ticket's `kb-context`: call the MCP tool\n`kb_resolve` when available, otherwise `kb resolve <ticket-file>` (or\n`kb resolve - < ticket.md`). The hub may have published since the last session,\nso a ref that was `ok` yesterday can be `stale` today — checking only at\nhandover is too late, because the plan may already rest on changed content.\n\n- **broken** → STOP. This is a blocker: report to the BA that the ticket needs\n  re-pinning. Never implement around a citation that no longer resolves.\n- **stale** → show BOTH versions and let the humans decide: `kb resolve` returns\n  the pinned content plus the reason; `kb get <doc-id> <section> [--level l3]`\n  returns the CURRENT hub version. Do NOT use `kb diff` — it compares the local\n  `.kb/` worktree against a local git rev, and this repo holds no local copy of\n  the cited domain document.\n- **ok** → continue.\n",
    'SHARED-HARD-RULES': '## Hard rules\n\n- A ticket without a resolvable `kb-context` is not implementable — send it back, never improvise the missing context.\n- Broken citation = blocker; stale citation = both versions surfaced, humans decide; neither is ever silently ignored.\n- No production code without a failing test observed first. No exception for small tickets, deadlines, or "obvious" changes.\n- Never claim done without showing the verification output.\n- Never invent or "remember" a standard value — every code/format/enum/threshold in code or tests is verbatim from the resolved section at the pinned version, with a citation comment.\n- `<repo>-svc` is for locating and cross-checking work only. It is never a source for an AC or a standard value.\n- The ticket is the BA\'s artifact: report placeholder resolutions and AC findings back; never edit the ticket.\n- An AC that cannot be implemented as written becomes `OPEN(BA)` — never reinterpreted, and never pushed past mid-implementation.\n- Never edit a test to make it pass; diagnose the cause.\n- Code is ground truth: when either code-knowledge document disagrees with the code, trust the code and note the mismatch.\n- Never modify a `reviewed` section of `-svc`; propose an amend.\n- `hist.*` entries are appended only by `kb svc note`, never hand-edited.\n- Never work on the default branch; never push to a protected branch; never merge; never tick DoD/AC checkboxes for humans.\n- KB feedback items found during implementation go in the PR description — dropping them silently violates DoD.\n',
    'SHARED-NEXT-STEP': '## Next step — ALWAYS end your response with this block\n\nClose every response with a state line and an ordered list of next steps.\nInclude it even when you stopped early or hit an error — especially then.\n\n    ## Next step\n\n    → 1. <next step in flow> — <what it does>   (next in flow)\n      2. <revise the current phase> — <how>\n      3. <stop/park> — <where the work is saved>\n\n    State: design <✅ approved|⬜ not written> · plan <✅ approved|⬜ not written> · tasks <n>/<m> · PR <✅ opened|⬜ not opened>\n\nRules:\n- Option 1 is ALWAYS the next step in flow order: design → plan → execute → handover.\n- Show the exact command with the ticket id already filled in, ready to copy.\n- The `State:` line always shows all four markers, even the ones not yet reached.\n- A blocker takes option 1 instead and says so, e.g.\n  `→ 1. Send back to the BA — ref ATM-STD §5.3 is broken, re-pin needed`.\n  Flow order never hides a blocker.\n',
}


def _dev_wrapper_names(skill: str) -> tuple[str, ...]:
    return (
        f"claude-skill-{skill}.md",
        f"claude-command-{skill}.md",
        f"copilot-{skill}.prompt.md",
        f"cursor-{skill}.md",
    )


def _landed_dev_wrapper_names() -> tuple[str, ...]:
    return tuple(
        name
        for skill in LANDED_DEV_WORKFLOW_SKILLS
        for name in _dev_wrapper_names(skill)
    )


def _normalised(text: str) -> str:
    """Collapse every whitespace run to a single space.

    The wrappers are hard-wrapped prose. Matching a needle against the raw text
    makes that phrase untouchable by the wrap — a line break in the middle of it
    fails the test — which is how 161-character lines ended up in files that
    wrap at ~72. Dev needles are matched against normalised text instead, so the
    prose can be re-wrapped freely.
    """
    return " ".join(text.split())


def _dev_shared_block(name: str, block: str) -> str:
    """One wrapper's copy of a SHARED-* block, verbatim."""
    first, last = SHARED_BLOCKS[block]
    text = _read_init_template(name)
    assert text.count(first) == 1, f"{name}: {block} opening line not found once"
    assert text.count(last) == 1, f"{name}: {block} closing line not found once"
    start = text.index(first)
    return text[start : text.index(last, start) + len(last)]


def _dev_wrapper_text(name: str) -> str:
    """The whole wrapper, whitespace-normalised."""
    return _normalised(_read_init_template(name))


def _dev_wrapper_body(name: str) -> str:
    """The wrapper's OWN prose: everything outside the three SHARED-* blocks.

    Every wrapper carries the shared blocks by construction, so a needle those
    blocks already satisfy asserts nothing about the skill it is named for
    unless it is matched against this body.
    """
    text = _read_init_template(name)
    for block in SHARED_BLOCKS:
        text = text.replace(_dev_shared_block(name, block), "\n\n", 1)
    for block, (first, _last) in SHARED_BLOCKS.items():
        assert first not in text, f"{name}: {block} survived the strip"
    return _normalised(text)


def test_dev_wrappers_carry_byte_identical_shared_blocks():
    """3 blocks x 20 files, every copy byte-identical to canon.

    The 20 is spelled out rather than derived so that adding a skill to
    DEV_WORKFLOW_SKILLS trips here and forces a conscious update. It does not
    detect a missing wrapper FILE — the per-skill existence tests and the
    FileNotFoundError out of _read_init_template do that.

    Comparing every copy to SHARED_BLOCK_TEXT (canon) rather than only to
    names[0] (pairwise) is the point: a fleet-wide edit that mutates every
    copy identically — e.g. deleting the same line from all 20 files —
    stays pairwise-equal and used to pass here. It cannot stay equal to a
    canon it never touches.
    """
    names = _landed_dev_wrapper_names()
    assert len(names) == 20, names
    for block, reference in SHARED_BLOCK_TEXT.items():
        assert reference.strip(), f"{block}: empty canon"
        for name in names:
            assert _dev_shared_block(name, block) == reference, (
                f"{name}: {block} is not byte-identical to canon"
            )


def test_dev_implement_ticket_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for name in _dev_wrapper_names("dev-implement-ticket"):
        assert base.joinpath(name).is_file(), name


def test_dev_implement_ticket_carries_the_five_orchestrator_steps():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        text = _dev_wrapper_text(name)
        for step in ("Intake", "Resolve", "Ground", "Placeholders", "Run the phases"):
            assert step in text, f"{name} missing step {step}"


def test_dev_implement_ticket_uses_resolve_and_get_never_diff():
    # Whole-text needles on purpose: `kb_resolve` / `kb resolve` / `kb get` live
    # in SHARED-FRESHNESS, which the wrappers point at instead of restating
    # ("**Resolve** triages exactly as in the Freshness re-check above"). What
    # keeps them honest is test_dev_wrappers_carry_byte_identical_shared_blocks;
    # the skill-specific half is asserted against the body in the test below.
    for name in _dev_wrapper_names("dev-implement-ticket"):
        text = _dev_wrapper_text(name)
        assert "kb_resolve" in text, name          # MCP tool
        assert "kb resolve" in text, name          # CLI fallback
        assert "kb get " in text, name             # current hub version
        assert "kb diff" not in text.replace("Do NOT use `kb diff`", ""), name


def test_dev_implement_ticket_ground_step_escalates_to_l3_in_its_own_words():
    # The Ground step's L3 escalation IS skill-specific, so it is asserted
    # against the body. The claude-command wrapper is a thin Skill invoker and
    # deliberately does not restate it, so it is not in this list.
    for name in (
        "claude-skill-dev-implement-ticket.md",
        "copilot-dev-implement-ticket.prompt.md",
        "cursor-dev-implement-ticket.md",
    ):
        body = _dev_wrapper_body(name)
        assert "kb get " in body, name
        assert "--level l3" in body, name


def test_dev_implement_ticket_checks_ticket_dependencies():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        text = _dev_wrapper_text(name)
        assert "## Dependencies" in text, name
        assert "Sequencing" in text, name
        assert "Blocked by" in text, name


def test_dev_implement_ticket_carries_placeholder_and_ticket_ownership_rules():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        text = _dev_wrapper_text(name)
        body = _dev_wrapper_body(name)
        assert "%%TODO: verify against codebase%%" in text, name
        # Both needles below are satisfied by SHARED-HARD-RULES in every file,
        # so they are asserted against the body: the Placeholders step must
        # state the ownership rule and the OPEN(BA) escape hatch itself.
        # Imperative in the full-content mirrors, declarative in the command
        # wrapper's list of declaratives — either wording counts, neither may
        # go missing.
        assert (
            "never edit the ticket" in body or "never edits the ticket" in body
        ), name
        assert "OPEN(BA)" in body, name


def test_claude_skill_dev_implement_ticket_has_expected_frontmatter():
    text = _read_init_template("claude-skill-dev-implement-ticket.md")
    assert text.startswith("---\n")
    assert "name: dev-implement-ticket\n" in text
    assert "/dev-implement-ticket" in text


def test_copilot_dev_implement_ticket_prompt_has_agent_mode():
    text = _read_init_template("copilot-dev-implement-ticket.prompt.md")
    assert "mode: agent" in text


def test_every_landed_claude_command_is_a_skill_invoker():
    # A command wrapper is a pointer to the skill, never a second
    # implementation of it — guard that for all five, not just one.
    for skill in LANDED_DEV_WORKFLOW_SKILLS:
        name = f"claude-command-{skill}.md"
        text = _dev_wrapper_text(name)
        assert f"Invoke the `{skill}` skill with the Skill tool" in text, name


def test_dev_design_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for name in _dev_wrapper_names("dev-design"):
        assert base.joinpath(name).is_file(), name


def test_dev_design_carries_the_three_paths_and_the_ratchet():
    for name in _dev_wrapper_names("dev-design"):
        text = _dev_wrapper_text(name)
        for path in ("spike", "bounded", "architectural"):
            assert path in text, f"{name} missing path {path}"
        assert "one-way" in text, name
        assert "take the heavier one" in text, name


def test_dev_design_writes_the_design_file_only_on_the_architectural_path():
    for name in _dev_wrapper_names("dev-design"):
        text = _dev_wrapper_text(name)
        assert "docs/impl/<ticket-id>-design.md" in text, name
        assert "architectural path only" in text, name


def test_dev_design_carries_gate_one_and_the_ac_rule():
    for name in _dev_wrapper_names("dev-design"):
        text = _dev_wrapper_text(name)
        assert "GATE 1" in text, name
        # SHARED-HARD-RULES carries OPEN(BA) in every file, so the design
        # wrapper's own AC escape hatch is asserted against the body.
        assert "OPEN(BA)" in _dev_wrapper_body(name), name
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
        text = _dev_wrapper_text(name)
        assert "one task per AC" in text, name
        assert "names the test that proves it" in text, name


def test_dev_plan_pins_the_plan_file_and_checkbox_shape():
    for name in _dev_wrapper_names("dev-plan"):
        text = _dev_wrapper_text(name)
        assert "docs/impl/<ticket-id>-plan.md" in text, name
        assert "- [ ]" in text, name
        for heading in ("Files", "Interfaces", "Steps"):
            assert f"**{heading}**" in text, f"{name} missing {heading}"


def test_dev_plan_first_step_is_always_the_failing_test():
    for name in _dev_wrapper_names("dev-plan"):
        text = _dev_wrapper_text(name)
        assert "step 1 always being the failing test" in text, name


def test_dev_plan_closes_with_cross_cutting_verification_from_cmd_sections():
    for name in _dev_wrapper_names("dev-plan"):
        text = _dev_wrapper_text(name)
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
        # "worktree" alone is satisfied twice over by text every wrapper has:
        # SHARED-FRESHNESS ("`.kb/` worktree") and the `using-git-worktrees`
        # counterpart line. The Isolate step is the only place that says
        # "git worktree", so that is the needle, matched against the body.
        assert "git worktree" in _dev_wrapper_body(name), name
        text = _dev_wrapper_text(name)
        assert "Never work directly on the default branch" in text, name


def test_dev_execute_demands_an_observed_failing_test():
    for name in _dev_wrapper_names("dev-execute"):
        text = _dev_wrapper_text(name)
        assert "observe it fail" in text, name
        assert "never seen red proves nothing" in text, name


def test_dev_execute_has_a_review_checkpoint_and_shown_verification():
    for name in _dev_wrapper_names("dev-execute"):
        text = _dev_wrapper_text(name)
        assert "review checkpoint" in text, name
        assert "cmd.test" in text and "cmd.lint" in text, name
        assert "show the output" in text, name


def test_dev_execute_forbids_editing_tests_and_deciding_ambiguous_acs():
    for name in _dev_wrapper_names("dev-execute"):
        text = _dev_wrapper_text(name)
        assert "Never edit a test to make it green" in text, name
        assert "return to `dev-design`" in text, name


def test_dev_execute_is_resumable():
    for name in _dev_wrapper_names("dev-execute"):
        text = _dev_wrapper_text(name)
        assert "first unticked task" in text, name


def test_claude_skill_dev_execute_has_expected_frontmatter():
    assert "name: dev-execute\n" in _read_init_template("claude-skill-dev-execute.md")


def test_copilot_dev_execute_prompt_has_agent_mode():
    assert "mode: agent" in _read_init_template("copilot-dev-execute.prompt.md")


def test_dev_handover_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for name in _dev_wrapper_names("dev-handover"):
        assert base.joinpath(name).is_file(), name


def test_dev_handover_rechecks_freshness_and_pastes_real_output():
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        assert "one final time" in text, name
        assert "paste the real output" in text, name
        assert "completion claim without it is not accepted" in text, name


def test_dev_handover_lists_the_pr_contents():
    # Body, not whole text: SHARED-HARD-RULES carries `kb-context` and
    # OPEN(BA) in all 20 wrappers, so whole-text needles for those two would
    # pass even with no PR-contents list in the file at all.
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        for item in ("ticket id", "kb-context", "AC→test map",
                     "placeholder-resolution", "OPEN(", "KB gap"):
            assert item in text, f"{name} missing PR item {item}"


def test_dev_handover_records_service_history_and_amend_findings():
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        assert "kb svc note" in text, name
        assert "amend needed:" in text, name
        # SHARED-HARD-RULES says "Never modify a `reviewed` section of `-svc`"
        # — a different verb, so this needle is the handover wrapper's own
        # sentence and belongs in the body.
        assert "Never edit a `reviewed` section" in text, name


def test_dev_handover_leaves_pr_and_merge_to_the_human():
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        assert "GATE 3" in text and "GATE 4" in text, name
        assert "The agent does neither" in text, name


def test_claude_skill_dev_handover_has_expected_frontmatter():
    assert "name: dev-handover\n" in _read_init_template("claude-skill-dev-handover.md")


def test_copilot_dev_handover_prompt_has_agent_mode():
    assert "mode: agent" in _read_init_template("copilot-dev-handover.prompt.md")


def test_all_dev_workflow_wrappers_carry_the_next_step_block():
    for skill in DEV_WORKFLOW_SKILLS:
        for name in _dev_wrapper_names(skill):
            text = _dev_wrapper_text(name)
            assert "## Next step" in text, name
            assert "(next in flow)" in text, name
            assert "State:" in text, name


def test_all_dev_workflow_wrappers_name_their_superpowers_counterpart():
    for skill in DEV_WORKFLOW_SKILLS:
        for name in _dev_wrapper_names(skill):
            assert "superpowers" in _dev_wrapper_body(name), name


def test_all_dev_workflow_wrappers_carry_the_tdd_and_evidence_rules():
    for skill in DEV_WORKFLOW_SKILLS:
        for name in _dev_wrapper_names(skill):
            text = _dev_wrapper_text(name)
            assert "No production code without a failing test observed first" in text, name
            assert "Never claim done without showing the verification output" in text, name


def test_dev_implement_ticket_caveats_the_documents_that_do_not_exist_yet():
    # The Ground step sends the agent at `<repo_id>-code` and `-svc`, which
    # Stages B and C ship. `dev-plan` caveats its analogous `-code §cmd.*`
    # gap in all four of its wrappers; the orchestrator must too, or a Dev
    # reports a missing document as a KB gap.
    for name in _dev_wrapper_names("dev-implement-ticket"):
        assert "until Stages B and C ship" in _dev_wrapper_body(name), name


def test_every_dev_workflow_wrapper_ends_on_the_next_step_block():
    # §5.3 requires the block to be the LAST thing in the file, not merely
    # present. A4 shipped four wrappers with a sentence after it and the
    # containment test above stayed green, so containment is not the contract.
    for skill in DEV_WORKFLOW_SKILLS:
        for name in _dev_wrapper_names(skill):
            text = _read_init_template(name)
            assert text.endswith("  Flow order never hides a blocker.\n"), name


def test_dev_wrappers_carry_the_freshness_triage_rules():
    # The block's commands are pinned by the orchestrator test; its triage is
    # not, and a fleet-wide reword of these two bullets passed everything.
    for skill in DEV_WORKFLOW_SKILLS:
        for name in _dev_wrapper_names(skill):
            text = _dev_wrapper_text(name)
            assert "**broken** → STOP" in text, name
            assert "show BOTH versions" in text, name


def test_copilot_and_cursor_wrappers_differ_only_in_their_frontmatter_name():
    # Each skill has three independently-authored prose variants (skill,
    # copilot, cursor) and only ~6 needles as the cross-form contract — this
    # is the cheapest drift guard available: copilot and cursor are supposed
    # to carry identical bodies, differing only on line 2 of the frontmatter
    # (`mode: agent` vs `name: <skill>`).
    for skill in DEV_WORKFLOW_SKILLS:
        copilot = _read_init_template(f"copilot-{skill}.prompt.md").splitlines()
        cursor = _read_init_template(f"cursor-{skill}.md").splitlines()
        assert copilot[:1] + copilot[2:] == cursor[:1] + cursor[2:], skill
