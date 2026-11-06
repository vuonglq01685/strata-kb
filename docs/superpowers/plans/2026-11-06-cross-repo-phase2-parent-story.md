# Cross-repo Phase 2 — Parent story + child tickets — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A BA can write a parent story (index only) plus one normal child ticket per repo. Lint keeps parent and children consistent, plan-ingest publishes both and fails closed, the hub shows the story with rolled-up status, and no runner or claim ever treats a parent as a task.

**Architecture:** A new `storylint.py` owns the parent-story format (`> Kind: parent story`, `## Split` table) and the parent↔child consistency rules. `ticketlint` dispatches parents to it and runs the child rules on children. `planingest` gates parents on that lint and aborts the whole publish when any parent fails. `planstatus` and the local `kb mission next` add parent rows (roll-up, `is_parent`). Children take their `depends_on` from the split, and mission children inherit their parent's mission blockers. `picker`, claim `take` and `done` skip parents.

**Tech Stack:** Python 3.11+, typer, pydantic, starlette, jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-cross-repo-story-split-design.md` (§0 ids/headers/uniqueness, §4, §5; failure cases for phase 2). Phase 1 (routing) is merged on `main` (1.35.0).

## Global Constraints

- Version 1.35.0 → 1.36.0; CHANGELOG entry `## 1.36.0 — <date>` in the existing style.
- Parent header line: `> Kind: parent story` (header block only). Parent bug (`> Kind: parent bug`) is phase 5; this phase must reject it with error copy `parent bug is not supported yet (phase 5)`.
- Child id: `<parent-id>.<repo-id>`, a later child for the same repo `<parent-id>.<repo-id>.<n>` (n ≥ 2). Child headers: `> Parent story: <parent-id> @ rev <N>` and `> Target repo: <repo-id>`.
- Parent sections: `## User Story`, `## Split` (columns exactly `Child | Repo | AC | Blocked by | Own fix | Why`), `## Change log` (the existing 6-column table `Rev | Date | Trigger | What changed | Affected | Review`, existing triggers only). A parent has no `## Acceptance Criteria` and no `## Definition of Ready`.
- AC split cell may write `AC7 (replaces AC2)`.
- Child `- Blocked by:` ids count only as exact split ids, never through `US_ID_IN_CELL_RE` / `BARE_US_RE`.
- New status `in progress` is used for parents only. `StoryStatus` gains `is_parent: bool = False` and `parent: str = ""` (both serialised, read with `.get` by `hubapi._story`).
- plan-ingest is fail-closed: when any parent story fails lint, exit non-zero and write nothing (`PlanIngestError`, message names the parent and its first error).
- Duplicate ticket stem anywhere under `tickets/` → `PlanIngestError` naming both paths (it used to be "kept the first"); `kb ticket lint` reports the same error for the file it lints.
- BA-side behavior for repos with no parent stories is unchanged: same statuses, same published sections, same lint results.
- CI gate: `ruff check .`, `ruff format --check .`, `pyright`, `pytest -q -n auto`.

## Review Focus

1. **A parent story edited without editing its children** (an AC moved in the split but not in the child) → lint error on the parent, publish refused, and the hub keeps the last good plan. Test in Task 3.
2. **Child of a mission story** (`M-x-US3.web-app`) → backlog membership is checked against `M-x-US3`, not the child id. Its `Blocked by` sibling ids need not be in `## Sequencing`. Test in Task 2.
3. **A child whose `Blocked by` names a sibling id containing dots** (`US-12.payments-api`) → parsed as one exact id and blocks until that sibling is done. Test in Task 4.
4. **A parent file on a pre-1.36 hub or runner**: older code sees it as a normal ticket and it fails DoR there. Plan-ingest from 1.36 publishes it, so an old hub lists it as `ready`. The release note must tell users to upgrade the hub before writing parent stories. Doc check in Task 6.
5. **Two BAs, one deletes a child file while the parent still lists it** → CI lints that parent (deletes included) and fails. Test in Task 6.

---

### Task 1: Parent-story format and consistency lint (`storylint`)

**Files:**
- Create: `src/strata_kb/storylint.py`
- Modify: `src/strata_kb/ticket.py` (header helpers next to `target_header`)
- Create: `src/strata_kb/templates/init/parent-story-template.md`
- Test: `tests/test_storylint.py` (new)

**Interfaces:**
- Produces:
  ```python
  # ticket.py
  KIND_RE: re.Pattern[str]
  def ticket_kind(text: str) -> str | None             # "parent story" | "parent bug" | other | None (header block only)
  def parent_story_pin(text: str) -> tuple[str, int] | None   # from `> Parent story: X @ rev N` (rev 1 if absent)
  CHILD_ID_RE: re.Pattern[str]                          # ^<parent>\.<repo>(\.\d+)?$, parent/repo per existing id rules
  # storylint.py
  @dataclass(frozen=True)
  class SplitRow: child: str; repo: str; acs: tuple[str, ...]; replaces: dict[str, str]; blocked_by: tuple[str, ...]; own_fix: str; why: str
  def parse_split(text: str) -> list[SplitRow]
  def lint_parent(parent_text: str, children: dict[str, str | None], *, parent_id: str) -> LintReport
  def lint_child_against_parent(child_text: str, child_id: str, parent_text: str | None, parent_id: str) -> list[Issue]
  ```
  `children` maps each split child id to its text, or None when the file is missing. `LintReport` and `Issue` are the existing types from `lintcore` / `ticketlint`.
- Rules (`lint_parent` errors unless noted, copy is the implementer's but must name the ids):
  - title present; `> Kind: parent story`; `> Revision:`; `## User Story`, `## Split` and `## Change log` present; no `## Acceptance Criteria`, no `## Definition of Ready`.
  - split columns exactly as in Global Constraints. Child ids match `CHILD_ID_RE` with this parent. No duplicate child.
  - every split child file exists (children value not None);
  - an AC id is in only one live child row (a `(replaces X)` target may stay in a done child);
  - `Blocked by` ids exist in the split; no cycle (`dependency cycle: a → b → a`);
  - `planrev.check_revision` on the parent (existing triggers, 6 columns).
  - `lint_child_against_parent`: child has `> Parent story:` naming the parent; child is listed in the split; child AC ids == its split row's ACs; child `- Blocked by:` ids == split row's; `> Target repo:` == split row repo; child `## User Story` == parent's (whitespace-normalised); each child has ≥2 ACs (existing rule). Parent missing (`parent_text is None`) → error `parent story <id> not found — pass its text or keep it in the same folder`.
  - `> Kind: parent bug` → error `parent bug is not supported yet (phase 5)`.

- [ ] **Step 1: Write failing tests** in `tests/test_storylint.py`: one passing fixture (parent + two children); then one failing fixture per rule above (the test name ends with the rule, e.g. `test_ac_in_two_children_is_error`, `test_split_child_missing_file_is_error`, `test_child_blocked_by_differs_from_split_is_error`, `test_child_user_story_differs_is_error`, `test_cycle_in_split_is_error`, `test_parent_with_dor_is_error`, `test_parent_bug_not_supported`, `test_replaces_lets_old_ac_stay_in_done_child`); plus `test_parse_split_reads_dotted_ids` and `test_child_id_re`.
- [ ] **Step 2: Run** `pytest tests/test_storylint.py -q` → FAIL.
- [ ] **Step 3: Implement** using `lintcore` table/section helpers (as `missionlint` does). Write `parent-story-template.md` in the style of `ticket-template.md`, with guidance comments. Keep `ticket.py` a leaf module (see `tests/test_layering.py`).
- [ ] **Step 4: Run** `pytest tests/test_storylint.py tests/test_layering.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: parent story format and parent/child consistency lint`.

### Task 2: `kb ticket lint` and MCP — parents, children, mission children

**Files:**
- Modify: `src/strata_kb/ticketlint.py` (`lint` 696, `check_parent_mission` 484, `_check_backlog_membership` 584, `_check_blocked_by_declared` 654)
- Modify: `src/strata_kb/cli.py` (`ticket lint` command: pass the sibling files of the ticket's folder)
- Modify: `src/strata_kb/mcp.py` (`kb_ticket_lint` 330)
- Test: `tests/test_ticketlint.py`, `tests/test_cli_ticket.py`, `tests/test_mcp*.py` (extend)

**Interfaces:**
- Consumes: Task 1 (`ticket_kind`, `parent_story_pin`, `storylint.*`).
- Produces:
  - `ticketlint.lint(text, hub, *, path=None, missions_dir=None, fail_on_stale=False, ticket_id=None, load_mission=None, load_ticket: Callable[[str], str | None] | None = None) -> LintReport`. `load_ticket(id)` returns a sibling's text (parent or child) or None.
  - Dispatch: a text whose `ticket_kind` is a parent kind goes to `storylint.lint_parent`. Its children come from `load_ticket`, and a `> Parent mission:` line on the parent is checked with today's `check_parent_mission`, using the parent's own id. A text with `> Parent story:` gets the normal story lint plus `lint_child_against_parent`, with the parent from `load_ticket`.
  - Mission children (spec §5): when the child's parent has `> Parent mission: M-x`, backlog membership is checked for the **parent id**. The child itself carries no `> Parent mission:` line (lint error if it does: `a child ticket inherits its parent's mission — remove '> Parent mission:'`). `_check_blocked_by_declared` skips ids that are siblings in the parent's split.
  - CLI `kb ticket lint <file>`: `load_ticket` reads `<file's folder>/<id>.md`. A duplicate stem elsewhere under the same `tickets/` root → error `duplicate ticket id <id>: <path a>, <path b>`.
  - MCP `kb_ticket_lint(ticket_markdown, ticket_id=None, mission_markdown=None, parent_markdown=None, children_markdown: dict[str, str] | None = None)`. A child without `parent_markdown` → error `parent not given — pass parent_markdown`. A parent without `children_markdown` → its existence checks are reported as errors naming the missing children.
  - With `hub` given (CI): an id published by another BA repo's plan → error `ticket id <id> is already published by <repo>` (use `planstatus.plan_docs`).
  - With `hub` given: a parent whose id is already done in a dev repo's `-svc` history → error `<id> is already implemented — a done ticket cannot become a parent story`. Live claims live on the hub server, not in the git clone, so `kb ticket lint` adds the note `claim check skipped (needs the hub API)` instead.

- [ ] **Step 1: Write failing tests:** `test_lint_dispatches_parent_story`, `test_child_lint_runs_parent_rules`, `test_child_without_parent_text_is_error_on_mcp`, `test_mission_child_backlog_checks_parent_id` (Review Focus 2), `test_mission_child_with_parent_mission_line_is_error`, `test_sibling_blocked_by_not_required_in_sequencing`, `test_duplicate_stem_is_error`, `test_id_published_by_other_ba_repo_is_error`, `test_plain_ticket_lint_unchanged` (golden: an existing fixture gives the same issues as before).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_ticketlint.py tests/test_cli_ticket.py tests/test_mcp*.py tests/test_storylint.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: ticket lint understands parent stories and their children`.

### Task 3: plan-ingest — publish parents, fail closed, demote children

**Files:**
- Modify: `src/strata_kb/planingest.py` (`_select` 293, `run` 410)
- Modify: `src/strata_kb/planrev.py` (`demotions` 117)
- Test: `tests/test_planingest.py` (extend)

**Interfaces:**
- Consumes: Task 1–2 (`ticketlint.lint(..., load_ticket=)`, `storylint`).
- Produces:
  - `_select`: a parent publishes when its lint passes, with no DoR gate (like a mission). A child publishes when it lints, with its parent loaded, and its DoR is ticked. Parent and children of a mission story go to the parent mission's group. Other parents and children go to `TICKETS_GROUP`.
  - Fail closed: if any parent story fails lint, `run` raises `PlanIngestError("parent story <id> fails lint: <first error> — nothing published")` before writing anything (the existing doc dir stays as it was).
  - Duplicate stem → `PlanIngestError("duplicate ticket id <id>: <a>, <b>")`. This replaces today's "kept the first" skip.
  - `planrev.demotions(missions, tickets, parents: dict[str, str] | None = None)`. A child whose `> Parent story: P @ rev N` is behind P's revision, and that a later P change-log row lists in `Affected`, reads `draft` with reason `parent story rev <M> affects this ticket`. A child whose target `-svc` already lists it as done is exempt; plan-ingest has no hub, so that check is in Task 4.

- [ ] **Step 1: Write failing tests:** `test_parent_and_children_published`, `test_parent_lint_failure_publishes_nothing` (pre-existing doc dir byte-identical after the error) (Review Focus 1), `test_duplicate_stem_is_an_error`, `test_child_demoted_by_later_parent_row`, `test_child_not_in_affected_not_demoted`, `test_repo_without_parents_publishes_identically` (golden vs pre-change output).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_planingest.py tests/test_planrev*.py tests/test_ingest_seam.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: plan-ingest publishes parent stories and fails closed on an inconsistent one`.

### Task 4: Plan status — parent rows, roll-up, child dependencies

**Files:**
- Modify: `src/strata_kb/missionnext.py` (`StoryStatus` 52; `statuses` 247)
- Modify: `src/strata_kb/planstatus.py` (`_plan_repo`, `_loose_rows`, `_blocked_by_tokens`)
- Modify: `src/strata_kb/cli.py` (local `kb mission next`: read parents from `tickets/`)
- Modify: `src/strata_kb/hubapi.py` (`_story`: `.get("is_parent", False)`, `.get("parent", "")`)
- Test: `tests/test_planstatus_parents.py` (new), `tests/test_cli_mission.py` (extend)

**Interfaces:**
- Consumes: Task 1 (`ticket_kind`, `parent_story_pin`, `storylint.parse_split`), Task 3 (published layout, `planrev.demotions(..., parents=)`).
- Produces:
  - `StoryStatus.is_parent: bool = False`, `StoryStatus.parent: str = ""` (last fields).
  - Parent row: `is_parent=True`, `target_repo=None`. Status from the roll-up: `done` when every child is done; `blocked` when no child is ready and at least one is blocked; otherwise `in progress`. Reasons: `k/N done`.
  - Child row: `parent=<parent id>`. `depends_on` = split `Blocked by`, matched as exact ids (Review Focus 3), plus, for a mission child, the parent story's mission `Depends on`. A mission child also inherits its parent's D-row and open-question blockers and its demotion.
  - A split row with no published child → a child row with status `to-draft` and reason `child not written yet`.
  - Demoted child (Task 3 rule) whose target `-svc` lists it as done stays `done`.
  - Same rows from the local `kb mission next` (BA repo, reads `tickets/`) and from the hub.
  - Rows for repos without parent stories are unchanged.
  - Every consumer of status strings learns `in progress`: `planstatus.FROM_HUB_LABELS`, the planui status labels and the `kb mission next` text output.

- [ ] **Step 1: Write failing tests:** `test_parent_row_rolls_up_in_progress_done_blocked`, `test_child_depends_on_from_split_exact_dotted_ids`, `test_mission_child_inherits_mission_depends_on`, `test_unwritten_split_child_is_to_draft`, `test_done_child_not_demoted`, `test_local_mission_next_shows_parent_and_children`, `test_hubapi_story_tolerates_missing_parent_keys`, `test_plan_without_parents_unchanged` (golden).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Keep `planstatus.py` changes local to the parent/child pass. If the file passes ~600 lines, move the parent roll-up into `src/strata_kb/planparents.py`.
- [ ] **Step 4: Run** `pytest tests/test_planstatus*.py tests/test_mission_next*.py tests/test_missionnext.py tests/test_cli_mission.py tests/test_api_cloud_routes.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: plan status shows parent stories with rolled-up children`.

### Task 5: Runners and claims — a parent is never a task

**Files:**
- Modify: `src/strata_kb/autorun/picker.py` (`_dev_tasks`, `_ba_tasks` 73)
- Modify: `src/strata_kb/autorun/done.py` (`all_done`)
- Modify: `src/strata_kb/web/claim_api.py` (`take` 170)
- Test: `tests/test_autorun_picker.py`, `tests/test_autorun_done.py`, `tests/test_claim_api*.py` (extend)

**Interfaces:**
- Consumes: `StoryStatus.is_parent`, `.parent`, child `to-draft` rows (Task 4).
- Produces:
  - `_dev_tasks` never yields a row with `is_parent`.
  - `_ba_tasks` never yields `--amend <parent>`. For each child row with status `to-draft` and a `parent`, it yields `Task("ba-ticket-author", <child id>)`.
  - `all_done` for a Dev ignores `is_parent` rows. For the BA it counts them.
  - Claim `take` on a parent id → HTTP 400 `{"error": "parent_story", "detail": "<id> is a parent story — claim one of its children"}`. The runner treats it like `ClaimRejectedError` for that candidate and moves to the next one; it must not stop the runner. Add an arm next to `UnknownTicketError` in `_claim_pick`.

- [ ] **Step 1: Write failing tests:** `test_parent_never_a_dev_task`, `test_ba_tasks_draft_unwritten_children`, `test_ba_never_amends_parent`, `test_all_done_dev_ignores_parent`, `test_claim_take_parent_refused`, `test_runner_skips_parent_claim_refusal`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_autorun_*.py tests/test_claim*.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: runners and claims never take a parent story`.

### Task 6: Hub UI, CI lint of parents, docs, release

**Files:**
- Modify: `src/strata_kb/web/planui.py` (`plan_ticket_page` 267, plan pages) and its templates under `src/strata_kb/templates/web/`
- Modify: `src/strata_kb/templates/init/kb-ticket-lint.yml` (+ the repo's own `.github/workflows` copy if the drift tests require it)
- Modify: `docs/src/guide-ba.{en,vi}.md` (new "Stories across repos" section), `docs/src/guide-hub.{en,vi}.md` (upgrade note); rebuild those PDFs with `uv run --extra docs python docs/src/build_pdf.py <names>`
- Modify: `CHANGELOG.md`, `pyproject.toml`, `uv.lock`, `tests/test_readme.py` (1.36.0)
- Test: `tests/test_web_plan*.py`, `tests/test_templates.py`, `tests/test_readme.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  - Hub ticket page of a parent: the split table, with each child's repo, status, and a link to the child. A child's page links its parent and its siblings. The plan list shows the parent with `k/N done`.
  - `kb-ticket-lint.yml`: after linting changed files, also run `kb ticket lint` on every file under `tickets/` whose header has `> Kind: parent story` and that lives in a folder where any file was added, changed **or deleted** in the PR (Review Focus 5). Keep `--diff-filter=ACMR` for the per-file loop; detect folders from `--diff-filter=ACMRD`.
  - Guide (en+vi, same facts): the parent/child format with a worked example (`US-12`, `US-12.payments-api`, `US-12.web-app`), what lint checks, that publish fails closed, that runners never take a parent. Also: write parent stories only after the hub is on 1.36 (Review Focus 4).

- [ ] **Step 1: Write failing tests:** `test_parent_page_shows_split_and_children`, `test_child_page_links_parent_and_siblings`, `test_ticket_lint_workflow_lints_parents_of_deleted_children` (string needles on the rendered workflow), and the version pin at 1.36.0.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**, update the docs and CHANGELOG (with an **Upgrade.** bullet: hub first), and bump the version.
- [ ] **Step 4: Run** the full gate: `ruff check . && ruff format --check . && pyright && pytest -q -n auto` → no new failures against the pre-existing offline set.
- [ ] **Step 5: Commit** `docs: parent stories in the hub UI, CI and guides — 1.36.0`.
