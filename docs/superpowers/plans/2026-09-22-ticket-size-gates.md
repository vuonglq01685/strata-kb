# Ticket size gates — PR 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb ticket lint` fails a ticket that carries more than 10 acceptance criteria, or more than one user story. Both are scope errors — the fix is to split the ticket, never to merge two conditions into one AC. The ticket template, the four `ba-ticket-author` wrappers, the review rubric and both BA guides say the same thing, so the BA learns the rule before the gate teaches it.

**Architecture:** Two small checks next to their existing siblings in `ticketlint.py`. `_check_ac_count(ac_items)` reuses the item list `_check_ac_present` already returns (no second parse of the section); `_check_story_count(text)` counts `ticket.STORY_RE` matches in the `## User Story` body, exactly as `_check_story` reads that body. Both are called from `lint()` next to the check they bound. No new module, no config key, no CLI change.

**Tech Stack:** Python 3.11+, pytest (`uv run pytest`). Branch: `feat/sa-greenfield-pr2` at `1ef5f5e`.

## Global Constraints

- No version bump: `pyproject.toml` `version` and `uv.lock` untouched. CHANGELOG entry under `## Unreleased`.
- No new dependency. `mdutils.py` frozen. No CLI/MCP imports in `ticketlint.py`.
- Exit codes unchanged. `cli.ticket_lint` ends with `raise typer.Exit(2 if report.stale_errors == errors else 1)` — a size error is not a stale error, so a ticket that trips only a new rule exits **1**, never 2. No test may need an exit-code pin changed.
- `MAX_AC` is a module-level constant in `ticketlint.py`, not a config key. No lower-bound change: `_check_ac_present`'s "at least 2" rule stays exactly as it is. No mission-level cap.
- Both new rules are **errors**, with no escape hatch (no `OPEN(<owner>)` suppression, no marker).
- CLAUDE.md: run `impact({target: "lint", direction: "upstream"})` (the `ticketlint.lint` function), plus `impact` on `_check_ac_present` and `_check_story`, before editing `ticketlint.py`; run `detect_changes()` before each commit. If the GitNexus index is stale, run `node .gitnexus/run.cjs analyze` from the project root first. **If the MCP server is down** (this session's `strata-kb` MCP reported `CONNECTION_CLOSED`), say so in the commit body — one line, e.g. `GitNexus MCP unreachable; impact/detect_changes skipped` — and continue.
- Commit format: `<type>: <description>` (feat/fix/refactor/docs/test/chore). Attribution trailer per session reminder.
- `uv run pytest tests/test_ticketlint.py tests/test_templates.py tests/test_init.py -q` green after every task; full `uv run pytest -q` green before the last commit.

---

## File structure

| File | Change |
|---|---|
| `src/strata_kb/ticketlint.py` | `MAX_AC = 10`; `_check_ac_count`; `_check_story_count`; two call lines in `lint()` |
| `tests/test_ticketlint.py` | `_ac_lines` helper; 4 new cases (11 AC, 10 AC, two stories, one comma-rich story) |
| `src/strata_kb/templates/init/ticket-template.md` | one `## Definition of Ready` checkbox line |
| `src/strata_kb/templates/init/review-rubric.md` | one `## Business coverage` checklist item |
| `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md` | one sentence appended to the Draft step's **AC quality bar** paragraph |
| `src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md` | the same sentence |
| `src/strata_kb/templates/init/cursor-ba-ticket-author.md` | **derived** from the copilot file, never re-typed |
| `src/strata_kb/templates/init/claude-command-ba-ticket-author.md` | **untouched** — it is a thin prose wrapper with no Draft step (see Task 3, Step 1) |
| `tests/test_templates.py` | 3 needle tests (template DoR line, rubric item, wrapper sentence) |
| `docs/src/guide-ba.en.md` | §6.1 gains two bullets |
| `docs/src/guide-ba.vi.md` | §6.1 gains the same two bullets, in Vietnamese |
| `CHANGELOG.md` | one bullet appended under `## Unreleased` |

---

### Task 1: The two size rules in the lint engine

**Files:**
- Modify: `src/strata_kb/ticketlint.py`
- Test: `tests/test_ticketlint.py`

**Interfaces:**
- Produces:
  - `ticketlint.MAX_AC: int = 10` — module-level constant
  - `ticketlint._check_ac_count(ac_items: list[str]) -> list[Issue]` — one error when `len(ac_items) > MAX_AC`
  - `ticketlint._check_story_count(text: str) -> list[Issue]` — one error when the `## User Story` body holds more than one story shape
- Consumes: `ticket.STORY_RE`, `lintcore.section_body`, the `ac_items` list `_check_ac_present` already returns.

- [ ] **Step 0: Impact analysis before touching the module**

Run, via the GitNexus MCP:

```
impact({target: "lint", direction: "upstream"})
impact({target: "_check_ac_present", direction: "upstream"})
impact({target: "_check_story", direction: "upstream"})
```

Report the blast radius (direct callers, affected processes, risk level) before editing. Expected callers of `lint`: `cli.ticket_lint` and the `kb_ticket_lint` MCP tool — both thin wrappers whose signature does not change here. **Warn the user before proceeding if any of the three returns HIGH or CRITICAL risk.** If the MCP is unreachable, say so and continue.

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/test_ticketlint.py`:

```python
# --- PR 3: ticket size gates ------------------------------------------------


def _ac_lines(n: int) -> str:
    """`n` clean ACs: unique id, a bracketed citation, and a digit each,
    so no OTHER rule can fire on them and a size failure is unambiguous.
    Shape copied from `test_duplicate_ac_ids_fail`, minus the duplicate
    id."""
    return "\n".join(
        f"- [ ] AC{i}: Show airspace field {i} per [arinc-kb:arinc-424 §5.3]"
        for i in range(1, n + 1)
    )


def test_more_than_ten_acceptance_criteria_fail(
    fed_hub: Path, golden_block: str
):
    text = _build_ticket(
        golden_block, overrides={"## Acceptance Criteria": _ac_lines(11)}
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any(
        "Acceptance Criteria has 11 items (max 10)" in m
        for m in _errors(report)
    )


def test_exactly_ten_acceptance_criteria_pass(
    fed_hub: Path, golden_block: str
):
    """The cap is inclusive — 10 is the maximum, not the first failure."""
    text = _build_ticket(
        golden_block, overrides={"## Acceptance Criteria": _ac_lines(10)}
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert not any("(max 10)" in m for m in _errors(report))


def test_two_user_stories_fail(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## User Story": (
                "As a dispatcher, I want to see restrictive airspace "
                "details, so that I can brief the crew accurately.\n\n"
                "As a planner, I want to export the airspace list, so "
                "that I can attach it to the flight file."
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("User Story has 2 stories" in m for m in _errors(report))


def test_one_comma_rich_user_story_passes(fed_hub: Path, golden_block: str):
    """`STORY_RE` is lazy under `re.S`, so `findall` consumes exactly one
    story per match: a single story full of commas — and carrying an
    incidental 'as a' after 'I want' — must still count as 1, not 2."""
    text = _build_ticket(
        golden_block,
        overrides={
            "## User Story": (
                "As a flight dispatcher, working the evening shift, I "
                "want the restrictive airspace details, refreshed every "
                "30 s, shown as a side panel, so that I can brief the "
                "crew without reading the raw feed."
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert not any("stories" in m for m in _errors(report))
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_ticketlint.py -q -k "acceptance_criteria or user_stor"`

Expected: `test_more_than_ten_acceptance_criteria_fail` and `test_two_user_stories_fail` FAIL (`assert report.passed is False` — the ticket still passes today). `test_exactly_ten_acceptance_criteria_pass`, `test_one_comma_rich_user_story_passes` and the pre-existing `-k` matches (`test_a_single_acceptance_criterion_fails`, `test_a_one_letter_user_story_fails`, `test_a_short_but_real_user_story_passes`, `test_vague_acceptance_criteria_fail`) PASS. If any of those pre-existing tests fails, stop — the fixture is wrong, not the engine.

- [ ] **Step 3: Add `_check_story_count` after `_check_story`**

In `src/strata_kb/ticketlint.py`, directly after `_check_story` (it ends with `return issues` at line 87) and before `def _check_ac_present`, insert:

```python
def _check_story_count(text: str) -> list[Issue]:
    """One ticket, one story. Two stories under one heading make every AC
    ambiguous about which story accepts it, and the split the BA avoided
    lands on the dev instead.

    `STORY_RE.findall` is a reliable count: the pattern is lazy under
    `re.S` and ends at 'so that', so each match consumes exactly one
    story and the scan resumes past it. A single comma-rich story — even
    one saying 'shown as a side panel' after 'I want' — yields 1, because
    the incidental 'as a' sits inside the first match's span.
    """
    body = lintcore.section_body(text, "## User Story")
    if body is None:
        return []  # heading missing — already reported by check_headings
    found = len(ticket.STORY_RE.findall(body))
    if found <= 1:
        return []
    return [
        Issue(
            "error",
            f"User Story has {found} stories — one ticket per story, "
            "split the ticket",
        )
    ]
```

- [ ] **Step 4: Add `MAX_AC` and `_check_ac_count` after `_check_ac_present`**

In the same file, directly after `_check_ac_present` (it ends with `return [], items`) and before the existing `_AC_ID_RE = re.compile(r"^(AC\d+)\b", re.I)` line, insert:

```python
# Upper bound on acceptance criteria. Deliberately NOT a config key: the
# only real ticket measured so far carried 27 AC — six natural clusters
# that should have been six tickets — and a threshold tuned
# on a single sample is a guess, not a policy. Revisit when ~20 real
# tickets exist and the p90 is known.
MAX_AC = 10


def _check_ac_count(ac_items: list[str]) -> list[Issue]:
    """The ceiling that `_check_ac_present`'s 'at least 2' has no opinion
    about. More AC than a reviewer can hold in one pass is a scope
    problem, not a formatting one — the fix is a second ticket, never two
    conditions merged into one AC to duck the cap."""
    if len(ac_items) <= MAX_AC:
        return []
    return [
        Issue(
            "error",
            f"Acceptance Criteria has {len(ac_items)} items "
            f"(max {MAX_AC}) — split the ticket, one user story per "
            "ticket",
        )
    ]
```

- [ ] **Step 5: Call both from `lint()`**

In `lint()` (around lines 402–406), replace:

```python
    issues += _check_story(text)

    ac_issues, ac_items = _check_ac_present(text)
    issues += ac_issues
    issues += _check_ac_ids(ac_items)
```

with:

```python
    issues += _check_story(text)
    issues += _check_story_count(text)

    ac_issues, ac_items = _check_ac_present(text)
    issues += ac_issues
    issues += _check_ac_count(ac_items)
    issues += _check_ac_ids(ac_items)
```

- [ ] **Step 6: Run the engine suite**

Run: `uv run pytest tests/test_ticketlint.py -q`

Expected: all PASS. `test_golden_ticket_passes` (2 AC, 1 story) and `test_unticked_definition_of_ready_boxes_are_a_warning_only` are the regression pins — neither new rule may fire on the golden ticket.

- [ ] **Step 7: Run the full suite and commit**

Run: `uv run pytest -q`
Expected: all PASS — no other suite feeds `lint()` an oversized ticket.

Run `detect_changes()` via the GitNexus MCP; confirm only `ticketlint.lint`, `ticketlint._check_ac_count`, `ticketlint._check_story_count` and their tests are listed. MCP down → note it in the commit body.

```bash
git add src/strata_kb/ticketlint.py tests/test_ticketlint.py
git commit -m "feat(ticketlint): fail a ticket over 10 acceptance criteria or with two user stories"
```

---

### Task 2: Ticket template DoR line and review rubric item

**Files:**
- Modify: `src/strata_kb/templates/init/ticket-template.md`
- Modify: `src/strata_kb/templates/init/review-rubric.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: a `## Definition of Ready` checkbox the BA ticks before handover, and a `## Business coverage` rubric item the reviewer scores — both naming the same numbers as Task 1's errors.
- No engine change. `test_template_headings_match_contract` and `test_template_carries_every_recommended_heading` (in `tests/test_ticketlint.py`) count headings, not checklist rows; nothing pins the DoR item count or the template's line count, so both edits are additive and safe.

- [ ] **Step 1: Write the failing needle tests**

Append to the end of `tests/test_templates.py`:

```python
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
        "of two conditions written to stay under the cap"
    ) in _normalised(body)
```

- [ ] **Step 2: Run them to verify the failure**

Run: `uv run pytest tests/test_templates.py -q -k "size_gates or caps_the_ticket_size"`
Expected: both FAIL on the `assert ... in _normalised(...)` line. Nothing else may fail.

- [ ] **Step 3: Add the DoR checkbox**

In `src/strata_kb/templates/init/ticket-template.md`, replace:

```markdown
- [ ] Every AC is acceptance-testable; no weasel words remain (docs/ac-quality.md)
- [ ] Dependencies, NFR, UI spec, Out of scope, Test data filled or "N/A — <reason>"
```

with:

```markdown
- [ ] Every AC is acceptance-testable; no weasel words remain (docs/ac-quality.md)
- [ ] One user story and at most 10 acceptance criteria — a bigger scope is two tickets
- [ ] Dependencies, NFR, UI spec, Out of scope, Test data filled or "N/A — <reason>"
```

- [ ] **Step 4: Add the rubric checklist item**

In `src/strata_kb/templates/init/review-rubric.md`, replace:

```markdown
- [ ] Every unknown is owned: `OPEN(<owner>)` + an `## Open questions`
      row — vagueness without an owner fails this item.

## Dev implementability
```

with:

```markdown
- [ ] Every unknown is owned: `OPEN(<owner>)` + an `## Open questions`
      row — vagueness without an owner fails this item.
- [ ] One user story and ≤ 10 acceptance criteria; no AC is a compound
      of two conditions written to stay under the cap

## Dev implementability
```

- [ ] **Step 5: Run the template and init suites**

Run: `uv run pytest tests/test_templates.py tests/test_init.py tests/test_ticketlint.py -q`
Expected: all PASS. `test_review_rubric_doc_carries_both_axes_and_the_scale`, `test_ticket_template_dor_names_the_grounding_gate` and `test_both_document_templates_carry_the_review_record_section` are the pins that would catch a mis-anchored edit.

- [ ] **Step 6: Commit**

Run `detect_changes()`; only the two template resources and `tests/test_templates.py` should be listed. MCP down → note it in the commit body.

```bash
git add src/strata_kb/templates/init/ticket-template.md \
        src/strata_kb/templates/init/review-rubric.md \
        tests/test_templates.py
git commit -m "feat(templates): ticket DoR and review rubric name the one-story, 10-AC ceiling"
```

---

### Task 3: The `ba-ticket-author` wrappers teach the split before Lint

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md`
- Modify: `src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md`
- Derive: `src/strata_kb/templates/init/cursor-ba-ticket-author.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Produces: one sentence at the end of the Draft step's **AC quality bar** paragraph in the three full-content wrappers.
- Invariant preserved: `copilot-ba-ticket-author.prompt.md` and `cursor-ba-ticket-author.md` still differ only on frontmatter line 2 (`test_copilot_and_cursor_ba_sa_wrappers_differ_only_on_frontmatter_line_two`, `tests/test_templates.py:2628`). The cursor file is **derived by script**, never edited by hand.

- [ ] **Step 1: Confirm the command wrapper has no Draft step (checked, recorded here)**

`claude-command-ba-ticket-author.md` is a thin prose wrapper: it names the pipeline on one line (`Pipeline: Intake → Parent mission → Ground → Draft → Pin → Lint → …`) and then summarises the skill's hard rules as running prose. There is no numbered `4. **Draft**` step and no **AC quality bar** paragraph to extend. **Leave the file untouched** — the sentence belongs to the step it qualifies, and the command wrapper delegates that step to the skill. The needle test below therefore runs over `BA_TICKET_AUTHOR_FULL_TEMPLATES` (skill, copilot, cursor), matching the file's own existing split at line 193: *"The command variant is a thin pointer to the skill — v2 content markers only apply to the three full-content mirrors."*

- [ ] **Step 2: Write the failing needle test**

Append to the end of `tests/test_templates.py`:

```python
def test_ba_ticket_full_wrappers_teach_the_ticket_split():
    """The command wrapper is exempt: it has no Draft step to qualify,
    only a prose summary of the skill's rules (see line 193's note)."""
    for name in BA_TICKET_AUTHOR_FULL_TEMPLATES:
        assert (
            'One AC is one testable condition and one outcome; a ticket '
            'that needs more than 10 AC, or a second "As a …" story, is '
            "two tickets — split it before Lint, never merge ACs to fit."
        ) in _ba_wrapper_text(name), name
```

- [ ] **Step 3: Run it to verify the failure**

Run: `uv run pytest tests/test_templates.py -q -k teach_the_ticket_split`
Expected: FAIL on `claude-skill-ba-ticket-author.md` (the first name in the list).

- [ ] **Step 4: Extend the skill wrapper's Draft step**

In `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md`, replace:

```markdown
   **AC quality bar** — every AC must be verifiable by someone who has
   NOT read the KB. Banned weasel words per `docs/ac-quality.md`
   ("appropriate", "configured", "a subset", "responsive", …). When a
   value is not settled, write `OPEN(<owner>)` inside the AC AND add a
   row to `## Open questions` — never write vague and move on.
```

with:

```markdown
   **AC quality bar** — every AC must be verifiable by someone who has
   NOT read the KB. Banned weasel words per `docs/ac-quality.md`
   ("appropriate", "configured", "a subset", "responsive", …). When a
   value is not settled, write `OPEN(<owner>)` inside the AC AND add a
   row to `## Open questions` — never write vague and move on. One AC is
   one testable condition and one outcome; a ticket that needs more than
   10 AC, or a second "As a …" story, is two tickets — split it before
   Lint, never merge ACs to fit.
```

- [ ] **Step 5: Extend the copilot wrapper's Draft step**

In `src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md`, the **AC quality bar** paragraph is byte-identical to the skill's. Apply the exact same replacement as Step 4 — same `old` block, same `new` block.

- [ ] **Step 6: Derive the cursor wrapper**

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

- [ ] **Step 7: Run the template suite**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q`
Expected: all PASS — in particular `test_copilot_and_cursor_ba_sa_wrappers_differ_only_on_frontmatter_line_two`, `test_ba_ticket_author_templates_carry_the_v2_markers`, `test_ba_ticket_author_templates_pin_the_parallel_vs_sequential_split` and `test_ba_ticket_pipeline_line_names_the_new_step`.

- [ ] **Step 8: Commit**

Run `detect_changes()`; only the three wrapper resources and `tests/test_templates.py` should be listed. MCP down → note it in the commit body.

```bash
git add src/strata_kb/templates/init/claude-skill-ba-ticket-author.md \
        src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md \
        src/strata_kb/templates/init/cursor-ba-ticket-author.md \
        tests/test_templates.py
git commit -m "feat(ba-ticket-author): tell the BA to split before Lint, not to merge ACs to fit"
```

---

### Task 4: BA guides (EN/VI) and CHANGELOG

**Files:**
- Modify: `docs/src/guide-ba.en.md` (§6.1, lines 301–307)
- Modify: `docs/src/guide-ba.vi.md` (§6.1, lines 296–303)
- Modify: `CHANGELOG.md`
- Test: none — nothing under `tests/` reads either guide (verified by grep); the full suite is the only gate.

**Interfaces:**
- Produces: the two rules listed where the guides already list what makes the gate fail (`# 6. What the gate checks — and what it does not` → `## 6.1 Errors (the gate fails)`).
- VI stays Vietnamese; commands, section headings and `[doc-id §section]` forms stay English, as the rest of that file does.

- [ ] **Step 1: Add the two bullets to the English guide**

In `docs/src/guide-ba.en.md`, replace:

```markdown
- **Required sections present**: Summary, User Story, Background, Acceptance
  Criteria, Use cases, both Mermaid diagrams, KB context, Definition of Ready.
- **Every `## KB context` ref resolves** at its pinned hub commit. No broken or
  malformed refs.
```

with:

```markdown
- **Required sections present**: Summary, User Story, Background, Acceptance
  Criteria, Use cases, both Mermaid diagrams, KB context, Definition of Ready.
- **At most 10 acceptance criteria.** More than ten `- [ ]` items under
  `## Acceptance Criteria` fails the gate. Split the ticket — merging two
  conditions into one AC to fit under the cap is the thing the rule exists to
  stop.
- **Exactly one user story.** More than one `As a … I want … so that …` shape
  under `## User Story` fails the gate. One ticket per story.
- **Every `## KB context` ref resolves** at its pinned hub commit. No broken or
  malformed refs.
```

- [ ] **Step 2: Add the two bullets to the Vietnamese guide**

In `docs/src/guide-ba.vi.md`, replace:

```markdown
- **Có đủ các mục bắt buộc**: Summary, User Story, Background, Acceptance
  Criteria, Use cases, cả hai sơ đồ Mermaid, KB context, Definition of Ready.
- **Mọi tham chiếu trong `## KB context` phân giải được** tại commit hub đã ghim.
  Không có tham chiếu hỏng hay sai định dạng.
```

with:

```markdown
- **Có đủ các mục bắt buộc**: Summary, User Story, Background, Acceptance
  Criteria, Use cases, cả hai sơ đồ Mermaid, KB context, Definition of Ready.
- **Tối đa 10 tiêu chí chấp nhận.** Nhiều hơn mười mục `- [ ]` dưới
  `## Acceptance Criteria` sẽ làm fail cổng. Hãy tách ticket — gộp hai điều
  kiện vào một AC cho vừa mức trần chính là điều luật này sinh ra để chặn.
- **Đúng một user story.** Nhiều hơn một dạng `As a … I want … so that …` dưới
  `## User Story` sẽ làm fail cổng. Mỗi story một ticket.
- **Mọi tham chiếu trong `## KB context` phân giải được** tại commit hub đã ghim.
  Không có tham chiếu hỏng hay sai định dạng.
```

- [ ] **Step 3: Append the CHANGELOG bullet**

In `CHANGELOG.md`, replace the last `## Unreleased` bullet and the heading that follows it:

```markdown
- BA repos: `/sa-ticket-ground` now runs **inside** the BA pipelines — `ba-ticket-author` step 7 (Ground technical, after `DoR: PASS`) and `ba-mission-plan` step 5 (Ground services, after the backlog is confirmed) — instead of being a manual follow-up, and its handover ends with a fixed `## Needs input` block naming every decision still waiting for a human. The SA proposes an `OPEN` row in the parent mission's `## Technology decisions` for anything the code does not have yet and references it as `[NEW: D<n>]`; only a human flips `OPEN` to `DECIDED`. Ticket and mission templates, the review rubric, `QUICKSTART-BA.md` and both BA guides updated to match. Re-run `kb init --kind ba` to pick up the new skill and template text.

## 1.1.0 — 2026-09-21
```

with:

```markdown
- BA repos: `/sa-ticket-ground` now runs **inside** the BA pipelines — `ba-ticket-author` step 7 (Ground technical, after `DoR: PASS`) and `ba-mission-plan` step 5 (Ground services, after the backlog is confirmed) — instead of being a manual follow-up, and its handover ends with a fixed `## Needs input` block naming every decision still waiting for a human. The SA proposes an `OPEN` row in the parent mission's `## Technology decisions` for anything the code does not have yet and references it as `[NEW: D<n>]`; only a human flips `OPEN` to `DECIDED`. Ticket and mission templates, the review rubric, `QUICKSTART-BA.md` and both BA guides updated to match. Re-run `kb init --kind ba` to pick up the new skill and template text.
- `kb ticket lint` fails a ticket with more than 10 acceptance criteria, or with more than one `As a … I want … so that …` story under `## User Story`. Both are scope errors, not formatting ones: the fix is to split the ticket, never to merge two conditions into one AC to fit under the cap. The ticket template's Definition of Ready, the `ba-ticket-author` wrappers, the review rubric's Business-coverage axis and both BA guides say the same thing. Exit codes are unchanged (`1` on failure). Re-run `kb init --kind ba` to pick up the new template text.

## 1.1.0 — 2026-09-21
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: all PASS. `tests/test_readme.py` still passes — no command, option or exit code changed.

- [ ] **Step 5: Run `detect_changes()` and commit**

Run `detect_changes()` via the GitNexus MCP (`node .gitnexus/run.cjs detect-changes` from the project root if the MCP is down); confirm only `ticketlint.*` and the docs/template resources touched by Tasks 1–4 are listed, and that no execution flow outside `kb ticket lint` is affected. MCP down → note it in the commit body.

```bash
git add docs/src/guide-ba.en.md docs/src/guide-ba.vi.md CHANGELOG.md
git commit -m "docs: BA guides and CHANGELOG record the one-story, 10-AC ticket size gates"
```

---

## Self-review

| Decision | Task | Where |
|---|---|---|
| AC cap, error level, `MAX_AC = 10` module constant, no config key, comment about revisiting at ~20 real tickets | 1 | Step 4 |
| AC message shape `Acceptance Criteria has 14 items (max 10) — split the ticket, one user story per ticket` | 1 | Step 4 (f-string reproduces it verbatim); Step 1 asserts the `11 items (max 10)` prefix |
| One-story rule via `len(ticket.STORY_RE.findall(body)) > 1`, error, no escape hatch | 1 | Step 3 |
| Story message shape `User Story has 2 stories — one ticket per story, split the ticket` | 1 | Step 3; Step 1 asserts it |
| Checks placed next to their siblings, called from `lint()` right after `_check_ac_present` / `_check_story` | 1 | Steps 3–5 |
| No lower-bound change, no mission cap, no config key | Global Constraints | — |
| Tests: 11 AC → `(max 10)`; 10 AC → clean; two stories → `2 stories`; comma-rich one story → clean; citation on every fixture AC; 11 lines by comprehension | 1 | Step 1 (`_ac_lines`) |
| Template DoR line next to the ac-quality checkbox | 2 | Step 3 |
| Rubric Business-coverage item | 2 | Step 4 |
| Wrapper Draft sentence in the four wrappers | 3 | Steps 1, 4, 5, 6 |
| copilot/cursor differ only on frontmatter line 2; cursor derived by script | 3 | Step 6 |
| Needle tests: DoR line, rubric item (axis-scoped via `lintcore.section_body`), wrapper sentence over `BA_TICKET_AUTHOR_FULL_TEMPLATES` | 2, 3 | Task 2 Step 1, Task 3 Step 2 |
| Guides EN/VI in the section listing what lint checks; VI stays Vietnamese | 4 | Steps 1–2 |
| CHANGELOG bullet appended under `## Unreleased` | 4 | Step 3 |
| GitNexus `impact` on `lint`, `_check_ac_present`, `_check_story`; `detect_changes()` before each commit; MCP-down note in the commit body | 1 | Step 0, and every task's commit step |
| No version bump, no new dependency, `mdutils.py` frozen, exit codes unchanged, `<type>: <description>` commits | Global Constraints | — |

**Verified against the files at `1ef5f5e`, not assumed:**

- `ticket.STORY_RE.findall` is a sound counter. Run against the real regex: a two-story body → `2`; a one-story body with five commas → `1`; a one-story body wrapped across three lines → `1`; `"…I want to see airspace as a map layer, so that…"` (an incidental `as a` after `I want`) → `1`; and the exact comma-rich fixture used in Task 1 Step 1 → `1`. The lazy `.+?` under `re.S` ends each match at the first `so that`, and the scan resumes past it, so an inner `as a` can never open a second match. **No fallback to counting `\bas an?\s` is needed.**
- The 11-AC fixture fires no other rule: `acquality.ac_substance` returns `None`, `acquality.weasel_hits` returns `[]`, and `lintcore.BRACKET_CITE_RE` matches, for `AC1`, `AC2` and `AC11` alike.
- `cli.ticket_lint` ends with `raise typer.Exit(2 if report.stale_errors == errors else 1)` — a size error is not a stale error, so failure is exit 1.
- Nothing pins the DoR checklist length or the template's line count. `tests/test_ticketlint.py::test_template_headings_match_contract` (line 585) and `test_template_carries_every_recommended_heading` (line 1003) count `##` headings only; `test_unticked_definition_of_ready_boxes_are_a_warning_only` counts the *golden ticket fixture's* three rows, not the template's. `tests/test_init.py:880` only asserts the substring `"Definition of Ready"` is present.
- No test reads `docs/src/guide-ba.*.md`, and no build step consumes them, so Task 4 needs no test.

**Deviations from the brief, deliberate:**

1. **`claude-command-ba-ticket-author.md` is left untouched.** The brief allowed for this ("check whether it has a Draft sentence to extend or only a summary — then leave it and say so"). It has no numbered Draft step and no **AC quality bar** paragraph: it is a prose pointer that delegates the pipeline to the skill. The needle test therefore runs over `BA_TICKET_AUTHOR_FULL_TEMPLATES` (3 files), matching the file's own precedent at `tests/test_templates.py:193`.
2. **`_check_story_count` takes `text`, not the section body**, per the brief's `_check_story_count(text)` signature — it calls `lintcore.section_body(text, "## User Story")` internally, exactly as `_check_story` does. Counting over the whole ticket would miscount a story shape quoted in `## Summary` or `## Background`.
3. **The CHANGELOG bullet is appended after the existing `## Unreleased` bullets**, not inserted at the top of the section as the PR 1 plan did. The brief says "appended"; chronological order within the section is preserved.
