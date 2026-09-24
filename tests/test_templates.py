from importlib import resources
from pathlib import Path

import pytest
import yaml

from strata_kb import lintcore
from strata_kb.initcmd import COMMON_TEMPLATES, HUB_TEMPLATES, CHILD_TEMPLATES
from strata_kb.conventions import CONVENTION_PARTS, LANG_IDS

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
    "Intake", "Parent mission", "Ground", "Draft", "Pin", "Lint",
    "Ground technical", "Maturity review", "Review → save",
)


def test_all_web_templates_exist_as_package_resources():
    base = resources.files("strata_kb").joinpath("templates/web")
    for name in WEB_TEMPLATES:
        assert base.joinpath(name).is_file(), name


# headers.py's CSP ships `script-src 'self'` with no 'unsafe-inline' /
# 'unsafe-hashes' — every current browser refuses to run an inline
# event-handler attribute under that policy (Task 10 fix round 1). TestClient
# never enforces CSP and never runs JS, so this is the only test that can
# catch a template regressing back to one.
#
# Round 2 fix: the first version of this pattern was double-quote-only
# (missed onchange='...' and unquoted onclick=go()) and matched any
# on<letters>= lookalike (onward="x"). Both are fixed the same way — an
# explicit whitelist of real HTML event-handler attribute names, with the
# quote made optional so single-quoted and unquoted values both match.
# Scan is HTML-only now (was also scanning .js/.css, which is how app.js's
# OWN explanatory comment about onchange tripped this test on itself).
_EVENT_HANDLER_ATTRS = (
    "onclick", "ondblclick", "onchange", "oninput", "onsubmit", "onreset",
    "onload", "onerror", "onfocus", "onblur",
    "onkeydown", "onkeyup", "onkeypress",
    "onmousedown", "onmouseup", "onmouseover", "onmouseout",
    "onmouseenter", "onmouseleave", "onmousemove",
    "ondrag", "ondragstart", "ondragend", "ondragenter", "ondragleave",
    "ondragover", "ondrop",
    "onscroll", "onwheel", "ontoggle", "onselect", "oncontextmenu",
    "oncopy", "oncut", "onpaste",
)
_INLINE_HANDLER_RE_SRC = (
    r"\b(?:" + "|".join(_EVENT_HANDLER_ATTRS) + r")\s*=\s*['\"]?"
)
_SCANNED_SUFFIXES = (".html",)


def test_web_templates_carry_no_inline_event_handlers():
    import re

    pattern = re.compile(_INLINE_HANDLER_RE_SRC, re.IGNORECASE)
    base = resources.files("strata_kb").joinpath("templates/web")
    with resources.as_file(base) as root:
        root = Path(root)
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in _SCANNED_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                pytest.fail(
                    f"{path.relative_to(root)}:{line_no}: inline event "
                    f"handler {match.group()!r} — headers.py's CSP ships "
                    "script-src 'self' with no 'unsafe-inline', so a "
                    "browser refuses to run this; move it to "
                    "static/app.js as a delegated listener instead"
                )


def test_inline_handler_pattern_catches_single_and_unquoted_handlers():
    """Two-direction proof for round 2's fix: single-quoted and unquoted
    handlers must both trip the pattern; CSS/Jinja lookalikes must not."""
    import re

    pattern = re.compile(_INLINE_HANDLER_RE_SRC, re.IGNORECASE)
    assert pattern.search("<input onclick='go()'>")  # single-quoted
    assert pattern.search("<input onclick=go()>")  # unquoted
    assert pattern.search('<input onchange="this.form.submit()">')  # double-quoted
    assert not pattern.search('<div style="transition:.2s">')
    assert not pattern.search('<button data-status-btn="all">')
    assert not pattern.search("{{ 'checked' if semantic_on }}")
    assert not pattern.search('<input data-onward="x">')  # not a real event name


def test_data_autosubmit_contract_between_search_html_and_app_js():
    """data-autosubmit is a cross-file string contract -- search.html's two
    controls carry the attribute, app.js's delegated listener selects it by
    the same string. No shared constant ties them together, so a typo or
    rename in either file silently kills both controls and nothing else
    would notice."""
    base = resources.files("strata_kb").joinpath("templates/web")
    search_html = base.joinpath("search.html").read_text(encoding="utf-8")
    app_js = base.joinpath("static/app.js").read_text(encoding="utf-8")
    assert search_html.count("data-autosubmit") == 2
    assert "[data-autosubmit]" in app_js


def test_all_init_templates_exist_as_package_resources():
    base = resources.files("strata_kb").joinpath("templates/init")
    for mapping in (COMMON_TEMPLATES, HUB_TEMPLATES, CHILD_TEMPLATES):
        for resource_name in mapping.values():
            assert base.joinpath(resource_name).is_file(), resource_name


def _read_init_template(name: str) -> str:
    base = resources.files("strata_kb").joinpath("templates/init")
    return base.joinpath(name).read_text(encoding="utf-8")


def test_ba_ticket_author_templates_exist_as_package_resources():
    base = resources.files("strata_kb").joinpath("templates/init")
    for name in BA_TICKET_AUTHOR_TEMPLATES:
        assert base.joinpath(name).is_file(), name


def test_ba_ticket_author_templates_carry_the_nine_pipeline_steps():
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
    from strata_kb.initcmd import BA_TEMPLATES

    base = resources.files("strata_kb").joinpath("templates/init")
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
    from strata_kb.acquality import WEASEL_PHRASES

    text = _read_init_template("ac-quality.md")
    for phrase in WEASEL_PHRASES:
        assert phrase in text, phrase


def test_every_quoted_doc_phrase_is_in_the_detector():
    import re as _re

    from strata_kb.acquality import WEASEL_PHRASES

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
    from strata_kb.initcmd import BA_TEMPLATES

    base = resources.files("strata_kb").joinpath("templates/init")
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
    'SHARED-FRESHNESS': '## Freshness re-check (run this FIRST, every time)\n\nCheap check first: `kb resolve --status-only --cache\ndocs/impl/<ticket-id>-context.md <ticket-file>` (no CLI → `kb_resolve`;\ncheck the cache `version:` yourself). Exit 0 → use the cache, do NOT\nre-pull pinned content. A `cache-*` line or a non-ok verdict → `kb resolve\n--write-cache <same path> <ticket-file>` (no CLI → `kb_resolve`, write the\nlayout by hand), then fill `## Placeholder map` below the marker; never\nedit above it.\n\n- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a\n  citation that no longer resolves.\n- **stale** → show BOTH versions, humans decide: the resolve gives the\n  pinned content and the reason, `kb get <doc-id> <section> [--level l3]`\n  the current hub version. Do NOT use `kb diff` — it compares the local\n  `.kb/` worktree to a local git rev, not this repo to the hub.\n- **ok** → continue.\n',
    'SHARED-HARD-RULES': '## Hard rules\n\n- A ticket without a resolvable `kb-context` is not implementable — send it back, never improvise the missing context.\n- Broken citation = blocker; stale citation = both versions surfaced, humans decide; neither is ever silently ignored.\n- No production code without a failing test observed first. No exception for small tickets, deadlines, or "obvious" changes.\n- Never claim done without showing the verification output.\n- Never invent or "remember" a standard value — every code/format/enum/threshold in code or tests is verbatim from the resolved section at the pinned version, with a citation comment.\n- `<repo>-svc` is for locating and cross-checking work only. It is never a source for an AC or a standard value.\n- The ticket is the BA\'s artifact: report placeholder resolutions and AC findings back; never edit the ticket.\n- An AC that cannot be implemented as written becomes `OPEN(BA)` — never reinterpreted, and never pushed past mid-implementation.\n- Never edit a test to make it pass; diagnose the cause.\n- Code is ground truth: when either code-knowledge document disagrees with the code, trust the code and note the mismatch.\n- Never modify a `reviewed` section of `-svc`; propose an amend.\n- `hist.*` entries are appended only by `kb svc note`, never hand-edited.\n- Never work on the default branch; never push to a protected branch; never merge; never tick DoD/AC checkboxes for humans.\n- KB feedback items found during implementation go in the PR description — dropping them silently violates DoD.\n',
    'SHARED-NEXT-STEP': '## Next step — ALWAYS end your response with this block\n\nClose every response with a state line and an ordered list of next steps.\nInclude it even when you stopped early or hit an error — especially then.\n\n    ## Next step\n\n    → 1. <next step in flow> — <what it does>   (next in flow)\n      2. <revise the current phase> — <how>\n      3. <stop/park> — <where the work is saved>\n\n    State: design <✅ approved|📝 draft|⬜ not written> · plan <✅ approved|📝 draft|⬜ not written|⚠ missing, N commits|n/a (spike)> · tasks <n>/<m> · PR <✅ opened|✅ merged|❌ closed|⬜ not opened|? unknown>\n\nRules:\n- Option 1 is ALWAYS the next step in flow order: design → plan → execute → handover.\n- Show the exact command with the ticket id already filled in, ready to copy.\n- The `State:` line always shows all four markers, even the ones not yet reached.\n- A blocker takes option 1 instead and says so, e.g.\n  `→ 1. Send back to the BA — ref ATM-STD §5.3 is broken, re-pin needed`.\n  Flow order never hides a blocker.\n',
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
    """The wrapper's OWN prose: everything outside the three SHARED-* blocks
    and, for the 16 wrappers that carry it, the review dispatch contract.

    Every wrapper carries the shared blocks by construction, so a needle those
    blocks already satisfy asserts nothing about the skill it is named for
    unless it is matched against this body. The review contract is the same
    kind of trap for a review-flavoured needle ("at most 3 rounds", "BLOCKER",
    "the Dev") — it used to slip through unstripped, so any such needle
    passed against every one of the 16 contract-carrying wrappers regardless
    of what that wrapper's own prose said.
    """
    text = _read_init_template(name)
    for block in SHARED_BLOCKS:
        text = text.replace(_dev_shared_block(name, block), "\n\n", 1)
    for block, (first, _last) in SHARED_BLOCKS.items():
        assert first not in text, f"{name}: {block} survived the strip"
    contract_first = REVIEW_CONTRACT_BOUNDS[0]
    if contract_first in text:
        text = text.replace(_review_contract(name), "\n\n", 1)
        assert contract_first not in text, f"{name}: REVIEW-CONTRACT survived the strip"
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
    base = resources.files("strata_kb").joinpath("templates/init")
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
    base = resources.files("strata_kb").joinpath("templates/init")
    for name in _dev_wrapper_names("dev-design"):
        assert base.joinpath(name).is_file(), name


def test_dev_design_carries_the_three_paths_and_the_ratchet():
    for name in _dev_wrapper_names("dev-design"):
        text = _dev_wrapper_text(name)
        for path in ("spike", "bounded", "architectural"):
            assert path in text, f"{name} missing path {path}"
        assert "one-way" in text, name
        assert "take the heavier one" in text, name


def test_dev_design_writes_the_design_file_on_every_path():
    # Task F-H2/F-M8 supersedes the old architectural-only contract this
    # test used to pin (Phase 5 Stage A): every path now writes the design
    # file, so "architectural path only" is gone from the wrapper's own
    # prose — see test_dev_design_writes_a_file_on_every_path_with_a_status_header
    # for the full new contract, asserted against the body.
    for name in _dev_wrapper_names("dev-design"):
        text = _dev_wrapper_text(name)
        assert "docs/impl/<ticket-id>-design.md" in text, name


def test_dev_design_carries_gate_one_and_the_ac_rule():
    for name in _dev_wrapper_names("dev-design"):
        text = _dev_wrapper_text(name)
        assert "GATE 1" in text, name
        # SHARED-HARD-RULES carries OPEN(BA) in every file, so the design
        # wrapper's own AC escape hatch is asserted against the body.
        assert "OPEN(BA)" in _dev_wrapper_body(name), name
        assert "reinterpreting an ac is forbidden" in text.lower(), name


def test_dev_design_spike_path_names_dev_handover_as_option_one():
    # Final-review finding 6: the option-1 sentence used to say
    # `/dev-plan` unconditionally while the same file said a spike ends
    # at `dev-handover` with no plan — self-contradictory on re-entry.
    for name in _dev_wrapper_names("dev-design"):
        body = _dev_wrapper_body(name)
        assert "unless `path: spike`" in body, name
        assert "option 1 is `/dev-handover <ticket-id>`" in body, name


def test_dev_design_gate_one_approves_a_spike_too():
    # A spike design left at `draft` forever (GATE 1 only mentioned
    # `dev-plan` refusing a draft) never reads as approved on re-entry.
    for name in _dev_wrapper_names("dev-design"):
        body = _dev_wrapper_body(name)
        assert "A spike's design is flipped to `status: approved`" in body, name


def test_claude_skill_dev_design_has_expected_frontmatter():
    text = _read_init_template("claude-skill-dev-design.md")
    assert "name: dev-design\n" in text


def test_copilot_dev_design_prompt_has_agent_mode():
    assert "mode: agent" in _read_init_template("copilot-dev-design.prompt.md")


def test_dev_plan_templates_exist_as_package_resources():
    base = resources.files("strata_kb").joinpath("templates/init")
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
    base = resources.files("strata_kb").joinpath("templates/init")
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
    base = resources.files("strata_kb").joinpath("templates/init")
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
    #
    # Batch 7 (E2) note: "ticket id" and "placeholder-resolution" were the
    # pre-canon wording of the "Assemble the PR description" bullet. That
    # bullet now names the eight `REQUIRED_SECTIONS` in canon spelling
    # ("Ticket", "Placeholder resolutions") to match `pull-request-template.md`
    # and `test_every_required_section_is_named_in_the_dev_handover_wrappers`
    # below — updated here rather than left pinning retired wording.
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        for item in ("Ticket", "kb-context", "AC→test map",
                     "Placeholder resolutions", "OPEN(", "KB gap"):
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


# Final review, Important 1(a): `kb svc note` validates the service
# against THIS repo's own committed `-code`, which `kb-code.yml`
# regenerates and publishes on the hub but never writes back here — so a
# ticket that added or renamed a service must run `kb code-ingest` first,
# or the terminal step of the flow hard-fails on a service that is real,
# just not locally known yet.
def test_dev_handover_tells_the_dev_to_refresh_code_for_a_new_service():
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        assert "run `kb code-ingest` first" in text, name
        assert "never writes back here" in text, name


def test_dev_handover_leaves_pr_and_merge_to_the_human():
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        assert "GATE 3" in text and "GATE 4" in text, name
        assert "The agent does neither" in text, name


def test_dev_handover_has_a_spike_branch():
    # Final-review finding 6: dev-design sends a spike straight to
    # dev-handover with no plan and usually no code; the handover
    # wrapper had no branch at all for that case (spec §3: recommendation
    # in the PR's `## Findings`, or a ticket comment with no PR).
    for name in _dev_wrapper_names("dev-handover"):
        body = _dev_wrapper_body(name)
        assert "path: spike" in body, name
        assert "no plan and" in body and "no code" in body, name
        assert "`n/a (spike)`" in body, name


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


def test_dev_implement_ticket_caveats_the_svc_document_by_repo_state():
    # Phase 5 Stage C shipped `dev-code-seed` (7b6500b) and `kb svc note`
    # (e3703b5) on this branch, so C3 retired the "until Stage C ships it"
    # wording this test used to pin (task-C3-brief.md, R1 ruling): the
    # Ground step sends the agent at `<repo_id>-code` and `-svc`, and
    # `<repo_id>-svc` can still be absent on any GIVEN repo — not because
    # the plugin lacks the feature, but because that repo has not run its
    # one-time `dev-code-seed` bootstrap yet. That is a per-repo-state
    # fact, exactly like the `-code` half below, and is pinned the same
    # way. `dev-plan` caveats its analogous `-code §cmd.*` gap the same
    # way, in all four of its wrappers; the orchestrator must caveat its
    # own remaining `-svc` gap too, or a Dev reports a missing document as
    # a KB gap.
    for name in _dev_wrapper_names("dev-implement-ticket"):
        assert (
            "generated, unpublished: run `kb publish`"
            in _dev_wrapper_body(name)
        ), name


def test_dev_plan_and_dev_implement_ticket_caveat_the_code_document_by_repo_state():
    # Task B10 fix (c): `-code` is missing on any repo that has not run
    # `kb code-ingest` yet — a per-repo-state fact, not a plugin-version
    # gap — and both skills that read `-code` must say so, or a Dev on a
    # freshly-scaffolded repo gets no guidance and reports it as a KB gap
    # (the exact regression fix (c) closed). Neither half was pinned by
    # any assertion before this test. Each needle is the substring
    # actually shared, verbatim, by that skill's own four wrapper forms —
    # the two skills phrase it differently from each other, so one
    # needle does not cover both.
    for name in _dev_wrapper_names("dev-plan"):
        assert "`kb code-ingest` not yet run" in _dev_wrapper_body(name), name
    for name in _dev_wrapper_names("dev-implement-ticket"):
        assert (
            "`kb code-ingest` for `<repo_id>-code`"
            in _dev_wrapper_body(name)
        ), name


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


def test_kb_code_workflow_has_both_triggers():
    text = _read_init_template("kb-code.yml")
    assert "push:" in text
    assert "workflow_dispatch:" in text
    assert "pull_request:" in text


def test_kb_code_trigger_list_is_pinned():
    # Task review, Important 7: nothing bounds the `on:` block today --
    # adding `pull_request_target` later would make the publish job's
    # `if: github.event_name != 'pull_request'` true for a PR-controlled
    # ref, running `kb ci-publish` with `id-token: write` against
    # attacker-influenced content. Pinning the exact trigger set (not
    # just "push/pull_request/workflow_dispatch are present", which a
    # fourth trigger would still satisfy) means a new trigger fails this
    # test until it is deliberately reviewed here too.
    import yaml

    wf = yaml.safe_load(_read_init_template("kb-code.yml"))
    # PyYAML's default (YAML 1.1) resolver reads a bare `on:` key as the
    # boolean `True`, not the string "on" -- this is the actual parsed
    # key, not a typo.
    triggers = wf[True]
    assert set(triggers) == {"push", "pull_request", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["main", "master"]}


def test_kb_code_publish_job_runs_the_full_chain():
    text = _read_init_template("kb-code.yml")
    assert "kb code-ingest" in text
    assert "kb build" in text
    assert "kb ci-publish" in text


def test_kb_code_pull_request_job_validates_but_never_publishes():
    import yaml

    wf = yaml.safe_load(_read_init_template("kb-code.yml"))
    jobs = wf["jobs"]
    pr_job = next(j for name, j in jobs.items() if "validate" in name)
    steps = " ".join(str(s.get("run", "")) for s in pr_job["steps"])
    assert "kb build" in steps
    assert "ci-publish" not in steps
    assert "code-ingest" not in steps


def test_kb_code_never_scaffolds_svc_in_ci():
    assert "--scaffold-svc" not in _read_init_template("kb-code.yml")


def test_kb_code_has_no_hardcoded_url_or_token():
    text = _read_init_template("kb-code.yml")
    assert "https://" not in text
    assert "secrets." not in text
    assert "id-token: write" in text


def test_kb_code_publish_job_if_is_pinned_to_negated_pull_request():
    # Regression guard: `if: github.event_name != 'pull_request'` on the
    # publish job is the ONLY thing stopping a same-repo branch PR from
    # running `kb ci-publish` with `id-token: write` and publishing
    # unreviewed content to the hub (fork PRs are separately protected by
    # GitHub withholding a write-scoped GITHUB_TOKEN, but that protection
    # does not cover same-repo PRs). A substring check like
    # `"pull_request" in condition` would still pass if this were inverted
    # to `==` -- pin the exact expression so both deleting the `if:` and
    # flipping the operator fail this test.
    import yaml

    wf = yaml.safe_load(_read_init_template("kb-code.yml"))
    assert wf["jobs"]["publish"]["if"] == "github.event_name != 'pull_request'"


def test_kb_code_validate_job_has_read_only_permissions():
    # Task review, Important 7: the validate job had no `permissions:`
    # block at all, inheriting the repository's default token scope,
    # while kb-publish.yml already scopes its own job explicitly.
    import yaml

    wf = yaml.safe_load(_read_init_template("kb-code.yml"))
    assert wf["jobs"]["validate"]["permissions"] == {"contents": "read"}


def test_kb_code_workflow_has_a_concurrency_group():
    # Task review, Important 7: without this, two quick merges race two
    # `kb ci-publish` runs, each opening its own hub PR against the same
    # -code document.
    import yaml

    wf = yaml.safe_load(_read_init_template("kb-code.yml"))
    concurrency = wf["concurrency"]
    assert concurrency["group"] == "kb-code-${{ github.ref }}"
    assert concurrency["cancel-in-progress"] is False


def test_kb_code_publish_checkout_does_not_fetch_full_history():
    # Task review, Important 7: `fetch-depth: 0` was unnecessary --
    # code-ingest only ever runs `rev-parse HEAD` and
    # `show -s --format=%cs HEAD`, both satisfied by the default shallow
    # checkout -- and its own comment stated a false reason for it.
    assert "fetch-depth" not in _read_init_template("kb-code.yml")


# --- Phase 5 Stage C: dev-code-seed --------------------------------------
#
# Deliberately NOT added to DEV_WORKFLOW_SKILLS / LANDED_DEV_WORKFLOW_SKILLS
# above: dev-code-seed implements no ticket, so two of the three SHARED-*
# blocks (SHARED-FRESHNESS re-resolves a ticket's kb-context;
# SHARED-HARD-RULES is ticket/AC/TDD wording) do not apply, and
# SHARED-NEXT-STEP's canon text hardcodes the design/plan/execute/handover
# flow order, which this one-time bootstrap does not follow. Spec Sec13
# scopes the "all six" obligation to exactly two things: the next-step
# block and the one-line superpowers-counterpart reference — both are
# asserted below, in dev-code-seed's own words.


def _dev_code_seed_names() -> tuple[str, ...]:
    return (
        "claude-skill-dev-code-seed.md",
        "claude-command-dev-code-seed.md",
        "copilot-dev-code-seed.prompt.md",
        "cursor-dev-code-seed.md",
    )


def test_dev_code_seed_templates_exist_as_package_resources():
    base = resources.files("strata_kb").joinpath("templates/init")
    for name in _dev_code_seed_names():
        assert base.joinpath(name).is_file(), name


def test_dev_code_seed_carries_the_seven_steps():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        for step in ("Preflight", "Extract", "Draft", "Review", "Approve",
                     "Flows", "Validate and publish"):
            assert step in text, f"{name} missing step {step}"


def test_dev_code_seed_uses_the_existing_commands_unchanged():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "kb code-ingest --scaffold-svc" in text, name
        assert "kb summarize" in text, name
        assert "kb approve" in text, name
        assert "kb publish" in text, name


def test_dev_code_seed_carries_the_draft_is_a_draft_rule():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "The LLM draft is a **draft**" in text, name
        assert "approving it unread defeats the gate" in text, name


def test_dev_code_seed_forbids_publishing_pending_and_warns_about_redo():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "never publish `pending` knowledge" in text, name
        assert "--redo" in text, name
        assert "resets the **whole** document" in text, name


def test_dev_code_seed_never_edits_the_generated_document():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "Never edit `-code`" in text, name


# Final review, Minor 7: step 6's hand-added `flow.*` manifest entry names
# `summary` and the TODO marker but not `file`, which `models.
# SectionEntry.file` requires (no default) -- an agent that omits or
# guesses it produces exactly the confusing `kb build` error this step
# exists to prevent.
def test_dev_code_seed_step_6_names_the_required_file_field():
    for name in _dev_code_seed_names():
        text = _dev_wrapper_text(name)
        assert "file: flows" in text, name


def test_dev_code_seed_ends_with_the_next_step_block():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "## Next step" in text, name
        assert "State:" in text, name
        # Task review, Important 1: spec Sec13:484 names the "(next in
        # flow)" marker as one of three required elements of the next-step
        # block for ALL six skills, and every one of the 20 Stage A
        # wrappers carries it (pinned at :677 above for those five). R2
        # licensed rewriting the canon TEXT for the one-time seed flow, not
        # dropping this flow-agnostic marker, which applies verbatim here.
        assert "(next in flow)" in text, name


# Final review, Minor 8: the deferred four-way byte-identity guard for
# dev-code-seed. Deferral reasoning ("the four forms are unlikely to
# drift") was disproved by events on this very branch: the BA mission
# wrappers drifted silently across forms and were caught only by
# test_init.py:963's analogous guard. `## Steps` onward covers this
# skill's own Steps + Hard rules + Next-step text in one slice (unlike
# the dev-workflow SHARED-* blocks, dev-code-seed has no canon dict of
# its own to compare against, so the first wrapper form stands in as
# canon here — a fleet-wide edit that mutates all four identically would
# still slip past this the same way review round 3's own note about
# SHARED_BLOCK_TEXT describes, but it still catches the class of drift
# that actually happened on this branch: one form silently diverging
# from its siblings).
def test_dev_code_seed_wrappers_are_byte_identical_from_steps_onward():
    names = _dev_code_seed_names()
    canon_text = _read_init_template(names[0])
    canon = canon_text[canon_text.index("## Steps"):]
    assert canon.strip(), "empty canon"
    for name in names[1:]:
        text = _read_init_template(name)
        assert text[text.index("## Steps"):] == canon, name


def test_claude_skill_dev_code_seed_has_expected_frontmatter():
    text = _read_init_template("claude-skill-dev-code-seed.md")
    assert "name: dev-code-seed\n" in text


def test_copilot_dev_code_seed_prompt_has_agent_mode():
    assert "mode: agent" in _read_init_template("copilot-dev-code-seed.prompt.md")


# R2 ruling: dev-code-seed still owes spec Sec13's "all six" obligation for
# the superpowers-counterpart line, even though it is excluded from the
# SHARED-* canon comparison above (it has no superpowers counterpart at
# all, so its own line names that explicitly rather than pointing at one).
def test_dev_code_seed_wrappers_name_their_superpowers_counterpart():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "Counterpart in the superpowers plugin" in text, name


# --- Phase 5 Stage C Task C3: retire the Stage-A interim fallbacks -------
#
# R1 ruling (task-C3-D1-report.md): the brief's file list was wrong in both
# directions. dev-plan/dev-execute's `-code §cmd.*` fallback paragraphs were
# already worded non-temporally (Stage A shipped them that way), so they are
# asserted here but not edited. dev-implement-ticket's Ground step DID carry
# an "until Stage C ships it" sentence the brief missed, so it is added to
# this test's skill list alongside dev-plan/dev-execute/dev-handover.


def test_dev_wrappers_no_longer_carry_the_stage_a_interim_fallbacks():
    for skill in ("dev-plan", "dev-execute", "dev-handover", "dev-implement-ticket"):
        for name in _dev_wrapper_names(skill):
            text = _read_init_template(name)
            assert "until Stage B" not in text, name
            assert "until Stage C" not in text, name
            assert "this command does not exist yet" not in text, name


def test_dev_plan_and_execute_read_cmd_sections_as_the_primary_source():
    for skill in ("dev-plan", "dev-execute"):
        for name in _dev_wrapper_names(skill):
            text = _read_init_template(name)
            assert "cmd.test" in text, name
            assert "cmd.lint" in text, name


def test_dev_handover_runs_svc_note_unconditionally():
    # Task review fix: the raw-text needle used to pass in
    # claude-command-dev-handover.md via the SHARED-HARD-RULES bullet
    # ("`hist.*` entries are appended only by `kb svc note`") rather than
    # via the handover step's own text (which wraps as "kb svc" / "note
    # <service>" in that file). `_dev_wrapper_body` strips the shared
    # blocks and normalises whitespace, so this now tests the step
    # itself. The negative needle is pinned to the exact retired
    # sentence, not the generic phrase "skip the step" — a legitimate
    # repo-state fallback (added by the same fix round) is allowed to use
    # "skip"/"step" wording of its own without tripping this assertion.
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        assert "kb svc note" in text, name
        assert "skip the step and say so in one line in the PR" not in text, name


def test_config_dev_yaml_no_longer_carries_the_stage_a_interim_fallback():
    # Task review Important 4: `config-dev.yaml` ships to every adopting
    # `dev` repo and carried its own "-svc is not available yet" claim.
    # It sits outside `_dev_wrapper_names`'s reach (that helper only
    # names the four wrapper forms per skill), so the fleet-wide guard
    # above could not see it. `QUICKSTART-dev.md` carries the same
    # retired claim twice but is out of scope here — owned by another
    # agent in this same fix round.
    text = _read_init_template("config-dev.yaml")
    assert "not available yet" not in text
    assert "until Stage C" not in text


def test_quickstart_dev_documents_the_context_cache():
    text = _read_init_template("QUICKSTART-dev.md")
    assert "<ticket-id>-context.md" in text
    assert "docs/impl/.gitignore" in text


# --- The eight BA wrappers hand code detail to sa-ticket-ground (spec 2026-09-20 §6) --

BA_WRAPPERS = (
    "claude-skill-ba-ticket-author.md",
    "claude-command-ba-ticket-author.md",
    "copilot-ba-ticket-author.prompt.md",
    "cursor-ba-ticket-author.md",
    "claude-skill-ba-mission-plan.md",
    "claude-command-ba-mission-plan.md",
    "copilot-ba-mission-plan.prompt.md",
    "cursor-ba-mission-plan.md",
)

SA_WRAPPERS = (
    "claude-skill-sa-ticket-ground.md",
    "claude-command-sa-ticket-ground.md",
    "copilot-sa-ticket-ground.prompt.md",
    "cursor-sa-ticket-ground.md",
)
# The three full-content forms; the command wrapper is a thin skill invoker.
SA_FULL_WRAPPERS = (SA_WRAPPERS[0], SA_WRAPPERS[2], SA_WRAPPERS[3])


# Task 11 (MEDIUM-5): every BA wrapper's maturity-review step must point at
# both the base rubric and its create-once `.local.md` override (mirrors
# `docs/conventions/<lang>.local.md`'s pointer convention on the dev side).
@pytest.mark.parametrize("name", BA_WRAPPERS)
def test_every_ba_wrapper_names_the_local_override(name):
    text = _read_init_template(name)
    assert "docs/review-rubric.local.md" in text
    # Task 11 review Minor 2: pin the ac-quality half too, so a future
    # reflow can't silently drop it from any wrapper while this test
    # keeps passing on the rubric half alone.
    assert "docs/ac-quality.local.md" in text


def _ba_wrapper_text(name: str) -> str:
    """A BA wrapper's whole text, whitespace-normalised.

    BA wrappers carry none of the three dev-workflow SHARED-* blocks, so
    `_dev_wrapper_body`'s block-stripping does not apply here — this is
    the BA-side equivalent of `_dev_wrapper_text`. Several needles are
    multi-word phrases hand-wrapped across lines in eight files; matching
    them against raw text makes the phrase untouchable by a future
    reflow (see `_normalised`'s docstring above). Matching against
    normalised text instead lets the prose wrap freely.
    """
    return _normalised(_read_init_template(name))


BA_TICKET_WRAPPERS = BA_WRAPPERS[:4]
BA_MISSION_WRAPPERS = BA_WRAPPERS[4:]


# Spec 2026-09-20-sa-grounding-design §6 (decision A3): the BA skills no
# longer read <repo>-code / <repo>-svc. They write the placeholder and hand
# the document to /sa-ticket-ground, which fills the SA-owned section.
def test_ba_wrappers_hand_code_detail_to_the_sa_skill():
    for name in BA_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "%%TODO: verify against codebase%%" in text, name
        assert "/sa-ticket-ground" in text, name
        assert "Never read `<repo>-code` or `<repo>-svc` yourself" in text, name


def test_ba_wrappers_no_longer_ground_code_detail_themselves():
    for name in BA_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "Container(alias, label, technology, description)" not in text, name
        assert "Ground code detail in the hub" not in text, name
        assert "Technology | none" not in text, name
        assert "trust it for names" not in text, name


def test_ba_ticket_wrappers_leave_technical_grounding_to_the_sa():
    for name in BA_TICKET_WRAPPERS:
        assert "## Technical grounding" in _ba_wrapper_text(name), name
    for name in ("claude-skill-ba-ticket-author.md", "copilot-ba-ticket-author.prompt.md", "cursor-ba-ticket-author.md"):
        assert "is SA-owned: leave it exactly as the template ships it" in _ba_wrapper_text(name), name


def test_ba_mission_wrappers_leave_services_and_order_to_the_sa():
    for name in BA_MISSION_WRAPPERS:
        assert "## Services & order" in _ba_wrapper_text(name), name


def test_ba_wrappers_still_carry_their_pre_phase5_rules():
    """Stage D adds; it must not remove anything Phase 4/4.1 established."""
    for name in ("claude-skill-ba-ticket-author.md", "claude-skill-ba-mission-plan.md"):
        text = _read_init_template(name)
        assert "kb_context_new" in text, name
        assert "Maturity review" in text, name
        assert "Never fabricate" in text or "never invent" in text.lower(), name


# --- C5: a shorter freshness block, the hard rules left alone ---------------


def test_shared_freshness_keeps_the_kb_diff_trap_and_the_three_verdicts():
    block = _normalised(SHARED_BLOCK_TEXT["SHARED-FRESHNESS"])
    for needle in ("**broken**", "**stale**", "**ok**", "kb diff", "kb_resolve",
                   "re-pin", "--level l3"):
        assert needle in block, needle
    # Final review F4: "Do NOT use `kb diff`" was trimmed to the bare
    # fragment "NOT `kb diff`", losing the imperative. Guard the full
    # restored phrase here, at this test's own site, rather than only
    # via test_dev_implement_ticket_uses_resolve_and_get_never_diff's
    # replace() call.
    assert "Do NOT use `kb diff`" in block


# --- C1: the freshness re-check reuses the context cache --------------------


def test_shared_freshness_prefers_the_cache_and_status_only():
    block = _normalised(SHARED_BLOCK_TEXT["SHARED-FRESHNESS"])
    for needle in ("--status-only --cache", "-context.md", "--write-cache",
                   "below the marker", "never edit above it", "`cache-*`"):
        assert needle in block, needle


def test_dev_implement_ticket_writes_the_context_cache():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        text = _dev_wrapper_body(name)
        assert "docs/impl/<ticket-id>-context.md" in text, name
        assert "Placeholder map" in text, name


def test_dev_handover_pastes_the_status_only_output():
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        assert "--status-only" in text, name


def test_shared_freshness_stays_within_the_c1_ceiling():
    # C5 shrank the block to 605 characters; C1 (context cache) grew it
    # back to 882 because the *algorithm* changed — cache + --status-only
    # first, full resolve only on miss — not because the wording got loose.
    # The ceiling still fails on a silent re-expansion into explanatory
    # paragraphs.
    assert len(SHARED_BLOCK_TEXT["SHARED-FRESHNESS"]) <= 900


def test_shared_hard_rules_were_not_touched_by_the_c5_round():
    """C5 shrinks the freshness block only.

    Measured 2026-08-24: regrouping the 14 hard rules into 8 saves 5% of
    the block, 16% under the most aggressive rewording that still carries
    all 14 constraints. Both are too little to justify a diff in which a
    rewritten rule and a deleted rule look identical. This test pins the
    decision: the block's length and bullet count stay where they are, so
    a later "tidy-up" has to argue with the numbers first.
    """
    block = SHARED_BLOCK_TEXT["SHARED-HARD-RULES"]
    bullets = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(bullets) == 14, len(bullets)
    assert len(block) == 1531, len(block)


# --- C3: the per-task subagent gets its task, not the whole plan ------------


def test_dev_execute_hands_the_subagent_only_its_own_task():
    for name in _dev_wrapper_names("dev-execute"):
        text = _dev_wrapper_body(name)
        assert "task block" in text, name
        assert "Interfaces" in text, name
        assert "the plan is incomplete" in text, name
        assert "dev-plan" in text, name


# --- C4: search budget discipline ------------------------------------------

SEARCH_BUDGET_WRAPPERS = BA_WRAPPERS + _dev_wrapper_names("dev-implement-ticket")


def test_search_budget_is_a_number_not_a_gesture():
    # Final review F10: "500" and "800" checked separately are each
    # satisfiable on their own (a version number, a line count) without
    # the budget literal actually surviving. The literal is the en dash
    # range "500–800", confirmed present as one token in all 12
    # wrappers; assert on that instead of the two halves.
    for name in SEARCH_BUDGET_WRAPPERS:
        text = _normalised(_read_init_template(name))
        assert "500–800" in text, name
        assert "within the token budget" not in text, name


def test_search_budget_names_what_the_budget_buys():
    for name in SEARCH_BUDGET_WRAPPERS:
        text = _normalised(_read_init_template(name))
        assert "kb_get_section" in text, name
        assert "encoded in code" in text, name


# --- B4: the handover carries the ticket's measured cost --------------------
#
# The four ba-ticket-author wrappers are already enumerated at the top of
# this file as BA_TICKET_AUTHOR_TEMPLATES (line 14) — reuse it rather than
# spelling the names a second time.


def test_dev_handover_reports_usage_in_the_pr():
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        assert "kb usage report" in text, name
        assert "## Usage" in text, name
        # An empty ledger is a finding, not a reason to drop the section.
        assert "no usage recorded yet" in text, name


def test_ba_ticket_author_reports_usage_at_handover():
    for name in BA_TICKET_AUTHOR_TEMPLATES:
        text = _ba_wrapper_text(name)
        assert "kb usage report" in text, name
        # The BA repo's ledger is only half the ticket's lifetime cost.
        assert "authoring cost" in text, name


# --- A4: kb-context tags are derived by the engine, never authored ----------


def test_ba_wrappers_never_pass_tags_to_kb_context_new():
    for name in BA_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert 'kb context new --refs "<refs>" --tags' not in text, name
        assert "(+ tags)" not in text, name


def test_ba_wrappers_say_who_owns_the_tags():
    for name in BA_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "Tags are NOT yours to set" in text, name
        assert "hub vocabulary" in text, name


def test_ba_wrappers_keep_tags_as_a_search_filter():
    """The Search step's `kb query --tags` line survives; only the pin
    path lost tags.

    Scoped to the 7 wrappers that actually carry a Search step —
    `BA_TICKET_AUTHOR_FULL_TEMPLATES` union `BA_MISSION_PLAN_TEMPLATES`.
    `claude-command-ba-ticket-author.md` never had a `kb query` line at
    all, so it is excluded rather than guarded by nothing. Asserting
    the full literal (not just "kb query" and "--tags" separately)
    matters: Task 5's own added sentence ends "...are search keywords
    for `kb query --tags`, nothing more.", which would otherwise
    satisfy the weaker two-piece assertion by itself.
    """
    for name in BA_TICKET_AUTHOR_FULL_TEMPLATES + BA_MISSION_PLAN_TEMPLATES:
        text = _ba_wrapper_text(name)
        assert 'kb query "<text>" --tags <tags>' in text, name


# --- C2: review rounds 2-3 verify gaps, they do not re-read the draft -------


def test_ba_wrappers_use_a_single_gap_verifier_for_rounds_two_and_three():
    for name in BA_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "gap-verifier" in text, name


def test_ba_wrappers_keep_round_one_two_perspective():
    """C2 shrinks rounds 2-3 only; round 1 keeps both reviewers.

    Scoped to the 7 full-shaped wrappers, not all of BA_WRAPPERS:
    `claude-command-ba-ticket-author.md` never named either reviewer
    role by this exact phrase (it is the short wrapper with "no
    maturity detail"), and C2's Step 6 edit for that file adds only
    the `gap-verifier` clause, not these two phrases. Same asymmetry
    as `test_ba_wrappers_do_not_let_the_gap_verifier_invent_a_score`.
    """
    for name in ("claude-skill-ba-ticket-author.md", "claude-skill-ba-mission-plan.md",
                 "copilot-ba-ticket-author.prompt.md", "cursor-ba-ticket-author.md",
                 "copilot-ba-mission-plan.prompt.md", "cursor-ba-mission-plan.md",
                 "claude-command-ba-mission-plan.md"):
        text = _ba_wrapper_text(name)
        assert "Business-coverage reviewer" in text, name
        assert "Dev-implementability reviewer" in text, name


def test_ba_wrappers_do_not_let_the_gap_verifier_invent_a_score():
    """Final-review F2: the old justification ("it does not score an
    axis, having not read enough of the draft to score one") was true
    only for a genuinely dispatched subagent, and false for the two
    dialects that run the gap-verifier pass themselves — a
    self-passing agent HAS read the whole draft. All 7 wrappers now
    carry an instruction instead of that description, so the rule
    holds regardless of which branch a given runtime takes.
    """
    for name in ("claude-skill-ba-ticket-author.md", "claude-skill-ba-mission-plan.md",
                 "copilot-ba-ticket-author.prompt.md", "cursor-ba-ticket-author.md",
                 "copilot-ba-mission-plan.prompt.md", "cursor-ba-mission-plan.md",
                 "claude-command-ba-mission-plan.md"):
        text = _ba_wrapper_text(name)
        assert "does not score an axis" not in text, name
        assert "do **not** re-score an axis in this pass" in text, name
        assert "carry the previous round's score forward" in text, name


# --- Batch 5 (D conventions pack): base conventions templates ---------------

# The two sections that stay in the entry file whatever else moves: the
# citation rule and the lint preset. `## Linting (preset)` in particular is
# named by the dev-plan wrappers, which is pinned below in
# test_dev_plan_refuses_a_draft_design_and_writes_the_cmd_headers.
CONVENTIONS_SECTION_HEADINGS = (
    "## Citation comments",
    "## Linting (preset)",
)

# Moved into `<lang>/coding-style.md` (the first four) and
# `<lang>/testing.md` (the last) when a language's pack lands.
CONVENTIONS_MOVED_HEADINGS = (
    "## Naming",
    "## Module structure",
    "## Error handling",
    "## Logging",
    "## Testing",
)
CONVENTIONS_PACK_MARKER = "## Conventions pack"


def test_conventions_python_and_ts_templates_carry_the_full_skeleton():
    for name, needles in (
        (
            "conventions-python.md",
            ("ruff.toml", "ruff check . && ruff format --check ."),
        ),
        (
            "conventions-ts.md",
            ("eslint.config.mjs", "npx eslint . && npx prettier --check .", ".prettierrc.json"),
        ),
    ):
        text = _read_init_template(name)
        for heading in CONVENTIONS_SECTION_HEADINGS:
            assert heading in text, f"{name}: missing {heading!r}"
        for needle in needles:
            assert needle in text, f"{name}: missing {needle!r}"
        assert ".local.md" in text, name          # override pointer in the header
        assert ".editorconfig" in text, name      # editorconfig block present
        assert "per ATM-STD §5.3" in text, name   # citation-comment example
        assert "cmd.lint" in text, name           # preset names the recorded command


def test_conventions_java_and_go_templates_carry_the_full_skeleton():
    for name, needles in (
        (
            "conventions-java.md",
            ("spotless", "checkstyle", "googleJavaFormat", "spotlessCheck", "resources.text.fromArchiveEntry", "checkstyleConfig"),
        ),
        (
            "conventions-go.md",
            (".golangci.yml", "golangci-lint run", "gofmt"),
        ),
    ):
        text = _read_init_template(name)
        for heading in CONVENTIONS_SECTION_HEADINGS:
            assert heading in text, f"{name}: missing {heading!r}"
        for needle in needles:
            assert needle in text, f"{name}: missing {needle!r}"
        assert ".local.md" in text, name
        assert ".editorconfig" in text, name
        assert "per ATM-STD §5.3" in text, name
        assert "cmd.lint" in text, name


def test_conventions_php_and_dotnet_templates_carry_the_full_skeleton():
    for name, needles in (
        (
            "conventions-php.md",
            (".php-cs-fixer.dist.php", "@PSR12", "php-cs-fixer check"),
        ),
        (
            "conventions-dotnet.md",
            ("dotnet format --verify-no-changes", "dotnet_diagnostic", "EnforceCodeStyleInBuild"),
        ),
    ):
        text = _read_init_template(name)
        for heading in CONVENTIONS_SECTION_HEADINGS:
            assert heading in text, f"{name}: missing {heading!r}"
        for needle in needles:
            assert needle in text, f"{name}: missing {needle!r}"
        assert ".local.md" in text, name
        assert ".editorconfig" in text, name
        assert "per ATM-STD §5.3" in text, name
        assert "cmd.lint" in text, name


def test_conventions_local_stub_and_pointer_templates():
    stub = _read_init_template("conventions-local-stub.md")
    assert "never rewrites it" in stub
    assert "OVERRIDE" in stub

    mdc = _read_init_template("conventions-pointer.mdc")
    assert "globs: {globs}" in mdc
    assert "alwaysApply: false" in mdc

    instr = _read_init_template("conventions-pointer.instructions.md")
    assert 'applyTo: "{globs}"' in instr

    for text in (mdc, instr):
        assert "docs/conventions/{lang}.md" in text
        assert "docs/conventions/{lang}.local.md" in text
        # raw-text needle kept to one source line — the phrase wraps
        assert "wins locally" in text


@pytest.mark.parametrize("lang", LANG_IDS)
def test_conventions_entry_file_links_its_pack(lang):
    """Every entry file is an index: it links its five language pack files
    and the five shared ones, and none of the moved headings survives in
    it. Naming / Module structure / Error handling / Logging now live in
    `<lang>/coding-style.md`, Testing in `<lang>/testing.md`."""
    text = _read_init_template(f"conventions-{lang}.md")
    assert CONVENTIONS_PACK_MARKER in text, f"{lang}: entry file has no pack table"
    for part in CONVENTION_PARTS:
        assert f"({lang}/{part}.md)" in text, f"{lang}: no link to {lang}/{part}.md"
        assert f"(common/{part}.md)" in text, f"{lang}: no link to common/{part}.md"
    for heading in CONVENTIONS_MOVED_HEADINGS:
        assert heading not in text, f"{lang}: {heading!r} should have moved into the pack"


@pytest.mark.parametrize("lang", LANG_IDS)
def test_language_pack_templates_exist_and_extend_their_common_file(lang):
    """Every language in LANG_IDS has all five pack templates, each opening
    with the extends line that names its common counterpart, carrying a
    real title on line 3 and real section content — not just the T1
    skeleton (extends line, blank, title, blank, ownership paragraph)."""
    base = resources.files("strata_kb").joinpath("templates/init")
    names = {part: f"conventions-{lang}-{part}.md" for part in CONVENTION_PARTS}
    for part, name in names.items():
        assert base.joinpath(name).is_file(), name
        text = _read_init_template(name)
        assert text.startswith(
            f"> This file extends [common/{part}.md](../common/{part}.md) with "
        ), name
        lines = text.splitlines()
        # line 1: extends line, line 2: blank, line 3: title.
        assert lines[2].startswith("# "), f"{name}: line 3 is not the title"
        assert "\n## " in text, f"{name}: no section heading — content missing"
        assert len(lines) >= 12, f"{name}: looks like unfilled T1 boilerplate"
        for banned in ("ECC", "everything-claude", "~/.claude", "See skill:"):
            assert banned not in text, f"{name}: {banned!r} survived"


def test_common_pack_templates_exist_and_carry_no_extends_line():
    base = resources.files("strata_kb").joinpath("templates/init")
    for part in CONVENTION_PARTS:
        name = f"conventions-common-{part}.md"
        assert base.joinpath(name).is_file(), name
        text = _read_init_template(name)
        assert text.startswith("# "), name
        assert "This file extends" not in text, name
        assert "\n## " in text, f"{name}: no section heading — content missing"
        assert len(text.splitlines()) >= 12, f"{name}: looks like unfilled T1 boilerplate"
        for banned in ("ECC", "everything-claude", "~/.claude", "See skill:"):
            assert banned not in text, f"{name}: {banned!r} survived"


def test_python_coding_style_pack_keeps_the_moved_logging_needle():
    # 02dd7d8 moved `## Logging` out of the entry file into the pack; this
    # pins the needle so a future edit can't silently drop the section's
    # content along with the heading.
    text = _read_init_template("conventions-python-coding-style.md")
    assert "logging.getLogger" in text


# --- Batch 5 (D conventions pack): skill-text round -------------------------


def test_dev_plan_first_task_sets_up_the_linter_when_the_repo_has_none():
    # D1: the existing bullet only handles "no -code document" by asking for
    # commands; a repo with NO linter at all had nothing to record and no
    # guidance. The preset lives in the Linting section of the scaffolded
    # conventions base file.
    for name in _dev_wrapper_names("dev-plan"):
        text = _dev_wrapper_text(name)
        assert "no linter at all" in text, name
        assert "docs/conventions/<lang>.md" in text, name
        assert "*Linting* section" in text, name
        assert "first task" in text, name
        assert "docs/conventions/<lang>.local.md" in text, name


def test_dev_execute_review_checkpoint_points_at_the_conventions_files():
    # D4: "the repo's existing conventions" was unactionable — the checkpoint
    # now names the scaffolded files, the local-wins order, and the
    # conflict-becomes-a-finding rule.
    for name in _dev_wrapper_names("dev-execute"):
        text = _dev_wrapper_text(name)
        assert "docs/conventions/<lang>.md" in text, name
        assert "docs/conventions/<lang>.local.md" in text, name
        assert "the repo wins locally" in text, name
        assert "the repo's existing conventions" not in _dev_wrapper_body(name), name


# --- Batch 7 (E1 + E2): the PR evidence gate --------------------------------

import re as _re

from strata_kb.prlint import REQUIRED_SECTIONS

DEV_HANDOVER_TEMPLATES = _dev_wrapper_names("dev-handover")
EXEMPTION_SLUGS = ("config", "ci", "docs", "style")


def _pr_template_headings() -> list[str]:
    text = _read_init_template("pull-request-template.md")
    return [
        m.group(1).strip()
        for m in _re.finditer(r"^##[ \t]+(.+?)[ \t]*$", text, _re.MULTILINE)
    ]


def test_pr_template_headings_are_the_canon_in_order():
    # Canon pin, place 1 of 3: the shipped template against the module.
    assert tuple(_pr_template_headings()) == REQUIRED_SECTIONS


def test_every_required_section_is_named_in_the_dev_handover_wrappers():
    # Canon pin, place 2 of 3: the skill that assembles the body must name
    # every section the gate demands, or the gate fails PRs the skill wrote.
    for name in DEV_HANDOVER_TEMPLATES:
        body = _dev_wrapper_body(name)
        for section in REQUIRED_SECTIONS:
            assert _normalised(section) in body, f"{name}: {section}"


def test_pr_workflow_triggers_include_edited_and_have_no_paths_filter():
    text = _read_init_template("kb-pr-lint.yml")
    assert "types: [opened, edited, synchronize, reopened]" in text
    # Catches `paths:` and `paths-ignore:` at any indent (e.g. a 2-space
    # nested key), not just the two exact spellings checked before.
    assert not _re.search(r"^\s*paths(-ignore)?:", text, _re.MULTILINE)
    assert "\n  pr-lint:" in text, "the job name is frozen for branch protection"


def test_pr_workflow_has_a_concurrency_group():
    # `edited` fires on every description edit, so an author iterating on a
    # PR body would otherwise queue one run per keystroke-batch.
    import yaml

    wf = yaml.safe_load(_read_init_template("kb-pr-lint.yml"))
    concurrency = wf["concurrency"]
    assert concurrency["group"] == "pr-lint-${{ github.event.pull_request.number }}"
    assert concurrency["cancel-in-progress"] is True


def test_pr_workflow_never_interpolates_the_body_into_the_script():
    # The injection mitigation pinned as a test rather than left as an
    # intention: the body may reach the script only through `env:`.
    text = _read_init_template("kb-pr-lint.yml")
    assert "PR_BODY: ${{ github.event.pull_request.body }}" in text
    run_blocks = text.split("run: |")[1:]
    for block in run_blocks:
        assert "github.event.pull_request.body" not in block
    assert 'kb pr lint "$RUNNER_TEMP/body.md"' in text
    # Total pin, not just multi-line `run: |` blocks: a single-line
    # `- run: echo ${{ github.event.pull_request.body }}` would sail past
    # the run_blocks check above without this.
    assert text.count("github.event.pull_request.body") == 1


def test_tdd_exemptions_doc_carries_the_four_slugs_and_the_boundary():
    text = _read_init_template("tdd-exemptions.md")
    for slug in EXEMPTION_SLUGS:
        assert f"`{slug}`" in text, slug
    # Normalised, not raw: the shipped doc hard-wraps this exact phrase as
    # "...with no\nobservable behaviour..." — a real newline, not a space —
    # so the raw-text needle can never match without reflowing Task 3's
    # shipped prose, which is out of scope for this task. `_normalised`
    # is the file's own documented tool for matching a phrase a hard-wrap
    # is free to break across lines.
    assert "no observable behaviour" in _normalised(text)
    assert "when the plan is written" in text
    assert "Exempt: <config|ci|docs|style> — verified by <what>" in text


def test_tdd_exemptions_doc_names_every_slug_prlint_recognizes():
    # Ties the doc to prlint.EXEMPTION_SLUGS itself, not the hand-copied
    # tuple above — a slug added in code with no matching doc update fails
    # this test (final-review finding 4).
    from strata_kb.prlint import EXEMPTION_SLUGS as PRLINT_EXEMPTION_SLUGS

    text = _read_init_template("tdd-exemptions.md")
    for slug in PRLINT_EXEMPTION_SLUGS:
        assert f"`{slug}`" in text, slug


DEV_PLAN_TEMPLATES = _dev_wrapper_names("dev-plan")
DEV_EXECUTE_TEMPLATES = _dev_wrapper_names("dev-execute")


def test_dev_plan_requires_an_exemption_line_for_a_task_with_no_test():
    for name in DEV_PLAN_TEMPLATES:
        body = _dev_wrapper_body(name)
        assert "docs/tdd-exemptions.md" in body, name
        assert _normalised("Exempt: <config|ci|docs|style>") in body, name


def test_dev_execute_honours_a_declared_exemption_and_refuses_an_undeclared_one():
    for name in DEV_EXECUTE_TEMPLATES:
        body = _dev_wrapper_body(name)
        assert "docs/tdd-exemptions.md" in body, name
        assert "Exempt:" in body, name
        # The undeclared case returns to dev-plan; it is never the
        # implementer's call.
        assert _normalised("return the task to `dev-plan`") in body, name


def test_dev_handover_reports_the_exemptions_or_none():
    for name in DEV_HANDOVER_TEMPLATES:
        body = _dev_wrapper_body(name)
        assert _normalised("## TDD exemptions") in body, name
        assert _normalised("`none`") in body, name


def test_quickstart_dev_names_the_pr_gate_and_the_required_check():
    text = _read_init_template("QUICKSTART-dev.md")
    assert "kb pr lint" in text
    assert "docs/tdd-exemptions.md" in text
    assert "required check" in text


SUMMARIZE_WRAPPERS = [
    "claude-skill-kb-summarize.md",
    "copilot-kb-summarize.instructions.md",
    "cursor-kb-summarize.md",
    "cursor-kb-summarize.mdc",
]


def _tpl(name: str) -> str:
    return resources.files("strata_kb.templates.init").joinpath(name).read_text(encoding="utf-8")


_REPO_ROOT = Path(__file__).resolve().parent.parent


# Every one of these is a hand-maintained copy, inside this repo, of a file
# that ships to every scaffolded repo. Only the first pair used to be pinned,
# and the other five drifted exactly the way you would expect: a batch that
# corrected one sentence had to correct five hand-kept copies of it, by hand.
_REPO_MIRRORS = [
    (".claude/skills/kb-summarize/SKILL.md", "claude-skill-kb-summarize.md"),
    (".claude/commands/kb-summarize.md", "claude-command-kb-summarize.md"),
    (".claude/skills/kb-ingest/SKILL.md", "claude-skill-kb-ingest.md"),
    (".claude/skills/kb-publish/SKILL.md", "claude-skill-kb-publish.md"),
    (".github/prompts/kb-ingest.prompt.md", "copilot-kb-ingest.prompt.md"),
    (".github/prompts/kb-publish.prompt.md", "copilot-kb-publish.prompt.md"),
]


@pytest.mark.parametrize("mirror,template", _REPO_MIRRORS)
def test_repo_mirror_is_the_shipped_template(mirror, template):
    assert (_REPO_ROOT / mirror).read_text(encoding="utf-8") == _tpl(template)


@pytest.mark.parametrize("name", SUMMARIZE_WRAPPERS)
def test_summarize_wrappers_use_print_prompt_not_l3(name):
    text = _tpl(name)
    assert "kb summarize <doc-id> --print-prompt" in text
    assert "--level l3" not in text
    assert "kb build --strict" in text
    assert "Table-only section:" not in text   # engine alone decides table-only


def test_claude_skill_summarize_contract_and_validation():
    text = _tpl("claude-skill-kb-summarize.md")
    assert '[{"section_id": "...", "l2_summary": "...", "l1_summary": "..."}, ...]' in text
    assert '"table_only"' not in text
    assert "HARD LIMIT" in text and "≤ 25 words" in text
    assert "kb build --allow-pending --strict" in text
    assert "max 30 words" in text


def test_quickstart_ba_does_not_claim_ci_enforces_stale_refs():
    text = _read_init_template("QUICKSTART-ba.md")
    enforced, _, not_enforced = text.partition("What lint does **not** enforce")
    assert "stale" not in enforced.lower()
    assert "stale" in not_enforced.lower()
    assert "--fail-on-stale" in text


# Task 12: Task 3 made `[doc-id §section]` (BRACKET_CITE_RE) the only
# citation form the gate parses; the bare `doc-id §section` form
# (INLINE_CITE_RE) is now a migration warning. Every scaffolded template
# and BA wrapper must teach the bracketed form so a freshly authored
# ticket does not collect a migration warning from its first line.
_CITATION_TEMPLATES = (
    "ticket-template.md",
    "mission-template.md",
    "review-rubric.md",
    "ac-quality.md",
    "QUICKSTART-ba.md",
    *BA_WRAPPERS,
    *SA_WRAPPERS,
)


@pytest.mark.parametrize("name", _CITATION_TEMPLATES)
def test_every_citation_example_is_bracketed(name):
    """A template that teaches the bare form, in the text a BA might
    actually copy into ticket prose, teaches a migration warning.

    Scans `lintcore.citation_scan_text` — the same view the gate itself
    scans (comments, fences, and kb-context blocks stripped) — rather
    than the raw file: a template may show the real, un-bracketed
    citation SYNTAX once inside a fenced block as reference material
    (e.g. QUICKSTART-ba.md's '<repo>-code §svc.<name>'), which is never
    prose a BA would paste verbatim and never reaches the gate's own
    scan of a real ticket either."""
    text = _read_init_template(name)
    scanned = lintcore.citation_scan_text(text)
    bare = [
        m.group(0)
        for m in lintcore.INLINE_CITE_RE.finditer(
            lintcore.BRACKET_CITE_RE.sub("", scanned)
        )
    ]
    assert bare == []


def test_the_ticket_template_shows_the_bracketed_form():
    assert "[doc-id §section]" in _read_init_template("ticket-template.md")


# --- Task 13 (MEDIUM-6): pinned CLI, concurrency, annotated failures --------


def test_ticket_lint_workflow_has_a_concurrency_block():
    assert "concurrency:" in _read_init_template("kb-ticket-lint.yml")


def _lint_dispatch_run_script(text: str) -> str:
    """The `run:` body of the 'Lint changed ...' step, parsed out of the raw
    workflow YAML (mirrors tests/test_init.py's `_extract_lint_dispatch_script`,
    which needs a rendered `init_repo()` checkout this module doesn't have)."""
    data = yaml.safe_load(text)
    for step in data["jobs"]["lint"]["steps"]:
        if "Lint changed" in step.get("name", ""):
            return step["run"]
    raise AssertionError("no step with 'Lint changed' in its name in kb-ticket-lint.yml")


def test_ticket_lint_workflow_annotates_and_summarises():
    # Task 13 review (Important 2): a raw substring check on the whole file
    # would pass even if these strings only ever appeared in a comment. Pin
    # them to actual (non-comment) lines of the executed dispatch script.
    text = _read_init_template("kb-ticket-lint.yml")
    run_script = _lint_dispatch_run_script(text)
    code_lines = [
        line
        for line in run_script.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    code = "\n".join(code_lines)
    assert "--json" in code
    assert "GITHUB_STEP_SUMMARY" in code
    assert "::error file=" in code


def test_ticket_lint_workflow_keeps_a_non_https_hub_scheme():
    assert "${STRATA_KB_HUB#https://}" not in _read_init_template(
        "kb-ticket-lint.yml"
    )


def test_quickstart_ba_documents_the_ci_variables():
    text = _read_init_template("QUICKSTART-ba.md")
    assert "vars.STRATA_KB_HUB" in text
    assert "secrets.KB_HUB_TOKEN" in text
    assert "fork" in text.lower()


def test_pr_workflow_checks_out_the_branch_read_only_for_the_plan_file():
    import yaml

    wf = yaml.safe_load(_read_init_template("kb-pr-lint.yml"))
    steps = wf["jobs"]["pr-lint"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    assert steps.index(checkout) < steps.index(next(s for s in steps if "Check the PR" in s.get("name", "")))


# --- Task 13: one tightening rule in every preset, plus the lint values ----

TIGHTENING_RULE = "The preset below is the target strength."


def test_every_conventions_preset_carries_the_one_tightening_rule():
    for lang in ("python", "ts", "java", "go", "dotnet", "php"):
        text = _normalised(_read_init_template(f"conventions-{lang}.md"))
        assert TIGHTENING_RULE in text, lang
        assert "narrow" in text and "## Findings" in text, lang
        assert "exactly as shown" not in text, lang


def test_presets_lint_the_rules_their_prose_states():
    py = _read_init_template("conventions-python.md")
    assert '"T20"' in py and '"N"' in py
    ts = _read_init_template("conventions-ts.md")
    assert '"no-console": "error"' in ts
    java = _read_init_template("conventions-java.md")
    assert "[*.java]\nindent_size = 2" in java
    assert "maxWarnings = 0" not in java.split("```groovy")[1].split("```")[0]


def test_dev_design_writes_a_file_on_every_path_with_a_status_header():
    for name in _dev_wrapper_names("dev-design"):
        body = _dev_wrapper_body(name)
        assert "Every path writes `docs/impl/<ticket-id>-design.md`" in body, name
        assert "`path: <spike|bounded|architectural>`" in body, name
        assert "`status: draft`" in body, name
        assert "`status: approved`" in body, name
        assert "in chat" not in body, name
        assert "architectural path only" not in body, name


def test_dev_plan_refuses_a_draft_design_and_writes_the_cmd_headers():
    for name in _dev_wrapper_names("dev-plan"):
        body = _dev_wrapper_body(name)
        assert "`status: approved`" in body, name
        assert "`cmd.test: <command>`" in body, name
        assert "`cmd.lint: <command>`" in body, name
        assert "`status: draft`" in body, name
        assert "path: spike" in body, name
        assert "in chat" not in body, name
        assert "untouched tree" not in body, name
        assert "Linting* section of `docs/conventions/<lang>.md`" in body, name


def test_dev_implement_ticket_names_every_re_entry_case():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        body = _dev_wrapper_body(name)
        for needle in ("status: draft", "N commits on branch", "--state merged",
                       "--state closed", "two tickets in flight",
                       "git switch -c <ticket-id>", "gh not installed"):
            assert needle in body, f"{name}: {needle}"


def test_quickstart_dev_separates_machine_enforced_from_prompt_only():
    text = _read_init_template("QUICKSTART-dev.md")
    _, _, rest = text.partition("## What is enforced")
    machine, _, prompt_only = rest.partition("### Prompt-only")
    assert "### Machine-enforced" in machine
    assert "`kb pr lint`" in machine and "`kb build`" in machine
    for rule in ("TDD", "verbatim", "read-only", "GATE 1", "OPEN(BA)"):
        assert rule in prompt_only, rule
    assert "nothing in `kb` enforces or measures" in prompt_only
    assert "No such command 'pr'" not in text


def test_dev_implement_ticket_ground_step_tells_generated_from_published():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        body = _dev_wrapper_body(name)
        assert ".kb/<repo_id>-code/" in body, name
        assert "generated, unpublished: run `kb publish`" in body, name
        assert "is missing whenever" not in body, name


def test_pr_review_rubric_templates_exist_as_package_resources():
    base = resources.files("strata_kb").joinpath("templates/init")
    for name in ("pr-review-rubric.md", "pr-review-rubric-local-stub.md"):
        assert base.joinpath(name).is_file(), name


def test_pr_review_rubric_carries_both_halves_and_the_ladder():
    text = _read_init_template("pr-review-rubric.md")
    assert "## Pre-code axes" in text
    assert "## Merge-risk axes" in text
    for level in ("BLOCKER", "SUGGESTED", "NOTE", "NITS"):
        assert level in text, level
    # The wide reviewer's defining rule: the diff alone is not the review.
    assert "not the review" in _normalised(text)


def test_pr_review_rubric_names_every_merge_risk_axis():
    body = _normalised(_read_init_template("pr-review-rubric.md"))
    for axis in (
        "Security & authorization",
        "Data integrity",
        "Performance & scale",
        "Contract & backward compatibility",
        "Migration, rollout & rollback",
        "Observability",
        "Test adequacy",
        "Production readiness",
    ):
        assert axis in body, axis


def test_pr_review_rubric_is_wired_into_dev_kind_only():
    from strata_kb import initcmd

    assert initcmd.DEV_TEMPLATES["docs/pr-review-rubric.md"] == "pr-review-rubric.md"
    assert initcmd.DEV_LOCAL_OVERRIDES == {
        "docs/pr-review-rubric.local.md": "pr-review-rubric-local-stub.md",
    }
    for kind in ("hub", "child", "ba"):
        assert "docs/pr-review-rubric.md" not in initcmd.expected_files(kind), kind


def test_impl_gitignore_excludes_the_review_artefacts():
    text = _read_init_template("impl-gitignore.txt")
    assert "*-review/" in text


REVIEW_CONTRACT_SKILLS = ("dev-design", "dev-plan", "dev-execute", "dev-handover")

REVIEW_CONTRACT_BOUNDS = (
    "## Review dispatch contract (every review in this flow)\n",
    "  `Review: ✅ r<n> (fallback, Dev-approved)`.\n",
)

# Canon text for each of the five review blocks, extracted verbatim (via
# repr(), same discipline as SHARED_BLOCK_TEXT above — never hand-retyped)
# from a landed wrapper. Unlike SHARED_BLOCKS/SHARED_BLOCK_TEXT (3 blocks x
# 20 files, every skill carries all three), these five blocks have two
# different file counts — the contract lives in 16 wrappers (the four
# phases that dispatch a reviewer), each A-block lives in only the 4
# wrappers of its own skill — so they get their own dict rather than
# joining SHARED_BLOCKS, whose own test asserts a block is present in all
# 20 wrappers.
REVIEW_BLOCK_BOUNDS = {
    "REVIEW-CONTRACT": REVIEW_CONTRACT_BOUNDS,
    "A1": (
        "## A1 — independent design review (before GATE 1)\n",
        "no SUGGESTED gap left open; NOTE and NITS are recorded, not fixed.\n",
    ),
    "A2": (
        "## A2 — independent plan review (before GATE 2)\n",
        "left open; NOTE and NITS are recorded, not fixed.\n",
    ),
    "A4": (
        "## A4 — narrow branch review (after the last task)\n",
        "`/dev-handover <ticket-id>`.\n",
    ),
    "A5": (
        "## A5 — merge-risk review (before GATE 3)\n",
        "becomes the fix, not the PR.\n",
    ),
}

# Extracted the same way as SHARED_BLOCK_TEXT: repr() of each block sliced
# out of a landed wrapper (claude-skill-dev-design.md for A1, ...-dev-plan.md
# for A2, ...-dev-execute.md for A4, ...-dev-handover.md for A5, and
# claude-skill-dev-design.md again for the contract), never hand-retyped.
REVIEW_BLOCK_TEXT = {
    "REVIEW-CONTRACT": "## Review dispatch contract (every review in this flow)\n\n- The author and the reviewer are NEVER the same subagent. A self-review\n  never satisfies a review step.\n- A reviewer starts from a fresh context and gets no conversation history —\n  hand it only the paths it must read and the constraints that bind it.\n- Artefacts move as FILE PATHS, never pasted into the dispatch prompt: the\n  draft, the diff, the report. Whatever you paste stays in your context for\n  the rest of the session.\n- Never pre-judge: a dispatch prompt never tells a reviewer what not to flag\n  and never rates a finding's severity for it.\n- Name the model on every dispatch — a standard model for authors and\n  implementers, the most capable one available for reviewers. Never inherit\n  the session default silently.\n- Findings → fix subagent → re-review, at most 3 rounds. A BLOCKER or SUGGESTED still\n  standing after round 3 stops the flow and goes to the Dev.\n- A finding that contradicts the approved design or plan is never auto-fixed:\n  show the finding beside the text that mandates it and let the Dev choose.\n- Criteria come from the source that matches the review: the rubric's\n  `## Pre-code axes` for A1 and A2, its `## Merge-risk axes` for A5, and\n  `docs/conventions/<lang>.md` — plus the five pack files it links under\n  `docs/conventions/<lang>/` and `docs/conventions/common/` — for A3 and A4.\n  Each one's own `.local.md` override wins over its base file. Severity is\n  always BLOCKER / SUGGESTED / NOTE / NITS.\n- Where the runtime cannot dispatch subagents, run the review as its own pass\n  that reads ONLY the paths it was handed and reuses nothing it remembers from\n  drafting, and write up its findings the same way — then STOP and hand the\n  result to the Dev. The phase does not advance on a fallback pass: one\n  context reviewing itself is a weaker substitute, not an equivalent — only\n  the Dev's explicit go-ahead advances it, recorded in the tick itself, e.g.\n  `Review: ✅ r<n> (fallback, Dev-approved)`.\n",
    "A1": "## A1 — independent design review (before GATE 1)\n\nWrite the design in its own context: dispatch a `design-author` subagent with\nthe resolved context cache path, the ticket's acceptance criteria, the\nconventions paths, and this phase's own authoring rules above — what the\ndesign must cover, and how placeholders and standard values are cited — and\nlet it write `docs/impl/<ticket-id>-design.md` with `status: draft`. You\norchestrate; you do not draft and then judge your own draft.\n\nThat design is a draft until a reviewer that never saw it being written\nsays otherwise. Dispatch a `design-reviewer` subagent and hand it exactly\nthese things: the path `docs/impl/<ticket-id>-design.md`, the ticket's\nacceptance criteria, and the `## Pre-code axes` of `docs/pr-review-rubric.md`\nplus `docs/pr-review-rubric.local.md`. Not your reasoning, not this\nconversation.\n\nIt returns pass/fail per axis plus a gap list in which every gap names the\nsection it lives in, its severity, and a proposed fix. Apply BLOCKER and\nSUGGESTED gaps through a fix subagent, then re-review — at most 3 rounds.\n\nRecord every round in the design file's `## Review record` table, creating it\nbelow the design body on round 1:\n\n    | Date | Round | Verdict | Reviewer | Open gaps |\n    |---|---|---|---|---|\n    | <date> | 1 | BLOCKER x1 | design-reviewer | AC3 not addressed |\n\nGATE 1 is offered only after A1 comes back clean — clean means no BLOCKER and\nno SUGGESTED gap left open; NOTE and NITS are recorded, not fixed.\n",
    "A2": "## A2 — independent plan review (before GATE 2)\n\nDispatch a `plan-author` subagent to turn the approved design into the plan —\nit gets the design file path, the ticket's acceptance criteria, the\n`cmd.test` / `cmd.lint` commands, and this phase's own authoring rules above\n— the one-task-per-AC shape, the three per-task headings, the `Exempt:` line\nformat, the ordering rules — and nothing else. Then review it with a\ndifferent context.\n\nDispatch a `plan-reviewer` subagent with a fresh context. Hand it exactly: the\npath `docs/impl/<ticket-id>-plan.md`, the ticket's acceptance criteria, and the\n`## Pre-code axes` of `docs/pr-review-rubric.md` plus\n`docs/pr-review-rubric.local.md`. It answers five questions and nothing else:\n\n- Is there exactly one task per AC — none missing, none invented?\n- Does every task state its failing test before its implementation?\n- Is each task's **Interfaces** entry complete enough that its implementer\n  never has to read outside its own task block? An incomplete entry is a\n  BLOCKER: it is what forces an implementer to read wider and guess.\n- Does every task with no test declare `Exempt: <config|ci|docs|style>` and\n  name its verification?\n- Is every `Depends on:` line consistent with Files and Interfaces — no\n  two tasks without a dependency path share a path, every consumed\n  interface names its producer, no cycle? A miss is a BLOCKER. The\n  reviewer also runs `kb plan waves` and quotes its output; an error\n  there is a BLOCKER on its own.\n\nFix subagent, re-review, at most 3 rounds. Record each round in the plan file's\n`## Review record` table, same shape as the design file's. GATE 2 is offered\nonly after A2 comes back clean — clean means no BLOCKER and no SUGGESTED gap\nleft open; NOTE and NITS are recorded, not fixed.\n",
    "A4": "## A4 — narrow branch review (after the last task)\n\nEvery box ticked is not the same as the ticket being done. Write the branch\ndiff to `docs/impl/<ticket-id>-review/branch.diff`\n(`mkdir -p docs/impl/<ticket-id>-review` if it does not exist yet, then\n`git diff $(git merge-base <default-branch> HEAD)..HEAD`) and dispatch a\n`branch-reviewer` subagent with that path, the plan, the ticket, and\n`docs/conventions/<lang>.md`, the five pack files it links, and its\n`.local.md` override. One question\nonly: does this branch fulfil the ticket — every AC covered by a test,\nnothing built that no AC asked for, and no later task quietly breaking an\nearlier one?\n\nKeep the lens narrow here; merge risk is A5's job in `dev-handover`, against a\ndifferent rubric. Fix subagent, re-review, at most 3 rounds. Only once A4\ncomes back clean — no BLOCKER and no SUGGESTED left — is option 1\n`/dev-handover <ticket-id>`.\n",
    "A5": "## A5 — merge-risk review (before GATE 3)\n\nA4 asked whether the branch does what the ticket said. A5 asks a different\nquestion, in a different context: is this safe to merge into the default\nbranch?\n\nIf `docs/impl/<ticket-id>-review/branch.diff` does not exist yet — a cold\nhandover session, a fresh clone or worktree, or hand-implemented code that\nnever ran `dev-execute` — build it yourself first, with the same command A4\nuses: `mkdir -p docs/impl/<ticket-id>-review && git diff $(git merge-base\n<default-branch> HEAD)..HEAD > docs/impl/<ticket-id>-review/branch.diff`.\n\nDispatch a `merge-risk-reviewer` subagent on the most capable model available.\nGive it the persona plainly: a tech lead reviewing before a production deploy,\nassuming real traffic, concurrent requests, retries, and more than one running\ninstance. Hand it `docs/impl/<ticket-id>-review/branch.diff`, the ticket, and\nthe `## Merge-risk axes` of `docs/pr-review-rubric.md` plus\n`docs/pr-review-rubric.local.md`.\n\n**The diff alone is not the review.** Say so in the dispatch: the reviewer\nopens the files the change reaches — callers, siblings, migrations, permission\ndeclarations, contracts, tests — and traces the affected flow end to end before\njudging. A finding that only names a category is not a finding; it states why\nthis code, on this path, is dangerous.\n\nIt writes `docs/impl/<ticket-id>-review/merge-risk.md`: one row per finding\n(severity, file, line, why it is dangerous, proposed fix), then the verdict\nline `Blocking: Yes` while any BLOCKER stands, `Blocking: No` otherwise.\nBLOCKER and SUGGESTED findings get a fix round, then re-review, at most 3\nrounds — same routing as A3: only a standing BLOCKER keeps the verdict\n`Blocking: Yes`.\n\nCopy the table and the verdict line into the PR body's `## Review` section —\n`kb pr lint` fails the PR when the verdict line is missing and when it reads\n`Blocking: Yes`. NOTE and NITS findings go to `## Findings` as feedback\nitems, recorded rather than fixed.\n\nA branch whose A5 still reports `Blocking: Yes` never reaches GATE 3. Option 1\nbecomes the fix, not the PR.\n",
}


def _review_block(name: str, block: str) -> str:
    first, last = REVIEW_BLOCK_BOUNDS[block]
    text = _read_init_template(name)
    assert text.count(first) == 1, f"{name}: {block} opening line not found once"
    assert text.count(last) == 1, f"{name}: {block} closing line not found once"
    start = text.index(first)
    return text[start : text.index(last, start) + len(last)]


def _review_contract(name: str) -> str:
    return _review_block(name, "REVIEW-CONTRACT")


def test_review_contract_is_byte_identical_across_the_four_phase_skills():
    """1 block x 16 files, every copy checked against canon (not just against
    each other — see test_dev_wrappers_carry_byte_identical_shared_blocks'
    comment for why pairwise comparison is the hole this closes). The four
    phases dispatch reviewers; the two remaining dev wrappers
    (dev-implement-ticket, dev-code-seed) dispatch none, so the contract
    deliberately does not live there."""
    names = [
        name for skill in REVIEW_CONTRACT_SKILLS for name in _dev_wrapper_names(skill)
    ]
    assert len(names) == 16
    canon = REVIEW_BLOCK_TEXT["REVIEW-CONTRACT"]
    assert canon.strip(), "REVIEW-CONTRACT: empty canon"
    for name in names:
        assert _review_contract(name) == canon, name


@pytest.mark.parametrize(
    "block,skill",
    [
        ("A1", "dev-design"),
        ("A2", "dev-plan"),
        ("A4", "dev-execute"),
        ("A5", "dev-handover"),
    ],
)
def test_a_block_is_byte_identical_across_its_four_wrapper_forms(block, skill):
    """4 files per A-block, every copy checked against canon, same reasoning
    as the contract test above."""
    canon = REVIEW_BLOCK_TEXT[block]
    assert canon.strip(), f"{block}: empty canon"
    for name in _dev_wrapper_names(skill):
        assert _review_block(name, block) == canon, name


def test_review_contract_pins_the_rules_that_make_it_independent():
    body = _normalised(_review_contract("claude-skill-dev-design.md"))
    assert "NEVER the same subagent" in body
    assert "no conversation history" in body
    assert "FILE PATHS, never pasted" in body
    assert "never rates a finding's severity for it" in body
    assert "at most 3 rounds" in body
    assert "most capable one available" in body


def test_the_contract_is_absent_from_the_non_dispatching_wrappers():
    first = REVIEW_CONTRACT_BOUNDS[0]
    for skill in ("dev-implement-ticket", "dev-code-seed"):
        for name in _dev_wrapper_names(skill):
            assert first not in _read_init_template(name), name


def test_dev_design_dispatches_an_independent_reviewer_before_gate_one():
    for name in _dev_wrapper_names("dev-design"):
        body = _dev_wrapper_body(name)
        assert "A1" in body, name
        assert "design-author" in body, name
        assert "design-reviewer" in body, name
        assert "Pre-code axes" in body, name
        assert "## Review record" in body, name
        assert "GATE 1 is offered only after A1 comes back clean" in body, name


# Pin the `## Review record` table's shape, not just its heading: A2's
# review record table below reuses the same shape, so a change that keeps
# the heading but drops or reorders a column would still satisfy the bare
# "## Review record" needle above and pass unnoticed.
def test_dev_design_review_record_table_has_the_five_columns():
    for name in _dev_wrapper_names("dev-design"):
        body = _dev_wrapper_body(name)
        assert "| Date | Round | Verdict | Reviewer | Open gaps |" in body, name


# A1 must be dispatched, and its result checked, before GATE 1 is offered —
# a wrapper that moved A1 below the GATE 1 heading would still satisfy every
# other A1 needle. Only 3 of the 4 dev-design wrappers carry "## GATE 1" as
# a heading: claude-command-dev-design.md compresses GATE 1 into bold prose
# with no heading of its own, so it is not in this list.
DEV_DESIGN_WRAPPERS_WITH_GATE_ONE_HEADING = (
    "claude-skill-dev-design.md",
    "copilot-dev-design.prompt.md",
    "cursor-dev-design.md",
)


def test_dev_design_a1_precedes_the_gate_one_heading():
    for name in DEV_DESIGN_WRAPPERS_WITH_GATE_ONE_HEADING:
        text = _read_init_template(name)
        assert text.index("## A1 —") < text.index("## GATE 1"), name


# dev-plan and dev-handover have no "## GATE 2" / "## GATE 3" heading of
# their own — GATE 2/3 are a bullet inside "## Steps" (an outline that
# mentions the gate before it describes the review that unlocks it, the
# same summary-before-detail shape claude-command-dev-design.md uses for
# GATE 1). The text that actually governs the gate is the closing sentence
# inside the A2/A5 section itself, so that is what must follow the A-block
# heading, mirroring the A1/GATE-1 test above.
def test_dev_plan_a2_precedes_the_gate_two_offer_sentence():
    for name in _dev_wrapper_names("dev-plan"):
        text = _read_init_template(name)
        assert text.index("## A2 —") < text.index("GATE 2 is offered"), name


def test_dev_handover_a5_precedes_the_gate_three_offer_sentence():
    for name in _dev_wrapper_names("dev-handover"):
        text = _read_init_template(name)
        assert text.index("## A5 —") < text.index("never reaches GATE 3"), name


def test_dev_plan_dispatches_an_independent_reviewer_before_gate_two():
    for name in _dev_wrapper_names("dev-plan"):
        body = _dev_wrapper_body(name)
        assert "A2" in body, name
        assert "plan-author" in body, name
        assert "plan-reviewer" in body, name
        assert "Pre-code axes" in body, name
        assert "one task per AC" in body, name
        assert "GATE 2 is offered only after A2 comes back clean" in body, name


# A2's own reason for existing: an incomplete Interfaces entry is what
# forces a task-execute subagent to read outside its own task block and
# guess. It is currently the least-protected line in the block — nothing
# else in this file pins it — so a rewording that softened "BLOCKER" to a
# NOTE, or dropped the rule outright, would pass every other A2 assertion.
def test_dev_plan_a2_treats_an_incomplete_interfaces_entry_as_a_blocker():
    for name in _dev_wrapper_names("dev-plan"):
        body = _dev_wrapper_body(name)
        assert (
            "An incomplete entry is a BLOCKER: it is what forces an "
            "implementer to read wider and guess." in body
        ), name


def test_dev_plan_a2_requires_the_exempt_line_and_the_failing_test_question():
    for name in _dev_wrapper_names("dev-plan"):
        body = _dev_wrapper_body(name)
        assert (
            "Does every task with no test declare `Exempt: "
            "<config|ci|docs|style>` and name its verification?" in body
        ), name
        assert (
            "Does every task state its failing test before its "
            "implementation?" in body
        ), name


def test_dev_execute_reviews_each_task_in_a_separate_context():
    for name in _dev_wrapper_names("dev-execute"):
        body = _dev_wrapper_body(name)
        assert "task-reviewer" in body, name
        assert "review checkpoint" in body, name
        # This is what actually proves the self-review was demoted from
        # gate to checkpoint: "review checkpoint" alone does not — it is a
        # substring of "self-review checkpoint", which named the step
        # before A3 existed and would pass unchanged either way.
        assert "never satisfies A3" in body, name
        assert "docs/impl/<ticket-id>-review/task-<n>.diff" in body, name
        assert "never `HEAD~1`" in body, name
        assert "two verdicts" in body, name
        assert "Review: ✅ r" in body, name


# A3 hands control back to the orchestrator before the review step runs —
# without this sentence the review reads as nested inside the implementer's
# own procedure, exactly the regression the change was written to prevent,
# and every needle in the test above still passes in that state.
def test_dev_execute_a3_runs_in_the_orchestrator_not_the_implementer():
    # claude-command-dev-execute.md compresses this to "back in the
    # orchestrator, write ..." rather than the full sentence the other
    # three wrappers carry verbatim — the shared substring is the needle
    # common to all four, since it is what proves the hand-back happens at
    # all.
    for name in _dev_wrapper_names("dev-execute"):
        body = _dev_wrapper_body(name)
        assert "back in the orchestrator" in body, name


def test_dev_execute_closes_the_branch_with_a_narrow_review():
    for name in _dev_wrapper_names("dev-execute"):
        body = _dev_wrapper_body(name)
        # The bare "A4" needle is two characters any incidental mention
        # satisfies (e.g. "A4" inside a version string); pin the heading.
        assert "## A4 — narrow branch review (after the last task)" in body, name
        assert "branch-reviewer" in body, name
        assert "branch.diff" in body, name
        # A4's lens is ticket fulfilment; merge risk is A5's job in handover.
        assert "merge risk is A5" in body, name


def test_dev_handover_runs_a_merge_risk_review_before_gate_three():
    for name in _dev_wrapper_names("dev-handover"):
        body = _dev_wrapper_body(name)
        assert "A5" in body, name
        assert "merge-risk-reviewer" in body, name
        assert "Merge-risk axes" in body, name
        assert "The diff alone is not the review" in body, name
        assert "Blocking: No" in body, name
        assert "never reaches GATE 3" in body, name


# The old coverage for A5's PR-assembly addition was satisfied by the
# unrelated, pre-existing "## Review record" heading (the design/plan
# review table), asserting nothing about A5 actually being added to the
# PR-assembly list. Pin the clause itself, in the handover step's own
# words.
def test_dev_handover_pr_assembly_adds_the_review_section():
    # claude-command-dev-handover.md drops the bold markdown around "Review"
    # on this bullet ("...and Review — A5's..." vs "...and **Review** —
    # A5's..." in the other three); skip the varying lead-in and pin the
    # clause that is identical across all four wrappers.
    for name in _dev_wrapper_names("dev-handover"):
        body = _dev_wrapper_body(name)
        assert (
            "A5's finding table and its `Blocking:` verdict line." in body
        ), name


# --- SA grounding layer (PR 1): the two SA-owned template sections ---------

TECHNICAL_GROUNDING_FIELDS = (
    "- Grounded on:",
    "- Service:",
    "- Files:",
    "- Tables:",
    "- Routes:",
    "- Externals:",
    "- Verify with:",
    "- Open decisions:",
)


def test_ticket_template_carries_the_technical_grounding_section():
    text = _read_init_template("ticket-template.md")
    assert text.count("## Technical grounding") == 1
    body = lintcore.section_body(text, "## Technical grounding")
    assert body is not None
    for field in TECHNICAL_GROUNDING_FIELDS:
        assert field in body, field
    assert "[NEW:" in body
    assert "kb ticket check" in body
    # Section order: recommended sections sit before '## Open questions'.
    # Anchored on the heading LINE (leading '\n'), not a bare substring —
    # a backticked '## X' mention earlier in the file would otherwise win.
    assert text.index("\n## Technical grounding") < text.index("\n## Open questions")


def test_ticket_template_has_no_flow_or_failure_mode_field():
    # Spec §3: deliberately absent — the code document cannot prove them.
    body = lintcore.section_body(
        _read_init_template("ticket-template.md"), "## Technical grounding"
    )
    assert body is not None
    assert "- Flow:" not in body
    assert "- Failure modes:" not in body


def test_ticket_template_dor_names_the_grounding_gate():
    text = _read_init_template("ticket-template.md")
    dor = lintcore.section_body(text, "## Definition of Ready")
    assert dor is not None
    assert "Technical grounding filled by SA" in dor
    assert "kb ticket check PASS" in dor


def test_technical_grounding_is_a_recommended_heading():
    from strata_kb import ticket

    assert "## Technical grounding" in ticket.RECOMMENDED_HEADINGS
    assert "## Technical grounding" not in ticket.REQUIRED_HEADINGS
    order = list(ticket.RECOMMENDED_HEADINGS)
    assert order.index("## Technical grounding") == order.index("## Open questions") - 1


def test_mission_template_carries_services_and_order():
    text = _read_init_template("mission-template.md")
    assert text.count("## Services & order") == 1
    body = lintcore.section_body(text, "## Services & order")
    assert body is not None
    assert "- Grounded on:" in body
    assert "| Order | Service | Depends on | Why this order |" in body
    assert "svc.<name>" in body
    assert "[NEW:" in body
    # Capability layer only — the comment says what must NOT go here.
    assert "no tables, no routes" in body
    # Anchored on the heading LINE (leading '\n'), not a bare substring —
    # a backticked '## X' mention earlier in the file would otherwise win.
    assert (
        text.index("\n## Sequencing")
        < text.index("\n## Services & order")
        < text.index("\n## Open questions")
    )


def test_mission_required_headings_are_untouched_by_services_and_order():
    from strata_kb import mission

    assert "## Services & order" not in mission.REQUIRED_MISSION_HEADINGS
    assert "## Services & order" not in mission.RECOMMENDED_MISSION_HEADINGS


# --- PR 2 (greenfield): the templates teach the [NEW: D<n>] form ------------


def test_ticket_template_teaches_the_decision_reference():
    body = lintcore.section_body(
        _read_init_template("ticket-template.md"), "## Technical grounding"
    )
    assert body is not None
    normalised = _normalised(body)
    assert "[NEW: D<n>]" in normalised
    assert (
        "Code the ticket will create → [NEW: D<n>], where D<n> is a DECIDED "
        "row of the parent mission's Technology decisions."
    ) in normalised
    assert "No parent mission → [NEW: <reason>]." in normalised
    assert "[NEW: <why it does not exist yet>]" not in normalised


def test_mission_template_teaches_the_decision_reference():
    text = _read_init_template("mission-template.md")
    decisions = lintcore.section_body(text, "## Technology decisions")
    services = lintcore.section_body(text, "## Services & order")
    assert decisions is not None and services is not None
    decisions_n = _normalised(decisions)
    services_n = _normalised(services)
    assert (
        "The SA appends rows here for services, tables and routes the mission "
        "will create; tickets reference them as [NEW: D<n>]."
    ) in decisions_n
    assert "Only a human flips OPEN to DECIDED." in decisions_n
    assert (
        "| D2 | New svc.<name> — <one line> | OPEN | <SA / tech lead> | <US id> |"
        in decisions_n
    )
    assert "[NEW: D<n>]" in services_n
    # The shipped example must show the form the gate expects ([NEW: D<n>]),
    # not the free-text form the gate nudges against ([NEW: <reason>]) —
    # ticketcheck.check() would accept either (it returns early on a
    # placeholder `Grounded on:` line, and a literal `D<n>` fails
    # DECISION_REF_RE so is treated as free text anyway); this is about the
    # example teaching the right habit, not engine behaviour.
    assert "[NEW: <why it does not exist yet>]" not in services_n
    # The marker exempts the whole row, `Depends on` included — so the
    # comment has to say where it goes.
    assert "the marker goes on the new service only" in services_n


def test_review_rubric_dev_axis_requires_every_placeholder_answered():
    body = lintcore.section_body(
        _read_init_template("review-rubric.md"), "## Dev implementability"
    )
    assert body is not None
    assert (
        "Every `%%TODO: verify against codebase%%` in a BA section is "
        "answered in `## Technical grounding` by an id, a `[NEW: D<n>]`, "
        "or an Open decisions entry — none is silently dropped."
    ) in _normalised(body)


def _sa_hard_rules(name: str) -> str:
    """One SA wrapper's `## Hard rules` block, verbatim, to end of file.

    Only the three full-content wrappers carry the block; the command
    wrapper is a thin skill invoker that summarises the rules in prose.
    """
    text = _read_init_template(name)
    assert text.count("\n## Hard rules\n") == 1, name
    return text[text.index("\n## Hard rules\n") :]


def test_sa_hard_rules_are_byte_identical_across_the_full_wrappers():
    canon = _sa_hard_rules(SA_FULL_WRAPPERS[0])
    for name in SA_FULL_WRAPPERS[1:]:
        assert _sa_hard_rules(name) == canon, name


def test_sa_hard_rules_carry_the_two_greenfield_rules():
    block = _normalised(_sa_hard_rules(SA_FULL_WRAPPERS[0]))
    assert (
        "A thing the code does not have yet is a design decision, not missing "
        "data: propose it as a `## Technology decisions` row (status OPEN, a "
        "human owner) and reference it as [NEW: D<n>]. Never park \"not built "
        "yet\" under Open decisions."
    ) in block
    assert (
        "You may APPEND rows to `## Technology decisions`; never edit or "
        "delete an existing row, never change a Status — only a human flips "
        "OPEN to DECIDED."
    ) in block


def test_sa_wrappers_carry_the_decision_reference_and_needs_input():
    for name in SA_WRAPPERS:
        text = _normalised(_read_init_template(name))
        assert "[NEW: D" in text, name
        assert "## Needs input" in text, name


def test_sa_wrappers_name_the_gate_with_its_flags():
    for name in SA_WRAPPERS:
        text = _normalised(_read_init_template(name))
        assert "kb ticket check <file> [--missions-dir <dir>]" in text, name
        assert 'kb ticket check --heading "## Services & order" <file>' in text, name


def test_sa_wrappers_react_to_the_real_engine_messages():
    """The skill's FAIL handling quotes ticketcheck's own wording, so an SA
    reading the gate output finds the instruction under the same words."""
    for name in SA_FULL_WRAPPERS:
        text = _normalised(_read_init_template(name))
        for message in (
            "needs a parent mission to hold the decision",
            "parent mission '<id>' not found under missions/",
            "decision D<n> not in <file>'s Technology decisions",
            "decision D<n> is <status> (owner: <x>)",
            "has Technology decisions — reference the row as [NEW: D<n>]",
        ):
            assert message in text, f"{name}: {message}"


def test_sa_claude_skill_and_cursor_wrappers_are_byte_identical():
    assert _read_init_template("claude-skill-sa-ticket-ground.md") == (
        _read_init_template("cursor-sa-ticket-ground.md")
    )


def test_ba_ticket_wrappers_run_the_sa_inside_the_pipeline():
    for name in BA_TICKET_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "Ground technical" in text, name
        assert "## Needs input" in text, name
        # The manual hand-off is gone; the only by-hand case left is a
        # re-ground after <repo>-code moves.
        assert "once the business sections are drafted" not in text, name
        assert "only when `-code` moves after handover" in text, name


def test_ba_ticket_full_wrappers_re_ground_only_on_a_check_failure():
    for name in BA_TICKET_AUTHOR_FULL_TEMPLATES:
        text = _ba_wrapper_text(name)
        assert "no shared context: the SA sees the file and the hub" in text, name
        assert "After every round that changed the draft, also run `kb ticket check`" in text, name
        assert "on PASS, do not re-ground" in text, name


def test_ba_ticket_claude_skill_alone_keeps_the_subagent_wording():
    """Only the Claude skill wrapper dispatches a real subagent; Copilot and
    Cursor have no such concept, so Task 4 reworded their step 7 into a
    dialect-neutral "separate run" — the skill keeps its original wording."""
    text = _ba_wrapper_text("claude-skill-ba-ticket-author.md")
    assert "as its own subagent" in text


def test_ba_ticket_pipeline_line_names_the_new_step():
    for name, needle in (
        (
            "claude-skill-ba-ticket-author.md",
            "Intake → Parent mission → Ground → Draft → Pin → Lint → "
            "Ground technical → Maturity review → Review",
        ),
        (
            "claude-command-ba-ticket-author.md",
            "Pipeline: Intake → Parent mission → Ground → Draft → Pin → Lint "
            "→ Ground technical → Maturity review → Review",
        ),
        (
            "copilot-ba-ticket-author.prompt.md",
            "Intake → Parent mission → Ground → Draft → Pin → Lint → "
            "Ground technical → Maturity review → Review, saved to "
            "tickets/<id>.md",
        ),
    ):
        assert needle in _ba_wrapper_text(name), name


def test_ba_mission_wrappers_run_the_sa_inside_the_pipeline():
    for name in BA_MISSION_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "Ground services" in text, name
        assert "[NEW: D" in text, name
        assert "hand the mission to `/sa-ticket-ground --mission`" not in text, name


def test_ba_mission_reviewer_receives_the_service_order():
    for name in BA_MISSION_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert (
            "Give it `## Services & order` as input" in text
        ), name


def test_ba_mission_pipeline_line_names_the_new_step():
    for name, needle in (
        (
            "claude-skill-ba-mission-plan.md",
            "Intake → Ground → Draft → Split → Ground services → Pin → Lint → "
            "Maturity review → Review",
        ),
        (
            "copilot-ba-mission-plan.prompt.md",
            "Intake → Ground → Draft → Split → Ground services → Pin → Lint → "
            "Maturity review → Review, saved to missions/M-<slug>.md",
        ),
    ):
        assert needle in _ba_wrapper_text(name), name


NON_DEV_WRAPPER_SKILLS = ("sa-ticket-ground", "ba-ticket-author", "ba-mission-plan")


def test_copilot_and_cursor_ba_sa_wrappers_differ_only_on_frontmatter_line_two():
    """The dev-side guard (`test_copilot_and_cursor_wrappers_differ_only_in_
    their_frontmatter_name`) covers DEV_WORKFLOW_SKILLS only; the BA and SA
    wrappers had no equivalent, which is how a three-file edit could drift."""
    for skill in NON_DEV_WRAPPER_SKILLS:
        copilot = _read_init_template(f"copilot-{skill}.prompt.md").splitlines()
        cursor = _read_init_template(f"cursor-{skill}.md").splitlines()
        assert copilot[:1] + copilot[2:] == cursor[:1] + cursor[2:], skill
        assert copilot[1] == "mode: agent", skill
        assert cursor[1] == f"name: {skill}", skill


def test_quickstart_ba_folds_the_sa_step_into_the_pipeline():
    text = _normalised(_read_init_template("QUICKSTART-ba.md"))
    assert "Greenfield repos: what `[NEW: D<n>]` means" in text
    assert "7. **Ground technical**" in text
    assert "Ground services" in text
    assert "--missions-dir" in text
    # The manual step 6 is gone — the agent invokes the SA itself.
    assert "6. **Ground the technical half**" not in text


_NUMBERED_STEP_RE = _re.compile(r"^\d+\.\s+\*\*.*$", _re.MULTILINE)
_GATES_ON_GROUNDING_PASS_RE = _re.compile(r"once .*? reports `Grounding: PASS`")


def test_no_ba_wrapper_gates_a_later_step_on_grounding_pass():
    """Fix wave 2, item 1: G2 makes an OPEN D-row a hard error the SA may
    never flip, so `sa-ticket-ground` can never report `Grounding: PASS`
    on a greenfield ticket. A later step whose trigger reads "once X
    reports `Grounding: PASS`" (e.g. step 8 keyed off step 7) therefore
    deadlocks forever — no numbered step line may read that way."""
    for name in BA_WRAPPERS:
        text = _read_init_template(name)
        for line in _NUMBERED_STEP_RE.findall(text):
            assert not _GATES_ON_GROUNDING_PASS_RE.search(line), f"{name}: {line}"


# --- PR 3 (ticket size gates): the templates teach the cap ------------------


def test_ticket_template_dor_names_the_size_gates():
    dor = lintcore.section_body(
        _read_init_template("ticket-template.md"), "## Definition of Ready"
    )
    assert dor is not None
    assert (
        "One user story and at most 10 acceptance criteria — a bigger "
        "scope is two tickets"
    ) in _normalised(dor)


def test_review_rubric_business_axis_caps_the_ticket_size():
    body = lintcore.section_body(
        _read_init_template("review-rubric.md"), "## Business coverage"
    )
    assert body is not None
    assert (
        "One user story and ≤ 10 acceptance criteria; no AC is a compound "
        "of two conditions written to stay under the cap."
    ) in _normalised(body)


def test_ba_ticket_full_wrappers_teach_the_ticket_split():
    """The command wrapper is exempt: it has no Draft step to qualify,
    only a prose summary of the skill's rules (see line 193's note)."""
    for name in BA_TICKET_AUTHOR_FULL_TEMPLATES:
        assert (
            'One AC is one testable condition and one outcome; a ticket '
            'that needs more than 10 AC, or a second "As a …" story, is '
            "two tickets — split it before Lint, never merge ACs to fit."
        ) in _ba_wrapper_text(name), name


def test_quickstart_ba_gate_list_names_the_size_gates():
    text = _normalised(_read_init_template("QUICKSTART-ba.md"))
    assert (
        "At most 10 acceptance criteria and exactly one `As a … I want … so "
        "that …` story — a bigger scope is two tickets"
    ) in text


# --- compose facts grounding (spec 2026-09-23) ---

def test_ticket_template_carries_the_compose_grounding_lines():
    text = _read_init_template("ticket-template.md")
    for needle in (
        "- Volumes: svc.<name> — <volume>, …; svc.<name> — none — or `none`",
        "- Healthchecks: svc.<name> — `<test command>`; svc.<name> — none; svc.<name> — disabled — or `none`",
        "- Devices: svc.<name> — <driver:caps>; svc.<name> — none — or `none`",
        "no value in an AC rests on a `DECIDED` note instead of a section id or a D-row",
    ):
        assert needle in text, needle


def test_ac_quality_doc_bans_shell_commands_in_an_ac():
    text = _read_init_template("ac-quality.md")
    assert "a shell command in the AC" in text
    assert "`## Test data & verification`" in text


def test_review_rubric_dev_axis_checks_compose_literals_against_grounding():
    text = _read_init_template("review-rubric.md")
    assert "matches the value on the corresponding `## Technical grounding` line, or carries `[NEW: D<n>]`" in text


def test_quickstarts_name_the_compose_facts():
    ba = _read_init_template("QUICKSTART-ba.md")
    dev = _read_init_template("QUICKSTART-dev.md")
    assert "volumes, healthcheck commands and device reservations" in ba
    assert "`Volumes:` / `Healthchecks:` / `Devices:`" in ba
    assert "named volumes, the healthcheck command and device reservations" in dev


@pytest.mark.parametrize("name", [
    "claude-skill-ba-ticket-author.md",
    "copilot-ba-ticket-author.prompt.md",
    "cursor-ba-ticket-author.md",
])
def test_ba_ticket_author_wrappers_carry_the_no_shell_and_no_rescore_rules(name):
    text = _normalised(_read_init_template(name))
    assert "An AC states an observable outcome, never a shell command" in text
    assert "A round that only closes open questions is not a review round and never changes a score" in text


# --- plan waves (spec 2026-09-24 §5): dev-plan and dev-execute -------------


def test_dev_plan_records_a_depends_on_line_per_task():
    for name in _dev_wrapper_names("dev-plan"):
        body = _dev_wrapper_body(name)
        assert "### Task <n>: <title>" in body, name
        assert "`Depends on: none` or `Depends on: task 2, task 5`" in body, name
        assert "derived, never chosen" in body, name
        assert "file-disjoint" in body, name
        assert "The closing verification task depends on every other task" in body, name
        assert "kb plan waves docs/impl/<ticket-id>-plan.md" in body, name


def test_dev_plan_a2_asks_the_fifth_question_and_runs_plan_waves():
    for name in _dev_wrapper_names("dev-plan"):
        body = _dev_wrapper_body(name)
        assert "Is every `Depends on:` line consistent with Files and Interfaces" in body, name
        assert "The reviewer also runs `kb plan waves` and quotes its output; an error there is a BLOCKER on its own" in body, name


def test_dev_execute_runs_plan_waves_and_lanes():
    for name in _dev_wrapper_names("dev-execute"):
        body = _dev_wrapper_body(name)
        assert "run `kb plan waves docs/impl/<ticket-id>-plan.md`" in body, name
        assert "an error returns the plan to `dev-plan`" in body, name
        assert "runs sequentially as today" in body, name
        assert "git worktree add .worktrees/<ticket-id>-task-<n> -b <ticket-id>-task-<n> HEAD" in body, name
        assert "git merge-base --is-ancestor" in body, name
        assert "at most **3 lanes at a time**" in body, name
        assert "Never use `run_in_background`; run every test in the foreground and let the call block." in body, name
        assert "git merge --no-ff <ticket-id>-task-<n>" in body, name
        assert "a conflict is a plan defect" in body, name
        assert "git diff <merge-commit>^1...<lane-branch>" in body, name
        assert "shows exactly the lane's own commits, for every lane in the wave" in body, name
        assert "A lane implementer never edits `docs/impl/<ticket-id>-plan.md`" in body, name
        assert "the first wave with an unticked task" in body, name
        assert "skips to A3" in body, name
        assert "must be gitignored" in body, name


def test_quickstart_dev_documents_plan_waves_and_lanes():
    text = _normalised(_read_init_template("QUICKSTART-dev.md"))
    assert "### Waves and lanes" in text
    assert "`Depends on:` line" in text
    assert "`kb plan waves docs/impl/<ticket-id>-plan.md`" in text
    assert "at most 3 lanes at a time" in text
    assert "- `kb plan waves <plan-file> [--json]`" in text


# --- mission next (spec 2026-09-24 §4.5): templates ---------------------------


def test_mission_template_teaches_the_cited_decision_row():
    text = _read_init_template("mission-template.md")
    decisions = _normalised(lintcore.section_body(text, "## Technology decisions"))
    assert (
        "In a greenfield repo the SA cites the architecture document in the "
        "Decision cell ([<arch-doc> §<section>]); a cited row is a recorded "
        "decision the BA flips once, at mission time (step 5b), not ticket by ticket."
    ) in decisions
    assert (
        "| D3 | New svc.<name> — <one line> [<arch-doc> §<section>] | OPEN | <SA / tech lead> | <US id> |"
        in decisions
    )
    # D2 stays exactly as the earlier pin expects
    assert "| D2 | New svc.<name> — <one line> | OPEN | <SA / tech lead> | <US id> |" in decisions


def test_mission_template_sequencing_allows_cross_mission_dependencies():
    text = _read_init_template("mission-template.md")
    seq = _normalised(lintcore.section_body(text, "## Sequencing"))
    assert "`Depends on` may name a story of another mission (`M-<other>-US<n>`)" in seq
    assert "write `none` for a story that starts first" in seq
    assert "`kb mission next` reads this table" in seq


def test_mission_template_dor_names_the_decided_rows_gate():
    dor = _normalised(lintcore.section_body(_read_init_template("mission-template.md"), "## Definition of Ready"))
    assert "- [ ] Every D-row blocking a story with no dependency is DECIDED (kb mission next shows it ready)" in dor


def test_sa_full_wrappers_cite_the_architecture_document_for_greenfield_rows():
    for name in SA_FULL_WRAPPERS:
        text = _normalised(_read_init_template(name))
        assert (
            "In a greenfield repo (`<repo>-code` has no `svc.*`) every service, "
            "table or route the mission needs comes from the architecture "
            "document on the hub: cite it in the Decision cell"
        ) in text, name
        assert "| D2 | New svc.api — REST gateway [myflix-arch §3.2] | OPEN | <SA / tech lead> | M-x-US1 |" in text, name
        assert "that absence is the BA's signal to keep the row `OPEN`" in text, name


def test_every_sa_wrapper_says_the_proposal_cites_the_architecture_document():
    for name in SA_WRAPPERS:
        assert "cites the architecture document" in _normalised(_read_init_template(name)), name
