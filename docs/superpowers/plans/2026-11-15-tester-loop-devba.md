# Tester Loop Block 1 (Dev/BA side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the loop "Tester FAIL → Dev fixes → Tester retests" and "regression defect → BA bug → Dev", by hand and in `kb auto` for BA and Dev.

**Architecture:** A new `reportfetch.py` (fetch a published report + images, CLI + MCP), a new `bugcandidates.py` (open/logged bug candidates over the hub or the hub API), `--fixes R<n>` in `svcnote`, reopened-aware Dev picking/done/claims, BA candidate picking, a closed-story check in `ticketlint`, and skill-body changes for Dev fix mode and BA `--from-report`.

**Tech Stack:** Python 3.12, typer, starlette, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-15-tester-loop-devba-design.md` (base: `docs/superpowers/specs/2026-11-14-tester-role-design.md` D3, D6, D11).

## Global Constraints

- Version 1.37.2 → 1.37.3 in this block (pyproject, uv.lock strata-kb entry, CHANGELOG `## 1.37.3 — 2026-11-15`, tests/test_readme.py). Tag only after block 3.
- No change to hub status derivation (`testflow.story_test_status`, `planstatus`).
- Dev pick order: reopened story children / unsplit stories, then reopened bugs, then ready bugs, then ready unparented tickets, then ready stories.
- Reopened ignores `depends_on`. Reopened `BUG-*` ids go to `dev-fix-bug`; others to `dev-implement-ticket`.
- `--fixes` value matches `R[1-9][0-9]*`; stored in refs as `fix:R<n>` (existing `missionnext._FIX_REF_RE`).
- `--from-report` argument: `<story> R<n> RD<k>`; bug header line: `> From report: <story> R<n> RD<k>`.
- Closed-story lint message: `story is closed — write a new story`; hub unreachable → warning.
- Every id from a CLI/URL/hub value checked with `planstatus.safe_name` before it becomes a path.
- Tests run with `GIT_CONFIG_GLOBAL=<scratchpad>/test-gitconfig` (env; see SDD contract).

## Review Focus

1. `kb report fetch` for a story with no published report, or a round that does not exist → exit 1 listing the rounds that exist; no file written (Task 1).
2. `kb svc note --fixes R2` re-run on a row that already has `fix:R1` and domain refs → keeps both, no duplicate `fix:R2` (Task 2).
3. A reopened child routed to another Dev repo → not picked here, and `all_done` for this repo is unaffected (Task 3).
4. Two candidates with the same `RD1` in different rounds → each maps to its own failure key; logging one leaves the other open (Task 5).
5. A ticket at its published revision under a closed story (CI re-lints parents) → passes lint (Task 7).

---

### Task 1: `kb report fetch` and MCP `kb_report_fetch`

**Files:**
- Create: `src/strata_kb/reportfetch.py`
- Modify: `src/strata_kb/cli.py` (`report_app` command `fetch`), `src/strata_kb/mcp.py` (tool next to `kb_ticket_fetch`), `src/strata_kb/templates/init/impl-gitignore.txt`
- Test: `tests/test_reportfetch.py`

**Interfaces:**
- Produces:
  - `class ReportFetchError(KbError)`
  - `rounds(hub: HubHandle, story: str) -> list[int]` — published rounds, ascending.
  - `render(hub: HubHandle, story: str, round_: int | None = None) -> tuple[int, str]` — (round, markdown with a provenance line `> Fetched from hub: <repo>:<doc> §<story>.R<n> @ <hub-rev7> — do not edit.` under the H1).
  - `assets_of(hub: HubHandle, story: str, round_: int) -> list[Path]` — image files under the `-test` doc's `assets/` that the report references (same refusals as `ticketfetch.split_assets`: symlink, outside folder).
  - CLI `kb report fetch <story> [--round N] [--child ID] [--out DIR] [--hub HUB] [--kb-dir]`: writes `<dir>/report-R<n>.md` and `<dir>/assets/…`; `<dir>` = `--out`, else `docs/impl/<child>/` with `--child`, else `docs/impl/<story>/`. Prints the written path.
  - MCP `kb_report_fetch(story: str, round: int | None = None) -> str` — the rendered markdown (no files).

- [ ] **Step 1: Failing tests** (use `plan_hub` + `publish_tests` from tests/test_testflow.py; `_text(STORY, n, verdict)` builds reports)

```python
def test_render_latest_round_with_provenance(plan_hub):
    publish_tests(plan_hub.root, "tester-one", STORY, _text(STORY, 1, "FAIL"), _text(STORY, 2, "FAIL"))
    n, text = reportfetch.render(plan_hub, STORY)
    assert n == 2 and f"§{STORY}.R2" in text and "do not edit" in text

def test_render_round_and_unknown_round(plan_hub):
    publish_tests(plan_hub.root, "tester-one", STORY, _text(STORY, 1, "FAIL"))
    assert reportfetch.render(plan_hub, STORY, 1)[0] == 1
    with pytest.raises(reportfetch.ReportFetchError, match="R1"):
        reportfetch.render(plan_hub, STORY, 5)

def test_no_report_and_unsafe_story(plan_hub):
    with pytest.raises(reportfetch.ReportFetchError): reportfetch.render(plan_hub, STORY)
    with pytest.raises(reportfetch.ReportFetchError): reportfetch.render(plan_hub, "../x")

def test_cli_writes_child_dir(plan_hub, tmp_path, monkeypatch):
    # cwd tmp_path; `kb report fetch STORY --child STORY.web --hub <root>` -> docs/impl/STORY.web/report-R1.md exists, exit 0
    ...

def test_cli_unknown_round_writes_nothing(plan_hub, tmp_path, monkeypatch):
    # --round 9 -> exit 1, output names the existing rounds, no docs/impl dir
    ...

def test_impl_gitignore_ignores_reports():
    text = resources.files("strata_kb.templates.init").joinpath("impl-gitignore.txt").read_text()
    assert "report-R*.md" in text
```

- [ ] **Step 2: Run** `uv run pytest tests/test_reportfetch.py -q` — FAIL.
- [ ] **Step 3: Implement** with `testflow._test_docs` / `testflow.section_text` for the section, `gitio.head_commit(hub.root)[:7]` for the rev, and the image regex/asset copy pattern of `ticketfetch.split_assets`. `--hub` option: `envvar="STRATA_KB_HUB"` like `ticket fetch`. MCP tool copies `kb_ticket_fetch`'s shape (`_hub` resolution, error string on `ReportFetchError`). Add `report-R*.md` (and its `assets/` if impl-gitignore lists ticket assets the same way) to `impl-gitignore.txt`.
- [ ] **Step 4: Run** the tests + `tests/test_mcp*.py` + `tests/test_init*.py` — PASS.
- [ ] **Step 5: Commit** `feat: kb report fetch and kb_report_fetch`.

---

### Task 2: `kb svc note --fixes R<n>`

**Files:**
- Modify: `src/strata_kb/svcnote.py` (`add_note`), `src/strata_kb/cli.py` (`svc_note`)
- Test: `tests/test_svcnote.py`

**Interfaces:**
- Produces: `svcnote.add_note(kb_dir, repo_id, service, note, fixes: str = "") -> SvcNoteReport` — when `fixes` is set: validates `R[1-9][0-9]*` (`SvcNoteError` otherwise), merges the existing row's refs (if the ticket already has a row) with `note.refs` and `fix:<fixes>`, de-duplicated, order kept (existing first). Without `fixes`, a re-run still keeps existing `fix:R<m>` refs (merge rule applies to `fix:` refs always). CLI option `--fixes R<n>`.

- [ ] **Step 1: Failing tests**

```python
def test_fixes_appends_fix_ref(tmp_kb):            # first note refs "svc.a" -> second with fixes="R1" -> refs contain "svc.a" and "fix:R1"
def test_fixes_rerun_keeps_both_no_duplicate(tmp_kb):  # R1 then R2 then R2 -> "fix:R1", "fix:R2" once each
def test_plain_rerun_keeps_fix_refs(tmp_kb):        # after fix:R1, a re-run without fixes keeps fix:R1
def test_bad_round_rejected(tmp_kb):                # fixes="2", "R0", "R01" -> SvcNoteError
def test_hub_reads_fix_done(...):                   # missionnext.fix_rounds_from_history on the written history.md -> {ticket: {1}}
def test_cli_fixes_option(tmp_path):                # CliRunner `kb svc note <svc> --ticket T --title t --fixes R1` exit 0
```
(Use the existing test_svcnote fixtures for a `-svc` doc with a service.)

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** `tests/test_svcnote.py tests/test_missionnext.py` — PASS.
- [ ] **Step 5: Commit** `feat: kb svc note --fixes R<n>`.

---

### Task 3: Dev side treats reopened as open work

**Files:**
- Modify: `src/strata_kb/autorun/picker.py` (`_dev_tasks`, new `reopened_here`), `src/strata_kb/autorun/done.py` (`all_done`), `src/strata_kb/autorun/runner.py` (`_still_ready_here`), `src/strata_kb/web/claim_api.py` (`close_done_tickets`)
- Test: `tests/test_autorun_picker.py`, `tests/test_autorun_done.py` (or the existing files that test these; find them), `tests/test_claim_api.py`

**Interfaces:**
- Produces:
  - `picker.reopened_here(t: StoryStatus, repo_id: str) -> bool` — `t.test_status == "reopened"`, not `t.is_parent`, `t.target_repo in (repo_id, None)`.
  - `_dev_tasks` yields, before every ready task: reopened non-bug rows (`dev-implement-ticket`), then reopened `BUG-` rows (`dev-fix-bug`), in plan order; `depends_on` ignored for them.
  - `all_done`: for the Dev (`not ba`), a ticket is open when `status != "done"` **or** `test_status == "reopened"` (reason text `"<id> reopened"`). BA rule unchanged here (Task 6 adds candidates).
  - `_still_ready_here`: true for `runnable_here(t) or reopened_here(t)`.
  - `close_done_tickets`: a row closes a Dev claim only when `status == "done"` and `test_status != "reopened"`.

- [ ] **Step 1: Failing tests**

```python
def test_reopened_child_picked_before_ready():   # rows: ready S2 (routed here), done+reopened S1.web (here) -> first Task("dev-implement-ticket","S1.web")
def test_reopened_bug_goes_to_fix_bug_after_stories():  # reopened BUG-3 + reopened S1.web -> S1.web first, then Task("dev-fix-bug","BUG-3")
def test_reopened_other_repo_not_picked():       # target_repo "dev-two" -> no task for "dev-one"
def test_reopened_ignores_depends_on():          # reopened row whose depends_on is not done -> still picked
def test_reopened_parent_not_picked():           # is_parent reopened row -> skipped, its reopened child picked
def test_all_done_false_while_reopened():        # every row done, one reopened routed here -> (False, "S1.web reopened"); routed elsewhere -> True
def test_close_done_keeps_reopened_claim(...):   # held Dev claim on a reopened row survives a listing
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** `tests/test_autorun*.py tests/test_claim*.py` — PASS.
- [ ] **Step 5: Commit** `feat: dev auto picks reopened tickets first`.

---

### Task 4: Dev skill fix mode and `--fixes` handover

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/dev-implement-ticket.md`, `bodies/dev-fix-bug.md`, `bodies/dev-handover.md`
- Test: `tests/test_template_bodies.py` or a new `tests/test_dev_fix_mode.py` (follow the existing body-assertion pattern)

**Interfaces:**
- Consumes: Task 1 CLI `kb report fetch <story> --child <id>` / MCP `kb_report_fetch`; Task 2 `kb svc note … --fixes R<n>`.
- Produces (skill text, asserted by tests):
  - `dev-implement-ticket` and `dev-fix-bug`: a `## Fix mode (reopened)` section. Trigger: the ticket's row in `kb mission next --from-hub --json` has `"test_status": "reopened"`. Steps: `kb report fetch <story> --child <id>` (story = the row's `parent` or the id itself) → for each defect with `Guilty: <id>`: reproduce as a failing test → root cause → fix → full suite → `/dev-handover` with `--fixes R<n>`; defects of other children listed, untouched; no design/plan stage; branch `fix/<id>-R<n>`; PR title `fix(<id>): R<n> defects D<k>[, D<k>]`.
  - Auto mode in both: same steps; the "Already finished" check in fix mode looks for a history row whose refs contain `fix:R<n>`.
  - `dev-handover`: in fix mode passes `--fixes R<n>` (round from the fetched `report-R<n>.md` name) to `kb svc note`; its own "Already finished" check uses `fix:R<n>` in fix mode.

- [ ] **Step 1: Failing tests** asserting each phrase: `## Fix mode (reopened)`, `"test_status": "reopened"`, `kb report fetch`, `--child`, `Guilty:`, `fix/<id>-R<n>`, `--fixes R<n>`, `fix:R<n>`, and that `dev-implement-ticket` fix mode says no design or plan stage.
- [ ] **Step 2: Run** — FAIL. **Step 3: Write** the sections (follow the existing body style; keep the existing steps untouched). Check the auto-mode allowlist pin test still passes (`kb report *` must be allowed for dev; add `Bash(kb report fetch*)` to the dev auto allowlist in `initcmd` if a test pins it).
- [ ] **Step 4: Run** `tests/test_template_bodies.py tests/test_init_settings.py tests/test_dev_fix_mode.py` — PASS.
- [ ] **Step 5: Commit** `feat: dev fix mode for reopened tickets`.

---

### Task 5: Bug candidates — logged vs open

**Files:**
- Create: `src/strata_kb/bugcandidates.py`
- Modify: `src/strata_kb/web/api.py` (`known_failures` adds `logged`), `src/strata_kb/web/testui.py` (candidates filter shows open only), `src/strata_kb/hubapi.py` (`known_failures()`), `src/strata_kb/buglint.py` (accept/check `> From report:`), `src/strata_kb/templates/init/bug-template.md` (commented optional header line)
- Test: `tests/test_bugcandidates.py`, `tests/test_web_tests.py`, `tests/test_buglint.py`

**Interfaces:**
- Produces:
  - `FROM_REPORT_RE = re.compile(r"^>\s*From report:\s*(\S+)\s+R([1-9]\d*)\s+(RD[1-9]\d*)\s*$", re.M)` (in `buglint`, reused here).
  - `@dataclass(frozen=True) class Candidate: key: str; story: str; round: int; rd_id: str; logged: bool`
  - `bugcandidates.candidates(hub: HubHandle) -> list[Candidate]` — `testflow.known_failures(load_facts)` entries; `logged` when a published bug section on the hub (plan doc sections with id starting `BUG-`) has a `> From report:` line whose `(story, round, rd_id)` resolves (via the published reports) to the same key.
  - `bugcandidates.open_candidates(hub: HubHandle | HubApi, plan_stories: set[str] | None = None) -> list[Candidate]` — not logged; with `plan_stories`, only candidates whose failing key's story (`key.split("/")[0]`) is in it. For `HubApi`, reads `HubApi.known_failures()`.
  - `HubApi.known_failures() -> dict[str, dict]` — GET `/api/tests/known-failures`.
  - API JSON per key gains `"logged": bool` (still lists logged keys: the Tester's regression guard needs them).
  - `buglint`: a `> From report:` header line must match `FROM_REPORT_RE`, else error `'> From report:' must be '<story> R<n> RD<k>'`.

- [ ] **Step 1: Failing tests**

```python
def test_candidate_open_until_bug_cites_it(plan_hub):  # FAIL report with RD1 -> one open candidate; publish a BUG ticket with "> From report: <story> R1 RD1" -> logged True, open_candidates empty
def test_same_rd_id_other_round_stays_open(plan_hub):  # RD1 in R1 (key A) and RD1 in R2 (key B); bug cites R1 RD1 -> A logged, B open
def test_api_known_failures_has_logged(web_client_logged_in, plan_hub)
def test_test_report_candidates_hide_logged(web_client_logged_in, plan_hub)
def test_buglint_from_report_shape(): # valid passes; "> From report: S RD1" -> error
def test_hubapi_known_failures(monkeypatch)  # stub _json -> dict returned
```
(Publishing a bug: reuse the planingest/plan_hub helpers that publish ticket sections; see tests/test_planstatus.py `publish_ba` and tests for `BUG-` tickets.)

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** (`bugcandidates` imports `planstatus`, `testflow`; neither imports it). **Step 4: Run** the three test files + `tests/test_hubapi.py` — PASS.
- [ ] **Step 5: Commit** `feat: bug candidates know when a bug logged them`.

---

### Task 6: BA picks and drafts bugs from candidates

**Files:**
- Modify: `src/strata_kb/autorun/picker.py` (`pick_ba` gains candidates), `src/strata_kb/autorun/runner.py` (`_task_for` BA branch, `_check_done` BA candidates count), `src/strata_kb/autorun/done.py` (`all_done(..., open_candidates: int = 0)`), `src/strata_kb/templates/init/bodies/ba-bug-report.md` (`--from-report` + Auto mode), BA allowlist in `initcmd` if pinned
- Test: `tests/test_autorun_picker.py`, `tests/test_autorun_done.py`, `tests/test_template_bodies.py` (or the BA skill test file)

**Interfaces:**
- Consumes: Task 5 `open_candidates`, Task 1 `kb report fetch`.
- Produces:
  - `picker.pick_ba(root, kb_dir, run=subprocess.run, skip=(), candidates: Sequence[Candidate] = ()) -> Task | None` — after mission blockers, before draft amends: `Task("ba-bug-report", f"--from-report {c.story} R{c.round} {c.rd_id}")` per candidate (skip keys honoured).
  - Runner BA: `candidates = bugcandidates.open_candidates(hub, plan_stories)` where `plan_stories` = every us_id of `picker.plan_next(hub)` rows of this BA repo; read failures → no candidates (log warning, never fail the pick).
  - `all_done(..., open_candidates=n)`: BA not done while `n > 0` (reason `"<n> open bug candidate(s)"`).
  - `ba-bug-report` body: `## --from-report <story> R<n> RD<k>` section — `kb report fetch <story> --round <n> --out <tmp>`, map the RD block (symptom → title, steps/expected/actual, evidence images → bug attachments, environment line, `Story:` → `> Related ticket:`), add `> From report: <story> R<n> RD<k>`, stop if a published or local bug already cites it; `## Auto mode` (branch `auto/BUG-<n>`, lint, PR, merge publishes; ends `AUTO-RESULT:` lines like `ba-ticket-author`).

- [ ] **Step 1: Failing tests**

```python
def test_pick_ba_candidate_after_blockers_before_drafts(): # mission blocker first, then Task("ba-bug-report","--from-report S1 R2 RD1"), then draft amend
def test_pick_ba_skips_skipped_candidate():
def test_all_done_ba_waits_for_candidates():  # all done, open_candidates=1 -> (False, "1 open bug candidate")
def test_runner_ba_candidates_read_failure_is_no_candidates(monkeypatch)
def test_ba_bug_report_body_from_report():    # phrases: "--from-report <story> R<n> RD<k>", "kb report fetch", "> From report:", "## Auto mode", "auto/BUG-<n>"
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** `tests/test_autorun*.py tests/test_template_bodies.py tests/test_init_settings.py` — PASS.
- [ ] **Step 5: Commit** `feat: BA auto drafts bugs from regression candidates`.

---

### Task 7: Closed-story amend refusal in `kb ticket lint`

**Files:**
- Modify: `src/strata_kb/ticketlint.py` (`lint`, with hub)
- Test: `tests/test_ticketlint.py` (or a new `tests/test_ticketlint_closed.py`)

**Interfaces:**
- Produces: `ticketlint.closed_story_issues(ticket_id: str, parent_id: str, local_revision: int, hub: HubHandle | None) -> list[Issue]`:
  - hub None or unreachable/plan read error → one warning `story status not checked (hub unreachable)`.
  - story = `parent_id or ticket_id`; closed = its `test_status == "closed"` in `planstatus.hub_plans(hub)` (row of that id).
  - published revision = `planrev.parse_revision` of the ticket's hub text (`ticketfetch.render`), `None` when unpublished.
  - error `story is closed — write a new story` when closed and (published is None (a new child) or `local_revision > published`).
  - Called from `lint()` when a hub is passed and the file is a story/child ticket (not a mission, not a bug).

- [ ] **Step 1: Failing tests** (closed state: `publish_tests` a PASS report for the plan_hub story)

```python
def test_amend_of_closed_story_is_error(plan_hub)          # local rev = published+1 -> error text exact
def test_unchanged_ticket_under_closed_story_passes(plan_hub)  # local rev == published -> no issue
def test_new_child_under_closed_parent_is_error(plan_hub)   # not on hub, parent closed -> error
def test_open_story_amend_passes(plan_hub)                  # no PASS report -> no issue
def test_no_hub_warns()                                     # hub None -> warning only
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** (import `planstatus`/`ticketfetch` inside the function to avoid import cycles). **Step 4: Run** `tests/test_ticketlint*.py tests/test_cli_ticket*.py` — PASS.
- [ ] **Step 5: Commit** `feat: ticket lint refuses amending a closed story`.

---

### Task 8: Release 1.37.3 (opened) and docs

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (strata-kb entry only), `CHANGELOG.md`, `README.md` (command table: `kb report fetch`), `tests/test_readme.py`

- [ ] **Step 1:** Update the readme test asserts to 1.37.3 / `1.37.3 — 2026-11-15` — FAIL.
- [ ] **Step 2:** Bump; CHANGELOG `## 1.37.3 — 2026-11-15` with a lead line ("The tester loop closes: …") and bullets for Tasks 1–7 (verify each claim against the code); README row for `kb report fetch`; tester row mentions the loop.
- [ ] **Step 3: Run** the full suite (GIT_CONFIG_GLOBAL rule) — only the 19 baseline env failures.
- [ ] **Step 4: Commit** `chore: open release 1.37.3`.
