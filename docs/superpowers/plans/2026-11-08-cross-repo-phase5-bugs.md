# Cross-repo stories — Phase 5: bugs across repos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A bug goes first to one first-responder repo. When that repo's Dev finds the root cause partly elsewhere, they propose child bugs. The BA turns the bug into a **parent bug**, with one child bug per repo plus the parent's own fix. The parent is done only by roll-up.

**Architecture:**
- **Format:** reuse the phase 2 parent machinery for `> Kind: parent bug`. Its `## Split` gets one extra row, for the bug itself, with `Own fix: yes|no`. Children are ordinary bugs `BUG-<n>.<repo>`, pinned with `> Parent bug: BUG-<n> @ rev N`.
- **Roll-up:** status rolls up children plus the own fix. The own fix becomes a `dev-fix-bug` task once its `Blocked by` is done.
- **Dev side:** `/dev-fix-bug` writes the child-bug proposal, records it on the hub as a Q&A question, and stops its claim. In auto mode it ends `AUTO-RESULT: blocked-split BUG-<n>`.
- **BA side:** `/ba-bug-report --child-of BUG-<n>`, reached directly or from `/ba-answer-questions`, writes the parent bug and child files.

**Tech Stack:** Python 3.11+, pytest, existing strata-kb modules (`ticket`, `storylint`, `buglint`, `planparents`, `planstatus`, `autorun/*`, `ticketqa`, `ticketclaim`), Markdown skill templates under `src/strata_kb/templates/init/`.

**Spec:** `docs/superpowers/specs/2026-11-05-cross-repo-story-split-design.md`. §9 is this phase. §0 (ids, digits-only bug numbering), §4 (parent rules, `Own fix`, roll-up), §10 (auto mode) and §11 (exact-id branch matching) bind it.

## Global Constraints

- **Version stays `1.35.0`**. Do not bump `pyproject.toml`, `uv.lock` or `tests/test_readme.py`. Phase 5 notes go into the existing `## 1.35.0 — 2026-11-05` CHANGELOG entry, after the phase 4 paragraph.
- **Ids:**
  - A child bug is `BUG-<n>.<repo-id>`, using the dot separator. A later child for the same repo is `BUG-<n>.<repo-id>.<k>`, with k ≥ 2.
  - Bug numbering ("highest `BUG-<n>.md` + 1") counts digits-only stems only (spec §0).
- **Parent bug header:** `> Kind: parent bug`. The bug keeps its id, file `tickets/bugs/BUG-<n>.md`, and its bug headers (`> Type:`, `> Severity:`, `> Revision:`, `> Target repo:` = the first-responder repo).
- **Split for a parent bug:**
  - The split has one row whose Child cell is the parent id itself. That row is the own-fix row: `Own fix` is `yes` or `no`, AC is `-`, and `Blocked by` names child ids.
  - Every other row is a child bug, with `Own fix` set to `-` and AC set to `-`. Bugs have no ACs.
- **First responder (§9):** `/ba-bug-report` asks the SA for a quick look after Intake. The SA proposes the first-responder repo, which becomes `> Target repo:`, and the BA accepts.
- **Root cause elsewhere (§9):**
  - `/dev-fix-bug` writes `rootcause.md` plus a child-bug proposal. Each proposed child carries the root cause and the reproduction steps for its repo.
  - In auto mode the run **ends** `AUTO-RESULT: blocked-split BUG-<n>`.
  - It never creates tickets.
- **Claim (§9, Review I5):** before BUG-<n> is edited into a parent, the first responder's claim is set to `stopped` with reason `split into child bugs`.
- **`/ba-bug-report --child-of BUG-<n>` writes files only.** Committing and publishing stay the BA's step (Review M11).
- **Done (§9):**
  - A parent bug is done by roll-up only: every child bug is done, and, when `Own fix: yes`, BUG-<n>'s own fix is done.
  - `close_done_tickets` and `all_done` use the roll-up.
  - A `-svc` history entry for BUG-<n> marks the own fix done, never the parent.
- **Auto mode (§10):** accepting child bugs is decided by the agent and checked by a fresh-context reviewer. Both are recorded where the BA would have accepted, on the parent bug's `## Change log`.
- **Phase 1-4 behaviour is unchanged** for parent stories, ordinary bugs and stories.
- **Layering:** `ticket.py` stays a leaf module. `storylint` must not import `ticketlint`. `ticketqa` may import `ticket`, `ticketfetch`, `planrev`, `lintcore` and `storylint`.
- **Skill text:**
  - Every off-path edit (text before `## Auto mode`) is mirrored in the matching `tests/fixtures/bodies-pre-auto/` file.
  - Hand-maintained copies (`claude-command-*` that are not include stubs) carry the same sections.
  - `ba-bug-report` has no `## Auto mode` and no pre-auto fixture; keep it that way.
- **MCP contract:** no new MCP tool. `tests-gate/golden/mcp_tools.json` changes only if a docstring changes deliberately; regenerate and review it in that case.
- **Test gate:** the full suite shows only the baseline failures. `ruff check`, `ruff format --check` and `pyright` are clean.

**Rulings made in this plan (the spec leaves these open):**
- **R1 — how the proposal travels.** The proposal reaches the BA repo as a Q&A question on BUG-<n>.
  - Question text: `Split proposal for BUG-<n>: <one line>`.
  - Context: the proposal table. `blocks`: empty.
  - Why: the Dev repo cannot write to the BA repo, and Q&A is the existing hub channel.
  - Cost if wrong: one extra question per split.
- **R2 — child bug header.** A child bug carries `> Parent bug: BUG-<n> @ rev <N>`. `ticket.PARENT_STORY_RE` and `parent_story_pin` accept both `Parent story` and `Parent bug`, so demotion and Q&A routing work unchanged. Cost if wrong: one regex.
- **R3 — the own fix is a task.**
  - A parent bug with `Own fix: yes` exposes `own_fix_ready` once every id in the own row's `Blocked by` is done and the own fix is not. The picker then yields `dev-fix-bug BUG-<n>` to the first-responder repo.
  - That runner re-takes its stopped claim; a re-take already sets it active.
  - Cost if wrong: the own fix waits for a human.
- **R4 — no rerun loop after `blocked-split`.** After a `blocked-split BUG-<n>` result, the runner persists BUG-<n> in a `waiting_split` set and skips it until the hub row reads `is_parent`. Cost if wrong: a skipped bug the BA never splits stays skipped until someone clears the state.

## Review Focus

1. **A `-svc` history entry for BUG-7** (the own fix merged) while a child is still open must leave the parent `in progress`, never `done`. Task 2 test `test_own_fix_done_alone_does_not_finish_parent_bug`.
2. **`Own fix: no`** must roll up `done` from the children alone, and must never yield an own-fix task. Task 2 test `test_own_fix_no_needs_children_only`.
3. **A parent bug split whose own-fix row is missing, or appears twice,** must fail lint and stop publish (fail closed). Task 1 tests `test_parent_bug_needs_exactly_one_own_row` and `test_parent_bug_duplicate_own_row`.
4. **A bug numbered after a child bug exists** (`BUG-7.payments-api.md` present) must get `BUG-8`, not a parse error or `BUG-7`. Task 5 drift test plus `test_next_bug_number_ignores_child_stems` (wherever numbering lives; if numbering is skill text only, pin it with a drift needle).
5. **The runner, after `blocked-split`,** must not re-run `dev-fix-bug BUG-7` on the next poll. Task 3 test `test_blocked_split_is_not_re_picked_until_parent`.

---

### Task 1: Parent bug format and lint

**Files:**
- Modify: `src/strata_kb/ticket.py` (`PARENT_STORY_RE` accepts `Parent bug`)
- Modify: `src/strata_kb/planparents.py` (`is_parent` covers `parent story` and `parent bug`; new `is_parent_bug`)
- Modify: `src/strata_kb/storylint.py` (a `lint_parent` branch for parent bugs; new `lint_bug_child_against_parent`)
- Modify: `src/strata_kb/buglint.py` (accept `> Parent bug:`; run the child checks when it is set)
- Modify: `src/strata_kb/ticketqa.py` (its parent check covers `parent bug`)
- Create: `src/strata_kb/templates/init/parent-bug-template.md`. Register it in `initcmd` as `docs/tickets/PARENT-BUG-TEMPLATE.md`, next to `PARENT-TEMPLATE.md`.
- Test: `tests/test_storylint.py`, `tests/test_buglint.py`, `tests/test_ticketlint_family.py`, `tests/test_planingest.py`, `tests/test_ticketqa.py`, `tests/test_init.py`

**Interfaces:**
- Produces:
  - `ticket.parent_story_pin(text)` returns `(parent_id, rev)` for both `> Parent story:` and `> Parent bug:`.
  - `planparents.is_parent(text)` returns True for both kinds. `planparents.is_parent_bug(text) -> bool`.
  - `storylint.own_row(rows, parent_id) -> SplitRow | None` returns the row whose child equals the parent id.
  - `storylint.lint_bug_child_against_parent(child_text, child_id, parent_text, parent_id) -> list[Issue]`.
- Parent bug lint rules, all errors:
  - every buglint rule on the parent text;
  - `## Split` and `## Change log` present; no `## User Story` required;
  - exactly one own row: error `parent bug needs exactly one split row for <id> itself (its own fix)`;
  - own row `Own fix` is `yes` or `no`: error `split row <id>: Own fix must be yes or no`;
  - child rows have `Own fix` `-`;
  - every AC cell is `-`: error `a parent bug's split has no ACs`;
  - child ids match `<parent-id>.<repo>(.k)`; Blocked by ids are in the split; no cycle;
  - every child row has a file, using phase 2's existing rule.
- Child bug rules (errors):
  - the pin names this parent;
  - `> Target repo:` equals the split row's repo;
  - the `- Blocked by:` line equals the split row.
- The phase 2 error `parent bug is not supported yet (phase 5)` is removed. Its tests change to assert the new rules.

- [ ] **Step 1: Write the failing tests.**
  - `test_parent_bug_lints` (a valid parent bug with an own row `yes` and two children);
  - `test_parent_bug_needs_exactly_one_own_row`;
  - `test_parent_bug_duplicate_own_row`;
  - `test_parent_bug_own_fix_value`;
  - `test_parent_bug_split_has_no_acs`;
  - `test_child_bug_pin_and_target_must_match`;
  - `test_parent_bug_pin_is_parsed` (`> Parent bug: BUG-7 @ rev 2` gives `("BUG-7", 2)`);
  - `test_planingest_publishes_parent_bug_and_children`;
  - `test_planingest_fails_closed_on_bad_parent_bug`;
  - `test_question_on_child_bug_goes_to_parent_bug` in ticketqa;
  - `test_init_installs_parent_bug_template`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Reuse `parse_split`, `_check_blocked_by` and `_find_cycle`. The own row is excluded from child-id checks and from the "has a ticket file" rule.
- [ ] **Step 4: Run** `pytest tests/test_storylint.py tests/test_buglint.py tests/test_ticketlint_family.py tests/test_planingest.py tests/test_ticketqa.py tests/test_init.py tests/test_layering.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: parent bug format: own-fix split row, child bugs pinned with > Parent bug`

---

### Task 2: Roll-up with the own fix; the own fix is a task

**Files:**
- Modify: `src/strata_kb/planparents.py` (`done_parents`, `family_rows`)
- Modify: `src/strata_kb/missionnext.py` (`StoryStatus.own_fix_ready: bool = False`)
- Modify: `src/strata_kb/planstatus.py` (raw `-svc` done of a parent bug counts as own-fix done, not parent done)
- Modify: `src/strata_kb/hubapi.py` (`_story` uses `.get("own_fix_ready", False)`)
- Modify: `src/strata_kb/autorun/picker.py` (`_dev_tasks` yields `Task("dev-fix-bug", <BUG-id>)` for a parent row with `own_fix_ready` and a matching `target_repo`)
- Modify: `src/strata_kb/autorun/done.py` (Dev `all_done` counts a pending own fix for its target repo)
- Test: `tests/test_planstatus_parents.py`, `tests/test_autorun_picker.py`, `tests/test_autorun_done.py`, `tests/test_api_claims.py`

**Interfaces:**
- Produces, for a parent bug's head row:
  - **Status:** `done` iff every child is done and, when `Own fix: yes`, the own fix is done. Otherwise it follows the existing `blocked` / `in progress` rules.
  - **Reasons:** `k/N done` plus `own fix done` or `own fix pending` when `Own fix: yes`.
  - **`own_fix_ready`:** True iff `Own fix: yes`, the own fix is not done, and every id in the own row's `Blocked by` is done.
  - **`target_repo`:** the parent's `> Target repo:`.
  - **JSON:** `kb mission next --json` and the hub plan JSON carry `own_fix_ready`.

- [ ] **Step 1: Write the failing tests.**
  - `test_own_fix_done_alone_does_not_finish_parent_bug`;
  - `test_own_fix_no_needs_children_only`;
  - `test_parent_bug_done_when_children_and_own_fix_done`;
  - `test_own_fix_ready_after_blockers_done`;
  - `test_picker_yields_own_fix_to_first_responder_only`;
  - `test_all_done_waits_for_pending_own_fix`;
  - `test_close_done_closes_parent_bug_claim_only_on_rollup`, through `GET /api/claims` and `close_done_tickets`, with a stopped BUG-7 claim.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** In `planstatus`, separate the raw done set from the merged one for parent bugs, so BUG-<n>'s own `-svc` entry feeds `own fix done` only.
- [ ] **Step 4: Run** `pytest tests/test_planstatus_parents.py tests/test_planstatus*.py tests/test_autorun_picker.py tests/test_autorun_done.py tests/test_api_claims.py tests/test_web_plans_parents.py -q`. Expected: PASS. Phase 2 parent-story goldens are unchanged.
- [ ] **Step 5: Commit**: `feat: parent bug rolls up children plus its own fix; own fix becomes a dev-fix-bug task`

---

### Task 3: `AUTO-RESULT: blocked-split` in the runner

**Files:**
- Modify: `src/strata_kb/autorun/claude.py` (`Kind` gains `"blocked-split"`; `parse_result` accepts `blocked-split BUG-<n>`; `prompt_for` lists the form)
- Modify: `src/strata_kb/autorun/runner.py` (`_settle`: persist the bug id in `waiting_split`, clear the task, and leave the claim phase unchanged; each poll drops ids whose hub row reads `is_parent`; the Dev pick skips the rest)
- Test: `tests/test_autorun_claude.py`, `tests/test_autorun_runner.py`

**Interfaces:**
- Produces:
  - `parse_result("AUTO-RESULT: blocked-split BUG-7")` returns `TaskResult("blocked-split", ("BUG-7",))`.
  - A malformed id falls to the existing `bad result line` failure.

- [ ] **Step 1: Write the failing tests.**
  - `test_parse_blocked_split`;
  - `test_parse_blocked_split_bad_id_is_failed`;
  - `test_blocked_split_is_not_re_picked_until_parent`, with fake claude and fake hub rows. After the result, the next pick skips BUG-7. Once BUG-7's row reads `is_parent`, the skip lifts and its own fix can be picked.
  - `test_blocked_split_survives_restart`, because the state file holds `waiting_split`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement**, using the existing task-state file and the `skip` collection already passed to the picker.
- [ ] **Step 4: Run** `pytest tests/test_autorun_claude.py tests/test_autorun_runner.py tests/test_autorun_picker.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: runner understands blocked-split and waits for the BA to split the bug`

---

### Task 4: `/dev-fix-bug` proposes child bugs

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/dev-fix-bug.md`, `claude-command-dev-fix-bug.md`, and the pre-auto fixture `tests/fixtures/bodies-pre-auto/dev-fix-bug.md`
- Test: `tests/test_template_bodies.py`, `tests/test_templates.py`

**Skill content:**
1. **Step 3 Root cause, new branch.** When the proven root cause lies wholly or partly in another dev repo:
   - Append `## Child bug proposal` to `docs/impl/<BUG-id>/rootcause.md`. It holds:
     - a table `| Child | Repo | Root cause | Reproduction | Blocked by |` (one row per repo; child id `<BUG-id>.<repo-id>`);
     - a line `Own fix: yes|no — <what this repo still fixes>`;
     - a line `Own fix blocked by: <child ids|->`.
   - Record it on the hub (R1): `kb_question_ask(ticket=<BUG-id>, question="Split proposal for <BUG-id>: <one line>", asked_by, context=<the proposal table and the two lines>, blocks="")`.
   - Set the claim: `kb claim update <BUG-id> --stopped "split into child bugs"`.
   - Never create a ticket. Never edit the bug file.
   - Interactive: tell the Dev to ask the BA to run `/ba-bug-report --child-of <BUG-id>`.
2. **Re-entry.** A `rootcause.md` with `## Child bug proposal` and the claim `stopped` means the proposal was already made. Interactive stops again. Auto ends `blocked-split` without asking again.
   - An own-fix run, in which the bug is now a parent bug and the runner yields `dev-fix-bug <BUG-id>`, re-takes the claim (it goes active).
   - It fixes only the own-fix part named in the parent's own split row, then proceeds as usual.
3. **Auto mode.** New gate bullet: `**Root cause elsewhere: "ask the BA to run /ba-bug-report --child-of"**` → write the proposal, record the question, stop the claim, then end `AUTO-RESULT: blocked-split <BUG-id>`. The Result line gains the form `AUTO-RESULT: blocked-split BUG-<n>`.

- [ ] **Step 1: Write the failing drift tests.** Needles in the body and the command copy:
  - `## Child bug proposal`
  - `Split proposal for <BUG-id>:`
  - `--stopped "split into child bugs"`
  - `AUTO-RESULT: blocked-split`
  - `/ba-bug-report --child-of`
  - `Never create a ticket`

  Add the gate to `_DEV_GATES` / `_ALL_GATES` as the existing dev-fix-bug gates do.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Write the text** into the body, the copy and the fixture.
- [ ] **Step 4: Run** `pytest tests/test_template_bodies.py tests/test_templates.py tests/test_init.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: dev-fix-bug proposes child bugs and ends blocked-split`

---

### Task 5: `/ba-bug-report`: first responder and `--child-of`

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/ba-bug-report.md`, `claude-command-ba-bug-report.md` (argument hint `[what broke | --child-of BUG-<n>]`)
- Test: `tests/test_templates.py`, `tests/test_template_bodies.py`

**Skill content:**
1. **First responder (after Intake).**
   - Run `/sa-ticket-ground --scope "<symptoms>"` as a separate run.
   - Propose the repo whose `-code` evidence matches the symptom as the first responder. The BA accepts or picks another, and that repo goes in `> Target repo:`.
   - `Repos: 0` keeps today's "ask the BA" rule.
   - This replaces "the BA chooses, never guess it from the symptom" with "the SA proposes from the evidence, the BA accepts".
2. **Numbering.** "The highest digits-only `BUG-<n>.md` stem plus one". A child stem `BUG-<n>.<repo>` is never counted.
3. **`--child-of BUG-<n>`.**
   - Read `tickets/bugs/BUG-<n>.md` and the proposal: the open Q&A question `Split proposal for BUG-<n>:` (`kb_question_list(ticket=BUG-<n>)`), or text the BA pastes.
   - Before editing, check that the first responder's claim reads `stopped` (`split into child bugs`) in `kb claim list`. If it is still active, stop and ask the Dev to stop it.
   - The BA accepts, edits or rejects the proposal. On accept:
     - Set `> Kind: parent bug` and bump `> Revision:` to N+1.
     - Add `## Split` from `docs/tickets/PARENT-BUG-TEMPLATE.md`: the own row (`Own fix`, `Blocked by` from the proposal) and one row per child.
     - Append a change-log row (trigger `scope`; Affected = the child ids) and a `**Split decision:**` line.
   - Write each child `tickets/bugs/<BUG-id>.<repo-id>.md` from `BUG-TEMPLATE.md`, with:
     - `> Type:` and `> Severity:` copied from the parent, and `> Revision: 1`;
     - `> Related ticket: <BUG-id>`, `> Target repo: <repo-id>`, `> Parent bug: <BUG-id> @ rev N+1`;
     - the `- Blocked by:` line;
     - the root cause and reproduction from the proposal.
   - Lint every child with `parent_markdown`, then the parent.
   - **Write files only. Never commit or publish.** The BA does that.
   - Answer the proposal question: `kb_question_answer(id, answer, answered_by, ticket_sections=<child ids>, answer_rev=N+1)`.

- [ ] **Step 1: Write the failing tests.** Drift needles over the body and the command copy:
  - `--child-of BUG-<n>`
  - `> Kind: parent bug`
  - `Own fix`
  - `> Parent bug: <BUG-id> @ rev`
  - `digits-only`
  - `Split proposal for BUG-<n>:`
  - `stopped`
  - `Write files only`
  - `/sa-ticket-ground --scope`

  Also add `test_next_bug_number_ignores_child_stems` as a needle if numbering is skill text only.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Write the text.** Keep `ba-bug-report` without an `## Auto mode` section.
- [ ] **Step 4: Run** `pytest tests/test_templates.py tests/test_template_bodies.py tests/test_init.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: ba-bug-report proposes the first responder and turns a bug into a parent bug with --child-of`

---

### Task 6: `/ba-answer-questions` handles a split proposal

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/ba-answer-questions.md`, `claude-command-ba-answer-questions.md`, and the pre-auto fixture
- Test: `tests/test_template_bodies.py`

**Skill content:**
- A question whose text starts `Split proposal for BUG-` is answered by running `/ba-bug-report --child-of <BUG-id>` in this run, not by the normal amend. The parent bug and child files then go into this run's branch.
- Auto-mode gate bullet: `**Split proposal: "The BA accepts, edits or rejects"**` → the agent decides and a fresh-context reviewer checks. Write an `**Auto decision:**` line and the `**Split decision:**` line on the parent bug's `## Change log`, with `accepted by: agent, reviewer agreed`.
  - On a reject, answer the question with the reason and leave the bug unsplit. The Dev's next run then reads the answer, as it does for any answered question.

- [ ] **Step 1: Write the failing drift tests.** Needles: `Split proposal for BUG-`, `/ba-bug-report --child-of`. Add the gate to `_BA_GATES`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Write the text** into the body, the copy and the fixture.
- [ ] **Step 4: Run** `pytest tests/test_template_bodies.py tests/test_templates.py tests/test_init.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: ba-answer-questions turns a split proposal into a parent bug`

---

### Task 7: End-to-end, guides, CHANGELOG

**Files:**
- Create: `tests/test_crossrepo_phase5_e2e.py`
- Modify: `docs/src/guide-ba.{en,vi}.md` and `docs/src/guide-dev.{en,vi}.md` (bugs across repos), the rebuilt PDFs, `CHANGELOG.md`

- [ ] **Step 1: Write the e2e tests** on a two-dev-repo hub. Reuse the helpers from `tests/test_crossrepo_phase3_e2e.py` and `tests/test_crossrepo_phase4_e2e.py`.
  - `test_parent_bug_flow_rolls_up`:
    - Publish BUG-7 targeted at `demo`.
    - Convert it to a parent bug with child `BUG-7.web` and own row `yes`, blocked by `BUG-7.web`. Publish.
    - Rows: BUG-7 `in progress` and not `own_fix_ready`; `BUG-7.web` `ready` for `web`.
    - Mark `BUG-7.web` done in `web-svc`: `own_fix_ready` becomes True for `demo`.
    - Mark BUG-7 done in `demo-svc`: the parent reads `done`.
  - `test_split_proposal_question_reaches_parent_bug`:
    - Ask `Split proposal for BUG-7: …` on BUG-7, then publish the parent bug and child at rev 2.
    - Answer with `ticket_sections=["BUG-7.web"]`, `answer_rev=2`. It reads `answered` only after the child is published.
- [ ] **Step 2: Run** `pytest tests/test_crossrepo_phase5_e2e.py -q`. Expected: PASS. A failure here is a defect in Tasks 1–3; fix it at its root.
- [ ] **Step 3: Docs.**
  - Guides: first responder chosen from SA evidence; the Dev's split proposal and `blocked-split`; `/ba-bug-report --child-of`; parent bug roll-up with `Own fix`; the stopped claim.
  - CHANGELOG phase 5 paragraph under `## 1.35.0`.
  - Rebuild the PDFs: `uv run --extra docs python docs/src/build_pdf.py guide-ba.en guide-ba.vi guide-dev.en guide-dev.vi`.
- [ ] **Step 4: Full gate.**
  - The full suite (with the `GIT_CONFIG_COUNT` env) shows only baseline failures.
  - ruff, format and pyright are clean.
  - `env -u CLAUDE_CODE_REMOTE KB_VENV=.venv pytest tests-gate/regression/test_mcp_contract.py tests-gate/e2e/test_server.py -q` passes.
- [ ] **Step 5: Commit**: `docs: phase 5 bugs across repos in the guides; e2e`
