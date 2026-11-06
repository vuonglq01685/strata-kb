# Cross-repo stories — Phase 3: detect and propose the split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/ba-ticket-author` and `/ba-mission-plan` detect early that a need touches several dev repos and propose a split. Once someone accepts it, the agent writes a parent story plus one child per repo. The BA picker then drafts any children not written yet.

**Architecture:** Phase 3 is mostly skill text, with four small code changes that the text depends on:
1. The parent lint accepts a planned child that has no file yet, and warns when the split decision is not recorded.
2. A single ticket whose grounding spans several repos gets a warning.
3. `kb ticket check --mission` checks each `<repo>:svc.*` id against that repo's own `-code` doc.
4. The BA picker yields `ba-ticket-author <child-id>` for unwritten children.

Phases 1–2 (routing, parent format, lint, publish, roll-up) are merged and stay unchanged.

**Tech Stack:** Python 3.11+, pytest, existing strata-kb modules (`storylint`, `ticketlint`, `ticketcheck`, `ticket`, `autorun/picker`), Markdown skill templates under `src/strata_kb/templates/init/`.

**Spec:** `docs/superpowers/specs/2026-11-05-cross-repo-story-split-design.md` (§6 is this phase; §0, §4, §5 and §10 bind it).

## Global Constraints

- **Version stays `1.35.0`** (owner, after phase 2). Do not bump `pyproject.toml`, `uv.lock` or `tests/test_readme.py`. Add the phase 3 notes to the existing `## 1.35.0 — 2026-11-05` CHANGELOG entry, under its phase 2 paragraph.
- **Child id format:** `<parent-id>.<repo-id>`; a later child for the same repo is `<parent-id>.<repo-id>.<n>` with n ≥ 2. The dot separator follows spec §0, and `ticket.CHILD_ID_RE` already parses it.
- **Child headers:** `> Parent story: <parent-id> @ rev <N>` and `> Target repo: <repo-id>`. A child never carries `> Parent mission:`.
- **Propose, never silently split.** A proposal must name the child count, ids, repo, ACs (by subject), order (`Blocked by`) and evidence (spec §6, "Left to the builder").
- **Each child gets ≥ 2 ACs.** Otherwise the proposal merges it into a sibling (spec §6.3, Review I10).
- **Reject keeps one ticket.** Lint then warns `grounding touches several repos` when the grounding names more than one repo (spec §6.4).
- **Auto mode:** the agent decides and a fresh-context reviewer checks, exactly like existing auto decisions. Both are written where the BA would have accepted: the parent's `## Change log` (spec §10).
- **Mission-time parents:** `/ba-mission-plan` writes the parent at mission time and drafts no children. `/ba-ticket-author` drafts them later, when the BA picker yields them (spec §6, mission-plan paragraph).
- **`## Services & order` may cite several `<repo>:<repo>-code` docs.** `kb ticket check --mission` resolves each id in its own repo's doc (spec §6, Review I13).
- **Off-path skill edits and fixtures.** An edit to a skill's text before `## Auto mode` must also be applied to the matching pre-auto fixture in `tests/fixtures/bodies-pre-auto/`, or `test_off_path_text_is_unchanged` fails.
- **Hand-maintained copies.** Sections that exist in hand-maintained copies must stay identical. These are `claude-skill-ba-ticket-author.md`, `claude-command-ba-mission-plan.md` and the `sa-ticket-ground` wrappers; `tests/test_template_bodies.py` enforces it.
- **No new MCP tool and no new CLI command.** `kb_ticket_lint` and `kb_ticket_check` keep their phase 2 signatures, so `tests-gate/golden/mcp_tools.json` must not change. Only docstrings may change; if one does, regenerate the golden file with `UPDATE_GOLDEN=1 KB_VENV=.venv` (unset `CLAUDE_CODE_REMOTE`).
- **`ticket.py` stays a leaf module** (`tests/test_layering.py`). `storylint` must not import `ticketlint`.
- **Test gate:** the full suite (`pytest -q -n auto`) shows only the baseline failures (offline tiktoken, no docling). `ruff check`, `ruff format --check` and `pyright` must be clean.

## Review Focus

1. **A deleted child whose split row still lists ACs** must still error `split child '<id>' has no ticket file`. Only a planned row (AC cell `-`) may be unwritten. Task 1 test `test_deleted_child_with_acs_still_errors`.
2. **A planned row's AC cell filled with ids that a sibling already owns** must trigger the existing uniqueness error. The child-author run must take the next free AC numbers. Task 1 test `test_filled_planned_row_reuses_sibling_ac_errors`.
3. **A `Services & order` row qualified with a repo that is not on the `Grounded on:` line** must give an error naming the repo, not silently fall back to the first doc. Task 2 test `test_qualifier_not_on_grounded_line_errors`.
4. **A single-repo mission (one `-code` entry, unqualified ids)** must produce byte-identical check output to today. Task 2 test `test_single_repo_mission_unchanged`.
5. **A picker run where `next` is an unwritten child of a mission-blocked parent** must yield `ba-mission-plan --amend` first, never `ba-ticket-author <child>`. Task 3 test `test_blocked_parent_child_waits_for_mission_amend`.

---

### Task 1: Planned children, split-decision record, multi-repo grounding warning

**Files:**
- Modify: `src/strata_kb/storylint.py` (`lint_parent`, `_check_shape`)
- Modify: `src/strata_kb/ticket.py` (new `grounded_repos`)
- Modify: `src/strata_kb/ticketlint.py` (`lint`: warning for a ticket that is neither a parent nor a child)
- Modify: `src/strata_kb/templates/init/parent-story-template.md` (AC-cell guidance plus the split-decision line)
- Test: `tests/test_storylint.py`, `tests/test_ticketlint_family.py`, `tests/test_planingest.py`, `tests/test_planstatus_parents.py`

**Interfaces:**
- Produces: `storylint.is_planned(row: SplitRow) -> bool`, which is True when `row.acs == ()` and the AC cell is in `_NO_VALUE`.
- Produces: `ticket.grounded_repos(text: str) -> list[str]`, the distinct repo ids, in order, of the `-code` entries on the `## Technical grounding` `- Grounded on:` line (built on `grounded_entries`).
- Produces: the split-decision line format `**Split decision:** <YYYY-MM-DD> — <n> children: <ids> — evidence: <citations> — accepted by: <who>`, placed under `## Change log`. Tasks 4 and 5 write it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_storylint.py`:
```python
def test_planned_unwritten_child_lints():
    # row AC cell "-", no file → no error
    report = lint_parent(parent_with_rows([(API, "demo", "AC1, AC2"), (WEB, "web", "-")]),
                         {API: child_text(API), WEB: None}, parent_id=US1)
    assert not [i for i in report.issues if i.level == "error"]

def test_deleted_child_with_acs_still_errors():
    report = lint_parent(parent_with_rows([(API, "demo", "AC1, AC2"), (WEB, "web", "AC3, AC4")]),
                         {API: child_text(API), WEB: None}, parent_id=US1)
    assert f"split child '{WEB}' has no ticket file" in messages(report)

def test_written_child_on_planned_row_errors():
    # a file exists but its row still says "-": the AC mismatch error fires (existing rule)
    ...

def test_filled_planned_row_reuses_sibling_ac_errors():
    # WEB row filled with "AC2, AC3" while API owns AC1, AC2
    assert "AC2 is in more than one split child" in messages(report)

def test_missing_split_decision_is_a_warning():
    w = [i for i in lint_parent(no_decision_parent, kids, parent_id=US1).issues if i.level == "warning"]
    assert [i.message for i in w] == [
        "no '**Split decision:**' line under '## Change log' — record who accepted the split"
    ]
```
The helper names (`parent_with_rows`, `child_text`, `messages`) are illustrative; reuse the fixture builders `tests/test_storylint.py` already has.

In `tests/test_ticketlint_family.py`:
```python
def test_single_ticket_grounded_on_two_repos_warns():
    # Grounded on: demo:demo-code @ abc, web:web-code @ def ; no Kind, no Parent story
    assert "grounding touches several repos (demo, web) — split it into a parent story (BA Guide 3.10) or keep one ticket" in warnings

def test_child_grounded_on_two_repos_does_not_warn(): ...
def test_one_repo_grounding_does_not_warn(): ...
```
In `tests/test_planingest.py`, add `test_mission_time_parent_with_planned_children_publishes`: a parent whose rows are all `-` and that has no child files publishes. In `tests/test_planstatus_parents.py`, add `test_planned_child_reads_to_draft`: the hub row has status `to-draft`, reason `child not written yet`, and the parent reads `in progress`, `0/2 done`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_storylint.py tests/test_ticketlint_family.py tests/test_planingest.py tests/test_planstatus_parents.py -q -k "planned or deleted_child or split_decision or two_repos or one_repo"`
Expected: FAIL. The planned child errors with `has no ticket file`; the warnings are missing.

- [ ] **Step 3: Implement**

- In `storylint.lint_parent`, emit `has no ticket file` only for rows that are not `is_planned(row)`.
- `_check_shape` adds the split-decision warning when no line under `## Change log` starts with `**Split decision:**`.
- `ticketlint.lint` adds the multi-repo warning (copy exactly as in the test) when `ticket.ticket_kind(text)` is None, `ticket.parent_story_pin(text)` is None, and `len(ticket.grounded_repos(text)) >= 2`.
- In the template:
  - The AC guidance gains: "`-` while the child is planned and not written yet (a mission-time split); the child's author fills it".
  - The template ships one example line under the change-log table: `**Split decision:** <date> — <n> children: <ids> — evidence: <citations> — accepted by: <BA name | agent, reviewer agreed>`.

- [ ] **Step 4: Run the tests to verify they pass**

Run the same command. Expected: PASS. Then run `pytest tests/test_storylint.py tests/test_ticketlint_family.py tests/test_planingest.py tests/test_planstatus_parents.py tests/test_init.py tests/test_mcp.py -q`. Expected: PASS, after updating any phase 2 fixture whose parent now warns for a missing split-decision line. Prefer adding the line to the fixture over filtering the warning.

- [ ] **Step 5: Commit**: `feat: planned split children, split-decision record, multi-repo grounding warning`

---

### Task 2: `kb ticket check --mission` across several `-code` docs

**Files:**
- Modify: `src/strata_kb/ticketcheck.py` (`check`, new `_check_services_multi`)
- Test: `tests/test_ticketcheck.py`

**Interfaces:**
- Consumes: `ticket.grounded_entries(line) -> list[tuple[str | None, str, str]]`.
- Produces: unchanged `check(...)` signature. When `heading == SERVICES_HEADING` and the `Grounded on:` line has ≥ 2 `-code` entries, `check` returns `_check_services_multi(...)`. Otherwise today's path runs untouched.

- [ ] **Step 1: Write the failing tests** (fake `load_doc` per repo, as the existing mission tests in `tests/test_ticketcheck.py` do):
```python
def test_two_repo_services_each_id_resolves_in_its_own_doc():
    # Grounded on: demo:demo-code @ r1, web:web-code @ r2
    # | 1 | demo:svc.api | - | ... |   | 2 | web:svc.web | demo:svc.api | ... |
    assert check(text, load_doc=two_docs, heading=SERVICES_HEADING).ok

def test_id_in_the_wrong_repo_errors():
    # web:svc.api where svc.api exists only in demo-code
    assert any(m.startswith("[web] ") and "svc.api" in m for m in errors)

def test_qualifier_not_on_grounded_line_errors():
    assert "svc 'notify:svc.mail': repo 'notify' is not on the 'Grounded on:' line" in errors

def test_unqualified_id_resolves_in_the_first_code_entry(): ...

def test_single_repo_mission_unchanged():
    # one -code entry, unqualified ids: issues and notes equal the pre-change output
```

- [ ] **Step 2: Run the tests to verify they fail**: `pytest tests/test_ticketcheck.py -q -k "two_repo or wrong_repo or qualifier or unqualified or single_repo_mission"`. Expected: FAIL.

- [ ] **Step 3: Implement `_check_services_multi(text, entries, **kwargs) -> LintReport`**

Algorithm (the signature does not determine it):
1. Assign each table row to a repo:
   - a row whose Service cell is qualified `<repo>:svc.x` goes to that repo;
   - an unqualified row goes to the first `-code` entry's repo;
   - a qualifier naming a repo that has no entry on the line gives the error from the test, and the row is dropped.
2. For each `-code` entry, build a text that is the original with the `## Services & order` section replaced by:
   - `- Grounded on: <that one entry>`,
   - the table header,
   - that repo's rows with every `<repo>:` qualifier of this repo stripped.
3. Run the existing `check()` on that text. Prefix each issue and note with `[<repo>] `.
4. A `Depends on` id qualified with another repo is checked for existence against that repo's loaded doc (section ids). It is stripped from the per-repo text before step 3, so the step-3 check does not see it.
5. Merge the issues and notes in entry order.

- [ ] **Step 4: Run** the step 2 command, then `pytest tests/test_ticketcheck.py tests/test_cli_mission.py tests/test_mcp.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**: `feat: mission check resolves each service id in its own repo's code doc`

---

### Task 3: BA picker drafts unwritten children

**Files:**
- Modify: `src/strata_kb/autorun/picker.py` (`_ba_tasks`)
- Test: `tests/test_autorun_picker.py`

**Interfaces:**
- Consumes: `kb mission next --json` rows with `status`, `us_id`, `parent`, `is_parent`, `reasons`, `mission_id` (phase 2 shape).
- Produces: a `Task("ba-ticket-author", "<child-id>")` for each row with `status == "to-draft"` and a non-empty `parent`, scanning `(*stories, *unparented)` in that order, after the existing `next` rule.

- [ ] **Step 1: Write the failing tests**
```python
def test_unwritten_child_yields_ba_ticket_author_child():
    assert first_task(data_with_child_to_draft) == Task("ba-ticket-author", "M-x-US1.web")

def test_unparented_parent_child_yields_too():  # US-12.web in `unparented`

def test_blocked_parent_child_waits_for_mission_amend():
    # parent row reasons contain "D1 OPEN"; its child is to-draft
    assert first_task(data) == Task("ba-mission-plan", "--amend M-x")

def test_parent_row_is_never_yielded():  # is_parent rows: never draft, amend or author
```

- [ ] **Step 2: Run them**: `pytest tests/test_autorun_picker.py -q -k "child or parent"`. Expected: the first two FAIL (phase 2 skips unwritten children).

- [ ] **Step 3: Implement.**
- Drop the `unwritten_children` exclusion from the `next` rule and from the to-draft scan.
- The to-draft scan iterates `rows` (`*stories, *unparented`) and skips `is_parent` rows.
- Replace the phase 2 comment with one line: "an unwritten child is drafted like any story (phase 3)".

- [ ] **Step 4: Run** `pytest tests/test_autorun_picker.py tests/test_autorun_runner.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**: `feat: BA picker drafts unwritten split children`

---

### Task 4: `sa-ticket-ground --scope` and `/ba-ticket-author` step 1b plus child mode

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/sa-ticket-ground.md` and the wrappers that hand-copy its sections (`claude-skill-sa-ticket-ground.md`, `claude-command-sa-ticket-ground.md`; check `copilot-`/`cursor-` for an include).
- Modify: `src/strata_kb/templates/init/bodies/ba-ticket-author.md`, `claude-skill-ba-ticket-author.md`, `claude-command-ba-ticket-author.md` (argument hint), plus the matching `tests/fixtures/bodies-pre-auto/` files.
- Test: `tests/test_template_bodies.py`

**Content to add (exact strings are pinned by the tests below):**

1. **`sa-ticket-ground` `--scope "<need>"` mode**, a new `## Scope mode — --scope "<need>"` section before `## Hard rules`:
   - Read-only: no file is written.
   - Run `kb_search` with `kinds=["dev"]` (CLI: `kb query "<text>" --kind dev`) for the routes, pages, tables, jobs and services the need implies.
   - Map each hit's doc id `<repo>-code` to `<repo>`. Ignore `-svc` hits.
   - Return exactly this block:
     ```
     ## Repo scope
     | Repo | Evidence | What the need touches |
     |---|---|---|
     | <repo-id> | [<repo-id>-code §<section-id>] | <route/page/table/job/service> |
     Repos: <n>
     ```
   - No hit means `Repos: 0` (greenfield). The target is then set at grounding.
2. **`sa-ticket-ground` `--mission` multi-repo rule** (Fill, Grounded on bullet):
   - When the mission's stories touch several repos, list each repo's `<repo-id>:<repo-id>-code @ <revision>` on the one `Grounded on:` line, comma-separated.
   - Qualify every `svc.*` in the table as `<repo-id>:svc.<name>`.
   - `kb ticket check --mission` checks each id in its own repo's document.
3. **`ba-ticket-author` step `1b. **Scope by repo**`**, between Intake and Parent mission. It is skipped in child mode and in Amend mode.
   - (a) Run `/sa-ticket-ground --scope "<need>"` as a separate run.
   - (b) `Repos: 0` or `1` → today's flow. With one repo, put `> Target repo: <repo-id>` under the title.
   - (c) `Repos: ≥ 2` → present a **split proposal**:
     - the child count;
     - each child id `<parent-id>.<repo-id>`, its repo, and the ACs by subject;
     - the order as `Blocked by`;
     - the evidence rows from the Repo scope block;
     - each child gets ≥ 2 ACs, otherwise merge it into a sibling.
   - (d) The BA accepts, edits or rejects.
     - Reject → one ticket, and lint will warn `grounding touches several repos` (Task 1).
     - Accept →
       - write the parent `tickets/<folder>/<parent-id>.md` from `PARENT-TEMPLATE.md`, with the `**Split decision:**` line (Task 1 format, `accepted by: <BA name>`);
       - draft the ACs once for the whole need, numbered AC1… across the story, and distribute them by the split;
       - write each child `tickets/<folder>/<child-id>.md`, with `> Parent story: <parent-id> @ rev 1`, `> Target repo: <repo-id>` and the parent's `## User Story` copied word for word;
       - run steps 6–8 **per child**: lint with `parent_markdown`, ground on the child's own repo, maturity review;
       - lint the parent last.
   - A mission story keeps the mission id as the parent id (`<M-id>-US<n>`), with the parent file at `tickets/<M-id>/<M-id>-US<n>.md`.
4. **`ba-ticket-author` child mode**, when the argument matches `<parent-id>.<repo-id>[.<n>]` and the parent file exists:
   - Intake comes from the parent: User Story verbatim, repo and `Blocked by` from its split row, folder = the parent's folder.
   - Step 1b is skipped.
   - AC ids are the next free numbers across the whole split (the highest AC number in any row, plus 1 onwards).
   - The same change fills that split row's AC cell, replacing `-`. No parent revision bump: the row was planned, not changed.
   - The `- Blocked by:` line in `## Dependencies` equals the split row.
5. **`ba-ticket-author` Auto mode** gets two new bullets in the existing `"<gate>" → <auto rule>` form:
   - `**Step 1b: "The BA accepts, edits or rejects"**` → decide the split yourself, then have a fresh-context reviewer check it. The reviewer gets the need, the Repo scope block and your proposal, and answers agree or object with a reason. On an objection, decide once more. Write the `**Split decision:**` line with `accepted by: agent, reviewer agreed` (or `reviewer objected: <reason>; decided again`) and an `**Auto decision:**` line. Parent and children go in one PR on `auto/<parent-id>`.
   - `**Child mode: Intake from the parent**` → the runner's task `ba-ticket-author <child-id>` names the child. The branch is `auto/<child-id>`.
   - The existing **Already finished** paragraph gains one sentence. A story that became a parent is finished when its parent file is on `main` and every split child reads `ready` or `done` in `kb mission next --json`. The parent row itself reads `in progress` and never `ready`.

- [ ] **Step 1: Write the failing drift tests** in `tests/test_template_bodies.py`. Each one asserts the needle is present in the body and in each hand-maintained copy:
```python
@pytest.mark.parametrize("name", ["bodies/sa-ticket-ground.md", "claude-skill-sa-ticket-ground.md"])
def test_sa_scope_mode_returns_the_repo_scope_block(name):
    t = _normal(_raw(name))
    for needle in ['## Scope mode — `--scope "<need>"`', "| Repo | Evidence | What the need touches |",
                   "Repos: <n>", 'kinds=["dev"]', "no file is written"]:
        assert needle in t, needle

def test_sa_mission_multi_repo_qualifies_service_ids(): ...  # "<repo-id>:svc.<name>"

@pytest.mark.parametrize("name", ["bodies/ba-ticket-author.md", "claude-skill-ba-ticket-author.md"])
def test_ticket_author_scope_by_repo_step(name):
    t = _normal(_raw(name))
    for needle in ["1b. **Scope by repo**", "/sa-ticket-ground --scope", "split proposal",
                   "each child gets ≥ 2 ACs", "**Split decision:**", "grounding touches several repos",
                   "> Parent story: <parent-id> @ rev 1", "> Target repo: <repo-id>"]:
        assert needle in t, needle

def test_ticket_author_child_mode_fills_the_planned_row(name): ...  # "next free", "replacing `-`"

def test_ticket_author_auto_mode_has_split_and_child_gates():
    # via _gates(): bullets whose gate part contains "Step 1b" and "Child mode", each with " → "
```
Also add both new gate fragments to `_BA_GATES["bodies/ba-ticket-author.md"]`.

- [ ] **Step 2: Run them**: `pytest tests/test_template_bodies.py -q -k "scope or split or child_mode or multi_repo"`. Expected: FAIL.

- [ ] **Step 3: Write the text** in each body and in each hand-maintained copy. Apply every off-path edit to the matching `tests/fixtures/bodies-pre-auto/` file too.

- [ ] **Step 4: Run** `pytest tests/test_template_bodies.py tests/test_templates.py tests/test_init.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**: `feat: ba-ticket-author scopes the need by repo and proposes a parent-story split`

---

### Task 5: `/ba-mission-plan` per-story repo proposal

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/ba-mission-plan.md`, `claude-command-ba-mission-plan.md` (and any other mission-plan wrapper that hand-copies these sections), plus the matching `tests/fixtures/bodies-pre-auto/` files.
- Test: `tests/test_template_bodies.py`

**Content:**
- New step `5c. **Repos per story**`, after 5b Decide:
  - For each backlog story, read the repos `## Services & order` attributes to it, or run `/sa-ticket-ground --scope "<story title and goal>"` when the table does not say.
  - When a story touches ≥ 2 repos, present the split proposal (same contents as ba-ticket-author 1b).
  - On accept, write the parent file `tickets/<M-id>/<M-id>-US<n>.md`:
    - headers `> Kind: parent story`, `> Revision: 1`, `> Parent mission: <M-id> @ rev <N>`;
    - the story's `## User Story`;
    - one split row per child, with AC cell `-` (planned) and `Blocked by` as proposed;
    - the `**Split decision:**` line.
  - No child files are written. `/ba-ticket-author <child-id>` drafts each child later, when the BA picker yields it.
  - The story's backlog row and `## Sequencing` row are unchanged: they name the parent id.
- Ground services (step 5) wording: the multi-repo `Grounded on:` and `<repo-id>:svc.<name>` rule from Task 4 item 2.
- Auto mode gets a new bullet: `**Step 5c: "present the split proposal" / accept**` → agent plus fresh-context reviewer, as in ba-ticket-author's Step 1b rule. The parent files go in the mission's PR.

- [ ] **Step 1: Write the failing drift tests**:
  - `test_mission_plan_repos_per_story_step` with the needles `5c. **Repos per story**`, `AC cell \`-\``, `> Parent mission: <M-id> @ rev <N>`, `**Split decision:**` and `No child files are written`, checked over the body and `claude-command-ba-mission-plan.md`;
  - add the new gate to `_BA_GATES`.
- [ ] **Step 2: Run them**: `pytest tests/test_template_bodies.py -q -k "mission_plan"`. Expected: FAIL.
- [ ] **Step 3: Write the text** (body, copies, pre-auto fixture).
- [ ] **Step 4: Run** `pytest tests/test_template_bodies.py tests/test_templates.py tests/test_init.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: ba-mission-plan proposes a per-repo split per backlog story`

---

### Task 6: End-to-end on a two-dev-repo hub, guides, CHANGELOG

**Files:**
- Create: `tests/test_crossrepo_phase3_e2e.py`
- Modify: `docs/src/guide-ba.en.md`, `docs/src/guide-ba.vi.md` (§3.10), the rebuilt `docs/strata-guide-ba.en.pdf` and `docs/strata-guide-ba.vi.pdf`, and `CHANGELOG.md`

- [ ] **Step 1: Write the e2e tests.** Reuse the `fed_hub`, `_dev`, `_mirror`, `write_repo` and `context_block` helpers that `tests/test_planstatus_parents.py` imports. Use two dev repos, `demo` and `web`.
```python
def test_mission_time_parent_publishes_and_picker_drafts_children(fed_hub, tmp_path):
    # BA repo: mission M-x with backlog US1; tickets/M-x/M-x-US1.md is a parent with
    # rows M-x-US1.demo (AC "-") and M-x-US1.web (AC "-", Blocked by M-x-US1.demo); no child files
    # → `kb ticket lint` on the parent has no error; plan-ingest publishes;
    #   hub rows: both children to-draft, parent "in progress" "0/2 done";
    #   picker._ba_tasks on the local `kb mission next --json` → first task ba-ticket-author M-x-US1.demo

def test_written_child_fills_its_row_and_goes_ready(fed_hub, tmp_path):
    # write M-x-US1.demo (AC1, AC2, DoR ticked) and fill its row "AC1, AC2"
    # → parent lint passes; publish; hub: M-x-US1.demo ready, M-x-US1.web to-draft

def test_two_repo_mission_check_passes(fed_hub, tmp_path):
    # mission Services & order grounded on demo:demo-code and web:web-code with qualified ids
    # → `kb ticket check --mission` exit 0
```
- [ ] **Step 2: Run** `pytest tests/test_crossrepo_phase3_e2e.py -q`. Expected: PASS (Tasks 1–3 are in). A failure here is a defect in Tasks 1–3: fix it at its root.
- [ ] **Step 3: Docs.**
  - Guide §3.10 (en, vi) gains "How the split is proposed": the step 1b proposal, accept or reject, child mode, mission-time parents with `-` AC cells, the `**Split decision:**` line, and the auto-mode rule.
  - Remove the phase 2 sentence saying BAs write children by hand.
  - CHANGELOG: under `## 1.35.0`, add a phase 3 paragraph with bullets for the scope step, child mode, mission-time parents, the picker, the multi-repo mission check and the two new lint warnings.
  - Rebuild the PDFs: `uv run --extra docs python docs/src/build_pdf.py guide-ba.en guide-ba.vi`.
- [ ] **Step 4: Full gate.**
  - `pytest -q -n auto` (env `GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=commit.gpgsign GIT_CONFIG_VALUE_0=false GIT_CONFIG_KEY_1=tag.gpgsign GIT_CONFIG_VALUE_1=false`): only the baseline failures.
  - `ruff check`, `ruff format --check` and `pyright`: clean.
  - `env -u CLAUDE_CODE_REMOTE KB_VENV=.venv pytest tests-gate/regression/test_mcp_contract.py -q`: PASS.
- [ ] **Step 5: Commit**: `docs: phase 3 split proposal in the BA guide; e2e on a two-repo hub`
