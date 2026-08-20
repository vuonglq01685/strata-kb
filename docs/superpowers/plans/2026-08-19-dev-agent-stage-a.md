# Phase 5 Stage A — kind `dev` + the 5-skill Dev workflow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a fourth repo kind (`kb init --kind dev`) carrying a complete, resumable Dev workflow — one orchestrator (`dev-implement-ticket`) plus four phase skills (`dev-design`, `dev-plan`, `dev-execute`, `dev-handover`) — so a Dev in a product repo can take a BA ticket, resolve its pinned `kb-context`, verify the `%%TODO%%` placeholders against real code, and implement it AC-by-AC under mandatory TDD with cited, verbatim standard values.

**Architecture:** No engine changes. A fourth `RepoKind` with its own `DEV_TEMPLATES` map (the exact Phase 4 `ba` pattern) plus 20 skill-wrapper template resources. All flow state is derived from files in `docs/impl/` — no state store, no new models. `models.py`, `build.py`, `searchdb`, federation, MCP (5 tools, golden contract byte-identical), and web are untouched.

**Tech Stack:** Python 3.11+, Typer, pytest, uv. Wrapper templates are Markdown package resources loaded via `importlib.resources`.

**Spec:** `docs/superpowers/specs/2026-08-19-dev-agent-design.md`

**Sibling plans (must land in this order):** this plan → `2026-08-19-dev-agent-stage-b.md` → `2026-08-19-dev-agent-stage-cd.md`.

## Global Constraints

Copied verbatim from the spec; every task's requirements implicitly include this section.

- **Five MCP tools, unchanged.** `tests-gate/golden/mcp_tools.json` stays byte-identical; `tests-gate/regression/test_mcp_contract.py` must stay green untouched (spec §3.1).
- **No pydantic model changes** — `models.py` is frozen (spec §3.3). **`build.py` is frozen** (spec §3.7).
- **TDD is non-negotiable** (spec §3.13): no production code without a failing test first, and the failing run must actually be observed. This applies to this plan's own execution, not only to the text being written.
- **Evidence before assertions** (spec §3.14): never report a task done without running the verification command and showing its output.
- **Ported, not copied** (spec §3.16): wrapper text is written for center-kb and must stand alone — a product repo is not guaranteed to have the superpowers plugin. Each wrapper carries exactly one line naming its superpowers counterpart. No vendored text, no conditional logic.
- **Every wrapper ends with the next-step block** (spec §5.3, verbatim shape in "Shared wrapper blocks" below).
- Hub/child/ba scaffolds gain **nothing**: `COMMON_TEMPLATES`, `HUB_TEMPLATES`, `CHILD_TEMPLATES`, `BA_TEMPLATES` are not modified by this plan.
- Hermetic tests: no network, no live hub, no LLM CLI.
- Windows dev box: run tests with `uv run pytest`; lint only touched files with `uv run ruff check <paths>` (whole-tree ruff has known pre-existing failures). Templates are written with `newline="\n"` by `init_repo`, so author them with LF endings.
- English template/skill text; conventional commits.
- Estimated effort: A1 ≈ 1 d, A2 ≈ 0.75 d, A3 ≈ 0.75 d, A4 ≈ 1 d, A5 ≈ 0.75 d, A6 ≈ 0.75 d, A7 ≈ 0.5 d — **≈ 5.5 dev-days**.

## File Structure

| File | Responsibility |
|---|---|
| `src/center_kb/templates/init/claude-skill-dev-implement-ticket.md` | orchestrator skill: intake → resolve → ground → placeholders → run phases |
| `src/center_kb/templates/init/claude-command-dev-implement-ticket.md` | 2-line Skill invoker + frontmatter (`kb-approve` pattern) |
| `src/center_kb/templates/init/copilot-dev-implement-ticket.prompt.md` | Copilot variant, `mode: agent`, CLI-only paths |
| `src/center_kb/templates/init/cursor-dev-implement-ticket.md` | Cursor variant |
| …same four-file set for `dev-design`, `dev-plan`, `dev-execute`, `dev-handover` | one phase each |
| `src/center_kb/templates/init/config-dev.yaml` | `kind: dev` + `hub:` + `repo_id:` + `intake:` |
| `src/center_kb/templates/init/QUICKSTART-dev.md` | one-page onboarding for a dev repo |
| `src/center_kb/initcmd.py` | `KIND_DEV`, `DEV_TEMPLATES`, 4-way `KINDS`/`template_map()` |
| `src/center_kb/cli.py` | `RepoKind.dev`, `KIND_DESCRIPTIONS`, `_resolve_kind` |
| `src/center_kb/config.py` | `KBConfig.kind` Literal gains `"dev"` |
| `tests/test_templates.py` | wrapper content assertions (extended per task) |
| `tests/test_init.py` | kind `dev` scaffold set + absence assertions |

## Shared wrapper blocks

These three blocks appear in multiple wrappers. They are defined **once here** and referenced by name in the tasks below; write them out verbatim each time (do not abbreviate in the wrapper files themselves).

**SHARED-NEXT-STEP** — the closing block of every wrapper (spec §5.3). Wrappers must contain this literal instruction text:

```markdown
## Next step — ALWAYS end your response with this block

Close every response with a state line and an ordered list of next steps.
Include it even when you stopped early or hit an error — especially then.

    ## Next step

    → 1. <next step in flow> — <what it does>   (next in flow)
      2. <revise the current phase> — <how>
      3. <stop/park> — <where the work is saved>

    State: design <✅ approved|⬜ not written> · plan <✅ approved|⬜ not written> · tasks <n>/<m> · PR <✅ opened|⬜ not opened>

Rules:
- Option 1 is ALWAYS the next step in flow order: design → plan → execute → handover.
- Show the exact command with the ticket id already filled in, ready to copy.
- The `State:` line always shows all four markers, even the ones not yet reached.
- A blocker takes option 1 instead and says so, e.g.
  `→ 1. Send back to the BA — ref ATM-STD §5.3 is broken, re-pin needed`.
  Flow order never hides a blocker.
```

**SHARED-HARD-RULES** — the hard-rules block (spec §5.9), verbatim in all five workflow wrappers:

```markdown
## Hard rules

- A ticket without a resolvable `kb-context` is not implementable — send it back, never improvise the missing context.
- Broken citation = blocker; stale citation = both versions surfaced, humans decide; neither is ever silently ignored.
- No production code without a failing test observed first. No exception for small tickets, deadlines, or "obvious" changes.
- Never claim done without showing the verification output.
- Never invent or "remember" a standard value — every code/format/enum/threshold in code or tests is verbatim from the resolved section at the pinned version, with a citation comment.
- `<repo>-svc` is for locating and cross-checking work only. It is never a source for an AC or a standard value.
- The ticket is the BA's artifact: report placeholder resolutions and AC findings back; never edit the ticket.
- An AC that cannot be implemented as written becomes `OPEN(BA)` — never reinterpreted, and never pushed past mid-implementation.
- Never edit a test to make it pass; diagnose the cause.
- Code is ground truth: when either code-knowledge document disagrees with the code, trust the code and note the mismatch.
- Never modify a `reviewed` section of `-svc`; propose an amend.
- `hist.*` entries are appended only by `kb svc note`, never hand-edited.
- Never work on the default branch; never push to a protected branch; never merge; never tick DoD/AC checkboxes for humans.
- KB feedback items found during implementation go in the PR description — dropping them silently violates DoD.
```

**SHARED-FRESHNESS** — the mandatory re-check at every entry point (spec §5.2):

```markdown
## Freshness re-check (run this FIRST, every time)

Before anything else, re-resolve the ticket's `kb-context`: call the MCP tool
`kb_resolve` when available, otherwise `kb resolve <ticket-file>` (or
`kb resolve - < ticket.md`). The hub may have published since the last session,
so a ref that was `ok` yesterday can be `stale` today — checking only at
handover is too late, because the plan may already rest on changed content.

- **broken** → STOP. This is a blocker: report to the BA that the ticket needs
  re-pinning. Never implement around a citation that no longer resolves.
- **stale** → show BOTH versions and let the humans decide: `kb resolve` returns
  the pinned content plus the reason; `kb get <doc-id> <section> [--level l3]`
  returns the CURRENT hub version. Do NOT use `kb diff` — it compares the local
  `.kb/` worktree against a local git rev, and this repo holds no local copy of
  the cited domain document.
- **ok** → continue.
```

---

## Task A1: `dev-implement-ticket` orchestrator wrappers

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-dev-implement-ticket.md`
- Create: `src/center_kb/templates/init/claude-command-dev-implement-ticket.md`
- Create: `src/center_kb/templates/init/copilot-dev-implement-ticket.prompt.md`
- Create: `src/center_kb/templates/init/cursor-dev-implement-ticket.md`
- Modify: `tests/test_templates.py`

**Interfaces:**
- Consumes: nothing (package resources only; wiring into `DEV_TEMPLATES` happens in Task A6).
- Produces: four resource names, consumed by Task A6's `DEV_TEMPLATES`. The test helper `_read_init_template(name)` already exists in `tests/test_templates.py` and is reused by Tasks A1–A5.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -k dev_implement_ticket -v`
Expected: FAIL — every test errors on a missing package resource (`claude-skill-dev-implement-ticket.md`).

- [ ] **Step 3: Write the Claude skill**

Create `src/center_kb/templates/init/claude-skill-dev-implement-ticket.md`. Frontmatter:

```markdown
---
name: dev-implement-ticket
description: Implement a BA ticket grounded in the KB — resolve its pinned kb-context, verify %%TODO%% placeholders against the codebase, then design → plan → execute → handover under mandatory TDD. Use when a Dev asks to implement / work on / pick up a ticket, or invokes /dev-implement-ticket.
---
```

Body, in this order:

1. A one-paragraph role statement: this skill is the ORCHESTRATOR of the pipeline Intake → Resolve → Ground → Placeholders → design → plan → execute → handover; it is also the **safe re-entry point** — called again on a ticket already in progress it detects state and offers the next step instead of redoing finished phases.
2. The one-line counterpart reference required by Global Constraints: *"Counterpart in the superpowers plugin: none — this orchestrator is center-kb specific; the phases it runs map to brainstorming, writing-plans, and subagent-driven-development."*
3. **SHARED-FRESHNESS** verbatim.
4. The five steps from spec §5.4, written out in full:
   - **Intake** — accept a pasted ticket body or a path; confirm ticket/US id and branch; read the ticket's `## Dependencies` (`Blocked by:` / `Blocks:`) and, when a `> Parent mission:` line is present, that mission's `## Sequencing` row; if this story is blocked by something unmerged, say so and let the Dev decide. No `kb-context` block → stop, the ticket is not Ready.
   - **Resolve** — triage as in SHARED-FRESHNESS.
   - **Ground** — read resolved L2; escalate to L3 via `kb_get_section … l3` (or `kb get <doc> <section> --level l3`) for any value that will be encoded in code or tests; then `kb_search` both own-repo documents — `<repo_id>-code` for structure and `<repo_id>-svc` for responsibility — and then read the actual code. State the rule: *knowledge orients, code decides.*
   - **Placeholders** — for each `%%TODO: verify against codebase%%`, verify the real name against the codebase and record `placeholder → verified value (file:line or code-knowledge ref)`; report the list to the BA; **never edit the ticket**; unverifiable here → `OPEN(BA)`.
   - **Run the phases** — invoke `dev-design`, then after the Dev approves it `dev-plan`, then `dev-execute`, then `dev-handover`. On re-entry, detect state from `docs/impl/<ticket-id>-design.md`, `docs/impl/<ticket-id>-plan.md`, the ticked-checkbox ratio in the plan, the current branch, and whether a PR exists — then skip finished phases and offer the next one.
5. **SHARED-HARD-RULES** verbatim.
6. **SHARED-NEXT-STEP** verbatim.

- [ ] **Step 4: Write the Claude command (2-line invoker)**

Create `src/center_kb/templates/init/claude-command-dev-implement-ticket.md`:

```markdown
---
description: Implement a BA ticket grounded in the KB — resolve pinned citations, verify %%TODO%% placeholders, then design → plan → execute → handover under TDD
argument-hint: "[ticket id, path, or pasted ticket]"
---

Invoke the `dev-implement-ticket` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the ticket when given; when empty,
ask for it during Intake.

Pipeline: Intake → Resolve → Ground → Placeholders → design → plan → execute
→ handover. This command is also the safe re-entry point: called again on a
ticket already in progress it reports state and offers the next step rather
than redoing finished phases.
```

- [ ] **Step 5: Write the Copilot and Cursor variants**

Create `copilot-dev-implement-ticket.prompt.md` with frontmatter `mode: agent` and a `description:` line, and `cursor-dev-implement-ticket.md` with frontmatter `name: dev-implement-ticket` and a `description:` line. Same body as the Claude skill with two substitutions:

- every MCP tool call is written CLI-first (`kb resolve`, `kb get`, `kb query`) with the MCP name mentioned as the alternative when the client exposes it;
- where the Claude skill says "invoke the `dev-design` skill", these say "run the `/dev-design` prompt (or follow `docs/impl/` conventions inline if prompts are unavailable)".

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_templates.py -k dev_implement_ticket -v`
Expected: PASS (8 tests).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check tests/test_templates.py
git add src/center_kb/templates/init/*dev-implement-ticket* tests/test_templates.py
git commit -m "feat: dev-implement-ticket orchestrator wrappers (phase 5A)"
```

---

## Task A2: `dev-design` wrappers (phase 1)

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-dev-design.md`
- Create: `src/center_kb/templates/init/claude-command-dev-design.md`
- Create: `src/center_kb/templates/init/copilot-dev-design.prompt.md`
- Create: `src/center_kb/templates/init/cursor-dev-design.md`
- Modify: `tests/test_templates.py`

**Interfaces:**
- Consumes: `_read_init_template(name)` and `_dev_wrapper_names(skill)` from Task A1.
- Produces: the design-artifact contract every later task depends on — `docs/impl/<ticket-id>-design.md`, written **only** on the architectural path.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
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
        assert "reinterpreting an AC is forbidden" in text.lower(), name


def test_claude_skill_dev_design_has_expected_frontmatter():
    text = _read_init_template("claude-skill-dev-design.md")
    assert "name: dev-design\n" in text


def test_copilot_dev_design_prompt_has_agent_mode():
    assert "mode: agent" in _read_init_template("copilot-dev-design.prompt.md")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -k dev_design -v`
Expected: FAIL — missing resource `claude-skill-dev-design.md`.

- [ ] **Step 3: Write the four wrappers**

Frontmatter for the Claude skill:

```markdown
---
name: dev-design
description: Turn an approved BA ticket into a technical design for THIS codebase — classify the work as spike / bounded / architectural, then design how to implement it. Use as phase 1 of implementing a ticket, or when invoked as /dev-design.
---
```

Body, per spec §5.5:

1. Role statement: the ticket **is** the specification — the BA already wrote and pinned it. This phase does not re-brainstorm the business need; it decides **how to implement it in this codebase**.
2. Counterpart line: *"Counterpart in the superpowers plugin: `superpowers:brainstorming` — if it is installed it is the newer source for the three-path method."*
3. **SHARED-FRESHNESS** verbatim.
4. Path classification table, stated out loud so the Dev can override it:
   - **spike** — a feasibility question the ticket itself raises → output is an answer + recommendation; anything built is labelled throwaway.
   - **bounded** — changes a flow that already exists in this repo → a few sentences to a few short paragraphs **in chat**; no design file.
   - **architectural** — new service, new table, new interface, or a change to how components fit → write `docs/impl/<ticket-id>-design.md` (**architectural path only**).
5. Classification rules: it measures **the repo, not your familiarity** — no existing flow to change means it is not bounded; between two paths **take the heavier one**; the ratchet is **one-way** — hidden complexity found later upgrades the path and you say so, nothing downgrades mid-ticket.
6. Design content: modules touched, interfaces added or changed, data changes, and the placeholder resolutions from the orchestrator's Placeholders step. Standard-derived values quoted verbatim with `doc-id §section`. Any AC that cannot be implemented as written becomes `OPEN(BA)`; **reinterpreting an AC is forbidden**.
7. **GATE 1**: the Dev approves before any plan is written. State explicitly that presenting the design and starting the plan in the same turn is skipping the gate.
8. **SHARED-HARD-RULES** verbatim.
9. **SHARED-NEXT-STEP** verbatim, with option 1 being `/dev-plan <ticket-id>`.

Claude command file: the same 2-line invoker shape as Task A1 Step 4, naming `dev-design` and `argument-hint: "[ticket id]"`. Copilot (`mode: agent`) and Cursor (`name: dev-design`) variants as in Task A1 Step 5.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_templates.py -k dev_design -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tests/test_templates.py
git add src/center_kb/templates/init/*dev-design* tests/test_templates.py
git commit -m "feat: dev-design phase-1 wrappers (phase 5A)"
```

---

## Task A3: `dev-plan` wrappers (phase 2)

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-dev-plan.md`
- Create: `src/center_kb/templates/init/claude-command-dev-plan.md`
- Create: `src/center_kb/templates/init/copilot-dev-plan.prompt.md`
- Create: `src/center_kb/templates/init/cursor-dev-plan.md`
- Modify: `tests/test_templates.py`

**Interfaces:**
- Consumes: the design artifact from Task A2 (`docs/impl/<ticket-id>-design.md`, or the approved in-chat design on the bounded path).
- Produces: `docs/impl/<ticket-id>-plan.md` — the file Task A4 reads and ticks. Its required shape: one task per AC (or several per large AC), each task carrying **Files**, **Interfaces**, and **Steps** as `- [ ]` checkboxes whose step 1 is always the failing test; plus a closing cross-cutting verification task.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -k dev_plan -v`
Expected: FAIL — missing resource `claude-skill-dev-plan.md`.

- [ ] **Step 3: Write the four wrappers**

Claude skill frontmatter:

```markdown
---
name: dev-plan
description: Turn an approved technical design into an implementation plan — one task per AC, each with a failing test first and checkboxes for resumable progress. Use as phase 2 of implementing a ticket, or when invoked as /dev-plan.
---
```

Body, per spec §5.6:

1. Counterpart line: *"Counterpart in the superpowers plugin: `superpowers:writing-plans`."*
2. **SHARED-FRESHNESS** verbatim.
3. Read the design: the file on the architectural path, the approved in-chat design otherwise.
4. Write `docs/impl/<ticket-id>-plan.md` with, per task: **Files** (create / modify / test), **Interfaces** (what it consumes from earlier tasks, what it produces for later ones — exact names and types, because a task's implementer sees only their own task), and **Steps** as `- [ ]` checkboxes with **step 1 always being the failing test**.
5. Rules: **one task per AC**, or several tasks for a large AC; every task **names the test that proves it**; tasks ordered so each one leaves the repo green; a closing task for cross-cutting verification (full suite + lint) using the commands from `-code §cmd.*`.
6. Include the note that until Stage B ships there is no `cmd.*` section yet: ask the Dev for the build/test/lint commands once and record them at the top of the plan file, so `dev-execute` and `dev-handover` can use them.
7. **GATE 2**: the Dev approves the plan. State that the checkbox file is also the resume point, so it must be complete enough for a different session to pick up cold.
8. **SHARED-HARD-RULES** verbatim.
9. **SHARED-NEXT-STEP** verbatim, option 1 = `/dev-execute <ticket-id>`.

Claude command, Copilot, Cursor variants as in Task A1 Steps 4–5, naming `dev-plan`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_templates.py -k dev_plan -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tests/test_templates.py
git add src/center_kb/templates/init/*dev-plan* tests/test_templates.py
git commit -m "feat: dev-plan phase-2 wrappers (phase 5A)"
```

---

## Task A4: `dev-execute` wrappers (phase 3)

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-dev-execute.md`
- Create: `src/center_kb/templates/init/claude-command-dev-execute.md`
- Create: `src/center_kb/templates/init/copilot-dev-execute.prompt.md`
- Create: `src/center_kb/templates/init/cursor-dev-execute.md`
- Modify: `tests/test_templates.py`

**Interfaces:**
- Consumes: `docs/impl/<ticket-id>-plan.md` from Task A3, including the recorded build/test/lint commands.
- Produces: ticked checkboxes in that same plan file plus one commit per task — the state Task A5 reads.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -k dev_execute -v`
Expected: FAIL — missing resource `claude-skill-dev-execute.md`.

- [ ] **Step 3: Write the four wrappers**

Claude skill frontmatter:

```markdown
---
name: dev-execute
description: Execute an approved implementation plan task-by-task under mandatory TDD in an isolated workspace, verifying and committing each task. Resumable. Use as phase 3 of implementing a ticket, or when invoked as /dev-execute.
---
```

Body, per spec §5.7:

1. Counterpart line: *"Counterpart in the superpowers plugin: `superpowers:subagent-driven-development`, with `test-driven-development`, `using-git-worktrees`, `systematic-debugging`, and `requesting-code-review` folded in."*
2. **SHARED-FRESHNESS** verbatim.
3. **Isolate** — ensure an isolated workspace before touching code: a dedicated branch, and a git worktree where the environment supports it, named from the ticket id. **Never work directly on the default branch.**
4. **Per unticked task**, in its own subagent where the runtime supports it (sequential passes otherwise):
   1. write the test → **run it → observe it fail**. State the reason: a test that was **never seen red proves nothing**.
   2. write the minimum code → run → pass.
   3. **review checkpoint** — pass/fail, not a score: does the test actually exercise that AC; is every standard-derived value verbatim with a citation comment; does the change follow the repo's existing conventions; did anything else break.
   4. **verify** — run `cmd.test` and `cmd.lint` (from `-code §cmd.*`, or the commands recorded at the top of the plan file) and **show the output**.
   5. tick the checkboxes, commit the task.
5. **When a test fails unexpectedly** — reproduce, find the actual cause, fix the cause. **Never edit a test to make it green**, never widen a tolerance to pass, never mark a task done with a failing test.
6. **When an AC turns out not to be implementable as written** — stop that task, **return to `dev-design`**, record `OPEN(BA)`. Do not decide the ambiguity yourself, and do not push past it because the code is half written.
7. **Resumable** — a later run re-checks freshness, re-reads the plan, and continues at the **first unticked task**.
8. **SHARED-HARD-RULES** verbatim.
9. **SHARED-NEXT-STEP** verbatim, option 1 = `/dev-handover <ticket-id>` once every task is ticked, otherwise `/dev-execute <ticket-id>` to continue.

Claude command, Copilot, Cursor variants as in Task A1 Steps 4–5, naming `dev-execute`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_templates.py -k dev_execute -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tests/test_templates.py
git add src/center_kb/templates/init/*dev-execute* tests/test_templates.py
git commit -m "feat: dev-execute phase-3 wrappers (phase 5A)"
```

---

## Task A5: `dev-handover` wrappers (phase 4)

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-dev-handover.md`
- Create: `src/center_kb/templates/init/claude-command-dev-handover.md`
- Create: `src/center_kb/templates/init/copilot-dev-handover.prompt.md`
- Create: `src/center_kb/templates/init/cursor-dev-handover.md`
- Modify: `tests/test_templates.py`

**Interfaces:**
- Consumes: the plan file and git state from Task A4.
- Produces: a PR description; and the `kb svc note` invocation contract that Stage C's Task C2 implements. Until Stage C ships, the wrapper instructs the agent to skip the `kb svc note` step with a one-line note in the PR saying service history was not recorded (the command does not exist yet).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_dev_handover_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for name in _dev_wrapper_names("dev-handover"):
        assert base.joinpath(name).is_file(), name


def test_dev_handover_rechecks_freshness_and_pastes_real_output():
    for name in _dev_wrapper_names("dev-handover"):
        text = _read_init_template(name)
        assert "one final time" in text, name
        assert "paste the real output" in text, name


def test_dev_handover_lists_the_pr_contents():
    for name in _dev_wrapper_names("dev-handover"):
        text = _read_init_template(name)
        for item in ("ticket id", "kb-context", "AC→test map",
                     "placeholder-resolution", "OPEN(", "KB gap"):
            assert item in text, f"{name} missing PR item {item}"


def test_dev_handover_records_service_history_and_amend_findings():
    for name in _dev_wrapper_names("dev-handover"):
        text = _read_init_template(name)
        assert "kb svc note" in text, name
        assert "amend needed:" in text, name
        assert "Never edit a `reviewed` section" in text, name


def test_dev_handover_leaves_pr_and_merge_to_the_human():
    for name in _dev_wrapper_names("dev-handover"):
        text = _read_init_template(name)
        assert "GATE 3" in text and "GATE 4" in text, name
        assert "The agent does neither" in text, name


def test_claude_skill_dev_handover_has_expected_frontmatter():
    assert "name: dev-handover\n" in _read_init_template("claude-skill-dev-handover.md")


def test_copilot_dev_handover_prompt_has_agent_mode():
    assert "mode: agent" in _read_init_template("copilot-dev-handover.prompt.md")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -k dev_handover -v`
Expected: FAIL — missing resource `claude-skill-dev-handover.md`.

- [ ] **Step 3: Write the four wrappers**

Claude skill frontmatter:

```markdown
---
name: dev-handover
description: Close out a ticket — re-check citation freshness, run the full suite and paste the real output, record service history, and assemble the PR description. The Dev opens the PR and merges. Use as phase 4 of implementing a ticket, or when invoked as /dev-handover.
---
```

Body, per spec §5.8:

1. Counterpart line: *"Counterpart in the superpowers plugin: `superpowers:verification-before-completion`."*
2. Re-check freshness **one final time** — a hub publish mid-implementation must surface here, not in review. (SHARED-FRESHNESS verbatim.)
3. Run the **full** suite and linters (`-code §cmd.*`, or the commands recorded in the plan file) and **paste the real output**. State that a completion claim without it is not accepted.
4. Record service history: `kb svc note <service> --ticket <id> --title "<title>" --refs "<refs>"` for **each** service touched, so the entries land in this same PR. Add the interim note: until Stage C ships this command does not exist — skip the step and say so in one line in the PR.
5. Assemble the PR description containing: the **ticket id**; the **kb-context** refs so the reviewer can `kb resolve` them; the **AC→test map**; the **placeholder-resolution** list; every **OPEN(** …) finding; the verification output; and every **KB gap**, ambiguity, or contradiction found, as a concrete feedback item (issue or PR on the owning child repo / hub).
6. If the ticket **changed what a service is responsible for**, report `amend needed: <repo_id>-svc §svc.<name>` as a PR finding. **Never edit a `reviewed` section.**
7. **GATE 3** the Dev opens the PR; **GATE 4** the Dev merges. **The agent does neither.**
8. **SHARED-HARD-RULES** verbatim.
9. **SHARED-NEXT-STEP** verbatim, option 1 = "Open the PR yourself" with the branch name filled in.

Claude command, Copilot, Cursor variants as in Task A1 Steps 4–5, naming `dev-handover`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_templates.py -k dev_handover -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Verify the shared blocks landed in all five skills**

Append to `tests/test_templates.py` and run:

```python
def test_all_dev_workflow_wrappers_carry_the_next_step_block():
    for skill in DEV_WORKFLOW_SKILLS:
        for name in _dev_wrapper_names(skill):
            text = _read_init_template(name)
            assert "## Next step" in text, name
            assert "(next in flow)" in text, name
            assert "State:" in text, name


def test_all_dev_workflow_wrappers_name_their_superpowers_counterpart():
    for skill in DEV_WORKFLOW_SKILLS:
        for name in _dev_wrapper_names(skill):
            text = _read_init_template(name)
            assert "superpowers" in text, name


def test_all_dev_workflow_wrappers_carry_the_tdd_and_evidence_rules():
    for skill in DEV_WORKFLOW_SKILLS:
        for name in _dev_wrapper_names(skill):
            text = _read_init_template(name)
            assert "No production code without a failing test observed first" in text, name
            assert "Never claim done without showing the verification output" in text, name
```

Run: `uv run pytest tests/test_templates.py -k dev_ -v`
Expected: PASS (all Stage A template tests, 40+).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check tests/test_templates.py
git add src/center_kb/templates/init/*dev-handover* tests/test_templates.py
git commit -m "feat: dev-handover phase-4 wrappers + shared-block assertions (phase 5A)"
```

---

## Task A6: init kind `dev` — config, QUICKSTART, and wiring

**Files:**
- Create: `src/center_kb/templates/init/config-dev.yaml`
- Create: `src/center_kb/templates/init/QUICKSTART-dev.md`
- Modify: `src/center_kb/initcmd.py` (add `KIND_DEV`, `DEV_TEMPLATES`; `KINDS` and `template_map()` 3-way → 4-way)
- Modify: `src/center_kb/cli.py` (`RepoKind.dev`; `KIND_DESCRIPTIONS`; `_resolve_kind` prompt loop)
- Modify: `src/center_kb/config.py:36` (`KBConfig.kind` Literal gains `"dev"`)
- Modify: `tests/test_init.py`

**Interfaces:**
- Consumes: the 20 wrapper resources from Tasks A1–A5.
- Produces: `initcmd.KIND_DEV = "dev"`, `initcmd.DEV_TEMPLATES: dict[str, str]`, `expected_files("dev")`, and a working `kb init --kind dev`. Stage B's Task B7 adds one row (`.github/workflows/kb-code.yml`) to `DEV_TEMPLATES`; Stage C's Task C1/C4 add the `dev-code-seed` and reused `kb-summarize`/`kb-approve`/`kb-publish` rows.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_init.py`:

```python
# --- Phase 5 Stage A: kind `dev` (product code repo) ------------------------

_DEV_STAGE_A_PATHS = (
    ".kb/config.yaml",
    ".kb/index.yaml",
    ".mcp.json",
    ".cursor/mcp.json",
    "docs/impl/.gitkeep",
    "QUICKSTART-DEV.md",
    ".claude/skills/dev-implement-ticket/SKILL.md",
    ".claude/commands/dev-implement-ticket.md",
    ".github/prompts/dev-implement-ticket.prompt.md",
    ".cursor/commands/dev-implement-ticket.md",
    ".claude/skills/dev-design/SKILL.md",
    ".claude/skills/dev-plan/SKILL.md",
    ".claude/skills/dev-execute/SKILL.md",
    ".claude/skills/dev-handover/SKILL.md",
)


def test_init_kind_dev_scaffolds_exactly_the_stage_a_set(tmp_path: Path):
    report = init_repo(tmp_path, "dev")
    assert sorted(report.created) == sorted(expected_files("dev"))
    assert report.skipped == []
    for rel in _DEV_STAGE_A_PATHS:
        assert (tmp_path / rel).is_file(), rel


def test_init_kind_dev_has_all_four_wrappers_per_workflow_skill(tmp_path: Path):
    init_repo(tmp_path, "dev")
    for skill in ("dev-implement-ticket", "dev-design", "dev-plan",
                  "dev-execute", "dev-handover"):
        assert (tmp_path / ".claude" / "skills" / skill / "SKILL.md").is_file(), skill
        assert (tmp_path / ".claude" / "commands" / f"{skill}.md").is_file(), skill
        assert (tmp_path / ".github" / "prompts" / f"{skill}.prompt.md").is_file(), skill
        assert (tmp_path / ".cursor" / "commands" / f"{skill}.md").is_file(), skill


def test_init_kind_dev_excludes_authoring_and_ba_artifacts(tmp_path: Path):
    init_repo(tmp_path, "dev")
    for name in ("kb-ingest", "kb-docker-setup", "kb-init"):
        assert not (tmp_path / ".claude" / "skills" / name).exists(), name
        assert not (tmp_path / ".cursor" / "commands" / f"{name}.md").exists(), name
    for name in ("ba-ticket-author", "ba-mission-plan"):
        assert not (tmp_path / ".claude" / "skills" / name).exists(), name
    assert not (tmp_path / ".github" / "workflows" / "kb-publish.yml").exists()
    assert not (tmp_path / ".github" / "workflows" / "kb-ticket-lint.yml").exists()
    assert not (tmp_path / "source").exists()
    assert not (tmp_path / "federation").exists()
    assert not (tmp_path / "tickets").exists()
    assert not (tmp_path / "docs" / "tickets").exists()


def test_init_dev_config_has_kind_repo_id_and_intake(tmp_path: Path):
    repo = tmp_path / "my-dev-repo"
    repo.mkdir()
    init_repo(repo, "dev")
    text = (repo / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "kind: dev" in text
    assert 'repo_id: "my-dev-repo"' in text
    assert "intake:" in text
    assert "hub:" in text


def test_dev_mcp_json_reuses_the_child_templates(tmp_path: Path):
    dev_repo = tmp_path / "d"
    child_repo = tmp_path / "c"
    dev_repo.mkdir()
    child_repo.mkdir()
    init_repo(dev_repo, "dev")
    init_repo(child_repo, "child")
    assert (dev_repo / ".mcp.json").read_text(encoding="utf-8") == (
        child_repo / ".mcp.json"
    ).read_text(encoding="utf-8")
    assert (dev_repo / ".cursor" / "mcp.json").read_text(encoding="utf-8") == (
        child_repo / ".cursor" / "mcp.json"
    ).read_text(encoding="utf-8")


def test_phase5_adds_nothing_to_hub_child_or_ba(tmp_path: Path):
    assert sorted(expected_files("hub")) == _PRE_PHASE4_HUB_FILES
    assert sorted(expected_files("child")) == _PRE_PHASE4_CHILD_FILES
    for rel in expected_files("ba"):
        assert "dev-" not in rel, rel


def test_config_accepts_kind_dev(tmp_path: Path):
    from center_kb.config import load_config

    init_repo(tmp_path, "dev")
    assert load_config(tmp_path / ".kb").kind == "dev"


def test_init_cli_accepts_kind_dev(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "dev"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "skills" / "dev-design" / "SKILL.md").is_file()


def test_kind_descriptions_lists_four_kinds():
    from center_kb.cli import KIND_DESCRIPTIONS

    assert "one of four kinds" in KIND_DESCRIPTIONS
    assert "dev" in KIND_DESCRIPTIONS


def test_noninteractive_init_error_string_is_unchanged(tmp_path: Path):
    # Frozen by contract (cli.py comment): the message still reads hub|child.
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 2
    assert "kb init requires --kind hub|child when not running interactively." in result.output


def test_quickstart_dev_content(tmp_path: Path):
    init_repo(tmp_path, "dev")
    text = (tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8")
    assert "/dev-implement-ticket" in text
    assert "CENTER_KB_HUB_URL" in text
    assert "CENTER_KB_HTTP_TOKEN" in text
    assert "federation/registry.yaml" in text
    assert "docs/impl/" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_init.py -k dev -v`
Expected: FAIL — `ValueError: kind must be one of ('hub', 'child', 'ba'), got 'dev'`.

- [ ] **Step 3: Write `config-dev.yaml`**

Create `src/center_kb/templates/init/config-dev.yaml`:

```yaml
# CENTER-KB — repo config (commit to git).
# kind: this repo's role. "dev" is a product code repo — it consumes the
#       shared KB while implementing BA tickets, and it publishes generated
#       knowledge about its OWN source code (<repo_id>-code) plus curated
#       service knowledge (<repo_id>-svc). It never ingests documents from
#       outside the repo (that's what `child` repos do).
kind: dev
# hub: git URL or kb-hub path of the MAIN HUB — the ONLY read source for
#      kb query / kb resolve / MCP. FILL THIS IN before implementing tickets.
hub: ""
# repo_id: repo name on the federation (pre-filled from the folder name)
repo_id: "{repo_id}"
# intake: https://kb.internal:8321   # publish code knowledge via OIDC CI
#         (zero secrets in this repo). This repo must also be allowlisted in
#         the hub's federation/registry.yaml before publishing works.
intake: ""
```

- [ ] **Step 4: Write `QUICKSTART-dev.md`**

Create `src/center_kb/templates/init/QUICKSTART-dev.md` covering, in this order:

1. What this repo kind is: a product code repo that consumes the KB and publishes knowledge about its own code. It never ingests outside documents.
2. **Setup once** — `pip install center-kb`; fill `hub:` and `intake:` in `.kb/config.yaml`; ask the hub maintainer to add this repo to `federation/registry.yaml`; export `CENTER_KB_HUB_URL` and `CENTER_KB_HTTP_TOKEN`; open the repo in Claude Code / Copilot Chat / Cursor.
3. **Implement a ticket** — the table of entry points from spec §5.2 (new ticket → `/dev-implement-ticket <ticket>`; design done → `/dev-plan <id>`; plan done or work in progress → `/dev-execute <id>`; hand-implemented → `/dev-handover <id>`; lost track → `/dev-implement-ticket <id>`; citation check only → `kb resolve <file>`).
4. **Where work lives** — `docs/impl/<ticket-id>-design.md` and `docs/impl/<ticket-id>-plan.md`; state is derived from those files plus the branch and the PR, so any phase resumes in a new session. `kb init` never touches your `docs/impl/` content.
5. **The four gates** — approve the design, approve the plan, open the PR, merge. The agent does none of them.
6. **What is enforced** — TDD with an observed failing test; no completion claim without shown verification output; standard values verbatim from pinned citations; the ticket is never edited by the agent.
7. **Upgrading** — re-run `kb init --kind dev` to pick up new templates; it only overwrites scaffold files whose content differs, never `.kb/config.yaml`, `.kb/index.yaml`, or anything you authored under `docs/impl/`. **If you hand-edited a wrapper, back it up first: your edits are lost.**
8. **CLI reference** — `kb init --kind dev`, `kb resolve <file> [--hub <url>]`, `kb get <doc-id> <section> [--level l3]`, `kb query "<text>"`, `kb doctor --hub <url>`.

- [ ] **Step 5: Wire `initcmd.py`**

In `src/center_kb/initcmd.py`, change line 10–11 to add the kind:

```python
KIND_BA = "ba"
KIND_DEV = "dev"
KINDS = (KIND_HUB, KIND_CHILD, KIND_BA, KIND_DEV)
```

After `BA_TEMPLATES` (line 88), add:

```python
# Kind `dev` — product code repo. It consumes the shared KB while implementing
# BA tickets and publishes knowledge about its OWN source code. Like BA_TEMPLATES
# this is deliberately NOT merged with COMMON_TEMPLATES (spec §4): a dev repo
# never ingests outside documents, so it carries none of the ingest/docker stack.
DEV_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-dev.yaml",
    ".kb/index.yaml": "index.yaml",
    ".mcp.json": "mcp-child.json",
    ".cursor/mcp.json": "cursor-mcp-child.json",
    "docs/impl/.gitkeep": "gitkeep.txt",
    "QUICKSTART-DEV.md": "QUICKSTART-dev.md",
    **{
        path: resource
        for skill in (
            "dev-implement-ticket",
            "dev-design",
            "dev-plan",
            "dev-execute",
            "dev-handover",
        )
        for path, resource in (
            (f".claude/skills/{skill}/SKILL.md", f"claude-skill-{skill}.md"),
            (f".claude/commands/{skill}.md", f"claude-command-{skill}.md"),
            (f".github/prompts/{skill}.prompt.md", f"copilot-{skill}.prompt.md"),
            (f".cursor/commands/{skill}.md", f"cursor-{skill}.md"),
        )
    },
}
```

Then change `template_map()` (line 113–119) to:

```python
def template_map(kind: str) -> dict[str, str]:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got '{kind}'")
    if kind == KIND_BA:
        return dict(BA_TEMPLATES)
    if kind == KIND_DEV:
        return dict(DEV_TEMPLATES)
    extra = HUB_TEMPLATES if kind == KIND_HUB else CHILD_TEMPLATES
    return {**COMMON_TEMPLATES, **extra}
```

- [ ] **Step 6: Wire `cli.py`**

Add `dev = "dev"` to `RepoKind`. In `KIND_DESCRIPTIONS`, change the first line to `This repo can be one of four kinds:` and append this paragraph after the `ba` one:

```
  dev   — Product code repo. Implements BA tickets grounded in the KB via
          the dev-implement-ticket workflow (design → plan → execute →
          handover, TDD enforced), and publishes generated knowledge about
          its own source code back to the hub. Never ingests outside
          documents.
```

In `_resolve_kind`, change the prompt string to `"Initialize this repo as (hub, child, ba, dev)"`, the accepted tuple to `("hub", "child", "ba", "dev")`, and the error to `f"Error: {answer!r} is not one of 'hub', 'child', 'ba', 'dev'."`. **Leave the non-interactive message at line 126 exactly as it is** — the comment above it records why, and a test freezes the string.

- [ ] **Step 7: Wire `config.py`**

Change line 36:

```python
    kind: Literal["", "hub", "child", "ba", "dev"] = ""
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/test_init.py -v` and `uv run pytest tests/test_templates.py -v`
Expected: PASS, including the pre-existing hub/child/ba tests (they must be untouched).

- [ ] **Step 9: Prove the MCP contract and full suite are intact**

Run: `uv run pytest -q`
Expected: PASS, with `tests-gate/regression/test_mcp_contract.py` green and no golden fixture diffs.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check src/center_kb/initcmd.py src/center_kb/cli.py src/center_kb/config.py tests/test_init.py
git add src/center_kb/initcmd.py src/center_kb/cli.py src/center_kb/config.py \
        src/center_kb/templates/init/config-dev.yaml \
        src/center_kb/templates/init/QUICKSTART-dev.md tests/test_init.py
git commit -m "feat: kb init --kind dev — product code repo with the 5-skill dev workflow (phase 5A)"
```

---

## Task A7: docs + release

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml` (version bump)

**Interfaces:**
- Consumes: everything from Tasks A1–A6.
- Produces: a released minor version; Stage B's plan starts from this baseline.

- [ ] **Step 1: Document kind `dev` in README**

Add a `dev` row/section wherever the three kinds are currently listed, covering: what the kind is, the one-line install/init/env setup, the five slash commands with the entry-point table from spec §5.2, where artifacts live (`docs/impl/`), the four human gates, and the reserved doc-id suffixes `-code` and `-svc` (spec §6.1) as names a domain document must not take — noting that the documents themselves arrive in Stages B and C.

- [ ] **Step 2: Verify the docs claims against the shipped templates**

Run: `uv run pytest tests/test_init.py tests/test_templates.py -q`
Expected: PASS. Then manually scaffold into a scratch directory and read what a Dev would actually see:

```bash
uv run kb init --kind dev "$TMPDIR/dev-smoke"
cat "$TMPDIR/dev-smoke/QUICKSTART-DEV.md"
ls -R "$TMPDIR/dev-smoke/.claude"
```
Expected: five skills and five commands present; QUICKSTART lists the same entry points as the README.

- [ ] **Step 3: Bump the version**

In `pyproject.toml`, bump the minor version (`0.15.0` → `0.16.0`).

- [ ] **Step 4: Full suite before release**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md pyproject.toml
git commit -m "docs: kind dev + the 5-skill dev workflow; chore: bump to 0.16.0"
```

---

## Self-review notes (spec coverage for Stage A)

| Spec section | Covered by |
|---|---|
| §3.13 TDD non-negotiable | A4 Step 1 (`observe it fail`, `never seen red proves nothing`), A5 Step 5 (all five wrappers) |
| §3.14 evidence before assertions | A4 Step 1 (`show the output`), A5 Step 1 (`paste the real output`), A5 Step 5 |
| §3.15 next-step guidance | Shared blocks + A5 Step 5 |
| §3.16 ported not copied | Shared blocks (counterpart line) + A5 Step 5 |
| §4 kind `dev` scaffold (Stage A rows) | A6 Steps 1, 5 |
| §4 boundary vs `child` | A6 Step 3 (`config-dev.yaml` comment), A7 Step 1 |
| §5.2 entry points, file-based state | A1 Step 3 item 4 (re-entry), A6 Step 4 item 3–4 |
| §5.3 next-step block | Shared blocks |
| §5.4 orchestrator 5 steps | A1 |
| §5.5 dev-design three paths | A2 |
| §5.6 dev-plan shape | A3 |
| §5.7 dev-execute TDD loop | A4 |
| §5.8 dev-handover DoD | A5 |
| §5.9 hard rules | Shared blocks, asserted in A1–A5 |
| §5.10 `kb diff` banned | A1 Step 1 (`test_dev_implement_ticket_uses_resolve_and_get_never_diff`) |
| §13 testing (Stage A rows) | A1–A6 test steps |
| §14 rollout | A7 |

**Deferred to Stage B by design:** `cmd.*` sections do not exist yet, so A3 Step 3 item 6 records the build/test/lint commands in the plan file instead — spec §14 states this fallback explicitly.

**Deferred to Stage C by design:** `kb svc note` does not exist yet, so A5 Step 3 item 4 skips it with a one-line PR note.
