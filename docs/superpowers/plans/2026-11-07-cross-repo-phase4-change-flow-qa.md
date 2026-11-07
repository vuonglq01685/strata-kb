# Cross-repo stories — Phase 4: change flow and Q&A at the parent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Describe changes at the parent and amend the affected children. Record business questions asked on a child against its parent. Let a question block sibling ACs only after someone accepts the widening. Mark a parent question answered only once every affected child is re-published. Re-check questions and the ticket revision right before a Dev merge.

**Architecture:**
- **Q&A store (`ticketqa.py`):** gains three nullable columns, added by a migration that runs inside `BEGIN IMMEDIATE`. It also gains parent routing: an ask on a child is recorded on the parent, and a list on a child includes the parent's questions. Each listed row gets a computed `blocks this ticket: yes|no` line built from normalised AC ids. A parent question's `answered` state is derived from its children's hub revisions.
- **MCP:** two new tools record a proposed block widening and its acceptance.
- **Lint:** checks that a parent change-log row's `Affected` cell names split children.
- **Skill text:** wires up the change flow (`/ba-ticket-author --amend <parent>`), the parent Q&A answer flow (`/ba-answer-questions`), the per-ticket Dev gate, and the `dev-handover` pre-merge re-check.

**Tech Stack:** Python 3.11+, sqlite3, pytest, FastMCP (existing `mcp.py`), Markdown skill templates under `src/strata_kb/templates/init/`.

**Spec:** `docs/superpowers/specs/2026-11-05-cross-repo-story-split-design.md`. §7 and §8 are this phase; §4 (demotion), §5 and §10 (auto mode) bind it.

## Global Constraints

- **Version stays `1.35.0`** (owner). Do not bump `pyproject.toml`, `uv.lock` or `tests/test_readme.py`. Phase 4 notes go into the existing `## 1.35.0 — 2026-11-05` CHANGELOG entry, after the phase 3 paragraph.
- **Q&A store columns:** nullable `asked_from TEXT`, `proposed_blocks TEXT`, `confirmed_by TEXT`. The migration checks the columns inside `BEGIN IMMEDIATE` (spec §8, Review M6). An old database keeps working and gains the columns on first open.
- **Ask on a child:** `kb_question_ask(ticket=<child>)` records the question on the **parent** (`ticket = <parent-id>`), with `asked_from = <child-id>`. `blocks` holds the asker's AC ids (spec §8).
- **List on a child:** `kb_question_list(ticket=<child>)` also returns the parent's questions, so the "already asked" check works (Review I2).
- **The Dev gate stops only when `blocks` names one of this ticket's AC ids.** Ids are compared after normalising `AC-2` → `AC2` (case-insensitive) (Review I2).
- **Proposed versus confirmed blocks.** `proposed_blocks` (sibling AC ids plus a reason) never blocks. It blocks only once `confirmed_by` is set. In `/ba-answer-questions` the BA accepts; in auto mode the agent decides and a fresh-context reviewer checks. The guide states: "Q&A names are self-declared, so `confirmed_by` is an audit trail, not an access control" (Review M7).
- **A parent question reads `answered`** only when every child in the `Affected` cell of the parent's change-log row for `answer_rev` is on the hub with `> Parent story: <parent> @ rev ≥ answer_rev`. For a parent question, `ticket_sections` is that row's `Affected` (Review C7).
- **Change flow (§7):**
  - The BA describes the change at the parent. The SA proposes which children to amend, which `.n` children to add for done children, and which children stay unchanged.
  - Once the proposal is accepted, the parent goes to rev N+1. The new row's `Affected` lists the children it touches.
  - Each listed child gets the normal amend: rev +1, trigger `scope` (or `question`), What changed `parent rev N+1: …`, one maturity round, and the DoR re-ticked.
  - A **done** child is never amended; its change becomes a new child `.n`. A **done parent** is frozen.
- **Pre-merge re-check (§8, Review I3):** right before merge, `dev-handover` re-runs `kb_question_list(ticket=<id>)` and compares the ticket's hub revision with the revision it fetched. A newly blocking question stops with `AUTO-RESULT: blocked-qa Q<id>[,…]`. A newer revision without a blocking question stops with `AUTO-RESULT: failed ticket-revised <ticket-id>` (see Ruling R1).
- **MCP contract:** this phase deliberately adds two tools (`kb_question_propose_blocks`, `kb_question_confirm_blocks`) and changes Q&A docstrings. Regenerate `tests-gate/golden/mcp_tools.json` in the task that changes the tools: `env -u CLAUDE_CODE_REMOTE UPDATE_GOLDEN=1 KB_VENV=.venv pytest tests-gate/regression/test_mcp_contract.py`. Then review the golden diff, which may only add.
- **Single-repo and non-parent behaviour is unchanged.** A question on an ordinary ticket is stored, listed and derived exactly as today, and has `asked_from = NULL`.
- **Skill text:**
  - Every off-path edit (text before `## Auto mode`) is also made in the matching `tests/fixtures/bodies-pre-auto/` file.
  - Hand-maintained copies (`claude-skill-*`, `claude-command-*`) carry the same sections. `tests/test_template_bodies.py` enforces this.
- **Layering:** `ticket.py` stays a leaf module. `ticketqa.py` may import `ticket`, `ticketfetch`, `planrev`, `lintcore` and `storylint`.
- **Test gate:** the full suite shows only the baseline failures (offline tiktoken, no docling). `ruff check`, `ruff format --check` and `pyright` are clean.

**Ruling R1 (made in this plan):** the spec says a newer revision "stops with `blocked-qa`". The runner's `blocked-qa` result must carry `Q<id>` values (`autorun/claude.py:50-53`), and a revision bump can come without any question. A bump with a blocking question still ends `blocked-qa Q<id>`. A bump without one ends `failed ticket-revised <ticket-id>`. Cost if wrong: the runner reports that case as failed rather than waiting. Demotion (§4) already keeps a revised child off the hub until it is re-published.

## Review Focus

1. **Opening an old `qa.db` from two processes at once** must not raise `duplicate column name`. The migration must be idempotent under `BEGIN IMMEDIATE`. Task 1 test `test_migration_twice_is_idempotent`.
2. **A question asked on a child whose parent is not on the hub** (the parent is demoted or unpublished) must not crash or silently record on the child. It must raise `QaError` naming the parent. Task 2 test `test_ask_on_child_without_parent_on_hub_refuses`.
3. **`blocks` written as `AC-2, ac3`** must match a child that owns `AC2` and `AC3`. Task 2 test `test_blocks_this_ticket_normalises_ac_ids`.
4. **A proposed block that is not yet confirmed** must not make a sibling's `blocks this ticket` read `yes`. Task 3 test `test_proposed_blocks_do_not_block_until_confirmed`.
5. **A parent question answered at rev 2, with only one of two Affected children re-published,** must read `waiting`, not `answered`. Task 4 test `test_parent_answer_waits_for_every_affected_child`.

---

### Task 1: Q&A store migration and new fields

**Files:**
- Modify: `src/strata_kb/ticketqa.py` (schema, `_COLUMNS`, `Question`, `_row_to_question`, `QaStore.__init__`, `ask`)
- Modify: `src/strata_kb/web/api.py` (the `/api/questions` JSON gains `asked_from`, `proposed_blocks`, `confirmed_by`)
- Test: `tests/test_ticketqa.py`, `tests/test_api_questions.py`

**Interfaces:**
- Produces: `Question` gains `asked_from: str | None = None`, `proposed_blocks: str | None = None` and `confirmed_by: str | None = None`. They are appended after `answered_at`, so positional construction stays valid. `QaStore.ask(..., asked_from: str | None = None)`.

- [ ] **Step 1: Write failing tests.**
  - `test_old_db_gains_new_columns`: create the database with the pre-phase-4 `CREATE TABLE` (copy today's schema string into the test), insert one row, open `QaStore`, then `get(1).asked_from is None` and `PRAGMA table_info` lists all three columns.
  - `test_migration_twice_is_idempotent`: open two `QaStore` objects on the same old database. Neither raises.
  - `test_ask_records_asked_from`.
  - `test_api_questions_json_has_new_fields`: the three keys are present and null for an ordinary question.
- [ ] **Step 2: Run** `pytest tests/test_ticketqa.py tests/test_api_questions.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
  - In `QaStore.__init__`, after `CREATE TABLE IF NOT EXISTS`, run in one `BEGIN IMMEDIATE` transaction: read `PRAGMA table_info(questions)`, then `ALTER TABLE questions ADD COLUMN <name> TEXT` for each of the three that is missing.
  - The new-database `CREATE TABLE` also includes the three columns.
  - `_row_to_question` reads them by position after `answered_at`.
- [ ] **Step 4: Run** `pytest tests/test_ticketqa.py tests/test_api_questions.py tests/test_web_questions.py tests/test_mcp_qa.py tests/test_autorun_qa.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: Q&A store gains asked_from, proposed_blocks, confirmed_by (migrated in place)`

---

### Task 2: Questions on a child go to its parent; per-ticket blocking

**Files:**
- Modify: `src/strata_kb/ticketqa.py` (`ask_question`, `list_questions`, `format_questions`, new `ac_ids`, new `effective_blocks`)
- Modify: `src/strata_kb/mcp.py` (docstrings of `kb_question_ask` and `kb_question_list` state the routing and the new output line)
- Test: `tests/test_ticketqa.py`, `tests/test_mcp_qa.py`; regenerate `tests-gate/golden/mcp_tools.json` (docstrings only)

**Interfaces:**
- Consumes: `ticket.parent_story_pin(text) -> tuple[str, int] | None`, `ticketfetch.find` / `read_section`, and `planrev.parse_revision`.
- Produces:
  - `ticketqa.ac_ids(text: str) -> frozenset[str]` parses `AC\d+` or `AC-\d+` in any case and normalises it to `AC<n>`.
  - `ticketqa.effective_blocks(q: Question) -> frozenset[str]` is `ac_ids(q.blocks)`, plus `ac_ids(q.proposed_blocks)` when `q.confirmed_by` is set.
  - `list_questions(..., ticket_ref=<id>)` rows gain a 4th item `blocks_this: bool | None`. It is `None` when no `ticket_ref` is given; otherwise it is `effective_blocks(q) & <that ticket's AC ids on the hub>` being non-empty.
  - `format_questions` prints `blocks this ticket: yes|no` when `blocks_this` is not None.

- [ ] **Step 1: Write failing tests.** They use a hub with a published parent `US1` and children `US1.demo` (AC1, AC2) and `US1.web` (AC3, AC4). Reuse the phase 2 family builders in `tests/test_planingest.py` and the `hub_with_ticket` / `publish_plan` helpers.
  - `test_ask_on_child_records_on_parent`: the row has `ticket == "US1"`, `asked_from == "US1.web"`, and `asked_rev` equal to the parent's hub revision.
  - `test_ask_on_child_without_parent_on_hub_refuses`: raises `QaError` matching `parent story US1 is not on the hub`.
  - `test_list_on_child_includes_parent_questions`: a question asked from `US1.demo` appears in the list for `US1.web`.
  - `test_blocks_this_ticket_normalises_ac_ids`: `blocks="AC-3, ac4"` gives `blocks_this` True for `US1.web` and False for `US1.demo`.
  - `test_ordinary_ticket_unchanged`: asking and listing a ticket that is not a child gives the same rows as before, with `blocks_this` computed against its own ACs.
  - In `tests/test_mcp_qa.py`: the output of `kb_question_list(ticket="US1.web")` contains `blocks this ticket: yes`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - In `ask_question`, read the ticket's hub section. When `parent_story_pin` is set, resolve the parent in the same BA repo, read its revision, and call `store.ask(repo, parent_id, …, asked_rev=parent_rev, asked_from=child_id)`.
  - `list_questions` with a child `ticket_ref` merges `store.list(repo, child)` and `store.list(repo, parent)`, ordered by id, with no duplicates.
  - Read the AC ids of `ticket_ref` from its hub section with `lintcore.ac_items` / `AC_ID_RE`, normalised.
- [ ] **Step 4: Run** `pytest tests/test_ticketqa.py tests/test_mcp_qa.py tests/test_api_questions.py tests/test_web_questions.py -q`. Expected: PASS. Then regenerate the golden file (docstring diff only) and run `env -u CLAUDE_CODE_REMOTE KB_VENV=.venv pytest tests-gate/regression/test_mcp_contract.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: a child's questions are recorded on its parent; list says whether a question blocks this ticket`

---

### Task 3: Proposed and confirmed block widening

**Files:**
- Modify: `src/strata_kb/ticketqa.py` (`QaStore.propose_blocks`, `QaStore.confirm_blocks`, module-level `propose_blocks`, `confirm_blocks`; `format_questions` prints `proposed blocks:` and `confirmed by:` when set)
- Modify: `src/strata_kb/mcp.py` (new tools `kb_question_propose_blocks(id: int, blocks: str, reason: str)` and `kb_question_confirm_blocks(id: int, confirmed_by: str)`, both through `_qa`)
- Modify: `tests/test_mcp.py` (the tool-name list) and regenerate the golden file
- Test: `tests/test_ticketqa.py`, `tests/test_mcp_qa.py`

**Interfaces:**
- Produces:
  - `proposed_blocks` is stored as `"<AC ids> — <reason>"`, for example `"AC2 — same minimum amount rule"`.
  - `confirm_blocks` sets `confirmed_by`. It refuses when there is no proposal, or when the question is already answered.
  - `propose_blocks` refuses on an answered question and on a reason that is empty after `strip()`. It replaces any earlier proposal and clears `confirmed_by`.
  - Both use the existing `_text` / `_name` validators and run inside `BEGIN IMMEDIATE`.

- [ ] **Step 1: Write failing tests.**
  - `test_proposed_blocks_do_not_block_until_confirmed`: propose `AC2` on a question from `US1.web`. `blocks_this` stays False for `US1.demo` until `confirm_blocks`, then becomes True.
  - `test_confirm_without_proposal_refuses`.
  - `test_propose_on_answered_refuses`.
  - `test_repropose_clears_confirmation`.
  - In `tests/test_mcp_qa.py`: a round trip through both tools, then the list output shows `proposed blocks: AC2 — …` and `confirmed by: <name>`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** as specified above.
- [ ] **Step 4: Run** the Q&A tests and `tests/test_mcp.py`. Then regenerate the golden file and check that its diff only adds the two tools and the docstring lines. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: proposed block widening blocks siblings only once confirmed`

---

### Task 4: A parent question is answered once every affected child is published

**Files:**
- Modify: `src/strata_kb/ticketqa.py` (`answer_question` validation; state derivation in `list_questions`)
- Test: `tests/test_ticketqa.py`

**Interfaces:**
- Produces:
  - **Answering a parent question:** `answer_question` on a question whose `ticket` is a parent story on the hub requires `answer_rev` and a non-empty `ticket_sections`. Each entry must match `ticket.CHILD_ID_RE` with this parent as its prefix. Otherwise it raises `QaError("parent question: ticket_sections must list the child ids of the change-log row for answer_rev")`.
  - **State of a parent question:** `open` when there is no answer. Otherwise `waiting` until the parent's hub revision is ≥ `answer_rev` **and** every id in `ticket_sections` is on the hub with `parent_story_pin(...)[1] >= answer_rev`. Then `answered`.
  - The existing `derive_state(q, hub_rev)` stays as it is for ordinary tickets.

- [ ] **Step 1: Write failing tests.**
  - `test_parent_answer_waits_for_every_affected_child`: answer at rev 2 with `["US1.demo", "US1.web"]`. Publish the parent at rev 2 and `US1.demo` pinned `@ rev 2`, with `US1.web` still `@ rev 1`. The state is `waiting`. Re-publish `US1.web` `@ rev 2` and the state becomes `answered`.
  - `test_parent_answer_needs_child_ids`: `ticket_sections=["## Acceptance Criteria"]` raises.
  - `test_ordinary_answer_state_unchanged`: the existing `derive_state` table test still passes unchanged.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Cache the child revisions per `(repo, child)` within one `list_questions` call, the same way `ticket_revision` is cached today. Make no git call.
- [ ] **Step 4: Run** `pytest tests/test_ticketqa.py tests/test_api_questions.py tests/test_web_questions.py tests/test_mcp_qa.py tests/test_autorun_qa.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: parent question reads answered only when every affected child is re-published`

---

### Task 5: Change flow at the parent (lint plus `/ba-ticket-author --amend <parent>`)

**Files:**
- Modify: `src/strata_kb/storylint.py` (`lint_parent`: rule on change-log `Affected`)
- Modify: `src/strata_kb/templates/init/bodies/ba-ticket-author.md`, `claude-skill-ba-ticket-author.md` and the pre-auto fixtures (Amend mode for a parent; Auto-mode gate)
- Test: `tests/test_storylint.py`, `tests/test_template_bodies.py`

**Interfaces:**
- Produces the lint error `change-log row <rev>: Affected '<x>' is not a child in the split`. It fires for any entry of a parent change-log row (rev ≥ 2) that is not a `## Split` child id. `-` and an empty cell are allowed.
- Produces the skill text below, which the drift tests pin.

**Skill content** goes into a new `### Amend a parent story` subsection inside `## Amend mode`:
1. The BA describes the change at the parent. `/ba-ticket-author --amend <parent-id>` reads the parent, its split and every written child.
2. Run `/sa-ticket-ground --scope "<change>"` (a separate run). Present a **change proposal**:
   - which children to amend, and which of their ACs;
   - which new children `<parent-id>.<repo-id>.<n>` to add, used for a child that is `done` in `kb mission next` and for a repo that is new to the story;
   - which children stay unchanged.

   A done child is never amended. A done parent (every child done) is frozen: a further change is a new story.
3. The BA accepts, edits or rejects. On accept:
   - bump the parent's `> Revision:` to N+1;
   - add the new children to `## Split` with AC cell `-`;
   - append one change-log row whose `Affected` lists every amended and every new child id;
   - write a `**Split decision:**` line when children were added.
4. For each amended child, run the normal Amend mode:
   - rev +1, with trigger `scope` (`question` only from `/ba-answer-questions`);
   - What changed `parent rev N+1: <what>`;
   - `> Parent story: <parent-id> @ rev N+1`;
   - one maturity round;
   - re-tick the DoR, or stop for that child when a box cannot be re-ticked.

   New children go through child mode.
5. Lint every changed child with `parent_markdown`, then lint the parent last, with `children_markdown`.

Auto-mode gate bullet: `**Amend a parent story: "The BA accepts, edits or rejects"**` → the agent decides and a fresh-context reviewer checks, as in Step 1b. Write an `**Auto decision:**` line. Parent and children go in one PR on `auto/<parent-id>`.

- [ ] **Step 1: Write failing tests.**
  - storylint: `test_change_log_affected_must_be_split_children` (an error for `US1.mobile` when that child is not in the split) and `test_change_log_affected_dash_allowed`.
  - Drift tests over the body and the skill copy, with the needles `### Amend a parent story`, `parent rev N+1:`, `A done child is never amended`, `<parent-id>.<repo-id>.<n>` and `children_markdown`.
  - Add the new gate to `_BA_GATES`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** the lint rule. Then write the text into the body, the skill copy and the pre-auto fixture.
- [ ] **Step 4: Run** `pytest tests/test_storylint.py tests/test_ticketlint_family.py tests/test_planingest.py tests/test_template_bodies.py tests/test_templates.py tests/test_init.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: amend a parent story: SA proposal, rev N+1, child amends; lint checks change-log Affected`

---

### Task 6: `/ba-answer-questions` for parent questions

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/ba-answer-questions.md`, its hand-maintained copies and the pre-auto fixture
- Test: `tests/test_template_bodies.py`

**Skill content:**
- **Walk.** A question whose ticket is a parent story is worked on the parent file. Its `asked_from` names the child that asked.
- **Triage first.** Before answering a parent question:
  - Run `/sa-ticket-ground --scope "<question>"` on the parent's children. Name the sibling ACs whose meaning the question shares.
  - When there are any, record them with `kb_question_propose_blocks(id, blocks, reason)`.
  - The BA accepts with `kb_question_confirm_blocks(id, confirmed_by=<git config user.name>)`, or declines and leaves the proposal unconfirmed.
  - State the limit: "Q&A names are self-declared, so `confirmed_by` is an audit trail, not an access control."
- **Answer once.**
  - The BA answers. The SA proposes the amendments, and the change flow in ba-ticket-author's `### Amend a parent story` runs.
  - Record with `kb_question_answer(id, answer, answered_by, ticket_sections=<the child ids in the new parent row's Affected>, answer_rev=<the new parent revision>)`.
  - The DoR stop applies to each amended child. When any child's box stays unticked, record no answer.
- **Auto mode gate bullet:** `**Triage: "The BA accepts with kb_question_confirm_blocks"**` → the agent decides, a fresh-context reviewer checks, and `confirmed_by` = `kb-auto`. The decision is logged as an `**Auto decision:**` line on the parent.

- [ ] **Step 1: Write failing drift tests.** Needles: `kb_question_propose_blocks`, `kb_question_confirm_blocks`, `an audit trail, not an access control`, `asked_from`, `ticket_sections=<the child ids`. Add the gate to `_BA_GATES`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Write the text** into the body, the copies and the fixture.
- [ ] **Step 4: Run** `pytest tests/test_template_bodies.py tests/test_templates.py tests/test_init.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: ba-answer-questions triages parent questions and answers once for every affected child`

---

### Task 7: Dev gate per ticket and the pre-merge re-check

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/{dev-implement-ticket,dev-design,dev-plan,dev-execute,dev-handover}.md`, their hand-maintained copies and the pre-auto fixtures
- Test: `tests/test_template_bodies.py`

**Skill content:**
- **The Question gate everywhere it appears.** An open or waiting question stops the flow only when its list row reads `blocks this ticket: yes`. A `no` row, for example one asked by a sibling, is read and never stops. This replaces the free-text "`blocks:` names an AC" test.
- **`dev-handover`: a new step `Pre-merge re-check`**, placed right before GATE 4 / the merge, and before `kb pr merge` in Auto mode:
  - Re-run `kb_question_list(ticket=<id>, status="all")`. Any row that is open or waiting and reads `blocks this ticket: yes` stops the merge: interactive mode tells the Dev; Auto ends `AUTO-RESULT: blocked-qa Q<id>[,…]`.
  - Fetch the ticket again with `kb_ticket_fetch`. If its `> Revision:` is higher than the revision this branch implemented, stop: interactive tells the Dev; Auto ends `AUTO-RESULT: failed ticket-revised <ticket-id>` (Ruling R1).
  - Add `ticket-revised <ticket-id>` to dev-handover's list of failed reasons in its Result line.

- [ ] **Step 1: Write failing drift tests.**
  - For each of the 5 bodies: `blocks this ticket: yes` is in the off-path text, and the old phrase "`blocks:` names an AC" is gone.
  - For dev-handover, with its copy: `Pre-merge re-check`, `kb_ticket_fetch`, `failed ticket-revised <ticket-id>`, and that the step comes before `kb pr merge` (assert the index order).
  - Update `_DEV_GATES` if a gate fragment changes.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Write the text** into the bodies, the copies and the fixtures.
- [ ] **Step 4: Run** `pytest tests/test_template_bodies.py tests/test_templates.py tests/test_init.py tests/test_autorun_claude.py -q`. Expected: PASS, and `autorun/claude.py` still parses `failed ticket-revised X` as a failed result. Add a parse test if none covers an arbitrary failed reason.
- [ ] **Step 5: Commit**: `feat: Dev gate stops only on questions blocking this ticket; handover re-checks before merge`

---

### Task 8: End-to-end, guides, CHANGELOG

**Files:**
- Create: `tests/test_crossrepo_phase4_e2e.py`
- Modify: `docs/src/guide-ba.{en,vi}.md` (§3.10 changes and Q&A at the parent), `docs/src/guide-dev.{en,vi}.md` (gate per ticket, pre-merge re-check), the rebuilt PDFs, and `CHANGELOG.md`

- [ ] **Step 1: Write the e2e tests.** They run on a hub with two dev repos and reuse the phase 3 e2e helpers in `tests/test_crossrepo_phase3_e2e.py`.
  - `test_question_from_child_blocks_sibling_only_after_confirm`: ask from `US1.web` with `blocks="AC3"`. The list for `US1.demo` reads `no`. Propose `AC2`; it still reads `no`. Confirm; it reads `yes`.
  - `test_answer_flow_answered_after_both_children_republished`:
    - Answer at parent rev 2 with Affected `US1.demo, US1.web`.
    - Re-publish via plan-ingest: parent rev 2, `US1.demo` `@ rev 2`. State `waiting`.
    - Then also `US1.web` `@ rev 2`. State `answered`.
  - `test_old_qa_db_upgrades_on_hub_open`: a hub whose `.kb-qa/qa.db` has the old schema serves `kb_question_list` without error.
- [ ] **Step 2: Run** `pytest tests/test_crossrepo_phase4_e2e.py -q`. Expected: PASS. A failure here is a defect in Tasks 1–4: fix it at its root.
- [ ] **Step 3: Docs.**
  - Guides:
    - change at the parent: SA proposal, rev N+1, child amends, and done children becoming `.n`;
    - questions on a child recorded on the parent;
    - proposed versus confirmed blocks, with the audit-trail sentence verbatim;
    - when a parent question reads answered;
    - the Dev gate per ticket and the pre-merge re-check.
  - CHANGELOG: a phase 4 paragraph and bullets under `## 1.35.0`, including "the Q&A store gains three nullable columns on first open; no action needed".
  - Rebuild the PDFs: `uv run --extra docs python docs/src/build_pdf.py guide-ba.en guide-ba.vi guide-dev.en guide-dev.vi`.
- [ ] **Step 4: Full gate.**
  - The full suite (with the `GIT_CONFIG_COUNT` env) shows only baseline failures.
  - ruff, format and pyright are clean.
  - `env -u CLAUDE_CODE_REMOTE KB_VENV=.venv pytest tests-gate/regression -q` shows only the regression failures that need offline tiktoken. The MCP contract test passes.
- [ ] **Step 5: Commit**: `docs: phase 4 change flow and Q&A at the parent in the guides; e2e`
