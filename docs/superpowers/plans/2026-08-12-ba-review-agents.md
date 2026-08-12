# BA Review Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a maturity-review layer to the BA authoring skills: two review agents (business coverage + dev implementability) score missions/tickets 1–5 against a scaffolded rubric, loop to threshold, and persist results in a `## Review record` section; lints warn (never error) when the record is missing or untouched.

**Architecture:** All changes land at the scaffold source (`src/center_kb/templates/init/` + lint modules); BA repos receive them via `kb init --kind ba`. The review itself is prompt-driven (skill markdown) — the only Python is one shared lint check plus template wiring.

**Tech Stack:** Python 3.11+ (repo venv is 3.13), pytest, importlib.resources for template tests.

**Spec:** `docs/superpowers/specs/2026-08-12-ba-review-agents-design.md`

## Global Constraints

- New lint checks are **warnings only** — they must never flip a `DoR` verdict (`LintReport.passed` unchanged).
- `REQUIRED_HEADINGS` / `REQUIRED_MISSION_HEADINGS` are compatibility contracts — never touch them.
- Template headings are English and never localized.
- The claude-command ticket variant (`claude-command-ba-ticket-author.md`) is a thin pointer — never edit it. The claude-command mission variant (`claude-command-ba-mission-plan.md`) is a full copy — keep it in sync.
- Run tests with: `.venv/bin/python -m pytest tests/<file> -v` from the repo root.
- Commit messages: conventional commits, no attribution trailer (disabled via user settings).
- Work on branch `feat/ba-review-agents` (already exists, spec committed).

---

### Task 1: `review-rubric.md` scaffolded doc

**Files:**
- Create: `src/center_kb/templates/init/review-rubric.md`
- Modify: `src/center_kb/initcmd.py` (BA_TEMPLATES dict, lines 68–87)
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: package resource `templates/init/review-rubric.md`, scaffolded to `docs/review-rubric.md` in BA repos. Later tasks (5, 6) reference the scaffolded path `docs/review-rubric.md` in skill text.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_templates.py -v -k review_rubric`
Expected: 2 FAIL (`KeyError: 'docs/review-rubric.md'` / file assertion).

- [ ] **Step 3: Create the rubric template**

Create `src/center_kb/templates/init/review-rubric.md` with exactly this content:

````markdown
# Maturity review rubric — missions & tickets

Used by the maturity-review step of `ba-mission-plan` and
`ba-ticket-author`. Two reviewers score the document independently —
one axis each. Edit this file to tune the criteria for your domain;
the skills read it at review time.

## Business coverage

Reviewer role: PO / stakeholder. Question: does this document cover
the business need, or only the happy path someone remembered?

Checklist (pass/fail each item):

- [ ] Every in-scope area of the mission has a corresponding US
      (missions) / every part of the story is covered by an AC (tickets).
- [ ] ACs cover the happy path AND edge cases AND error/empty states.
- [ ] Out of scope lists the things easily mistaken as in-scope —
      not just "everything else".
- [ ] The business value of the story/mission is stated and concrete.
- [ ] NFRs are quantified where the work touches large data volumes,
      concurrency, or real-time constraints.
- [ ] No architecture-blocking open question is still OPEN
      (missions: none blocking foundational stories).
- [ ] No statement contradicts the pinned KB sources.
- [ ] Every unknown is owned: `OPEN(<owner>)` + an `## Open questions`
      row — vagueness without an owner fails this item.

## Dev implementability

Reviewer role: the dev who picks this up next sprint. Question: can I
implement this without asking the BA anything?

Checklist (pass/fail each item):

- [ ] Implementable end-to-end without a follow-up question.
- [ ] Every AC is acceptance-testable with concrete values — no weasel
      words (banned list: `docs/ac-quality.md`).
- [ ] The UI spec names the MEANS of every visual distinction (label,
      color, shape, grouping) — or `N/A` / `OPEN(<owner>)`.
- [ ] Test data with expected values is present (or owned `OPEN`).
- [ ] Dependencies are listed ("None" counts; blank does not).
- [ ] Sequencing is feasible — nothing depends on later work.
- [ ] Every `OPEN(...)` and `%%TODO%%` has an owner.
- [ ] No weasel words anywhere in the body.

## Maturity scale

Score each axis 1–5:

| Level | Meaning |
|---|---|
| 1 | Initial — required sections missing or empty |
| 2 | Skeletal — structure present, content vague |
| 3 | Structured — complete structure, gaps exist but every gap is owned |
| 4 | Ready — a dev/PO would accept it; all checklist items pass or are owned `OPEN` (**threshold**) |
| 5 | Mature — no blocking open questions remain |

## Scoring rule

The score is the LOWEST level whose criteria are ALL satisfied.
Never average across checklist items. Threshold to stop the review
loop: both axes ≥ 4. Results are appended to the document's
`## Review record` section, one row per round.
````

- [ ] **Step 4: Wire into BA_TEMPLATES**

In `src/center_kb/initcmd.py`, add one entry to `BA_TEMPLATES` directly after the `"docs/ac-quality.md"` line:

```python
    "docs/ac-quality.md": "ac-quality.md",
    "docs/review-rubric.md": "review-rubric.md",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_templates.py tests/test_init.py tests/test_scaffold.py -v`
Expected: all PASS (existing init tests iterate `BA_TEMPLATES` values and pick up the new resource automatically).

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/review-rubric.md src/center_kb/initcmd.py tests/test_templates.py
git commit -m "feat: scaffold review-rubric.md into BA repos"
```

---

### Task 2: `## Review record` section in both document templates

**Files:**
- Modify: `src/center_kb/templates/init/ticket-template.md` (end of file, after `## Definition of Ready`)
- Modify: `src/center_kb/templates/init/mission-template.md` (end of file, after `## Definition of Ready`)
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: the literal heading `## Review record` and placeholder body `Not yet reviewed.` — Task 3's lint check and Tasks 5–6's skill text depend on these exact strings.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_both_document_templates_carry_the_review_record_section():
    for name in ("ticket-template.md", "mission-template.md"):
        text = _read_init_template(name)
        assert text.count("## Review record") == 1, name
        assert "Not yet reviewed." in text, name
        assert "docs/review-rubric.md" in text, name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_templates.py -v -k review_record_section`
Expected: FAIL (heading absent).

- [ ] **Step 3: Append the section to both templates**

Append to the END of `src/center_kb/templates/init/ticket-template.md` AND `src/center_kb/templates/init/mission-template.md` (identical block, after the `## Definition of Ready` section):

```markdown

## Review record
<!-- Filled by the maturity-review step (rubric: docs/review-rubric.md).
One row per review round; re-reviews append rows — keep the history.
Score = lowest maturity level fully satisfied; threshold is 4 per axis.
Gaps still open after the review are listed below the table and each
must have an `## Open questions` row. -->
Not yet reviewed.

| Date | Round | Business | Dev | Reviewer |
|---|---|---|---|---|

Open gaps: <none, or Q-ids with owners>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_templates.py tests/test_ticketlint.py tests/test_missionlint.py -v`
Expected: all PASS (template round-trip tests `test_template_carries_every_recommended_heading` etc. count recommended headings with `count(heading) == 1` — the new section adds none of those headings).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/init/ticket-template.md src/center_kb/templates/init/mission-template.md tests/test_templates.py
git commit -m "feat: Review record section in ticket & mission templates"
```

---

### Task 3: `check_review_record` in lintcore

**Files:**
- Modify: `src/center_kb/lintcore.py` (add after `check_recommended_sections`, ~line 262)
- Test: `tests/test_lintcore.py`

**Interfaces:**
- Consumes: `section_body(text, heading)`, `HTML_COMMENT_RE`, `Issue` — all already in `lintcore.py`.
- Produces: `REVIEW_RECORD_HEADING: str = "## Review record"` and `check_review_record(text: str) -> list[Issue]`. Task 4 wires it into both lints.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lintcore.py` (it already imports `lintcore`; follow its existing import style):

```python
# --- Review record (maturity review) ---


def test_check_review_record_warns_when_heading_missing():
    issues = lintcore.check_review_record("# T\n\n## Summary\nx\n")
    assert [i.level for i in issues] == ["warning"]
    assert "'## Review record' missing" in issues[0].message


def test_check_review_record_warns_on_untouched_placeholder():
    text = (
        "# T\n\n## Review record\n"
        "<!-- guidance -->\n"
        "Not yet reviewed.\n\n"
        "| Date | Round | Business | Dev | Reviewer |\n"
        "|---|---|---|---|---|\n"
    )
    issues = lintcore.check_review_record(text)
    assert [i.level for i in issues] == ["warning"]
    assert "placeholder" in issues[0].message


def test_check_review_record_warns_on_empty_body():
    text = "# T\n\n## Review record\n<!-- guidance only -->\n\n## Next\nx\n"
    issues = lintcore.check_review_record(text)
    assert [i.level for i in issues] == ["warning"]


def test_check_review_record_accepts_a_filled_record():
    text = (
        "# T\n\n## Review record\n"
        "| Date | Round | Business | Dev | Reviewer |\n"
        "|---|---|---|---|---|\n"
        "| 2026-08-12 | 1 | 4 | 4 | agent |\n\n"
        "Open gaps: none\n"
    )
    assert lintcore.check_review_record(text) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lintcore.py -v -k review_record`
Expected: 4 FAIL with `AttributeError: ... has no attribute 'check_review_record'`.

- [ ] **Step 3: Implement the check**

Add to `src/center_kb/lintcore.py`, directly after `check_recommended_sections`:

```python
REVIEW_RECORD_HEADING = "## Review record"

# The template ships this exact placeholder line; its survival means the
# maturity review never ran.
_REVIEW_PLACEHOLDER = "Not yet reviewed."


def check_review_record(text: str) -> list[Issue]:
    """Warning when the maturity review has not run — '## Review record'
    is missing, still empty, or still holds the template placeholder.
    Warning-level on purpose: the review is an authoring-time aid and the
    BA judges; nothing here may flip a DoR verdict."""
    body = section_body(text, REVIEW_RECORD_HEADING)
    if body is None:
        return [
            Issue(
                "warning",
                f"'{REVIEW_RECORD_HEADING}' missing — the maturity review "
                "has not run (rubric: docs/review-rubric.md)",
            )
        ]
    stripped = HTML_COMMENT_RE.sub("", body)
    if _REVIEW_PLACEHOLDER in stripped:
        return [
            Issue(
                "warning",
                f"'{REVIEW_RECORD_HEADING}' still holds the placeholder "
                f"'{_REVIEW_PLACEHOLDER}' — run the maturity review "
                "(rubric: docs/review-rubric.md)",
            )
        ]
    if not stripped.strip():
        return [
            Issue(
                "warning",
                f"'{REVIEW_RECORD_HEADING}' is empty — run the maturity "
                "review (rubric: docs/review-rubric.md)",
            )
        ]
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_lintcore.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/lintcore.py tests/test_lintcore.py
git commit -m "feat: lintcore check_review_record — warn when maturity review absent"
```

---

### Task 4: Wire the check into ticket & mission lints

**Files:**
- Modify: `src/center_kb/ticketlint.py` (in `lint()`, after `_check_owned_unknowns`, ~line 256)
- Modify: `src/center_kb/missionlint.py` (in `lint()`, after `check_placeholders`, ~line 377)
- Test: `tests/test_ticketlint.py`, `tests/test_missionlint.py`

**Interfaces:**
- Consumes: `lintcore.check_review_record(text)` from Task 3; the exact template strings from Task 2.

- [ ] **Step 1: Update the test builders so golden docs stay warning-free**

In `tests/test_ticketlint.py`: append `"## Review record"` to the END of the `ALL_HEADINGS` tuple (line 24, after `"## Definition of Ready"`), and add to `_default_sections`:

```python
        "## Review record": (
            "| Date | Round | Business | Dev | Reviewer |\n"
            "|---|---|---|---|---|\n"
            "| 2026-08-12 | 1 | 4 | 4 | agent |\n\n"
            "Open gaps: none"
        ),
```

In `tests/test_missionlint.py`: same two edits — append `"## Review record"` to the END of `ALL_MISSION_HEADINGS` (after `"## Definition of Ready"`) and add the identical `_default_sections` entry.

- [ ] **Step 2: Write the failing lint tests**

Append to `tests/test_ticketlint.py`:

```python
def test_missing_review_record_warns_but_passes(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(golden_block, skip="## Review record")
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert report.passed is True
    assert any(
        "'## Review record' missing" in w for w in _warnings(report)
    )


def test_placeholder_review_record_warns_but_passes(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(
        golden_block,
        overrides={"## Review record": "Not yet reviewed."},
    )
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert report.passed is True
    assert any("placeholder" in w for w in _warnings(report))


def test_filled_review_record_emits_no_review_warning(
    fed_hub: Path, golden_block: str
):
    report = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    assert not any("Review record" in w for w in _warnings(report))
```

Append to `tests/test_missionlint.py`:

```python
def test_missing_review_record_warns_but_passes(
    fed_hub: Path, golden_block: str
):
    report = missionlint.lint(
        _build_mission(golden_block, skip="## Review record"),
        _hub(fed_hub),
    )
    assert report.passed is True
    assert any(
        "'## Review record' missing" in w for w in _warnings(report)
    )


def test_placeholder_review_record_warns_but_passes(
    fed_hub: Path, golden_block: str
):
    report = missionlint.lint(
        _build_mission(
            golden_block,
            overrides={"## Review record": "Not yet reviewed."},
        ),
        _hub(fed_hub),
    )
    assert report.passed is True
    assert any("placeholder" in w for w in _warnings(report))
```

- [ ] **Step 3: Update the legacy warning-count test**

In `tests/test_ticketlint.py`, `test_legacy_nine_section_ticket_still_passes` (~line 850) builds a doc with only the 9 required sections — it now also triggers the missing-review-record warning. Change the count assertion and its comment:

```python
    # RECOMMENDED_HEADINGS warnings + 1 missing-Review-record warning.
    assert len(_warnings(report)) == len(ticket.RECOMMENDED_HEADINGS) + 1
```

- [ ] **Step 4: Run tests to verify the new ones fail**

Run: `.venv/bin/python -m pytest tests/test_ticketlint.py tests/test_missionlint.py -v -k review_record`
Expected: new tests FAIL (no warning emitted yet). `test_legacy_nine_section_ticket_still_passes` also FAILS (count is still `len(RECOMMENDED_HEADINGS)`).

- [ ] **Step 5: Wire the check into both lints**

`src/center_kb/ticketlint.py`, in `lint()` after `issues += _check_owned_unknowns(text)`:

```python
    issues += _check_owned_unknowns(text)
    issues += lintcore.check_review_record(text)
```

`src/center_kb/missionlint.py`, in `lint()` after `issues += check_placeholders(text)`:

```python
    issues += check_placeholders(text)
    issues += lintcore.check_review_record(text)
```

- [ ] **Step 6: Run the full lint suites**

Run: `.venv/bin/python -m pytest tests/test_ticketlint.py tests/test_missionlint.py tests/test_lintcore.py tests/test_mission_ticket_traceability.py tests/test_cli_mission.py tests/test_cli_ticket.py -v`
Expected: all PASS. `test_golden_mission_emits_no_new_warnings` passes because Step 1 gave the builder a filled record.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/ticketlint.py src/center_kb/missionlint.py tests/test_ticketlint.py tests/test_missionlint.py
git commit -m "feat: ticket & mission lint warn when the maturity review is absent"
```

---

### Task 5: Maturity-review step in the ticket-author skill + mirrors

**Files:**
- Modify: `src/center_kb/templates/init/claude-skill-ba-ticket-author.md`
- Modify: `src/center_kb/templates/init/cursor-ba-ticket-author.md`
- Modify: `src/center_kb/templates/init/copilot-ba-ticket-author.prompt.md`
- Test: `tests/test_templates.py`
- DO NOT touch `claude-command-ba-ticket-author.md` (thin pointer).

**Interfaces:**
- Consumes: `docs/review-rubric.md` (Task 1), `## Review record` + `Not yet reviewed.` (Task 2).
- Produces: the literal marker strings `Maturity review`, `docs/review-rubric.md`, `## Review record` in all three full-content mirrors (asserted by the test below; Task 6 mirrors the same markers for the mission skill).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_templates.py -v -k maturity_review_step`
Expected: FAIL on `'Maturity review'`.

- [ ] **Step 3: Edit `claude-skill-ba-ticket-author.md`**

Three edits:

(a) Pipeline line in the intro — change:
`pipeline: Intake → Parent mission → Ground → Draft → Pin → Lint → Review.`
to:
`pipeline: Intake → Parent mission → Ground → Draft → Pin → Lint → Maturity review → Review.`

(b) Insert a new workflow step between step 6 (**Lint**) and the final step, and renumber the final step from 7 to 8:

```markdown
7. **Maturity review** — once lint reports `DoR: PASS`, dispatch TWO
   review subagents IN PARALLEL, each reading the draft and
   `docs/review-rubric.md`:
   - *Business-coverage reviewer* — acts as PO/stakeholder; scores the
     "Business coverage" axis of the rubric.
   - *Dev-implementability reviewer* — acts as the dev who picks the
     ticket up next sprint; scores the "Dev implementability" axis.
   Keep the two roles in separate subagents — never blend the
   perspectives in one pass. Each reviewer returns: a 1–5 score (the
   LOWEST maturity level fully satisfied — never averaged), the
   checklist with pass/fail per item, and a gap list where every gap
   names the section it lives in and a proposed fix.

   Apply the fixes, re-run `kb ticket lint`, and review again — at most
   3 rounds total; stop early when both axes score ≥ 4. A gap you
   cannot close yourself (a missing business decision, missing input)
   is NEVER invented: write `OPEN(<owner>)` at the spot and add an
   `## Open questions` row.

   Record the result in `## Review record`: on the first round replace
   the `Not yet reviewed.` placeholder; append one table row per round
   (`| Date | Round | Business | Dev | Reviewer |`) and list the
   still-open gaps on the `Open gaps:` line. Report both scores and the
   remaining owned gaps to the BA in the handover summary.
8. **Review → save** — write the final Markdown to
   `tickets/<ticket-id>.md`. Hand it to the BA to review and commit;
   the BA — not you — pastes it into Jira.
```

(replace the existing step 7 body with the step 8 text above — the content is unchanged, only the number moves).

(c) Add one hard rule at the end of `## Hard rules`:

```markdown
- The maturity review never edits business intent on its own authority —
  it closes gaps with facts already confirmed by the BA or the KB, and
  everything else becomes an owned `OPEN(...)`. Scores below 4 after
  3 rounds are reported, not hidden.
```

- [ ] **Step 4: Edit the cursor and copilot mirrors**

`cursor-ba-ticket-author.md` and `copilot-ba-ticket-author.prompt.md`: same three edits, with two mirror-specific differences:

(a) frontmatter `description:` line — change `… Pin → Lint → Review, saved to tickets/<id>.md` to `… Pin → Lint → Maturity review → Review, saved to tickets/<id>.md`.

(b) These runtimes cannot dispatch subagents — the review step opens with self-review wording instead. Use this variant of the step's first paragraph (rest of the step text identical to the claude version):

```markdown
7. **Maturity review** — once lint reports `DoR: PASS`, run TWO
   sequential review passes yourself against `docs/review-rubric.md`,
   one role per pass — never blend the perspectives:
   - Pass 1, *Business-coverage reviewer* — act as PO/stakeholder;
     score the "Business coverage" axis of the rubric.
   - Pass 2, *Dev-implementability reviewer* — act as the dev who picks
     the ticket up next sprint; score the "Dev implementability" axis.
   Each pass produces: a 1–5 score (the LOWEST maturity level fully
   satisfied — never averaged), the checklist with pass/fail per item,
   and a gap list where every gap names the section it lives in and a
   proposed fix.
```

Also insert the new hard rule from Step 3(c) into both mirrors' hard-rules section.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_templates.py -v`
Expected: all PASS — including the pre-existing `test_ba_ticket_author_templates_carry_the_seven_pipeline_steps` (all seven step names are still substrings) and `test_claude_skill_ba_ticket_author_has_expected_frontmatter` (description untouched in the claude skill).

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/claude-skill-ba-ticket-author.md src/center_kb/templates/init/cursor-ba-ticket-author.md src/center_kb/templates/init/copilot-ba-ticket-author.prompt.md tests/test_templates.py
git commit -m "feat: maturity-review step in ba-ticket-author skill + mirrors"
```

---

### Task 6: Maturity-review step in the mission-plan skill + mirrors

**Files:**
- Modify: `src/center_kb/templates/init/claude-skill-ba-mission-plan.md`
- Modify: `src/center_kb/templates/init/cursor-ba-mission-plan.md`
- Modify: `src/center_kb/templates/init/copilot-ba-mission-plan.prompt.md`
- Modify: `src/center_kb/templates/init/claude-command-ba-mission-plan.md` (full copy — kept in sync)
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: `BA_REVIEW_MARKERS` tuple defined in Task 5's test; `docs/review-rubric.md`; `## Review record`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
BA_MISSION_PLAN_TEMPLATES = [
    "claude-skill-ba-mission-plan.md",
    "claude-command-ba-mission-plan.md",
    "copilot-ba-mission-plan.prompt.md",
    "cursor-ba-mission-plan.md",
]


def test_ba_mission_plan_templates_carry_the_maturity_review_step():
    for name in BA_MISSION_PLAN_TEMPLATES:
        text = _read_init_template(name)
        for marker in BA_REVIEW_MARKERS:
            assert marker in text, f"{name}: missing {marker!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_templates.py -v -k mission_plan_templates_carry_the_maturity`
Expected: FAIL on `'Maturity review'`.

- [ ] **Step 3: Edit all four mission templates**

Read each file first — the four mirrors share the same 7-step workflow (`Intake → Ground → Draft → Split → Pin → Lint → Review → save`) with per-mirror phrasing. In EACH file:

(a) Insert a new step 7 between step 6 (**Lint**) and the final **Review → save** step, and renumber **Review → save** to 8. Claude skill AND claude-command (both drive the Claude runtime, subagents available) get the parallel-subagent variant; cursor/copilot get the sequential self-review variant. Text is the Task 5 step text with three substitutions: `kb ticket lint` → `kb mission lint`; "the dev who picks the ticket up next sprint" → "the tech lead who will slice this mission into tickets"; `tickets/<ticket-id>.md` reference stays out (the mission save path is already in the existing final step).

Claude variant (skill + command):

```markdown
7. **Maturity review** — once lint reports `DoR: PASS`, dispatch TWO
   review subagents IN PARALLEL, each reading the draft and
   `docs/review-rubric.md`:
   - *Business-coverage reviewer* — acts as PO/stakeholder; scores the
     "Business coverage" axis of the rubric.
   - *Dev-implementability reviewer* — acts as the tech lead who will
     slice this mission into tickets; scores the "Dev implementability"
     axis.
   Keep the two roles in separate subagents — never blend the
   perspectives in one pass. Each reviewer returns: a 1–5 score (the
   LOWEST maturity level fully satisfied — never averaged), the
   checklist with pass/fail per item, and a gap list where every gap
   names the section it lives in and a proposed fix.

   Apply the fixes, re-run `kb mission lint`, and review again — at
   most 3 rounds total; stop early when both axes score ≥ 4. A gap you
   cannot close yourself (a missing business decision, missing input)
   is NEVER invented: write `OPEN(<owner>)` at the spot and add an
   `## Open questions` row.

   Record the result in `## Review record`: on the first round replace
   the `Not yet reviewed.` placeholder; append one table row per round
   (`| Date | Round | Business | Dev | Reviewer |`) and list the
   still-open gaps on the `Open gaps:` line. Report both scores and the
   remaining owned gaps to the BA in the handover summary.
```

Cursor/copilot variant: same text with the first paragraph swapped for the sequential self-review wording from Task 5 Step 4(b) ("run TWO sequential review passes yourself … one role per pass — never blend the perspectives", with the mission-specific role names above).

(b) If the file's intro or frontmatter description carries the pipeline arrow chain (`… Pin → Lint → Review`), extend it to `… Pin → Lint → Maturity review → Review`.

(c) Add the Task 5 Step 3(c) hard rule to each file's hard-rules section.

- [ ] **Step 4: Run the full template suite**

Run: `.venv/bin/python -m pytest tests/test_templates.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the whole test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/claude-skill-ba-mission-plan.md src/center_kb/templates/init/claude-command-ba-mission-plan.md src/center_kb/templates/init/cursor-ba-mission-plan.md src/center_kb/templates/init/copilot-ba-mission-plan.prompt.md tests/test_templates.py
git commit -m "feat: maturity-review step in ba-mission-plan skill + mirrors"
```
