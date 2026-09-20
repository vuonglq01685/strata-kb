# SA grounding layer — PR 1 (templates, skill, BA wrapper edits) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the SA-owned `## Technical grounding` (ticket) and `## Services & order` (mission) sections, the `sa-ticket-ground` skill in its four wrapper forms, and turn the BA skills into pure business writers that hand code detail to the SA — all as package resources laid out by `kb init --kind ba`.

**Architecture:** Everything a BA repo gets is a package resource under `src/strata_kb/templates/init/` mapped by `initcmd.BA_TEMPLATES`. This PR adds four SA wrapper resources to that map, edits the two document templates and the eight existing BA wrappers in place, and adds one heading to `ticket.RECOMMENDED_HEADINGS` (warning-level in `kb ticket lint`; legacy tickets keep passing). No engine code beyond that one constant. The `kb ticket check` gate is PR 2.

**Tech Stack:** Python 3.11+ (typer CLI already present), pytest, Markdown templates, `uv` lockfile.

**Spec:** `docs/superpowers/specs/2026-09-20-sa-grounding-design.md` (§2 decisions A1–A6, §3 ticket section, §4 mission section, §5 SA skill, §6 BA skill edits, §8 rollout PR 1).

## Global Constraints

- Templates and skill text in English; headings are the lint contract and are never localized.
- `ticket.REQUIRED_HEADINGS` is a compatibility contract — do not touch it. Only `RECOMMENDED_HEADINGS` changes (+1 entry).
- No new extractor. `src/strata_kb/mdutils.py` is frozen — never edit it.
- **NEVER bump the version.** `pyproject.toml` (`version = "1.0.1"`) and `uv.lock` are not touched by this PR. The CHANGELOG entry goes under an `## Unreleased` heading. No new dependency.
- The four `ba-mission-plan` wrappers must stay byte-identical from `## Workflow` to end of file (`tests/test_init.py::test_mission_wrapper_workflow_bodies_are_byte_identical`). Apply every mission-wrapper edit to all four identically.
- No template or wrapper may carry a bare `doc-id §section` citation outside a fence (`tests/test_templates.py::test_every_citation_example_is_bracketed`). Never type `§` in the new SA text.
- The ticket template's `## Technical grounding` has **no** `Flow` field and **no** `Failure modes` field — deliberate (spec §3).
- Before editing `BA_TEMPLATES` or `RECOMMENDED_HEADINGS`: impact was run 2026-09-20 (`risk: UNKNOWN`, zero graph callers) and confirmed by text search: `BA_TEMPLATES` is read by `initcmd.template_map` and `tests/test_templates.py`; `RECOMMENDED_HEADINGS` by `ticketlint.lint` (via `check_recommended_sections`), `tests/test_ticketlint.py`, `tests/test_mission_ticket_traceability.py`. Both changes are additive.
- Windows dev box: run Python as `.venv/Scripts/python.exe`; `uv` lives at `C:/Users/Admin/.local/bin/uv.exe` (not on PATH). Commit messages via `git commit -F <file>` (see memory: heredoc `-m` breaks on this box).
- Hooks deny `grep`/`ls`/`find`/`git log` in Bash. Use Read, `git ls-files <pathspec>`, `git rev-parse`, or a short Python script for text search.

---

## File map

| File | Action | Owner task |
|---|---|---|
| `src/strata_kb/templates/init/ticket-template.md` | insert `## Technical grounding` before `## Open questions`; add one DoR line | 1 |
| `src/strata_kb/ticket.py` | `RECOMMENDED_HEADINGS` += `"## Technical grounding"` | 1 |
| `tests/test_ticketlint.py` | `ALL_HEADINGS` + `_default_sections` gain the new section | 1 |
| `tests/test_mission_ticket_traceability.py` | `_real_ticket_text` sections gain the new key | 1 |
| `src/strata_kb/templates/init/mission-template.md` | insert `## Services & order` after `## Sequencing` | 2 |
| `src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md` | create | 3 |
| `src/strata_kb/templates/init/claude-command-sa-ticket-ground.md` | create | 3 |
| `src/strata_kb/templates/init/copilot-sa-ticket-ground.prompt.md` | create | 3 |
| `src/strata_kb/templates/init/cursor-sa-ticket-ground.md` | create | 3 |
| `src/strata_kb/initcmd.py` | `BA_TEMPLATES` +4 rows | 3 |
| `tests/test_templates.py` | new SA tests; `SA_WRAPPERS`; `_CITATION_TEMPLATES` += SA; replace the six D1 BA-wrapper tests | 3, 4 |
| 4 × `*-ba-ticket-author*` wrappers | strip code grounding, add hand-off bullet + Draft-step sentence | 4 |
| 4 × `*-ba-mission-plan*` wrappers | same, mission variant | 5 |
| `src/strata_kb/templates/init/QUICKSTART-ba.md` | new step 6; rewrite "Code knowledge on the hub" | 6 |
| `tests/test_init.py` | `test_quickstart_ba_points_at_code_knowledge` +2 needles | 6 |
| `README.md` | slash-command list; §12 SA paragraph | 6 |
| `CHANGELOG.md` | new `## Unreleased` entry (no version bump) | 6 |

---

### Task 1: Ticket template — `## Technical grounding` + `RECOMMENDED_HEADINGS`

**Files:**
- Modify: `src/strata_kb/templates/init/ticket-template.md` (insert before line 68 `## Open questions`; add a line under `## Definition of Ready`, currently lines 82–88)
- Modify: `src/strata_kb/ticket.py:34-41`
- Modify: `tests/test_ticketlint.py:26-43` (`ALL_HEADINGS`) and `:59-131` (`_default_sections`)
- Modify: `tests/test_mission_ticket_traceability.py:195-212` (the `sections` dict in `_real_ticket_text`)
- Test: `tests/test_templates.py` (append), `tests/test_ticketlint.py`

**Interfaces:**
- Produces: `ticket.RECOMMENDED_HEADINGS` now contains `"## Technical grounding"` between `"## Test data & verification"` and `"## Open questions"`. Tasks 4 and 6 rely on the heading string `## Technical grounding` verbatim.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_templates.py`:

```python
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
    assert text.index("## Technical grounding") < text.index("## Open questions")


def test_ticket_template_has_no_flow_or_failure_mode_field():
    # Spec §3: deliberately absent — the code document cannot prove them.
    body = lintcore.section_body(
        _read_init_template("ticket-template.md"), "## Technical grounding"
    )
    assert "- Flow:" not in body
    assert "- Failure modes:" not in body


def test_ticket_template_dor_names_the_grounding_gate():
    text = _read_init_template("ticket-template.md")
    dor = lintcore.section_body(text, "## Definition of Ready")
    assert "Technical grounding filled by SA" in dor
    assert "kb ticket check PASS" in dor


def test_technical_grounding_is_a_recommended_heading():
    from strata_kb import ticket

    assert "## Technical grounding" in ticket.RECOMMENDED_HEADINGS
    assert "## Technical grounding" not in ticket.REQUIRED_HEADINGS
    order = list(ticket.RECOMMENDED_HEADINGS)
    assert order.index("## Technical grounding") == order.index("## Open questions") - 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_templates.py -q -k "technical_grounding or flow_or_failure or grounding_gate"`
Expected: 4 FAILED (`count == 0`, `body is None`, heading not in `RECOMMENDED_HEADINGS`).

- [ ] **Step 3: Insert the section into `ticket-template.md`** — directly above the line `## Open questions` (currently line 68), paste verbatim:

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
- Tables: db.<table>.<column>, … — or `none`
- Routes: api.<tag> — <METHOD> <path>, … — or `none`
- Externals: int.<name>, … — or `none`
- Verify with: cmd.test — `<primary command, verbatim>`
- Open decisions:
  - none

```

Then in `## Definition of Ready`, after the line `- [ ] Every open question has an owner`, add:

```markdown
- [ ] Technical grounding filled by SA; kb ticket check PASS (Open decisions empty)
```

- [ ] **Step 4: Add the heading to `RECOMMENDED_HEADINGS`** in `src/strata_kb/ticket.py`:

```python
RECOMMENDED_HEADINGS: tuple[str, ...] = (
    "## Dependencies",
    "## Non-functional requirements",
    "## UI / presentation spec",
    "## Out of scope",
    "## Test data & verification",
    "## Technical grounding",   # SA-owned (spec 2026-09-20-sa-grounding-design §3)
    "## Open questions",
)
```

- [ ] **Step 5: Update the two ticket fixtures so golden tickets keep passing**

`tests/test_ticketlint.py` — in `ALL_HEADINGS`, insert `"## Technical grounding",` between `"## Test data & verification",` and `"## Open questions",`. In `_default_sections`, add this key right after `"## Test data & verification"`:

```python
        "## Technical grounding": (
            "- Grounded on: demo:demo-code @ c12b24f\n"
            "- Service: svc.airspace-service\n"
            "- Files:\n"
            "  - src/airspace/service.py\n"
            "- Tables: db.restrictive_airspace.designation\n"
            "- Routes: none\n"
            "- Externals: none\n"
            "- Verify with: cmd.test — `pytest -q --cov=airspace`\n"
            "- Open decisions:\n"
            "  - none"
        ),
```

`tests/test_mission_ticket_traceability.py` — in the `sections` dict inside `_real_ticket_text`, add the same key/value right after `"## Test data & verification"` (the dict is iterated by `ticket.RECOMMENDED_HEADINGS`, so a missing key is a `KeyError`).

- [ ] **Step 6: Run the affected suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_templates.py tests/test_ticketlint.py tests/test_mission_ticket_traceability.py -q`
Expected: all PASS. In particular `test_golden_ticket_passes` (no "recommended section missing" warning), `test_legacy_nine_section_ticket_still_passes` (count derives from `len(RECOMMENDED_HEADINGS)`), `test_template_carries_every_recommended_heading` (heading appears exactly once — the DoR line says "Technical grounding filled by SA", not the `## ` heading).

- [ ] **Step 7: Commit**

```bash
printf '%s\n' 'feat(ba): add SA-owned "Technical grounding" section to the ticket template' '' 'Recommended heading (warning-level in kb ticket lint); legacy tickets keep passing.' > /tmp/msg.txt
git add src/strata_kb/templates/init/ticket-template.md src/strata_kb/ticket.py tests/test_templates.py tests/test_ticketlint.py tests/test_mission_ticket_traceability.py
git commit -F /tmp/msg.txt
```

---

### Task 2: Mission template — `## Services & order`

**Files:**
- Modify: `src/strata_kb/templates/init/mission-template.md` (insert after the `## Sequencing` table, before `## Open questions`, currently line 68)
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Produces: heading string `## Services & order` and the table header `| Order | Service | Depends on | Why this order |`, referenced verbatim by Task 5 and Task 6.

- [ ] **Step 1: Write the failing test** — append to `tests/test_templates.py`:

```python
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
    assert text.index("## Sequencing") < text.index("## Services & order") < text.index("## Open questions")


def test_mission_required_headings_are_untouched_by_services_and_order():
    from strata_kb import mission

    assert "## Services & order" not in mission.REQUIRED_MISSION_HEADINGS
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_templates.py -q -k services_and_order`
Expected: 1 FAILED (`count == 0`), 1 PASSED (untouched-headings guard).

- [ ] **Step 3: Insert the section** — directly above `## Open questions` in `mission-template.md`, paste verbatim:

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

```

- [ ] **Step 4: Run the mission suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_templates.py tests/test_missionlint.py tests/test_cli_mission.py tests/test_init.py -q -k "mission or services_and_order"`
Expected: all PASS (mission lint's required-heading list is untouched; the new section is extra prose).

- [ ] **Step 5: Commit**

```bash
printf '%s\n' 'feat(ba): add SA-owned "Services & order" section to the mission template' > /tmp/msg.txt
git add src/strata_kb/templates/init/mission-template.md tests/test_templates.py
git commit -F /tmp/msg.txt
```

---

### Task 3: The `sa-ticket-ground` skill — four wrappers + `BA_TEMPLATES`

**Files:**
- Create: `src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md`
- Create: `src/strata_kb/templates/init/claude-command-sa-ticket-ground.md`
- Create: `src/strata_kb/templates/init/copilot-sa-ticket-ground.prompt.md`
- Create: `src/strata_kb/templates/init/cursor-sa-ticket-ground.md`
- Modify: `src/strata_kb/initcmd.py:87-109` (`BA_TEMPLATES`)
- Test: `tests/test_templates.py` (define `SA_WRAPPERS` next to `BA_WRAPPERS` at ~line 1215; extend `_CITATION_TEMPLATES` at ~line 1843; append tests)

**Interfaces:**
- Consumes: `initcmd.BA_TEMPLATES` (dict `target path -> resource name`), `initcmd.expected_files(kind)`.
- Produces: skill name `sa-ticket-ground`; command `/sa-ticket-ground <file> [--mission]`. Tasks 4–6 reference `/sa-ticket-ground` verbatim.

- [ ] **Step 1: Write the failing tests**

In `tests/test_templates.py`, right after the `BA_WRAPPERS = (...)` tuple (~line 1224), add:

```python
SA_WRAPPERS = (
    "claude-skill-sa-ticket-ground.md",
    "claude-command-sa-ticket-ground.md",
    "copilot-sa-ticket-ground.prompt.md",
    "cursor-sa-ticket-ground.md",
)
# The three full-content forms; the command wrapper is a thin skill invoker.
SA_FULL_WRAPPERS = (SA_WRAPPERS[0], SA_WRAPPERS[2], SA_WRAPPERS[3])
```

In `_CITATION_TEMPLATES` (~line 1843) add `*SA_WRAPPERS,` after `*BA_WRAPPERS,`.

Append at the end of the file:

```python
# --- SA grounding layer (PR 1): the sa-ticket-ground wrappers ---------------


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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_templates.py -q -k "sa_"`
Expected: FAILED on `is_file()` / `KeyError` / `FileNotFoundError`.

- [ ] **Step 3: Create `claude-skill-sa-ticket-ground.md`** with exactly this content:

````markdown
---
name: sa-ticket-ground
description: Fill the SA-owned "Technical grounding" section of a BA ticket (or "Services & order" of a mission plan) from the hub's <repo>-code document — section ids only, no inference. Use when a ticket has its business sections drafted and needs its technical half, or when the BA invokes /sa-ticket-ground.
---

# sa-ticket-ground — ground a ticket's technical half in the code document

You fill ONE section the BA never touches: `## Technical grounding` in a
ticket, or `## Services & order` in a mission plan (with `--mission`).
Your only source is the hub's `<repo>-code` document. You have **no
repository access** and you never read source code. You are **not a
reviewer** of the BA's work: you fill a different section, you do not
score it.

The argument is the ticket (or mission) file path; `--mission` switches
to the mission layer.

## Workflow

1. **Intake** — read the document. Identify the product repo id
   (`<repo-id>`) from the BA's input or the parent mission. Collect every
   `%%TODO: verify against codebase%%` in the BA-owned sections: these
   are the questions this pass must answer with an id or park under
   `Open decisions`.
2. **Load** — from `<repo-id>-code` on the hub only, via the MCP tool
   `kb_get_section` (fallback: `kb get <repo-id>-code <section-id>`),
   discovering ids with `kb_search` (fallback: `kb query`) restricted to
   that document. For a ticket: `struct.tree` (L3 for the file list),
   every `svc.*`, `cmd.test`, and the `db.*` / `api.*` / `int.*` sections
   whose names match the ticket's nouns. For a mission (`--mission`):
   `svc.*`, `dep.*`, `struct.tree` and the architecture document on the
   hub — do **not** load `db.*` or `api.*`; they pull the plan down to the
   wrong layer. Note the document's revision: `kb get` prints it in the
   citation `(<revision>)` and `kb_get_section` returns it — that value
   goes on the `Grounded on:` line.
3. **Fill** — write the section from the loaded sections and nothing
   else, field by field:
   - `Grounded on: <repo-id>:<repo-id>-code @ <revision>` — first line.
   - `Service:` — `svc.<name>` ids as the document spells them (a name
     over 40 characters carries an opaque 6-hex-character suffix; copy
     it, never retype it). The record has no directory field — a
     directory, when needed, is a `Files:` entry.
   - `Files:` — one path per sub-bullet, spelled exactly as `struct.tree`
     lists it. `struct.tree` stops at depth 4 and 600 lines: list the
     deepest directory it shows rather than a path you cannot see. A
     file the ticket will create: `<path> [NEW: <why it does not exist
     yet>]`.
   - `Tables:` — `db.<table>.<column>`, the column spelled as the table's
     `Column` cell. `none` when the ticket touches no table the document
     knows.
   - `Routes:` — `api.<tag> — <METHOD> <path>` copied from the tag's
     table. `none` when the document has no `api.*` for it.
   - `Externals:` — `int.<name>` ids, or `none`.
   - `Verify with:` — `cmd.test — \`<command>\``, the section's
     `Primary:` value or one of its alternatives, byte for byte.
   - `Open decisions:` — every question the document cannot answer,
     quoted in the BA's own words when it comes from a placeholder:
     internal flow, failure modes, request/response bodies, a table or
     route the BA assumed and the document lacks, a business statement
     that contradicts the code facts. `none` only when the list is empty.
   For a mission, the same discipline fills `## Services & order`: one
   row per `svc.<name>`, `Depends on` copied from the record, the reason
   citing that dependency; no files, no tables, no routes.
   Each BA placeholder is answered by an id here or parked here; the
   placeholder itself stays in the BA section untouched — the Dev reads
   the answer from this section.
4. **Gate** — run `kb ticket check <file>` (CLI; there is no MCP
   fallback). Fix every `[error]` and re-run until it prints
   `Grounding: PASS`. A non-empty `Open decisions` is a FAIL by design:
   report the list to the BA instead of emptying it by guessing. If the
   installed `kb` has no `ticket check` command yet, verify every id by
   hand against the document's `_manifest.yaml` section list and say in
   the handover that the gate did not run.
5. **Handover** — report: the ids grounded, the `[NEW]` entries, the
   open decisions (count and text), the BA placeholders answered, and any
   BA-section contradiction found. The BA decides what goes back to the
   business side and what goes to the Dev.

## Hard rules

- Every line in `## Technical grounding` must either
  - point at a section id that exists in the `<repo>-code` document, OR
  - carry `[NEW: <reason>]` saying why it does not exist yet, OR
  - go under `Open decisions`.
- No data → `Open decisions`. Never infer; never fill from a generic
  pattern or from what "a service like this usually has".
- Never edit a BA-owned section. A business statement that contradicts
  the code facts goes under `Open decisions`, quoted, not corrected.
- The first line is `Grounded on: <repo-id>:<doc-id> @ <revision>`,
  copied from the document's own manifest revision. Ground only on the
  hub's copy — a document you cannot find on the hub is not a source.
- Never write internal flow; never write failure modes — the document
  cannot prove either. Those questions go to `Open decisions` for the
  Dev, who has the code and GitNexus.
- `kb ticket check` failing to RUN is not a PASS. No CLI → tell the BA
  to install `strata-kb`; never hand over an unchecked section as
  checked.
- Never tick a Definition of Ready checkbox; only the BA confirms DoR.
- English headings stay English; write the section's free text in the
  BA's working language.
````

- [ ] **Step 4: Create the copilot and cursor forms** — identical to the skill file from the line `# sa-ticket-ground — ground …` onward (copy the body byte for byte). Only the frontmatter differs:

`copilot-sa-ticket-ground.prompt.md` starts:

```markdown
---
mode: agent
description: Fill the SA-owned "Technical grounding" section of a BA ticket (or "Services & order" of a mission plan) from the hub's <repo>-code document — section ids only, no inference. Use when a ticket has its business sections drafted and needs its technical half, or when the BA invokes /sa-ticket-ground.
---
```

`cursor-sa-ticket-ground.md` starts:

```markdown
---
name: sa-ticket-ground
description: Fill the SA-owned "Technical grounding" section of a BA ticket (or "Services & order" of a mission plan) from the hub's <repo>-code document — section ids only, no inference. Use when a ticket has its business sections drafted and needs its technical half, or when the BA invokes /sa-ticket-ground.
---
```

(The cursor frontmatter is therefore identical to the skill's, so all three bodies after `---\n` match.)

- [ ] **Step 5: Create `claude-command-sa-ticket-ground.md`**:

```markdown
---
description: Fill the SA-owned "Technical grounding" section of a BA ticket (or "Services & order" of a mission plan) from the hub's <repo>-code document, via the sa-ticket-ground skill
argument-hint: "<ticket-or-mission-file> [--mission]"
---

Invoke the `sa-ticket-ground` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the file path, and `--mission`
through when given.

Pipeline: Intake → Load → Fill → Gate → Handover. Hard rules the skill
enforces: every line of `## Technical grounding` points at a section id
that exists in `<repo>-code`, or carries `[NEW: <reason>]`, or goes
under `Open decisions`; no data → `Open decisions`, never inference;
never edit a BA-owned section — a contradiction is quoted there, not
corrected; `Grounded on: <repo-id>:<doc-id> @ <revision>` is the first
line, copied from the hub document's manifest revision; never write
internal flow or failure modes — the document cannot prove them;
`kb ticket check` failing to RUN is not a PASS; never tick a
Definition of Ready checkbox — only the BA confirms DoR.
```

- [ ] **Step 6: Wire the four rows into `BA_TEMPLATES`** in `src/strata_kb/initcmd.py`, directly after the four `ba-mission-plan` rows (line 100):

```python
    ".claude/skills/sa-ticket-ground/SKILL.md": "claude-skill-sa-ticket-ground.md",
    ".claude/commands/sa-ticket-ground.md": "claude-command-sa-ticket-ground.md",
    ".github/prompts/sa-ticket-ground.prompt.md": "copilot-sa-ticket-ground.prompt.md",
    ".cursor/commands/sa-ticket-ground.md": "cursor-sa-ticket-ground.md",
```

- [ ] **Step 7: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_templates.py tests/test_init.py -q -k "sa_ or citation_example or ba"`
Expected: all PASS, including `test_every_citation_example_is_bracketed[...sa-ticket-ground...]` (the SA text carries no bare `§` citation) and `test_hub_and_child_do_not_gain_mission_artifacts`.

- [ ] **Step 8: Commit**

```bash
printf '%s\n' 'feat(ba): add the sa-ticket-ground skill (Claude Code, Copilot, Cursor wrappers)' '' 'Fills the SA-owned Technical grounding / Services & order sections from <repo>-code. Ids only, no inference, no repository access.' > /tmp/msg.txt
git add src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md src/strata_kb/templates/init/claude-command-sa-ticket-ground.md src/strata_kb/templates/init/copilot-sa-ticket-ground.prompt.md src/strata_kb/templates/init/cursor-sa-ticket-ground.md src/strata_kb/initcmd.py tests/test_templates.py
git commit -F /tmp/msg.txt
```

---

### Task 4: `ba-ticket-author` wrappers stop grounding code detail

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md`
- Modify: `src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md`
- Modify: `src/strata_kb/templates/init/cursor-ba-ticket-author.md`
- Modify: `src/strata_kb/templates/init/claude-command-ba-ticket-author.md`
- Modify: `tests/test_templates.py:1254-1305` (replace six D1 tests)

**Interfaces:**
- Consumes: `/sa-ticket-ground` (Task 3), heading `## Technical grounding` (Task 1).

- [ ] **Step 1: Replace the six D1 tests with the new contract** — in `tests/test_templates.py` delete these functions entirely: `test_ba_wrappers_prefer_code_knowledge_for_names_and_meaning`, `test_ba_wrappers_explain_the_division_of_the_two_documents`, `test_ba_wrappers_only_fall_back_to_the_placeholder_when_neither_answers`, `test_ba_wrappers_fill_all_four_container_arguments`, `test_ba_wrappers_keep_svc_out_of_acceptance_criteria`, `test_ba_wrappers_do_not_mis_cite_technology_to_dep_star` (and the comment block above the last one). Keep `BA_WRAPPERS`, `test_every_ba_wrapper_names_the_local_override`, `_ba_wrapper_text`, `test_ba_wrappers_still_carry_their_pre_phase5_rules`. In their place add:

```python
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


def test_ba_mission_wrappers_leave_services_and_order_to_the_sa():
    for name in BA_MISSION_WRAPPERS:
        assert "## Services & order" in _ba_wrapper_text(name), name
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_templates.py -q -k "hand_code_detail or no_longer_ground or leave_technical_grounding or leave_services"`
Expected: 4 FAILED.

- [ ] **Step 3: Apply the edits with one script** (exact-string replacements; each asserts it matched exactly once). Save as `/tmp/ba_ticket_edit.py` and run with `.venv/Scripts/python.exe /tmp/ba_ticket_edit.py`:

```python
import re
from pathlib import Path

BASE = Path("src/strata_kb/templates/init")

GROUND_BLOCK = (
    "   Search results tagged `code` come from `<repo>-code` and `<repo>-svc`\n"
    "   — present them alongside domain candidates: a `-code` section is\n"
    "   machine-extracted (trust it for names) while a `-svc` section is\n"
    "   human-reviewed (trust it for responsibility). A known extractor\n"
    "   limit: a service built from source often renders `Technology | none`\n"
    "   in `-code` — the extractor looks for a dependency manifest in a\n"
    "   directory named after the compose service, and otherwise falls back\n"
    "   to the image name — so a `-code` hit for a service's name does not\n"
    "   guarantee it also answers for `technology`; when it reads `none`,\n"
    "   the existing `%%TODO: verify against codebase%%` rule applies to\n"
    "   that one argument, not the whole container.\n"
)

HARD_RULE_RE = re.compile(
    r"- \*\*Ground code detail in the hub's code knowledge before reaching for\n"
    r"  a placeholder\.\*\*.*?\n  domain section\.\n",
    re.S,
)

NEW_RULE_TICKET = (
    "- **Code-level detail is not yours to ground.** Write\n"
    "  `%%TODO: verify against codebase%%` where a service, table, route or\n"
    "  file name is needed, add the owned `## Open questions` row, and hand\n"
    "  the ticket to `/sa-ticket-ground` once the business sections are\n"
    "  drafted — it fills the SA-owned `## Technical grounding` section from\n"
    "  the hub's `<repo>-code` document and `kb ticket check` verifies every\n"
    "  id. Never read `<repo>-code` or `<repo>-svc` yourself.\n"
)

DRAFT_ANCHOR = "   verification, Open questions, KB context, Definition of Ready).\n"
DRAFT_ADD = (
    DRAFT_ANCHOR
    + "   `## Technical grounding` is SA-owned: leave it exactly as the template\n"
    "   ships it — `/sa-ticket-ground` fills it after your draft is saved.\n"
)

COMMAND_OLD_RE = re.compile(
    r"Ground code detail in the hub's code knowledge before reaching for a\n"
    r"placeholder:.*?Criterion\.\n",
    re.S,
)
COMMAND_NEW = (
    "Code-level detail is not yours to ground: write\n"
    "`%%TODO: verify against codebase%%` where a service, table, route or\n"
    "file name is needed, add the owned `## Open questions` row, and hand the\n"
    "ticket to `/sa-ticket-ground` once the business sections are drafted —\n"
    "it fills the SA-owned `## Technical grounding` section from the hub's\n"
    "`<repo>-code` document and `kb ticket check` verifies every id. Never\n"
    "read `<repo>-code` or `<repo>-svc` yourself; leave `## Technical\n"
    "grounding` exactly as the template ships it.\n"
)


def once(text: str, old: str, new: str, name: str, label: str) -> str:
    assert text.count(old) == 1, f"{name}: {label} matched {text.count(old)}x"
    return text.replace(old, new)


def once_re(text: str, rx: re.Pattern, new: str, name: str, label: str) -> str:
    assert len(rx.findall(text)) == 1, f"{name}: {label} matched {len(rx.findall(text))}x"
    return rx.sub(lambda _m: new, text)


for name in (
    "claude-skill-ba-ticket-author.md",
    "copilot-ba-ticket-author.prompt.md",
    "cursor-ba-ticket-author.md",
):
    p = BASE / name
    t = p.read_text(encoding="utf-8")
    t = once(t, GROUND_BLOCK, "", name, "ground block")
    t = once_re(t, HARD_RULE_RE, NEW_RULE_TICKET, name, "hard rule")
    t = once(t, DRAFT_ANCHOR, DRAFT_ADD, name, "draft anchor")
    p.write_text(t, encoding="utf-8", newline="\n")

p = BASE / "claude-command-ba-ticket-author.md"
t = p.read_text(encoding="utf-8")
t = once_re(t, COMMAND_OLD_RE, COMMAND_NEW, p.name, "command paragraph")
p.write_text(t, encoding="utf-8", newline="\n")
print("ok")
```

Expected output: `ok`. If an assertion fires, the wrapper text drifted from what this plan read on 2026-09-20 — open the file and apply the same three edits by hand (delete the ground paragraph in step 3, replace the "Ground code detail…" hard-rule bullet with `NEW_RULE_TICKET`, append the two-line note after the Draft step's section list).

- [ ] **Step 4: Run the wrapper suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_templates.py tests/test_init.py -q -k "ba or citation_example"`
Expected: all PASS — including the still-present markers tests (`test_ba_ticket_author_templates_carry_the_hard_rules_markers`, `test_ba_ticket_author_templates_carry_the_v2_markers`, `test_ba_ticket_author_templates_pin_the_parallel_vs_sequential_split`, `test_ticket_wrappers_document_the_refs_inheritance_rule`). The two mission tests added in Step 1 will still FAIL until Task 5 — that is expected here; confirm they are the only failures.

- [ ] **Step 5: Commit**

```bash
printf '%s\n' 'refactor(ba): ba-ticket-author hands code detail to sa-ticket-ground' '' 'Removes the <repo>-code/-svc grounding paragraph and the Container(...) rule from all four wrappers; the BA writes the placeholder, the SA fills Technical grounding.' > /tmp/msg.txt
git add src/strata_kb/templates/init/claude-skill-ba-ticket-author.md src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md src/strata_kb/templates/init/cursor-ba-ticket-author.md src/strata_kb/templates/init/claude-command-ba-ticket-author.md tests/test_templates.py
git commit -F /tmp/msg.txt
```

---

### Task 5: `ba-mission-plan` wrappers stop grounding code detail

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-ba-mission-plan.md`
- Modify: `src/strata_kb/templates/init/claude-command-ba-mission-plan.md`
- Modify: `src/strata_kb/templates/init/copilot-ba-mission-plan.prompt.md`
- Modify: `src/strata_kb/templates/init/cursor-ba-mission-plan.md`
- Test: `tests/test_templates.py` (from Task 4), `tests/test_init.py::test_mission_wrapper_workflow_bodies_are_byte_identical`

**Interfaces:**
- Consumes: `/sa-ticket-ground --mission` (Task 3), heading `## Services & order` (Task 2).

- [ ] **Step 1: Confirm the failing tests** (written in Task 4)

Run: `.venv/Scripts/python.exe -m pytest tests/test_templates.py -q -k "hand_code_detail or no_longer_ground or leave_services"`
Expected: FAILED for the four `*-ba-mission-plan*` names only.

- [ ] **Step 2: Apply the edits to all four mission wrappers with one script** — save as `/tmp/ba_mission_edit.py`, run with `.venv/Scripts/python.exe /tmp/ba_mission_edit.py`. All four mission wrappers carry the full workflow (the command form too), so one pass covers them and byte-identity from `## Workflow` is preserved by construction:

```python
import re
from pathlib import Path

BASE = Path("src/strata_kb/templates/init")

GROUND_BLOCK = (
    "   Search results tagged `code` come from `<repo>-code` and `<repo>-svc`\n"
    "   — present them alongside domain candidates: a `-code` section is\n"
    "   machine-extracted (trust it for names) while a `-svc` section is\n"
    "   human-reviewed (trust it for responsibility). A known extractor\n"
    "   limit: a service built from source often renders `Technology | none`\n"
    "   in `-code` — the extractor looks for a dependency manifest in a\n"
    "   directory named after the compose service, and otherwise falls back\n"
    "   to the image name — so a `-code` hit for a service's name does not\n"
    "   guarantee it also answers for `technology`; when it reads `none`,\n"
    "   the existing `%%TODO: verify against codebase%%` rule applies to\n"
    "   that one argument, not the whole container.\n"
)

HARD_RULE_RE = re.compile(
    r"- \*\*Ground code detail in the hub's code knowledge before reaching for\n"
    r"  a placeholder\.\*\*.*?\n  domain section\.\n",
    re.S,
)

NEW_RULE_MISSION = (
    "- **Code-level detail is not yours to ground.** Write\n"
    "  `%%TODO: verify against codebase%%` where a service or container name\n"
    "  is needed, add the owned `## Technology decisions` row, and hand the\n"
    "  mission to `/sa-ticket-ground --mission` once the BA confirms the\n"
    "  backlog — it fills the SA-owned `## Services & order` section from the\n"
    "  hub's `<repo>-code` document (`svc.*` and `depends_on` only). Never\n"
    "  read `<repo>-code` or `<repo>-svc` yourself.\n"
)

DRAFT_ANCHOR = "   component detail.\n"
DRAFT_ADD = (
    DRAFT_ANCHOR
    + "   `## Services & order` is SA-owned: leave it exactly as the template\n"
    "   ships it — `/sa-ticket-ground --mission` fills it after the backlog is\n"
    "   confirmed.\n"
)


def once(text, old, new, name, label):
    assert text.count(old) == 1, f"{name}: {label} matched {text.count(old)}x"
    return text.replace(old, new)


def once_re(text, rx, new, name, label):
    assert len(rx.findall(text)) == 1, f"{name}: {label} matched {len(rx.findall(text))}x"
    return rx.sub(lambda _m: new, text)


for name in (
    "claude-skill-ba-mission-plan.md",
    "claude-command-ba-mission-plan.md",
    "copilot-ba-mission-plan.prompt.md",
    "cursor-ba-mission-plan.md",
):
    p = BASE / name
    t = p.read_text(encoding="utf-8")
    t = once(t, GROUND_BLOCK, "", name, "ground block")
    t = once_re(t, HARD_RULE_RE, NEW_RULE_MISSION, name, "hard rule")
    t = once(t, DRAFT_ANCHOR, DRAFT_ADD, name, "draft anchor")
    p.write_text(t, encoding="utf-8", newline="\n")
print("ok")
```

Expected output: `ok`.

- [ ] **Step 3: Run the wrapper suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_templates.py tests/test_init.py -q -k "ba or mission or citation_example"`
Expected: all PASS — including `test_mission_wrapper_workflow_bodies_are_byte_identical`, `test_mission_wrappers_reference_the_required_headings`, `test_every_mission_wrapper_carries_the_no_silent_skip_rule`, `test_ba_mission_plan_templates_carry_the_v2_markers`, `test_mission_wrappers_carry_the_never_auto_rules`.

- [ ] **Step 4: Commit**

```bash
printf '%s\n' 'refactor(ba): ba-mission-plan hands service names to sa-ticket-ground --mission' > /tmp/msg.txt
git add src/strata_kb/templates/init/claude-skill-ba-mission-plan.md src/strata_kb/templates/init/claude-command-ba-mission-plan.md src/strata_kb/templates/init/copilot-ba-mission-plan.prompt.md src/strata_kb/templates/init/cursor-ba-mission-plan.md
git commit -F /tmp/msg.txt
```

---

### Task 6: QUICKSTART-BA, README, CHANGELOG (Unreleased), full verification

**Files:**
- Modify: `src/strata_kb/templates/init/QUICKSTART-ba.md` (after step 5 in "Create a ticket", lines 36–68; rewrite "Code knowledge on the hub", lines 99–125)
- Modify: `tests/test_init.py:1967-1976` (`test_quickstart_ba_points_at_code_knowledge`)
- Modify: `README.md:132` and `README.md:658-659` (§12)
- Modify: `CHANGELOG.md` (new `## Unreleased` entry at the top). Do NOT touch `pyproject.toml` or `uv.lock`.

**Interfaces:**
- Consumes: everything above. No new names.

- [ ] **Step 1: Extend the QUICKSTART test** — in `tests/test_init.py::test_quickstart_ba_points_at_code_knowledge` add after the last assert:

```python
    assert "/sa-ticket-ground" in text
    assert "## Technical grounding" in text
    assert "kb ticket check" in text
    # The BA skills no longer read the code documents themselves.
    assert "The BA skills do not read them" in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_init.py -q -k quickstart_ba_points_at_code_knowledge`
Expected: FAILED on `/sa-ticket-ground`.

- [ ] **Step 3: Edit `QUICKSTART-ba.md`**

(a) In "## Create a ticket", after item 5's sub-list (ends with "…the assistant never publishes for you."), add:

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

(b) Replace the whole "## Code knowledge on the hub" section (from that heading up to, not including, "## DoR rules (what CI enforces)") with:

````markdown
## Code knowledge on the hub

Alongside domain documents, the hub holds two documents per product
repo, published by that repo's `dev`-kind workflow: `<repo>-code`
(generated structure — names: `svc.*`, `db.*`, `api.*`, `int.*`,
`cmd.*`, `struct.tree`) and `<repo>-svc` (curated responsibility —
meaning).

The BA skills do not read them. Where a ticket or mission needs a
service, table, route or file name, `ba-ticket-author` and
`ba-mission-plan` write `%%TODO: verify against codebase%%` with an owned
open question, and `/sa-ticket-ground` answers those from `<repo>-code`
in the SA-owned section — `## Technical grounding` in a ticket,
`## Services & order` in a mission. Every id it writes is checked against
the document by `kb ticket check`; what the document cannot prove —
internal flow, failure modes, request bodies — is parked under
`Open decisions` for the Dev, who has the code.

The section reference itself, spelled the way a real citation is:

```text
<repo>-code §svc.<name>
<repo>-svc §svc.<name>
```

**One caution:** `<repo>-svc` grounds a diagram — it is never a substitute
for a domain citation in an Acceptance Criterion. A code/format/enum/
threshold that encodes a standard still has to come from a pinned domain
section, not from a service's responsibility text.

````

(c) In "## CLI reference" nothing changes in this PR — `kb ticket check` is documented when it ships (PR 2).

- [ ] **Step 4: Edit `README.md`**

(a) Line 132: change `` `/ba-ticket-author` and `/ba-mission-plan` on a `ba` `` to `` `/ba-ticket-author`, `/ba-mission-plan` and `/sa-ticket-ground` on a `ba` ``.

(b) In §12, after the paragraph ending "Markdown out, human in the loop by design." insert:

```markdown
**`sa-ticket-ground`** fills the one section the BA never touches:
`## Technical grounding` — service, files, tables, routes, externals and the
test command, each a section id that exists in the hub's `<repo>-code`
document, or `[NEW: <reason>]`, or parked under `Open decisions`. It has no
repository access and never infers: internal flow, failure modes and request
bodies are not in the document, so they go to `Open decisions` for the Dev.
With `--mission` it fills a mission plan's `## Services & order` from `svc.*`
and `depends_on` only. The BA skills themselves no longer read `-code`/`-svc`;
they write `%%TODO: verify against codebase%%` and hand off.
```

- [ ] **Step 5: CHANGELOG (no version bump)**

Insert at the top of `CHANGELOG.md`, directly under the intro paragraph (before `## 1.0.1 — 2026-09-19`). The heading is `## Unreleased` — this PR never bumps `pyproject.toml` or regenerates `uv.lock`; the maintainer assigns the version at release time:

```markdown
## Unreleased

### BA repos — the SA grounding layer

- **`/sa-ticket-ground`** (new skill on `ba` repos; Claude Code, Copilot and
  Cursor wrappers) fills the SA-owned `## Technical grounding` section of a
  ticket — or, with `--mission`, `## Services & order` of a mission plan — from
  the hub's `<repo>-code` document. Ids only: every line names a section id
  that exists in the document, or carries `[NEW: <reason>]`, or is parked
  under `Open decisions`. It has no repository access and never infers.
- `docs/tickets/TEMPLATE.md` gains `## Technical grounding` (a recommended
  section — `kb ticket lint` warns when it is missing; legacy tickets keep
  passing); `docs/missions/TEMPLATE.md` gains `## Services & order`. Neither
  has a `Flow` or `Failure modes` field: the code document cannot prove them.
- `ba-ticket-author` and `ba-mission-plan` no longer read `<repo>-code` /
  `<repo>-svc`; they write `%%TODO: verify against codebase%%` and hand off to
  the SA skill.
- `kb ticket check`, the machine gate for the new section, follows in a
  separate PR; until it lands the SA skill verifies ids by hand and says so.

Re-run `kb init --kind ba` to pick up the new templates and wrappers.

```

Verify nothing else moved: `git status --short` must list neither `pyproject.toml` nor `uv.lock`.

- [ ] **Step 6: Full verification**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all PASS (README pins in `tests/test_readme.py` are untouched by these edits; `tests/test_check_package.py` and `tests/test_init.py` see the new resources through `BA_TEMPLATES`).

Run: `.venv/Scripts/python.exe -m pytest tests/test_check_package.py -q` separately if the full run is slow — it verifies the package ships every mapped resource.

- [ ] **Step 7: Graph change analysis (CLAUDE.md, mandatory before commit)**

Call `mcp__gitnexus__detect_changes({scope: "all"})`. The index was 2 commits behind at planning time; if the result says `partial: true`, `truncated: true`, or stale, re-index first (`npx gitnexus analyze` in the repo root, or `node .gitnexus/run.cjs analyze --index-only` if that runner exists) and call again. Expected: the only changed symbols are `initcmd.BA_TEMPLATES` and `ticket.RECOMMENDED_HEADINGS`, both `additive`; no HIGH/CRITICAL risk.

- [ ] **Step 8: Commit**

```bash
printf '%s\n' 'docs(ba): document the SA grounding step' '' 'QUICKSTART-BA step 6 + Code knowledge rewrite, README §12 paragraph, CHANGELOG Unreleased entry. No version bump.' > /tmp/msg.txt
git add src/strata_kb/templates/init/QUICKSTART-ba.md tests/test_init.py README.md CHANGELOG.md
git commit -F /tmp/msg.txt
```

---

## Done when

- `.venv/Scripts/python.exe -m pytest -q` is green.
- `kb init --kind ba` into an empty temp dir produces `.claude/skills/sa-ticket-ground/SKILL.md`, the three sibling wrappers, and `docs/tickets/TEMPLATE.md` containing `## Technical grounding` once; `kb init --kind dev` into another temp dir produces none of the SA wrappers.
- `kb ticket lint` on `tests/test_ticketlint.py`'s golden ticket still reports `DoR: PASS` with no "recommended section missing" warning.
- `pyproject.toml` and `uv.lock` are byte-identical to `main` (no version bump).
- Branch is ready for PR: title `feat(ba): SA grounding layer — templates, sa-ticket-ground skill`; body links the spec and states that `kb ticket check` is PR 2.
