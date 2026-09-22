# SA greenfield grounding — PR 2 (skills, templates, docs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the shipped prompt/template surface what PR 1's engine already enforces. The SA proposes a `## Technology decisions` row for code that does not exist yet and references it as `[NEW: D<n>]` instead of parking "not built yet" under `Open decisions`; `sa-ticket-ground` runs *inside* `ba-ticket-author` (new step 7) and `ba-mission-plan` (new step 5) instead of as a manual follow-up; its handover ends with a fixed `## Needs input` block.

**Architecture:** No Python source changes. Twelve wrapper files under `src/strata_kb/templates/init/` carry the prompt text (four per skill: `claude-skill-*`, `claude-command-*`, `copilot-*.prompt.md`, `cursor-*.md`), plus two document templates, the review rubric, the BA quickstart and the two BA guides. Three invariants hold the twelve files together and are pinned by tests: the SA hard-rules block is byte-identical across the three full-content SA wrappers; `copilot-<skill>.prompt.md` and `cursor-<skill>.md` differ only on frontmatter line 2; `claude-skill-sa-ticket-ground.md` and `cursor-sa-ticket-ground.md` are byte-identical in full. Where two files must stay identical the plan edits one and *derives* the other with a shown command, never by re-typing prose.

**Tech Stack:** Python 3.11+, pytest (`uv run pytest`). Markdown templates shipped as package resources via `importlib.resources`. Spec: `docs/superpowers/specs/2026-09-22-sa-greenfield-grounding-design.md` §§3–5, §6.3, §7.

## Global Constraints

- **No version bump.** `pyproject.toml` `version` and `uv.lock` stay untouched. The CHANGELOG entry extends the existing `## Unreleased` block that PR 1 added — never create a second one, never open a new version heading.
- **No code changes.** Nothing under `src/strata_kb/*.py` is edited in this PR; it is templates, docs and tests only. If a needle test needs a helper, the helper goes in the test file.
- **Templates and skill text are English.** `docs/src/guide-ba.vi.md` stays Vietnamese, with English headings, section names and commands exactly as that file already does.
- **Byte-for-byte where the spec quotes.** The `## Needs input` block and the two new hard rules are quoted verbatim in spec §3 and must be copied character for character, including the `—`, `→` and `…` characters. Everywhere the spec paraphrases (template comments, pipeline step names), this plan already contains the final wording — use it as written.
- **PR 1 is done, do not re-do it.** `src/strata_kb/ticketcheck.py`, `src/strata_kb/cli.py`, `README.md`'s `kb ticket check` row and `tests/test_ticketcheck.py` / `tests/test_cli_ticket_check.py` landed on this branch (head `9d2b78c`). Do not touch them, with one exception: `tests/test_cli_ticket_check.py::test_docs_name_the_check_command` pins the QUICKSTART `## CLI reference` bullet `` - `kb ticket check <file> [--hub <url>]` ``; Task 6 updates that bullet to carry the new flags and changes that one assertion string to match (no other line of that test file).
- **Commit format:** `<type>: <description>` (feat / fix / refactor / docs / test / chore). Attribution trailer per the session reminder.
- **Green after every task:** `uv run pytest tests/test_templates.py tests/test_init.py -q` must pass at the end of each task. Run the full `uv run pytest -q` once, before the final commit.
- **GitNexus:** the CLAUDE.md `impact` rule is about Python symbols; this PR edits no Python symbol, so `impact` is not required. Run `detect_changes()` before each commit and confirm it reports no Python symbol changes. If the MCP server is down, say so in the commit body and continue.

---

## File structure

| File | Change |
|---|---|
| `src/strata_kb/templates/init/ticket-template.md` | `## Technical grounding` comment teaches `[NEW: D<n>]`; `Files:` example row uses it |
| `src/strata_kb/templates/init/mission-template.md` | `## Technology decisions` comment + a second example row; `## Services & order` comment and example row use `[NEW: D<n>]` |
| `src/strata_kb/templates/init/review-rubric.md` | one new Dev-implementability checklist item |
| `src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md` | Intake / Fill / Gate / Handover rewritten; two hard rules appended |
| `src/strata_kb/templates/init/cursor-sa-ticket-ground.md` | derived: byte-identical copy of the skill wrapper |
| `src/strata_kb/templates/init/copilot-sa-ticket-ground.prompt.md` | derived: the skill wrapper with line 2 = `mode: agent` |
| `src/strata_kb/templates/init/claude-command-sa-ticket-ground.md` | prose summary rewritten |
| `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md` | new step 7 *Ground technical*; steps 7–8 renumbered 8–9; review + handover + hard rule |
| `src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md` | same edits in its own dialect + frontmatter description |
| `src/strata_kb/templates/init/cursor-ba-ticket-author.md` | derived from the copilot wrapper |
| `src/strata_kb/templates/init/claude-command-ba-ticket-author.md` | pipeline line + code-detail paragraph |
| `src/strata_kb/templates/init/claude-skill-ba-mission-plan.md` | new step 5 *Ground services*; steps 5–8 renumbered 6–9; reviewer input + hard rule |
| `src/strata_kb/templates/init/claude-command-ba-mission-plan.md` | identical workflow edits (its body from `## Workflow` is the same text) |
| `src/strata_kb/templates/init/copilot-ba-mission-plan.prompt.md` | identical workflow edits + frontmatter description |
| `src/strata_kb/templates/init/cursor-ba-mission-plan.md` | derived from the copilot wrapper |
| `src/strata_kb/templates/init/QUICKSTART-ba.md` | step 6 folds into step 5 as sub-step 7; new "Greenfield repos" subsection; mission pipeline line |
| `docs/src/guide-ba.en.md` | nine-step pipeline box, §3.8 and §4.3 rewritten |
| `docs/src/guide-ba.vi.md` | the same, in Vietnamese |
| `docs/superpowers/specs/2026-09-20-sa-grounding-design.md` | §9 first bullet struck |
| `CHANGELOG.md` | one bullet appended under the existing `## Unreleased` |
| `tests/test_templates.py` | new needle / byte-identity tests |

**Not regenerated:** `docs/strata-guide-ba.{en,vi}.pdf`. `docs/src/build_pdf.py` requires macOS `/System/Library/Fonts/Supplemental` and is run by hand at release time; PR #62 (`b02ae92`), the previous guide-only change, updated the two `.md` sources and left the PDFs alone. This PR follows that precedent.

---

### Task 1: `ticket-template.md` and `mission-template.md` teach `[NEW: D<n>]`

**Files:**
- Modify: `src/strata_kb/templates/init/ticket-template.md`
- Modify: `src/strata_kb/templates/init/mission-template.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: a ticket template whose `## Technical grounding` comment names the `[NEW: D<n>]` form and its fallback, and a mission template whose `## Technology decisions` comment invites SA-appended rows and whose `## Services & order` example row references a D-row instead of free text.
- Consumes: nothing. These are leaf documents.

**Why the `## Services & order` row must change (PR 1 gap):** `kb ticket check` warns `<source> has Technology decisions — reference the row as [NEW: D<n>]` whenever a free-text `[NEW: …]` sits in a file that has a non-empty decisions table. The shipped mission template has both, so a freshly scaffolded mission emits that warning on its very first check. Fixing it is a template edit, not a code edit.

- [ ] **Step 1: Write the failing needle tests**

Append to the end of `tests/test_templates.py`:

```python
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
    # PR 1 gap: a free-text example row makes a freshly scaffolded mission
    # emit the "reference the row as [NEW: D<n>]" nudge on its first check.
    assert "[NEW: <why it does not exist yet>]" not in services_n
    # The marker exempts the whole row, `Depends on` included — so the
    # comment has to say where it goes.
    assert "the marker goes on the new service only" in services_n
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "teaches_the_decision_reference"`
Expected: 2 failed — `AssertionError` on `assert "[NEW: D<n>]" in normalised` for the ticket template and on the `The SA appends rows here…` assertion for the mission template.

- [ ] **Step 3: Edit `ticket-template.md`**

Replace this block (lines 68–79):

```markdown
## Technical grounding
<!-- SA-owned — filled by /sa-ticket-ground from the hub's <repo>-code
document, never by the BA. Every line points at a section id that exists
in that document, or carries [NEW: <reason>], or is parked under Open
decisions. No internal flow, no failure modes — the document cannot
prove them. Gate: `kb ticket check <this file>` must report
`Grounding: PASS`. -->
- Grounded on: <repo-id>:<repo-id>-code @ <revision>
- Service: svc.<name>
- Files:
  - <path exactly as listed in struct.tree>
  - <path> [NEW: <why it does not exist yet>]
```

with:

```markdown
## Technical grounding
<!-- SA-owned — filled by /sa-ticket-ground from the hub's <repo>-code
document, never by the BA. Every line points at a section id that exists
in that document, or carries [NEW: D<n>], or is parked under Open
decisions. Code the ticket will create → [NEW: D<n>], where D<n> is a
DECIDED row of the parent mission's Technology decisions. No parent
mission → [NEW: <reason>]. Open decisions is for code that EXISTS and
the document cannot prove — no internal flow, no failure modes — never
for a thing that is simply not built yet. Gate:
`kb ticket check <this file>` must report `Grounding: PASS`. -->
- Grounded on: <repo-id>:<repo-id>-code @ <revision>
- Service: svc.<name>
- Files:
  - <path exactly as listed in struct.tree>
  - <path> [NEW: D<n>]
```

- [ ] **Step 4: Edit `mission-template.md`, `## Technology decisions`**

Replace this block (lines 36–42):

```markdown
## Technology decisions
<!-- Every `%%TODO: verify against codebase%%` in the C4 sections has
exactly one row here. A placeholder without an owner means the mission
is not ready, even when lint passes. Status is OPEN or DECIDED. -->
| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | <e.g. storage engine choice> | OPEN | <who> | <US id> |
```

with:

```markdown
## Technology decisions
<!-- Every `%%TODO: verify against codebase%%` in the C4 sections has
exactly one row here. A placeholder without an owner means the mission
is not ready, even when lint passes. Status is OPEN or DECIDED. The SA
appends rows here for services, tables and routes the mission will
create; tickets reference them as [NEW: D<n>]. Only a human flips OPEN
to DECIDED. -->
| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | <e.g. storage engine choice> | OPEN | <who> | <US id> |
| D2 | New svc.<name> — <one line> | OPEN | <SA / tech lead> | <US id> |
```

- [ ] **Step 5: Edit `mission-template.md`, `## Services & order`**

Replace this block (lines 68–80):

```markdown
## Services & order
<!-- SA-owned — filled by /sa-ticket-ground --mission from the hub's
<repo>-code document. Capability layer only: one row per service this
mission touches, by its svc.<name> id; "Depends on" is copied from that
record's own `Depends on` cell. No file names, no function names,
no tables, no routes — those belong in each ticket's Technical grounding
section. A service the mission will create carries [NEW: <reason>]. -->
- Grounded on: <repo-id>:<repo-id>-code @ <revision>

| Order | Service | Depends on | Why this order |
|---|---|---|---|
| 1 | svc.<name> | <from record> | <reason, cites the dependency> |
| 2 | svc.<new-name> [NEW: <why it does not exist yet>] | svc.<name> | <reason> |
```

with:

```markdown
## Services & order
<!-- SA-owned — filled by /sa-ticket-ground --mission from the hub's
<repo>-code document. Capability layer only: one row per service this
mission touches, by its svc.<name> id; "Depends on" is copied from that
record's own `Depends on` cell. No file names, no function names,
no tables, no routes — those belong in each ticket's Technical grounding
section. A service the mission will create carries [NEW: D<n>], naming
its row in Technology decisions above. One marker exempts every unknown
svc.* on its row, "Depends on" included, so the marker goes on the new
service only — keep "Depends on" to services that already exist or
carry their own decision row. -->
- Grounded on: <repo-id>:<repo-id>-code @ <revision>

| Order | Service | Depends on | Why this order |
|---|---|---|---|
| 1 | svc.<name> | <from record> | <reason, cites the dependency> |
| 2 | svc.<new-name> [NEW: D<n>] | svc.<name> | <reason> |
```

- [ ] **Step 6: Run the template suites**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q`
Expected: all PASS. In particular `test_ticket_template_carries_the_technical_grounding_section` and `test_mission_template_carries_services_and_order` still pass — both assert `"[NEW:" in body`, which `[NEW: D<n>]` satisfies.

- [ ] **Step 7: Run `detect_changes()` and commit**

Run `detect_changes()` via the GitNexus MCP (or `node .gitnexus/run.cjs analyze` then retry if the index is stale); confirm no Python symbol is listed.

```bash
git add src/strata_kb/templates/init/ticket-template.md src/strata_kb/templates/init/mission-template.md tests/test_templates.py
git commit -m "docs(templates): teach [NEW: D<n>] in the ticket and mission templates"
```

---

### Task 2: the review rubric asks whether every placeholder was answered

**Files:**
- Modify: `src/strata_kb/templates/init/review-rubric.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: one new checklist item on the `## Dev implementability` axis, the verbatim text of spec §4 "Review rubric".
- Consumes: nothing.

- [ ] **Step 1: Write the failing test**

Append to the end of `tests/test_templates.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_templates.py -q -k "rubric_dev_axis"`
Expected: 1 failed — `AssertionError` (the phrase is not in the file).

- [ ] **Step 3: Add the checklist item**

In `src/strata_kb/templates/init/review-rubric.md`, replace:

```markdown
- [ ] Every `OPEN(...)` and `%%TODO%%` has an owner.
- [ ] No weasel words anywhere in the body.
```

with:

```markdown
- [ ] Every `OPEN(...)` and `%%TODO%%` has an owner.
- [ ] Every `%%TODO: verify against codebase%%` in a BA section is
      answered in `## Technical grounding` by an id, a `[NEW: D<n>]`, or
      an Open decisions entry — none is silently dropped.
- [ ] No weasel words anywhere in the body.
```

- [ ] **Step 4: Run the template suites**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q`
Expected: all PASS, including `test_review_rubric_doc_carries_both_axes_and_the_scale`.

- [ ] **Step 5: Run `detect_changes()` and commit**

```bash
git add src/strata_kb/templates/init/review-rubric.md tests/test_templates.py
git commit -m "docs(rubric): the Dev axis checks every codebase placeholder was answered"
```

---

### Task 3: the four `sa-ticket-ground` wrappers

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md`
- Derive: `src/strata_kb/templates/init/cursor-sa-ticket-ground.md` (byte-identical copy)
- Derive: `src/strata_kb/templates/init/copilot-sa-ticket-ground.prompt.md` (same, line 2 = `mode: agent`)
- Modify: `src/strata_kb/templates/init/claude-command-sa-ticket-ground.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: an SA skill that loads the parent mission's decisions table at Intake, resolves each placeholder to an id / `[NEW: D<n>]` / `Open decisions`, gates with `kb ticket check <file> [--missions-dir <dir>]` (or `--heading "## Services & order"` for a mission), and closes with the fixed `## Needs input` block. Two new hard rules.
- Consumes: the engine messages that PR 1's `ticketcheck._judge_new` emits — the Gate step quotes them so the SA reacts to the real output.
- Invariant produced: `claude-skill-sa-ticket-ground.md` == `cursor-sa-ticket-ground.md` byte for byte (verified: they are identical today); `copilot-sa-ticket-ground.prompt.md` differs from `cursor-sa-ticket-ground.md` only on line 2.

**Note on the fourth wrapper:** `claude-command-sa-ticket-ground.md` is a thin skill invoker (it has no `## Hard rules` heading — it summarises them in prose, and `test_every_landed_claude_command_is_a_skill_invoker` expects that shape). The byte-identity test therefore covers the three full-content wrappers, which is exactly what the existing `SA_FULL_WRAPPERS` constant is for.

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/test_templates.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "sa_hard_rules or sa_wrappers or sa_claude_skill"`
Expected: `test_sa_hard_rules_are_byte_identical_across_the_full_wrappers` and `test_sa_claude_skill_and_cursor_wrappers_are_byte_identical` PASS already (that is today's state, and they are the pin the rest of this task must not break); the other four FAIL with `AssertionError` naming the missing needle.

- [ ] **Step 3: Rewrite Intake in `claude-skill-sa-ticket-ground.md`**

Replace:

```markdown
1. **Intake** — read the document. Identify the product repo id
   (`<repo-id>`) from the BA's input or the parent mission. Collect every
   `%%TODO: verify against codebase%%` in the BA-owned sections: these
   are the questions this pass must answer with an id or park under
   `Open decisions`.
```

with:

```markdown
1. **Intake** — read the document. Identify the product repo id
   (`<repo-id>`) from the BA's input or the parent mission. Collect every
   `%%TODO: verify against codebase%%` in the BA-owned sections: these
   are the questions this pass must answer with an id, with
   `[NEW: D<n>]`, or by parking under `Open decisions`. Read the parent
   mission too: `> Parent mission: M-<slug>` under the ticket's title
   points at `missions/M-<slug>.md`. Load its `## Technology decisions`
   table — its D-rows are the only legal targets of `[NEW: D<n>]`. With
   `--mission` that table is in the file you are filling. No parent
   mission, no table: case 2 of Fill degrades to free text.
```

- [ ] **Step 4: Rewrite the opening of Fill in `claude-skill-sa-ticket-ground.md`**

Replace:

```markdown
3. **Fill** — write the section from the loaded sections and nothing
   else, field by field:
```

with:

```markdown
3. **Fill** — write the section from the loaded sections and nothing
   else. Every BA placeholder resolves to exactly one of three things:
   - an id that exists in `<repo>-code`;
   - `[NEW: D<n>]` — the thing does not exist yet, and row D<n> of the
     parent mission's `## Technology decisions` says what it will be. No
     matching row → append one first, then write the marker:
     `| D<n> | <concrete proposal: svc/table/route name and one line why> | OPEN | <human SA / tech lead> | <US id> |`
     The proposal is specific — a name the ticket can use — never "TBD".
     Without a parent mission this degrades to `[NEW: <reason>]`, and
     the handover says a mission would give the decision an owner;
   - `Open decisions` — only for code that EXISTS and the document
     cannot prove: internal flow, failure modes, body schemas, a
     contradiction with a BA statement. Never for a thing that is
     simply not built yet.

   On a `## Services & order` row a single `[NEW: D<n>]` exempts every
   unknown `svc.*` on that row, `Depends on` included. Put the marker on
   the new service only, and keep `Depends on` to services that already
   exist or carry their own decision row.

   Then fill the section field by field:
```

- [ ] **Step 5: Point the `Files:` example at a decision row**

In the same file, replace:

```markdown
   - `Files:` — one path per sub-bullet, spelled exactly as `struct.tree`
     lists it. `struct.tree` stops at depth 4 and 600 lines: list the
     deepest directory it shows rather than a path you cannot see. A
     file the ticket will create: `<path> [NEW: <why it does not exist
     yet>]`.
```

with:

```markdown
   - `Files:` — one path per sub-bullet, spelled exactly as `struct.tree`
     lists it. `struct.tree` stops at depth 4 and 600 lines: list the
     deepest directory it shows rather than a path you cannot see. A
     file the ticket will create: `<path> [NEW: D<n>]`.
```

- [ ] **Step 6: Rewrite the Gate step**

In the same file, replace:

```markdown
4. **Gate** — run `kb ticket check <file>` (CLI; there is no MCP
   fallback). Fix every `[error]` and re-run until it prints
   `Grounding: PASS`. A non-empty `Open decisions` is a FAIL by design:
   report the list to the BA instead of emptying it by guessing.
```

with:

```markdown
4. **Gate** — run `kb ticket check <file> [--missions-dir <dir>]` (CLI;
   there is no MCP fallback); for a mission,
   `kb ticket check --heading "## Services & order" <file>`.
   `--missions-dir` defaults to the ticket's sibling `missions/`
   directory — pass it when the missions live elsewhere. Fix every
   `[error]` and re-run until it prints `Grounding: PASS`. What the
   engine's own words mean:
   - `needs a parent mission to hold the decision` — no back-link. Ask
     the BA to add `> Parent mission: M-<slug>` under the title, or
     write `[NEW: <reason>]` instead.
   - `parent mission '<id>' not found under missions/` — pass
     `--missions-dir`; never delete the marker to silence it.
   - `decision D<n> not in <file>'s Technology decisions` — append the
     row there first.
   - `decision D<n> is <status> (owner: <x>)` — a human decides before
     Dev. Report it and stop; NEVER flip a Status to make the gate pass.
   - warning `has Technology decisions — reference the row as
     [NEW: D<n>]` — you used free text where a D-row belongs.
   A non-empty `Open decisions` is a FAIL by design: report the list to
   the BA instead of emptying it by guessing.
```

- [ ] **Step 7: Rewrite the Handover step and append the fixed block**

In the same file, replace:

```markdown
5. **Handover** — report: the ids grounded, the `[NEW]` entries, the
   open decisions (count and text), the BA placeholders answered, and any
   BA-section contradiction found. The BA decides what goes back to the
   business side and what goes to the Dev.
```

with (note the closing fence is at column 0 on purpose — the list ends
there, so the block below is byte-for-byte the spec's):

````markdown
5. **Handover** — report: the ids grounded, the `[NEW: D<n>]` entries,
   the open decisions (count and text), the BA placeholders answered,
   and any BA-section contradiction found. The BA decides what goes back
   to the business side and what goes to the Dev. End the report with
   this fixed block — English heading, entries in the BA's language:

```
## Needs input
- Decisions proposed (OPEN → DECIDED by owner): D3 (svc.billing, owner: <x>, blocks US2), …
- Open decisions for the Dev (code exists, document cannot prove): …
- BA-section contradictions: …
```
````

- [ ] **Step 8: Update the first hard rule and append the two new ones**

In the same file, replace:

```markdown
- Every line in the SA-owned section (`## Technical grounding`, or
  `## Services & order` with `--mission`) must either
  - point at a section id that exists in the `<repo>-code` document, OR
  - carry `[NEW: <reason>]` saying why it does not exist yet, OR
  - go under `Open decisions`.
```

with:

```markdown
- Every line in the SA-owned section (`## Technical grounding`, or
  `## Services & order` with `--mission`) must either
  - point at a section id that exists in the `<repo>-code` document, OR
  - carry `[NEW: D<n>]` naming a DECIDED row of the parent mission's
    `## Technology decisions` — `[NEW: <reason>]` only when there is no
    parent mission, OR
  - go under `Open decisions`.
```

Then replace the last hard rule:

```markdown
- English headings stay English; write the section's free text in the
  BA's working language.
```

with:

```markdown
- English headings stay English; write the section's free text in the
  BA's working language.
- A thing the code does not have yet is a design decision, not missing
  data: propose it as a `## Technology decisions` row (status OPEN, a
  human owner) and reference it as [NEW: D<n>]. Never park "not built
  yet" under Open decisions.
- You may APPEND rows to `## Technology decisions`; never edit or delete
  an existing row, never change a Status — only a human flips OPEN to
  DECIDED.
```

- [ ] **Step 9: Derive the cursor and copilot wrappers**

Do not re-type the prose. Run, from the project root:

```bash
uv run python - <<'PY'
from pathlib import Path

base = Path("src/strata_kb/templates/init")
skill = (base / "claude-skill-sa-ticket-ground.md").read_text(encoding="utf-8")
(base / "cursor-sa-ticket-ground.md").write_text(skill, encoding="utf-8")

lines = skill.splitlines(keepends=True)
assert lines[1] == "name: sa-ticket-ground\n", lines[1]
lines[1] = "mode: agent\n"
(base / "copilot-sa-ticket-ground.prompt.md").write_text("".join(lines), encoding="utf-8")
print("derived cursor + copilot sa-ticket-ground wrappers")
PY
```

Expected output: `derived cursor + copilot sa-ticket-ground wrappers`.

- [ ] **Step 10: Rewrite `claude-command-sa-ticket-ground.md`**

Replace the whole body below the frontmatter (lines 6–20):

```markdown
Invoke the `sa-ticket-ground` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the file path, and `--mission`
through when given.

Pipeline: Intake → Load → Fill → Gate → Handover. Hard rules the skill
enforces: every line of the SA-owned section (`## Technical grounding`,
or `## Services & order` with `--mission`) points at a section id that
exists in `<repo>-code`, or carries `[NEW: <reason>]`, or goes under
`Open decisions`; no data → `Open decisions`, never inference;
never edit a BA-owned section — a contradiction is quoted there, not
corrected; `Grounded on: <repo-id>:<doc-id> @ <revision>` is the first
line, copied from the hub document's manifest revision; never write
internal flow or failure modes — the document cannot prove them;
`kb ticket check` failing to RUN is not a PASS; never tick a
Definition of Ready checkbox — only the BA confirms DoR.
```

with:

```markdown
Invoke the `sa-ticket-ground` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the file path, and `--mission`
through when given.

Pipeline: Intake → Load → Fill → Gate → Handover. Hard rules the skill
enforces: every line of the SA-owned section (`## Technical grounding`,
or `## Services & order` with `--mission`) points at a section id that
exists in `<repo>-code`, or carries `[NEW: D<n>]` naming a DECIDED row
of the parent mission's `## Technology decisions` (`[NEW: <reason>]`
only when there is no parent mission), or goes under `Open decisions`;
a thing the code does not have yet is a design decision, not missing
data — propose it as a `## Technology decisions` row (status OPEN, a
human owner), never park "not built yet" under `Open decisions`; you
may APPEND rows to that table and never edit, delete or re-status an
existing one — only a human flips OPEN to DECIDED; code that exists and
the document cannot prove → `Open decisions`, never inference;
never edit a BA-owned section — a contradiction is quoted there, not
corrected; `Grounded on: <repo-id>:<doc-id> @ <revision>` is the first
line, copied from the hub document's manifest revision; never write
internal flow or failure modes — the document cannot prove them; the
gate is `kb ticket check <file> [--missions-dir <dir>]`, or
`kb ticket check --heading "## Services & order" <file>` for a mission,
and failing to RUN is not a PASS; the handover ends with the fixed
`## Needs input` block naming every decision still waiting for a human;
never tick a Definition of Ready checkbox — only the BA confirms DoR.
```

- [ ] **Step 11: Run the template suites**

Run: `uv run pytest tests/test_templates.py tests/test_init.py tests/test_cli_ticket_check.py -q`
Expected: all PASS. `test_every_citation_example_is_bracketed[*sa-ticket-ground*]` and `test_docs_name_the_check_command` are the two that would catch a mis-edit here.

- [ ] **Step 12: Run `detect_changes()` and commit**

```bash
git add src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md \
        src/strata_kb/templates/init/cursor-sa-ticket-ground.md \
        src/strata_kb/templates/init/copilot-sa-ticket-ground.prompt.md \
        src/strata_kb/templates/init/claude-command-sa-ticket-ground.md \
        tests/test_templates.py
git commit -m "feat(sa-ticket-ground): propose a decision row instead of parking \"not built yet\""
```

---

### Task 4: `ba-ticket-author` grounds the technical half in-pipeline

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md`
- Modify: `src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md`
- Derive: `src/strata_kb/templates/init/cursor-ba-ticket-author.md`
- Modify: `src/strata_kb/templates/init/claude-command-ba-ticket-author.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: a nine-step pipeline whose new step 7 *Ground technical* invokes `sa-ticket-ground` as its own subagent after `DoR: PASS`; a maturity review that feeds the Dev-implementability reviewer the technical half and re-runs `kb ticket check` after each changed round; a handover that carries `## Needs input` verbatim; an edited code-detail hard rule.
- Consumes: the `## Needs input` block produced in Task 3.
- Invariant produced: `copilot-ba-ticket-author.prompt.md` and `cursor-ba-ticket-author.md` still differ only on frontmatter line 2.

**Numbering note:** the spec calls the new step "6b". Markdown ordered lists cannot carry `6b.` as a list item, and these files are read as prose by an agent, so the step is inserted as `7.` and the two following steps are renumbered to `8.` and `9.`. The pipeline order is exactly the spec's.

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/test_templates.py`:

```python
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
        assert "as its own subagent" in text, name
        assert "After every round that changed the draft, also run `kb ticket check`" in text, name
        assert "on PASS, do not re-ground" in text, name


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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "ba_ticket_wrappers_run_the_sa or re_ground_only or ba_ticket_pipeline_line"`
Expected: 3 failed — `AssertionError: claude-skill-ba-ticket-author.md` on `"Ground technical" in text` and friends.

- [ ] **Step 3: `claude-skill-ba-ticket-author.md` — the pipeline sentence**

Replace:

```markdown
You are the ORCHESTRATOR of the ticket-authoring pipeline: Intake →
Parent mission → Ground → Draft → Pin → Lint → Maturity review → Review.
The ticket you write is a **draft** — the BA reviews it, commits it, and
pastes it into Jira; you never publish it yourself.
```

with:

```markdown
You are the ORCHESTRATOR of the ticket-authoring pipeline: Intake →
Parent mission → Ground → Draft → Pin → Lint → Ground technical →
Maturity review → Review. The ticket you write is a **draft** — the BA
reviews it, commits it, and pastes it into Jira; you never publish it
yourself.
```

- [ ] **Step 4: `claude-skill-ba-ticket-author.md` — insert step 7 and renumber**

Replace:

```markdown
7. **Maturity review** — once lint reports `DoR: PASS`, read
```

with:

```markdown
7. **Ground technical** — once lint reports `DoR: PASS`, save the draft
   and invoke `sa-ticket-ground` on the saved file **as its own
   subagent** — no shared context: the SA sees the file and the hub, not
   your reasoning. It fills the SA-owned `## Technical grounding`
   section from `<repo>-code`, proposes an `OPEN` row in the parent
   mission's `## Technology decisions` for anything the code does not
   have yet (referenced as `[NEW: D<n>]`), and runs `kb ticket check`
   until it reports `Grounding: PASS`. Keep its `## Needs input`
   block — it goes into your handover verbatim.
8. **Maturity review** — once lint reports `DoR: PASS`, read
```

Then replace:

```markdown
8. **Review → save** — write the final Markdown to
   `tickets/<ticket-id>.md`. Hand it to the BA to review and commit;
   the BA — not you — pastes it into Jira.
```

with:

```markdown
9. **Review → save** — write the final Markdown to
   `tickets/<ticket-id>.md`. Hand it to the BA to review and commit;
   the BA — not you — pastes it into Jira.
```

- [ ] **Step 5: `claude-skill-ba-ticket-author.md` — the reviewer gets the technical half**

Replace:

```markdown
   - *Dev-implementability reviewer* — acts as the dev who picks the
     ticket up next sprint; scores the "Dev implementability" axis.
   Keep the two roles in separate subagents — never blend the
```

with:

```markdown
   - *Dev-implementability reviewer* — acts as the dev who picks the
     ticket up next sprint; scores the "Dev implementability" axis.
     Give it the `## Technical grounding` section and the SA's
     `## Needs input` block as input — the technical half is half of
     what "implementable" means.
   Keep the two roles in separate subagents — never blend the
```

- [ ] **Step 6: `claude-skill-ba-ticket-author.md` — re-check and re-ground between rounds**

Replace:

```markdown
   Apply the fixes, re-run `kb ticket lint`, then review again — at most
   3 rounds total; stop early when both axes score ≥ 4.
```

with:

```markdown
   Apply the fixes, re-run `kb ticket lint`, then review again — at most
   3 rounds total; stop early when both axes score ≥ 4. After every
   round that changed the draft, also run `kb ticket check`: on FAIL,
   re-invoke `sa-ticket-ground` with only the changed sections and the
   failing lines (same discipline as `gap-verifier`); on PASS, do not
   re-ground.
```

- [ ] **Step 7: `claude-skill-ba-ticket-author.md` — the handover carries `## Needs input`**

Replace:

```markdown
   ticket id. When the command answers `no usage recorded yet`, report
   that instead of guessing a number.
```

with:

```markdown
   ticket id. When the command answers `no usage recorded yet`, report
   that instead of guessing a number. Carry the SA's `## Needs input`
   block into the handover verbatim: a D-row still waiting for `DECIDED`
   is the BA's to chase, not the Dev's.
```

- [ ] **Step 8: `claude-skill-ba-ticket-author.md` — the code-detail hard rule**

Replace:

```markdown
- **Code-level detail is not yours to ground.** Write
  `%%TODO: verify against codebase%%` where a service, table, route or
  file name is needed, add the owned `## Open questions` row, and hand
  the ticket to `/sa-ticket-ground` once the business sections are
  drafted — it fills the SA-owned `## Technical grounding` section from
  the hub's `<repo>-code` document and `kb ticket check` verifies every
  id. Never read `<repo>-code` or `<repo>-svc` yourself.
```

with:

```markdown
- **Code-level detail is not yours to ground.** Write
  `%%TODO: verify against codebase%%` where a service, table, route or
  file name is needed, add the owned `## Open questions` row, and let
  step 7 invoke `/sa-ticket-ground` on the saved draft — it fills the
  SA-owned `## Technical grounding` section from the hub's `<repo>-code`
  document and `kb ticket check` verifies every id. Re-run
  `/sa-ticket-ground` by hand only when `-code` moves after handover.
  Never read `<repo>-code` or `<repo>-svc` yourself.
```

- [ ] **Step 9: `copilot-ba-ticket-author.prompt.md` — frontmatter description**

Replace line 3:

```markdown
description: Draft a Dev-ready ticket grounded in the KB — Intake → Parent mission → Ground → Draft → Pin → Lint → Maturity review → Review, saved to tickets/<id>.md
```

with:

```markdown
description: Draft a Dev-ready ticket grounded in the KB — Intake → Parent mission → Ground → Draft → Pin → Lint → Ground technical → Maturity review → Review, saved to tickets/<id>.md
```

- [ ] **Step 10: `copilot-ba-ticket-author.prompt.md` — insert step 7 and renumber**

Replace:

```markdown
7. **Maturity review** — once lint reports `DoR: PASS`, read
```

with:

```markdown
7. **Ground technical** — once lint reports `DoR: PASS`, save the draft
   and invoke `sa-ticket-ground` on the saved file **as its own
   subagent** — no shared context: the SA sees the file and the hub, not
   your reasoning. It fills the SA-owned `## Technical grounding`
   section from `<repo>-code`, proposes an `OPEN` row in the parent
   mission's `## Technology decisions` for anything the code does not
   have yet (referenced as `[NEW: D<n>]`), and runs `kb ticket check`
   until it reports `Grounding: PASS`. Keep its `## Needs input`
   block — it goes into your handover verbatim.
8. **Maturity review** — once lint reports `DoR: PASS`, read
```

Then replace:

```markdown
8. **Review → save** — write the final Markdown to
   `tickets/<ticket-id>.md`; the BA reviews it, commits it, and pastes it
   into Jira.
```

with:

```markdown
9. **Review → save** — write the final Markdown to
   `tickets/<ticket-id>.md`; the BA reviews it, commits it, and pastes it
   into Jira.
```

- [ ] **Step 11: `copilot-ba-ticket-author.prompt.md` — the reviewer gets the technical half**

Replace:

```markdown
   - Pass 2, *Dev-implementability reviewer* — act as the dev who picks
     the ticket up next sprint; score the "Dev implementability" axis.
```

with:

```markdown
   - Pass 2, *Dev-implementability reviewer* — act as the dev who picks
     the ticket up next sprint; score the "Dev implementability" axis.
     Read the `## Technical grounding` section and the SA's
     `## Needs input` block for this pass — the technical half is half
     of what "implementable" means.
```

- [ ] **Step 12: `copilot-ba-ticket-author.prompt.md` — the three remaining edits**

Apply the identical replacements this file shares word-for-word with the skill wrapper. Replace:

```markdown
   Apply the fixes, re-run `kb ticket lint`, then review again — at most
   3 rounds total; stop early when both axes score ≥ 4.
```

with:

```markdown
   Apply the fixes, re-run `kb ticket lint`, then review again — at most
   3 rounds total; stop early when both axes score ≥ 4. After every
   round that changed the draft, also run `kb ticket check`: on FAIL,
   re-invoke `sa-ticket-ground` with only the changed sections and the
   failing lines (same discipline as `gap-verifier`); on PASS, do not
   re-ground.
```

Replace:

```markdown
   ticket id. When the command answers `no usage recorded yet`, report
   that instead of guessing a number.
```

with:

```markdown
   ticket id. When the command answers `no usage recorded yet`, report
   that instead of guessing a number. Carry the SA's `## Needs input`
   block into the handover verbatim: a D-row still waiting for `DECIDED`
   is the BA's to chase, not the Dev's.
```

Replace:

```markdown
- **Code-level detail is not yours to ground.** Write
  `%%TODO: verify against codebase%%` where a service, table, route or
  file name is needed, add the owned `## Open questions` row, and hand
  the ticket to `/sa-ticket-ground` once the business sections are
  drafted — it fills the SA-owned `## Technical grounding` section from
  the hub's `<repo>-code` document and `kb ticket check` verifies every
  id. Never read `<repo>-code` or `<repo>-svc` yourself.
```

with:

```markdown
- **Code-level detail is not yours to ground.** Write
  `%%TODO: verify against codebase%%` where a service, table, route or
  file name is needed, add the owned `## Open questions` row, and let
  step 7 invoke `/sa-ticket-ground` on the saved draft — it fills the
  SA-owned `## Technical grounding` section from the hub's `<repo>-code`
  document and `kb ticket check` verifies every id. Re-run
  `/sa-ticket-ground` by hand only when `-code` moves after handover.
  Never read `<repo>-code` or `<repo>-svc` yourself.
```

- [ ] **Step 13: Derive the cursor wrapper**

```bash
uv run python - <<'PY'
from pathlib import Path

base = Path("src/strata_kb/templates/init")
src = (base / "copilot-ba-ticket-author.prompt.md").read_text(encoding="utf-8").splitlines(keepends=True)
dst = base / "cursor-ba-ticket-author.md"
cur = dst.read_text(encoding="utf-8").splitlines(keepends=True)
assert src[1] == "mode: agent\n", src[1]
assert cur[1] == "name: ba-ticket-author\n", cur[1]
dst.write_text("".join(src[:1] + cur[1:2] + src[2:]), encoding="utf-8")
print("derived cursor-ba-ticket-author.md")
PY
```

Expected output: `derived cursor-ba-ticket-author.md`.

- [ ] **Step 14: `claude-command-ba-ticket-author.md` — pipeline line**

Replace:

```markdown
Pipeline: Intake → Parent mission → Ground → Draft → Pin → Lint → Maturity review → Review,
```

with:

```markdown
Pipeline: Intake → Parent mission → Ground → Draft → Pin → Lint → Ground technical → Maturity review → Review,
```

- [ ] **Step 15: `claude-command-ba-ticket-author.md` — the closing paragraph**

Replace:

```markdown
Code-level detail is not yours to ground: write
`%%TODO: verify against codebase%%` where a service, table, route or
file name is needed, add the owned `## Open questions` row, and hand the
ticket to `/sa-ticket-ground` once the business sections are drafted —
it fills the SA-owned `## Technical grounding` section from the hub's
`<repo>-code` document and `kb ticket check` verifies every id. Never
read `<repo>-code` or `<repo>-svc` yourself; leave `## Technical
grounding` exactly as the template ships it.
```

with:

```markdown
Code-level detail is not yours to ground: write
`%%TODO: verify against codebase%%` where a service, table, route or
file name is needed, add the owned `## Open questions` row, and let
step 7 (Ground technical) invoke `/sa-ticket-ground` on the saved
draft — it fills the SA-owned `## Technical grounding` section from the
hub's `<repo>-code` document, proposes an `OPEN` row in the parent
mission's `## Technology decisions` for anything the code does not have
yet (referenced as `[NEW: D<n>]`), and `kb ticket check` verifies every
id. Re-run `/sa-ticket-ground` by hand only when `-code` moves after
handover. Never read `<repo>-code` or `<repo>-svc` yourself; leave
`## Technical grounding` exactly as the template ships it, and carry the
SA's `## Needs input` block into your handover verbatim.
```

- [ ] **Step 16: Run the template suites**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q`
Expected: all PASS, including `test_copilot_and_cursor_wrappers_differ_only_in_their_frontmatter_name` (dev skills), `test_ba_ticket_author_templates_carry_the_seven_pipeline_steps`, `test_ba_wrappers_hand_code_detail_to_the_sa_skill`, `test_ba_ticket_author_reports_usage_at_handover` and `test_ba_wrappers_keep_round_one_two_perspective`.

- [ ] **Step 17: Run `detect_changes()` and commit**

```bash
git add src/strata_kb/templates/init/claude-skill-ba-ticket-author.md \
        src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md \
        src/strata_kb/templates/init/cursor-ba-ticket-author.md \
        src/strata_kb/templates/init/claude-command-ba-ticket-author.md \
        tests/test_templates.py
git commit -m "feat(ba-ticket-author): ground the technical half inside the pipeline"
```

---

### Task 5: `ba-mission-plan` grounds the service list in-pipeline

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-ba-mission-plan.md`
- Modify: `src/strata_kb/templates/init/claude-command-ba-mission-plan.md`
- Modify: `src/strata_kb/templates/init/copilot-ba-mission-plan.prompt.md`
- Derive: `src/strata_kb/templates/init/cursor-ba-mission-plan.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: a nine-step mission pipeline whose new step 5 *Ground services* invokes `sa-ticket-ground --mission` once the backlog and `## Sequencing` are confirmed; a Dev-implementability reviewer that receives `## Services & order`; an edited code-detail hard rule.
- Consumes: the SA wrapper from Task 3.

**Verified precondition:** `claude-skill-ba-mission-plan.md` from `## Workflow` to EOF is byte-identical to `claude-command-ba-mission-plan.md` from its `## Workflow` to EOF, and to `copilot-ba-mission-plan.prompt.md`'s. Steps 3–7 below therefore apply the *same* replacement text to all three files; only the intro/frontmatter edits differ per file.

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/test_templates.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "ba_mission_wrappers_run_the_sa or ba_mission_reviewer_receives or ba_mission_pipeline_line"`
Expected: 3 failed — `AssertionError: claude-skill-ba-mission-plan.md` on `"Ground services" in text` and friends.

- [ ] **Step 3: Insert step 5 and renumber — apply to all THREE full files**

Apply the next two replacements to `claude-skill-ba-mission-plan.md`, `claude-command-ba-mission-plan.md` and `copilot-ba-mission-plan.prompt.md`, in each case to the file's single occurrence.

Replace:

```markdown
5. **Pin** — once the BA confirms which sections actually apply, call the
```

with:

```markdown
5. **Ground services** — once the BA has confirmed the backlog and
   `## Sequencing` is filled, invoke `sa-ticket-ground --mission` on the
   draft. It fills the SA-owned `## Services & order` section from the
   hub's `<repo>-code` document and appends a `## Technology decisions`
   row (status `OPEN`, a human owner) for every service the mission will
   create, referenced from the service table as `[NEW: D<n>]`.
   `kb mission lint` already warns on an ownerless D-row — that warning
   is the BA's to close, never the SA's.
6. **Pin** — once the BA confirms which sections actually apply, call the
```

Replace:

```markdown
6. **Lint** — run `kb mission lint <file>` against the draft. Fix every
```

with:

```markdown
7. **Lint** — run `kb mission lint <file>` against the draft. Fix every
```

- [ ] **Step 4: Renumber steps 7 and 8 — all three files**

Replace:

```markdown
7. **Maturity review** — once lint reports `DoR: PASS`, read
```

with:

```markdown
8. **Maturity review** — once lint reports `DoR: PASS`, read
```

Replace:

```markdown
8. **Review → save** — write the final Markdown to
   `missions/<mission-id>.md`. Hand it to the BA to review and commit.
```

with:

```markdown
9. **Review → save** — write the final Markdown to
   `missions/<mission-id>.md`. Hand it to the BA to review and commit.
```

- [ ] **Step 5: The reviewer receives the service order — all three files**

Replace:

```markdown
   - *Dev-implementability reviewer* — acts as the tech lead who will
     slice this mission into tickets; scores the "Dev implementability"
     axis.
```

with:

```markdown
   - *Dev-implementability reviewer* — acts as the tech lead who will
     slice this mission into tickets; scores the "Dev implementability"
     axis. Give it `## Services & order` as input — the service order is
     what makes the backlog sliceable.
```

- [ ] **Step 6: The code-detail hard rule — all three files**

Replace:

```markdown
- **Code-level detail is not yours to ground.** Write
  `%%TODO: verify against codebase%%` where a service or container name
  is needed, add the owned `## Technology decisions` row, and hand the
  mission to `/sa-ticket-ground --mission` once the BA confirms the
  backlog — it fills the SA-owned `## Services & order` section from the
  hub's `<repo>-code` document (`svc.*` and its `Depends on` cell) and
  the architecture document. Never read `<repo>-code` or `<repo>-svc`
  yourself.
```

with:

```markdown
- **Code-level detail is not yours to ground.** Write
  `%%TODO: verify against codebase%%` where a service or container name
  is needed, add the owned `## Technology decisions` row, and let step 5
  (Ground services) invoke `/sa-ticket-ground --mission` once the BA
  confirms the backlog — it fills the SA-owned `## Services & order`
  section from the hub's `<repo>-code` document (`svc.*` and its
  `Depends on` cell) and the architecture document, and appends an
  `OPEN` decision row for every service the mission will create. Never
  read `<repo>-code` or `<repo>-svc` yourself.
```

- [ ] **Step 7: `claude-skill-ba-mission-plan.md` only — the pipeline sentence**

Replace:

```markdown
You are the ORCHESTRATOR of the mission-planning pipeline: Intake →
Ground → Draft → Split → Pin → Lint → Maturity review → Review. The
mission you write is a **draft** — the BA reviews and commits it. It
```

with:

```markdown
You are the ORCHESTRATOR of the mission-planning pipeline: Intake →
Ground → Draft → Split → Ground services → Pin → Lint → Maturity
review → Review. The mission you write is a **draft** — the BA reviews
and commits it. It
```

- [ ] **Step 8: `copilot-ba-mission-plan.prompt.md` only — frontmatter description**

Replace line 3:

```markdown
description: Draft an epic-level Mission Plan grounded in the KB — Intake → Ground → Draft → Split → Pin → Lint → Maturity review → Review, saved to missions/M-<slug>.md
```

with:

```markdown
description: Draft an epic-level Mission Plan grounded in the KB — Intake → Ground → Draft → Split → Ground services → Pin → Lint → Maturity review → Review, saved to missions/M-<slug>.md
```

- [ ] **Step 9: Derive the cursor wrapper**

```bash
uv run python - <<'PY'
from pathlib import Path

base = Path("src/strata_kb/templates/init")
src = (base / "copilot-ba-mission-plan.prompt.md").read_text(encoding="utf-8").splitlines(keepends=True)
dst = base / "cursor-ba-mission-plan.md"
cur = dst.read_text(encoding="utf-8").splitlines(keepends=True)
assert src[1] == "mode: agent\n", src[1]
assert cur[1] == "name: ba-mission-plan\n", cur[1]
dst.write_text("".join(src[:1] + cur[1:2] + src[2:]), encoding="utf-8")
print("derived cursor-ba-mission-plan.md")
PY
```

Expected output: `derived cursor-ba-mission-plan.md`.

- [ ] **Step 10: Pin the copilot/cursor invariant for the three non-dev skills**

Append to the end of `tests/test_templates.py`:

```python
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
```

- [ ] **Step 11: Run the template suites**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q`
Expected: all PASS, including the new `test_copilot_and_cursor_ba_sa_wrappers_differ_only_on_frontmatter_line_two`, `test_ba_mission_plan_templates_carry_the_maturity_review_step` and `test_ba_wrappers_do_not_let_the_gap_verifier_invent_a_score`.

- [ ] **Step 12: Run `detect_changes()` and commit**

```bash
git add src/strata_kb/templates/init/claude-skill-ba-mission-plan.md \
        src/strata_kb/templates/init/claude-command-ba-mission-plan.md \
        src/strata_kb/templates/init/copilot-ba-mission-plan.prompt.md \
        src/strata_kb/templates/init/cursor-ba-mission-plan.md \
        tests/test_templates.py
git commit -m "feat(ba-mission-plan): ground the service list inside the pipeline"
```

---

### Task 6: `QUICKSTART-ba.md`

**Files:**
- Modify: `src/strata_kb/templates/init/QUICKSTART-ba.md`
- Modify: `tests/test_cli_ticket_check.py` (one assertion string in `test_docs_name_the_check_command`)
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: the ticket recipe with SA grounding folded in as sub-step 7 of step 5 (the standalone step 6 is gone), a new `### Greenfield repos: what [NEW: D<n>] means` subsection, and a mission recipe naming *Ground services*.
- Consumes: the pipeline shape from Tasks 4 and 5.

- [ ] **Step 1a: Update the `## CLI reference` bullet and its PR 1 pin**

In `src/strata_kb/templates/init/QUICKSTART-ba.md`, replace:

```markdown
- `kb ticket check <file> [--hub <url>]` — run the SA grounding gate: every
  id in `## Technical grounding` must exist in the hub's `<repo>-code`
  document and `Open decisions` must be empty (`Grounding: PASS`)
```

with:

```markdown
- `kb ticket check <file> [--missions-dir <dir>] [--heading <h2>] [--hub <url>]`
  — run the SA grounding gate: every id in `## Technical grounding` must
  exist in the hub's `<repo>-code` document, every `[NEW: D<n>]` must name a
  `DECIDED` row of the parent mission's `## Technology decisions`
  (`--missions-dir`, default the sibling `missions/`), and `Open decisions`
  must be empty (`Grounding: PASS`). `--heading "## Services & order"`
  checks a mission plan's SA section against its own table
```

In `tests/test_cli_ticket_check.py::test_docs_name_the_check_command`, replace the one line

```python
    assert "- `kb ticket check <file> [--hub <url>]`" in quick
```

with

```python
    assert "- `kb ticket check <file> [--missions-dir <dir>] [--heading <h2>] [--hub <url>]`" in quick
```

Run: `uv run pytest tests/test_cli_ticket_check.py -q -k docs_name`
Expected: PASS.

- [ ] **Step 1: Write the failing test**

Append to the end of `tests/test_templates.py`:

```python
def test_quickstart_ba_folds_the_sa_step_into_the_pipeline():
    text = _normalised(_read_init_template("QUICKSTART-ba.md"))
    assert "Greenfield repos: what `[NEW: D<n>]` means" in text
    assert "7. **Ground technical**" in text
    assert "Ground services" in text
    assert "--missions-dir" in text
    # The manual step 6 is gone — the agent invokes the SA itself.
    assert "6. **Ground the technical half**" not in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_templates.py -q -k "quickstart_ba_folds"`
Expected: 1 failed — `AssertionError` on `"Greenfield repos: what \`[NEW: D<n>]\` means" in text`.

- [ ] **Step 3: Insert the new sub-step 7 and renumber**

Replace:

```markdown
   7. **Maturity review** — once lint reports `DoR: PASS`, it runs two
```

with:

```markdown
   7. **Ground technical** — it saves the draft and invokes
      `/sa-ticket-ground` on it as its own subagent. That fills the
      SA-owned `## Technical grounding` section from the hub's
      `<repo>-code` document (service, files, tables, routes, externals,
      test command — section ids only) and runs `kb ticket check` until
      it reports `Grounding: PASS`. You never fill that section
      yourself, and the SA never edits yours. Its `## Needs input` block
      comes back to you in the handover.
   8. **Maturity review** — once lint reports `DoR: PASS`, it runs two
```

Replace:

```markdown
   8. **Review → save** — it writes the draft to `tickets/<ticket-id>.md`
```

with:

```markdown
   9. **Review → save** — it writes the draft to `tickets/<ticket-id>.md`
```

- [ ] **Step 4: Delete the standalone step 6 and add the greenfield subsection**

Replace:

```markdown
6. **Ground the technical half** — invoke `/sa-ticket-ground
   tickets/<ticket-id>.md`. It fills the SA-owned `## Technical grounding`
   section from the hub's `<repo>-code` document (service, files, tables,
   routes, externals, test command — section ids only), parks what the
   document cannot prove under `Open decisions`, and runs
   `kb ticket check` until it reports `Grounding: PASS`. You never fill
   that section yourself, and the SA never edits yours. For a mission
   plan, `/sa-ticket-ground --mission missions/M-<slug>.md` fills
   `## Services & order` the same way.
```

with:

```markdown
Run `/sa-ticket-ground tickets/<ticket-id>.md` by hand only to re-ground
a ticket after `<repo>-code` has moved.

### Greenfield repos: what `[NEW: D<n>]` means

In a repo whose code is still a skeleton, most of what a ticket needs
does not exist yet. That is **not** missing data — it is a design
decision. The SA proposes it as a row in the parent mission's
`## Technology decisions` (status `OPEN`, a human owner) and writes
`[NEW: D<n>]` on the grounding line, pointing at that row.

`kb ticket check` verifies the reference: the row must exist and its
`Status` must be `DECIDED`. An `OPEN` row fails the gate and names its
owner — **you** decide and flip it to `DECIDED`; the SA never flips a
status. Pass `--missions-dir <dir>` when the missions do not sit in the
ticket's sibling `missions/` directory.

Only code that genuinely exists and the document cannot prove — internal
flow, failure modes, request bodies — belongs under `Open decisions` for
the Dev. A ticket with no parent mission has no table to point at and
keeps a free-text `[NEW: <reason>]`: the gate accepts it, but the
decision then has no owner.
```

- [ ] **Step 5: Name *Ground services* in the mission recipe**

Replace:

```markdown
1. `/ba-mission-plan` — the agent walks Intake → Ground → Draft →
   Split → Pin → Lint → Maturity review → Review and saves
   `missions/M-<slug>.md`.
```

with:

```markdown
1. `/ba-mission-plan` — the agent walks Intake → Ground → Draft →
   Split → Ground services → Pin → Lint → Maturity review → Review and
   saves `missions/M-<slug>.md`. At **Ground services** it invokes
   `/sa-ticket-ground --mission` itself: that fills the SA-owned
   `## Services & order` section and appends a `## Technology decisions`
   row for every service the mission will create.
```

- [ ] **Step 6: Run the template and init suites**

Run: `uv run pytest tests/test_templates.py tests/test_init.py tests/test_cli_ticket_check.py -q`
Expected: all PASS, including `test_quickstart_ba_points_at_code_knowledge`, `test_quickstart_ba_does_not_claim_ci_enforces_stale_refs`, `test_every_citation_example_is_bracketed[QUICKSTART-ba.md]` and `test_docs_name_the_check_command`.

- [ ] **Step 7: Run `detect_changes()` and commit**

```bash
git add src/strata_kb/templates/init/QUICKSTART-ba.md tests/test_templates.py tests/test_cli_ticket_check.py
git commit -m "docs(quickstart): fold SA grounding into the pipeline and explain [NEW: D<n>]"
```

---

### Task 7: the BA guides, English and Vietnamese

**Files:**
- Modify: `docs/src/guide-ba.en.md`
- Modify: `docs/src/guide-ba.vi.md`

**Interfaces:**
- Produces: a nine-step pipeline box, §3.8 describing the in-pipeline SA step plus `[NEW: D<n>]`, and §4.3 describing the in-pipeline mission step, in both languages.
- Consumes: the pipeline shape from Tasks 4 and 5.

**No test:** these two files are not package resources and no test reads them (they are PDF sources). Verification is `git diff` review plus the shared-content check in Step 5.

- [ ] **Step 1: `guide-ba.en.md` — the pipeline box**

Replace:

```markdown
Invoke `/ba-ticket-author` and describe the business need. The agent runs an
eight-step pipeline; your job is steps 1, 3 and 8.

```
  1 Intake            you describe the need
  2 Parent mission    optional — name the mission this story belongs to
  3 Ground            kb_search; YOU pick which sections apply
  4 Draft             story, ACs, use cases, two diagrams
  5 Pin               kb_context_new embeds the pinned block
  6 Lint              kb ticket lint until DoR: PASS
  7 Maturity review   two independent reviews, up to 3 rounds
  8 Review → save     you read it, commit it, paste it into the tracker
```
```

with:

```markdown
Invoke `/ba-ticket-author` and describe the business need. The agent runs a
nine-step pipeline; your job is steps 1, 3 and 9.

```
  1 Intake            you describe the need
  2 Parent mission    optional — name the mission this story belongs to
  3 Ground            kb_search; YOU pick which sections apply
  4 Draft             story, ACs, use cases, two diagrams
  5 Pin               kb_context_new embeds the pinned block
  6 Lint              kb ticket lint until DoR: PASS
  7 Ground technical  the SA fills Technical grounding; kb ticket check
  8 Maturity review   two independent reviews, up to 3 rounds
  9 Review → save     you read it, commit it, paste it into the tracker
```
```

- [ ] **Step 2: `guide-ba.en.md` — §3.8**

Replace:

```markdown
## 3.8 SA grounds the technical half

Once your draft is saved, hand it to the SA: `/sa-ticket-ground
tickets/<ticket-id>.md`. It fills the SA-owned `## Technical grounding`
section — service, files, tables, routes, externals, test command — each a
section id from the hub's `<repo>-code` document, or `[NEW: <reason>]`, or
parked under `Open decisions` when the document cannot prove it. It never
edits your sections; a business statement that contradicts the code facts is
quoted there, not corrected. `kb ticket check tickets/<ticket-id>.md` gates
it: PASS only when every id resolves and `Open decisions` is empty.
```

with:

```markdown
## 3.8 SA grounds the technical half

Step 7 runs this for you. Once lint reports `DoR: PASS`, the agent saves the
draft and invokes `/sa-ticket-ground` on it as its own subagent. It fills the
SA-owned `## Technical grounding` section — service, files, tables, routes,
externals, test command — each a section id from the hub's `<repo>-code`
document. It never edits your sections; a business statement that contradicts
the code facts is quoted there, not corrected.

Code that does not exist yet is not missing data, it is a design decision.
The SA proposes a row in the parent mission's `## Technology decisions`
(status `OPEN`, a human owner) and writes `[NEW: D<n>]` pointing at it. Only
code that exists and the document cannot prove — internal flow, failure
modes, request bodies — goes under `Open decisions` for the developer.

`kb ticket check tickets/<ticket-id>.md` gates it: PASS only when every id
resolves, every `[NEW: D<n>]` names a `DECIDED` row, and `Open decisions` is
empty. An `OPEN` row fails and names its owner — flipping it to `DECIDED` is
your call, never the agent's. The handover carries a `## Needs input` block
listing exactly those rows.

Run `/sa-ticket-ground` by hand only to re-ground a ticket after
`<repo>-code` has moved.
```

- [ ] **Step 3: `guide-ba.en.md` — §4.3 and the mission pipeline line**

Replace:

```markdown
The pipeline is **Intake → Ground → Draft → Split → Pin → Lint → Maturity
review → Review**, and it saves `missions/M-<slug>.md`.
```

with:

```markdown
The pipeline is **Intake → Ground → Draft → Split → Ground services → Pin →
Lint → Maturity review → Review**, and it saves `missions/M-<slug>.md`.
```

Replace:

```markdown
## 4.3 SA grounds the service list

Once you confirm the backlog, `/sa-ticket-ground --mission
missions/M-<slug>.md` fills `## Services & order` — one row per `svc.<name>`
from the hub's `<repo>-code` document, with `Depends on` copied from that
record. Capability layer only: no file names, no tables, no routes — those
belong to each ticket's own `## Technical grounding`, filled later at §3.8.
```

with:

```markdown
## 4.3 SA grounds the service list

Step 5 runs this for you. Once you confirm the backlog and `## Sequencing` is
filled, the agent invokes `/sa-ticket-ground --mission` and it fills
`## Services & order` — one row per `svc.<name>` from the hub's
`<repo>-code` document, with `Depends on` copied from that record. A service
the mission will create carries `[NEW: D<n>]`, pointing at a row the SA
appends to `## Technology decisions` for you to decide. Capability layer
only: no file names, no tables, no routes — those belong to each ticket's own
`## Technical grounding`, filled later at §3.8.
```

- [ ] **Step 4: `guide-ba.vi.md` — the same three edits, in Vietnamese**

Replace:

```markdown
Gọi `/ba-ticket-author` và mô tả nhu cầu nghiệp vụ. Agent chạy một pipeline tám
bước; phần việc của bạn là bước 1, 3 và 8.

```
  1 Intake            bạn mô tả nhu cầu
  2 Parent mission    tuỳ chọn — nêu mission mà story này thuộc về
  3 Ground            kb_search; CHÍNH BẠN chọn section nào áp dụng
  4 Draft             story, AC, use case, hai sơ đồ
  5 Pin               kb_context_new nhúng khối đã ghim
  6 Lint              kb ticket lint cho tới khi DoR: PASS
  7 Maturity review   hai lượt review độc lập, tối đa 3 vòng
  8 Review → save     bạn đọc, commit, dán vào hệ thống issue
```
```

with:

```markdown
Gọi `/ba-ticket-author` và mô tả nhu cầu nghiệp vụ. Agent chạy một pipeline chín
bước; phần việc của bạn là bước 1, 3 và 9.

```
  1 Intake            bạn mô tả nhu cầu
  2 Parent mission    tuỳ chọn — nêu mission mà story này thuộc về
  3 Ground            kb_search; CHÍNH BẠN chọn section nào áp dụng
  4 Draft             story, AC, use case, hai sơ đồ
  5 Pin               kb_context_new nhúng khối đã ghim
  6 Lint              kb ticket lint cho tới khi DoR: PASS
  7 Ground technical  SA điền Technical grounding; kb ticket check
  8 Maturity review   hai lượt review độc lập, tối đa 3 vòng
  9 Review → save     bạn đọc, commit, dán vào hệ thống issue
```
```

Replace:

```markdown
## 3.8 SA ghim phần kỹ thuật

Khi bản nháp đã lưu, hãy chuyển cho SA: `/sa-ticket-ground
tickets/<ticket-id>.md`. Lệnh này điền mục `## Technical grounding` do SA sở
hữu — service, file, bảng, route, external, lệnh test — mỗi dòng là một
section id lấy từ tài liệu `<repo>-code` trên hub, hoặc `[NEW: <lý do>]`,
hoặc được gác lại dưới `Open decisions` khi tài liệu không chứng minh được.
Nó không bao giờ sửa mục của bạn; một phát biểu nghiệp vụ mâu thuẫn với sự
thật trong code sẽ được trích lại ở đó, không bị sửa. `kb ticket check
tickets/<ticket-id>.md` là cổng: PASS chỉ khi mọi id phân giải được và
`Open decisions` rỗng.
```

with:

```markdown
## 3.8 SA ghim phần kỹ thuật

Bước 7 làm việc này thay bạn. Khi lint báo `DoR: PASS`, agent lưu bản nháp
rồi gọi `/sa-ticket-ground` trên chính file đó như một subagent riêng. Lệnh
này điền mục `## Technical grounding` do SA sở hữu — service, file, bảng,
route, external, lệnh test — mỗi dòng là một section id lấy từ tài liệu
`<repo>-code` trên hub. Nó không bao giờ sửa mục của bạn; một phát biểu
nghiệp vụ mâu thuẫn với sự thật trong code sẽ được trích lại ở đó, không bị
sửa.

Code chưa tồn tại không phải là thiếu dữ liệu, mà là một quyết định thiết
kế. SA đề xuất nó thành một dòng trong `## Technology decisions` của mission
cha (trạng thái `OPEN`, chủ sở hữu là một con người) và ghi `[NEW: D<n>]` trỏ
tới dòng đó. Chỉ những gì code đã có mà tài liệu không chứng minh được —
luồng nội bộ, tình huống lỗi, thân request — mới được gác dưới
`Open decisions` cho lập trình viên.

`kb ticket check tickets/<ticket-id>.md` là cổng: PASS chỉ khi mọi id phân
giải được, mọi `[NEW: D<n>]` trỏ tới một dòng `DECIDED`, và `Open decisions`
rỗng. Một dòng `OPEN` làm fail cổng và nêu tên chủ sở hữu — đổi nó sang
`DECIDED` là quyết định của bạn, không bao giờ của agent. Bản bàn giao mang
theo khối `## Needs input` liệt kê đúng những dòng đó.

Chỉ chạy `/sa-ticket-ground` bằng tay khi cần ghim lại một ticket sau lúc
`<repo>-code` đã thay đổi.
```

Replace:

```markdown
Pipeline là **Intake → Ground → Draft → Split → Pin → Lint → Maturity review →
Review**, và lưu ra `missions/M-<slug>.md`.
```

with:

```markdown
Pipeline là **Intake → Ground → Draft → Split → Ground services → Pin → Lint →
Maturity review → Review**, và lưu ra `missions/M-<slug>.md`.
```

Replace:

```markdown
## 4.3 SA điền danh sách service

Khi bạn đã xác nhận backlog, `/sa-ticket-ground --mission
missions/M-<slug>.md` điền `## Services & order` — mỗi dòng một `svc.<name>`
lấy từ tài liệu `<repo>-code` trên hub, cột `Depends on` chép từ chính record
đó. Chỉ ở lớp năng lực: không tên file, không bảng, không route — những cái
đó thuộc về `## Technical grounding` của từng ticket, điền sau ở mục 3.8.
```

with:

```markdown
## 4.3 SA điền danh sách service

Bước 5 làm việc này thay bạn. Khi bạn đã xác nhận backlog và `## Sequencing`
đã điền, agent gọi `/sa-ticket-ground --mission` và nó điền
`## Services & order` — mỗi dòng một `svc.<name>` lấy từ tài liệu
`<repo>-code` trên hub, cột `Depends on` chép từ chính record đó. Service mà
mission sẽ tạo mới mang `[NEW: D<n>]`, trỏ tới một dòng SA thêm vào
`## Technology decisions` để bạn quyết định. Chỉ ở lớp năng lực: không tên
file, không bảng, không route — những cái đó thuộc về `## Technical
grounding` của từng ticket, điền sau ở mục 3.8.
```

- [ ] **Step 5: Verify both guides agree on the load-bearing strings**

Run:

```bash
grep -c "Ground technical" docs/src/guide-ba.en.md docs/src/guide-ba.vi.md
grep -c "Ground services" docs/src/guide-ba.en.md docs/src/guide-ba.vi.md
grep -c "\[NEW: D<n>\]" docs/src/guide-ba.en.md docs/src/guide-ba.vi.md
grep -c "## Needs input" docs/src/guide-ba.en.md docs/src/guide-ba.vi.md
```

Expected: `2` / `2` / `2` / `1` for the English file and `2` / `2` / `2` / `1` for the Vietnamese file (the pipeline box plus the section body; `Ground services` in the pipeline line plus §4.3).

- [ ] **Step 6: Run the full suite and commit**

Run: `uv run pytest -q`
Expected: all PASS (no test reads these files; this is the regression net before the docs commit).

```bash
git add docs/src/guide-ba.en.md docs/src/guide-ba.vi.md
git commit -m "docs(guide-ba): SA grounding is step 7 now, and [NEW: D<n>] for greenfield"
```

---

### Task 8: strike the superseded follow-up and record the change

**Files:**
- Modify: `docs/superpowers/specs/2026-09-20-sa-grounding-design.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: §9's first bullet struck and pointed at the newer spec; one `## Unreleased` bullet covering PR 2.
- Consumes: everything above.

- [ ] **Step 1: Strike the §9 follow-up**

In `docs/superpowers/specs/2026-09-20-sa-grounding-design.md`, replace:

```markdown
- Auto-invoking SA after BA (hook or pipeline) — manual until the flow is
  stable.
```

with:

```markdown
- ~~Auto-invoking SA after BA (hook or pipeline) — manual until the flow is
  stable.~~ Superseded 2026-09-22 by
  `2026-09-22-sa-greenfield-grounding-design.md` §4 (decision G4):
  `sa-ticket-ground` now runs inside `ba-ticket-author` (step 7) and
  `ba-mission-plan` (step 5).
```

- [ ] **Step 2: Extend the `## Unreleased` entry**

In `CHANGELOG.md`, replace:

```markdown
- `kb ticket check` verifies `[NEW: D<n>]` markers against the parent mission's `## Technology decisions`: the row must exist and be `DECIDED` (an `OPEN` row fails, naming its owner). Greenfield tickets ground code that does not exist yet through a decided design row instead of parking it under `Open decisions`. New `--missions-dir` (default: the sibling `missions/`, as `kb ticket lint`) and `--heading "## Services & order"` to check a mission plan's SA section against its own table.

## 1.1.0 — 2026-09-21
```

with:

```markdown
- `kb ticket check` verifies `[NEW: D<n>]` markers against the parent mission's `## Technology decisions`: the row must exist and be `DECIDED` (an `OPEN` row fails, naming its owner). Greenfield tickets ground code that does not exist yet through a decided design row instead of parking it under `Open decisions`. New `--missions-dir` (default: the sibling `missions/`, as `kb ticket lint`) and `--heading "## Services & order"` to check a mission plan's SA section against its own table.
- BA repos: `/sa-ticket-ground` now runs **inside** the BA pipelines — `ba-ticket-author` step 7 (Ground technical, after `DoR: PASS`) and `ba-mission-plan` step 5 (Ground services, after the backlog is confirmed) — instead of being a manual follow-up, and its handover ends with a fixed `## Needs input` block naming every decision still waiting for a human. The SA proposes an `OPEN` row in the parent mission's `## Technology decisions` for anything the code does not have yet and references it as `[NEW: D<n>]`; only a human flips `OPEN` to `DECIDED`. Ticket and mission templates, the review rubric, `QUICKSTART-BA.md` and both BA guides updated to match. Re-run `kb init --kind ba` to pick up the new skill and template text.

## 1.1.0 — 2026-09-21
```

- [ ] **Step 3: Confirm no version bump crept in**

Run: `git diff main...HEAD --stat -- pyproject.toml uv.lock`
Expected: empty output.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS. `tests/test_cli_ticket_check.py::test_docs_name_the_check_command` reads the CHANGELOG — the `` `kb ticket check <file>` `` string it needs lives in the 1.0.2 entry and is untouched.

- [ ] **Step 5: Run `detect_changes()` and commit**

Run `detect_changes()` via the GitNexus MCP; confirm no Python symbol is listed for the whole PR.

```bash
git add CHANGELOG.md docs/superpowers/specs/2026-09-20-sa-grounding-design.md
git commit -m "docs: strike auto-invoking SA from the 2026-09-20 follow-ups; CHANGELOG"
```

---

## Self-review against spec

| Spec item | Task |
|---|---|
| §3 Intake reads the parent mission's `## Technology decisions` | 3 (Step 3) |
| §3 Fill — the three-way resolution, appended D-row, degradation without a mission | 3 (Step 4) |
| §3 Gate — `kb ticket check <file> [--missions-dir <dir>]`, `--heading "## Services & order"`, OPEN row is a reported FAIL | 3 (Step 6) |
| §3 Handover — the fixed `## Needs input` block, verbatim | 3 (Step 7) |
| §3 the two new hard rules, verbatim, byte-identical across the SA wrappers | 3 (Steps 8–9, test in Step 1) |
| §4 `ba-ticket-author` step 6b *Ground technical* as its own subagent | 4 (Steps 4, 10; shipped as step `7.` — see the numbering note) |
| §4 maturity review receives the technical half; re-check each changed round, re-ground only on FAIL | 4 (Steps 5–6, 11–12) |
| §4 handover carries `## Needs input` verbatim | 4 (Steps 7, 12, 15) |
| §4 `ba-ticket-author` hard-rule edit | 4 (Steps 8, 12, 15) |
| §4 `ba-mission-plan` step 4b *Ground services* after the backlog and `## Sequencing` | 5 (Step 3; shipped as step `5.`) |
| §4 `ba-mission-plan` reviewer receives `## Services & order` | 5 (Step 5) |
| §4 review rubric — the new Dev-implementability checklist item | 2 |
| §5 `ticket-template.md` comment gains the `[NEW: D<n>]` rule | 1 (Step 3) |
| §5 `mission-template.md` `## Technology decisions` comment + second example row | 1 (Step 4) |
| §5 `## Services & order` comment and example row use `[NEW: D<n>]` | 1 (Step 5) |
| §5 `QUICKSTART-ba.md` — step 6 folds in, new greenfield subsection | 6 |
| §5 `docs/src/guide-ba.{en,vi}.md` §3.8 / §4.3 | 7 |
| §5 README command table row | done in PR 1 — out of scope here |
| §6.3 needles: `[NEW: D` in both templates and the four SA wrappers | 1 (Step 1), 3 (Step 1) |
| §6.3 needles: `## Needs input` in the four SA wrappers | 3 (Step 1) |
| §6.3 needles: `Ground technical` in the four `ba-ticket-author` wrappers | 4 (Step 1) |
| §6.3 needles: `Ground services` in the four `ba-mission-plan` wrappers | 5 (Step 1) |
| §6.3 hard-rules block identical across the SA wrappers | 3 (Step 1) |
| §6.3 copilot/cursor differ only on frontmatter line 2 | 5 (Step 10) |
| §6.3 rubric carries the new checklist item | 2 (Step 1) |
| §7 PR 2 scope: 4 SA + 8 BA wrappers, 2 templates, rubric, quickstart, both guides, template tests | Tasks 1–7 |
| §7 strike "Auto-invoking SA after BA" in the 2026-09-20 spec §9 | 8 (Step 1) |
| §7 no version bump; CHANGELOG under `## Unreleased` | Global Constraints; 8 (Steps 2–3) |

### Deliberate deviations

1. **"6b" and "4b" ship as ordinary numbered steps.** Markdown ordered lists cannot carry `6b.` as a list item and these files are read as prose by an agent, so `ba-ticket-author` becomes a nine-step list (new `7. Ground technical`) and `ba-mission-plan` a nine-step list (new `5. Ground services`). The pipeline *order* is exactly the spec's. The guides, the quickstart and the pipeline description lines are renumbered to match, which the spec does not mention but a stale "eight-step pipeline" sentence would contradict the wrapper.
2. **The byte-identical hard-rules test covers three SA wrappers, not four.** `claude-command-sa-ticket-ground.md` has no `## Hard rules` heading — it is a thin skill invoker that summarises the rules in prose, a shape `test_every_landed_claude_command_is_a_skill_invoker` already depends on. The existing `SA_FULL_WRAPPERS` constant names exactly the three that carry the block; the needle tests (`[NEW: D`, `## Needs input`, the gate flags) still cover all four.
3. **`claude-skill-sa-ticket-ground.md` and `cursor-sa-ticket-ground.md` are kept byte-identical in full**, not just in the hard-rules block — that is their state today, and Task 3 derives cursor from the skill rather than re-typing prose. A new test pins it so the next edit cannot silently fork them.
4. **The ticket template's `Files:` example row also moves to `[NEW: D<n>]`.** Spec §5 mandates this only for the mission's `## Services & order` row, but leaving the ticket template's one example on the free-text form teaches the shape the gate now nudges against; the comment keeps `No parent mission → [NEW: <reason>]` as the documented fallback.
5. **`QUICKSTART-ba.md`'s `## CLI reference` bullet gains the two flags, and the PR 1 pin in `tests/test_cli_ticket_check.py::test_docs_name_the_check_command` is updated to the new string** (Task 6 Step 1a) — the one edit this PR makes to a PR 1 test file; a CLI reference that omits the flags the recipe tells the SA to pass would contradict the greenfield subsection.
6. **The PDFs under `docs/` are not regenerated.** `docs/src/build_pdf.py` needs macOS system fonts and is run by hand at release; PR #62 (`b02ae92`), the previous guide-only change, updated the two `.md` sources only.
7. **The SA skill's Gate step quotes the engine's real messages** (from PR 1's `ticketcheck._judge_new`) rather than paraphrasing them, and a test pins that. The spec describes the reactions but not the wording; matching the literal output is what makes the instruction findable when the SA reads a FAIL.
8. **Fix wave 1 reworded copilot/cursor step 7 in their own dialect** (no subagent concept there — "run `/sa-ticket-ground` ... as a separate run" instead of "invoke ... as its own subagent") and moved the test needle that pins the subagent wording onto the Claude skill alone.
9. **Fix wave 1 item B gated step 8 on `Grounding: PASS` — reverted in fix wave 2.** An `OPEN` D-row is a hard error the SA may never flip (G2), so `sa-ticket-ground` can never report `Grounding: PASS` on a greenfield ticket; gating step 8 on it deadlocked the pipeline. Fix wave 2 item 1 reverts step 8's trigger to `once lint reports `DoR: PASS`` and softens step 7's tail so an `OPEN` row is a reported FAIL routed to `## Needs input`, not a blocker.
10. **Fix wave 1 named the step-7 save path** (`tickets/<ticket-id>.md`, previously just "save the draft") and added the no-shared-context clause to the re-ground loop in step 8's FAIL branch; fix wave 2 item 4 relocates that clause onto the parenthetical it belongs with.
11. **`BA_TICKET_AUTHOR_PIPELINE_STEPS` now lists nine steps** (`Ground technical` and `Maturity review` split out, `Review → save` renamed), and the command wrapper's `Pipeline:` one-line summary gained the literal `→ save` suffix to match the skill's step name.
