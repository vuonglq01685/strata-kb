# Cross-repo Phase 1 — Routing, Blocked by, Done per target — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each Dev runner picks only tickets routed to its own repo, honors `- Blocked by:` for tickets outside a mission, and reads `done` from each ticket's own target repo.

**Architecture:** A ticket's target repo is read from a new `> Target repo:` header or a qualified `Grounded on: <repo>:<repo>-code`. `planstatus` (hub side) resolves target, dependencies and done per ticket and exposes `target_repo` on `StoryStatus` and the plan API. `picker` and `done.all_done` filter by the runner's `repo_id`, and the runner recovers from a stored task that vanished or is routed elsewhere.

**Tech Stack:** Python 3.11+, typer, pydantic, starlette, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-cross-repo-story-split-design.md` (§0 uniqueness note, §1, §2 legacy rule, §3, §11; phase 1 only).

## Global Constraints

- Version 1.34.5 → 1.35.0; CHANGELOG entry `## 1.35.0 — <date>`.
- Header line copy: `> Target repo: <repo-id>` (only in the header block, like `> Type:`).
- Blocked statuses (exact reason copy):
  - `no target repo` (≥2 dev repos on the hub and no target)
  - `target <x> is not a dev repo on the hub`
  - `blocked by <id> (not done)`
  - `dependency cycle: <a> → <b> → <a>`
- Single-dev-repo fallback: exactly one `kind == "dev"` repo in the federation → every ticket without a target is routed to it.
- Legacy unparented `- Blocked by:`: only a token equal to a ticket id published in the same BA plan counts; anything else is ignored (no block, no error).
- Hub plan API: new query parameter `for_repo=<dev-repo>`; the existing `repo` parameter (BA repo) is unchanged.
- Runner against a hub whose `/api/plan/next` rows lack `target_repo` refuses to start, message: `hub is older than 1.35 — upgrade the hub first`.
- PDF/MD ingest, mission statuses for stories with no target information, and every BA-side behavior stay unchanged.
- CI gate: `ruff check .`, `ruff format --check .`, `pyright`, `pytest -q -n auto`.

## Review Focus

1. **Hub with one dev repo and legacy tickets (no target anywhere)** → behaves exactly as today; every ticket is routed to that repo. Test in Task 2.
2. **Ticket grounded with an unqualified `Grounded on: payments-code @ r`** (no `<repo>:`) on a multi-repo hub → target resolved by the doc's unique holder, else `no target repo`. Test in Task 1.
3. **`Blocked by:` holding a Jira key or prose** (`ABC-123 — vendor API`) → never blocks. Test in Task 2.
4. **Stored task whose ticket was unpublished between runs** → runner drops it and picks again, never idles forever. Test in Task 4.
5. **Mission story whose ticket is routed to repo X** → only X's runner picks it; its mission `Depends on` still applies. Test in Task 3.

---

### Task 1: Target repo of a ticket

**Files:**
- Modify: `src/strata_kb/ticket.py` (header regexes near `TYPE_RE`, line ~141)
- Modify: `src/strata_kb/ticketlint.py` (header checks)
- Modify: `src/strata_kb/templates/init/bug-template.md`, `ticket-template.md` (document the optional header)
- Test: `tests/test_ticket_target.py` (new), `tests/test_ticketlint.py`

**Interfaces:**
- Produces:
  ```python
  # ticket.py
  TARGET_REPO_RE: re.Pattern[str]
  def target_header(text: str) -> str | None          # `> Target repo:` value, header block only
  def target_repo(text: str, holders: Callable[[str], list[str]] | None = None) -> str | None
  ```
  `target_repo`: header value if present; else the repo of the first `-code` entry of the first parseable `Grounded on:` line (`ticketcheck.grounded_entries`); an unqualified entry is resolved with `holders(doc_id)` (repo ids publishing that doc) when exactly one holder exists; else None.

- [ ] **Step 1: Write failing tests** in `tests/test_ticket_target.py`:
  - `test_header_wins_over_grounded_on`: header `web-app` + `Grounded on: payments-api:payments-api-code @ r1` → `"web-app"`.
  - `test_qualified_grounded_on_gives_repo` → `"payments-api"`.
  - `test_unqualified_grounded_on_resolved_by_unique_holder` (`holders=lambda d: ["payments-api"]`) → `"payments-api"`; two holders → `None` (Review Focus 2).
  - `test_svc_entry_skipped_for_code_entry`: `Grounded on: a:a-svc @ r, b:b-code @ r` → `"b"`.
  - `test_target_header_only_in_header_block`: a `> Target repo:` line inside a fence or below the first `##` is ignored.
  - `test_no_target_information` → `None`.
  In `tests/test_ticketlint.py`: `test_target_header_disagrees_with_grounded_on_is_error` (message contains `Target repo`), `test_target_header_alone_is_fine`.
- [ ] **Step 2: Run** `pytest tests/test_ticket_target.py tests/test_ticketlint.py -k target -q` → FAIL.
- [ ] **Step 3: Implement** the regex/functions in `ticket.py` (reuse `header_block`) and the lint error (only when both a header and a qualified `-code` Grounded-on repo exist and differ). Add the optional header to both templates with a one-line guidance comment; keep `tests/test_templates.py` / template drift tests green (update mirrors the way those tests require).
- [ ] **Step 4: Run** `pytest tests/test_ticket_target.py tests/test_ticketlint.py tests/test_templates.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: a ticket's target repo — header line or qualified grounding`.

### Task 2: Plan status — target, Blocked by, done per target

**Files:**
- Modify: `src/strata_kb/missionnext.py` (`StoryStatus`, line 52)
- Modify: `src/strata_kb/planstatus.py` (`_done_ids` 130, `_plan_repo` 150, `next_from_hub` 223)
- Modify: `src/strata_kb/hubapi.py` (`_story` 31, `plan_next` 66)
- Modify: `src/strata_kb/web/api.py` (`plan_next` 353)
- Test: `tests/test_planstatus_routing.py` (new)

**Interfaces:**
- Consumes: `ticket.target_repo` (Task 1).
- Produces:
  - `StoryStatus.target_repo: str | None = None` (new last field; `to_json`/`asdict` include it).
  - `planstatus.dev_repos(hub: HubHandle) -> list[str]` — repo ids of federation entries with `kind == "dev"`, sorted.
  - `planstatus.done_for(hub: HubHandle, target: str, cache: dict[str, set[str] | None]) -> set[str] | None` — done ids from `<target>-svc` history (via `ticketcheck.load_from_hub(hub.federation_dir, target, f"{target}-svc")`), memoised in `cache`.
  - `planstatus.next_from_hub(hub, repo=None, for_repo: str | None = None)` — when `for_repo` is given, returns only items whose `target_repo == for_repo` (parents/missions unaffected).
  - `HubApi.plan_next(repo=None, for_repo=None)`; `_story` reads `row.get("target_repo")`; the web route reads `for_repo` from the query.
- Rules (in `_plan_repo`, per published ticket section, using its L3 text):
  1. `target = ticket.target_repo(text, holders)`; if None and `len(dev_repos) == 1` → that repo.
  2. target None and ≥2 dev repos → status `blocked`, reason `no target repo`.
  3. target not in `dev_repos` → `blocked`, reason `target <x> is not a dev repo on the hub`.
  4. done: `id in done_for(hub, target, cache)`; with no target known, today's mission-level `_done_ids` result is used (unchanged behavior).
  5. unparented `depends_on` = tokens of `- Blocked by:` lines (first whitespace-separated token before ` — `) that equal a ticket id published in this same plan; any such id not done → `blocked`, reason `blocked by <id> (not done)`; a cycle among them → `blocked`, reason `dependency cycle: <a> → <b> → <a>` on every member.
  6. Mission stories: status rules unchanged; `target_repo` filled from the story's published ticket; done per target when known.

- [ ] **Step 1: Write failing tests** in `tests/test_planstatus_routing.py` using a fixture federation dir with one BA repo plan and two dev repos (`payments-api`, `web-app`) each with a `-svc` history (follow the fixtures in `tests/test_planstatus*.py` / `tests/test_mission_next*.py`):
  - `test_target_from_header_and_grounding` — rows carry `target_repo`.
  - `test_no_target_with_two_dev_repos_is_blocked` — reason `no target repo`.
  - `test_single_dev_repo_routes_legacy_tickets` — one dev repo, no targets → every ticket `target_repo == "<that repo>"`, statuses identical to today (Review Focus 1).
  - `test_unknown_target_is_blocked`.
  - `test_done_read_from_target_svc` — id listed only in `web-app-svc` history is done for a `web-app` ticket and not done for a `payments-api` ticket with the same history missing.
  - `test_blocked_by_published_sibling_blocks_until_done` and `..._unblocks_when_done`.
  - `test_blocked_by_jira_key_or_prose_never_blocks` (`ABC-123 — vendor`, `the vendor API`) (Review Focus 3).
  - `test_dependency_cycle_blocks_both`.
  - `test_for_repo_filters_rows`.
  - `test_hubapi_story_tolerates_missing_target_repo` (`_story` on a row without the key → `target_repo is None`).
  - `test_plan_api_passes_for_repo` (starlette TestClient, like existing api tests).
- [ ] **Step 2: Run** `pytest tests/test_planstatus_routing.py -q` → FAIL.
- [ ] **Step 3: Implement** per the rules above. Keep `_done_ids` for the no-target fallback; add `dev_repos`, `done_for`; thread `for_repo` through `next_from_hub`, the API route and `HubApi.plan_next`.
- [ ] **Step 4: Run** `pytest tests/test_planstatus_routing.py tests/test_planstatus*.py tests/test_mission_next*.py tests/test_web_api*.py -q` → PASS (no existing test changes).
- [ ] **Step 5: Commit** `feat: plan status routes each ticket to its target repo and honors Blocked by`.

### Task 3: Picker and done — route by repo

**Files:**
- Modify: `src/strata_kb/autorun/picker.py` (`_dev_tasks` 137, `dev_candidates` 150, `pick_dev` 168, `plan_next` 128)
- Modify: `src/strata_kb/autorun/done.py` (`all_done`)
- Modify: `src/strata_kb/autorun/runner.py` (callers of `pick_dev`, `dev_candidates`, `_check_done`)
- Test: `tests/test_autorun_picker.py`, `tests/test_autorun_done.py` (extend existing files; create if absent)

**Interfaces:**
- Consumes: `StoryStatus.target_repo`, `next_from_hub(..., for_repo=)`, `HubApi.plan_next(for_repo=)` (Task 2).
- Produces:
  - `picker.plan_next(hub, for_repo: str | None = None)`.
  - `picker.dev_candidates(hub, root, repo_id: str, skip=(), held=())` and `pick_dev(hub, root, repo_id: str, skip=(), held=())` — only tasks whose status row has `target_repo == repo_id`.
  - `_dev_tasks` yields an unparented ticket only when every `depends_on` id is in `done` (same rule as mission stories).
  - `done.all_done(stories, unparented, *, ba, open_questions=0, repo_id: str | None = None)` — for a Dev (`ba=False`, `repo_id` given) counts only rows routed to `repo_id`; "no tickets" when none are routed.

- [ ] **Step 1: Write failing tests:**
  - `test_dev_candidates_only_own_repo` — two ready tickets for `payments-api` and `web-app`; candidates for `web-app` = only its ticket.
  - `test_unparented_blocked_by_not_done_is_not_a_candidate`.
  - `test_mission_story_routed_and_depends_on_still_applies` (Review Focus 5).
  - `test_all_done_scoped_to_repo` — the other repo's open ticket does not keep this Dev's loop alive.
- [ ] **Step 2: Run** the new tests → FAIL.
- [ ] **Step 3: Implement**; pass `cfg.repo_id` from `runner` to `pick_dev`/`dev_candidates`/`all_done`; on cloud call `HubApi.plan_next(for_repo=cfg.repo_id)`.
- [ ] **Step 4: Run** `pytest tests/test_autorun_*.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: Dev runner picks only tickets routed to its repo`.

### Task 4: Runner — old hub refusal and stored-task recovery

**Files:**
- Modify: `src/strata_kb/autorun/runner.py` (`preflight` / `_task_for` 238, the `except` arms ~405-409)
- Modify: `src/strata_kb/hubapi.py` (expose whether rows carry `target_repo`)
- Modify: `src/strata_kb/autorun/claims.py` (`claim` 64) if needed for `unknown_ticket`
- Test: `tests/test_autorun_runner*.py` (extend)

**Interfaces:**
- Consumes: Task 2/3 APIs.
- Produces:
  - `hubapi.HubApi.plan_next(...)` raises `KbError("hub is older than 1.35 — upgrade the hub first")` when any row lacks the `target_repo` key (the server always sends the key, `null` allowed).
  - Runner preflight (dev, cloud) calls it once; on that error the runner stops with that message.
  - `_task_for`: before resuming a stored Dev task, re-read the plan (`for_repo=cfg.repo_id`); if the ticket is absent, not routed to this repo, or not `ready`, clear the task and attempts, log `<id> is no longer ready for <repo>; picking again`, drop the local claim, and pick again.
  - A claim `take` failing with reason `unknown_ticket` → same recovery (clear task, drop local claim, log, pick again) instead of the generic `idle`.
  - `kb publish` in a BA repo, when the hub's plan API answers without `target_repo`, prints a yellow warning `hub is older than 1.35: Dev runners will not route by repo` and still publishes (test `test_publish_warns_old_hub`).

- [ ] **Step 1: Write failing tests:**
  - `test_runner_refuses_old_hub` (fake HubApi rows without `target_repo`) → stop reason contains `hub is older than 1.35`.
  - `test_stored_task_unpublished_is_dropped_and_repicked` (Review Focus 4).
  - `test_stored_task_routed_elsewhere_is_dropped`.
  - `test_claim_unknown_ticket_recovers` — outcome is not `idle` forever; state.task cleared.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with the smallest change at the existing `except KbError` arm (match `unknown_ticket` in the message from `claimclient`) and in `_task_for`.
- [ ] **Step 4: Run** `pytest tests/test_autorun_*.py -q` → PASS.
- [ ] **Step 5: Commit** `fix: runner refuses an old hub and recovers from a vanished stored task`.

### Task 5: Local `kb mission next` done per target + `kb ticket fetch` warning

**Files:**
- Modify: `src/strata_kb/cli.py` (local mission-next done lookup ~4155-4199; `ticket fetch` command)
- Modify: `src/strata_kb/ticketfetch.py` (return the ticket text/target to the CLI if not already)
- Test: `tests/test_cli_mission_next*.py`, `tests/test_ticket_fetch*.py` (extend)

**Interfaces:**
- Consumes: `ticket.target_repo` (Task 1), `planstatus.done_for` (Task 2).
- Produces:
  - Local `kb mission next`: for a story whose local ticket has a target, done = `done_for(hub, target, cache)` when a hub is available; otherwise unchanged (`--repo-id` / first mission grounding).
  - `kb ticket fetch <id>` in a dev repo whose ticket targets another repo prints a yellow warning `<id> targets <x>, this repo is <repo_id>` and still fetches.

- [ ] **Step 1: Write failing tests:** `test_local_mission_next_done_per_target`, `test_ticket_fetch_warns_on_other_target`, `test_ticket_fetch_no_warning_same_target`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the touched test files → PASS.
- [ ] **Step 5: Commit** `feat: local mission next and ticket fetch know the target repo`.

### Task 6: Skills, branch lookups, guides, release

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/ba-bug-report.md` (and its claude/cursor/copilot wrappers + repo mirrors if any): ask the BA for the target repo (or use the only dev repo) and write `> Target repo:`.
- Modify: `src/strata_kb/templates/init/bodies/sa-ticket-ground.md`: the first `Grounded on:` entry is always qualified `<repo-id>:<repo-id>-code`.
- Modify: `src/strata_kb/templates/init/bodies/dev-implement-ticket.md:186`, `dev-fix-bug.md:171`: `git branch --list "*<ticket-id>*"` → exact names (`<prefix>/<ticket-id>` and `<prefix>/<ticket-id>-r<N>`); `ba-ticket-author.md:379`, `ba-mission-plan.md:330`: `git ls-remote --heads origin 'auto/<id>*'` → filter to `auto/<id>` and `auto/<id>-r<N>` only.
- Modify: `docs/src/guide-ba.{en,vi}.md` (target line for bugs; one ticket = one target repo), `docs/src/guide-dev.{en,vi}.md` (runner routes by repo; upgrade the hub before the runners), rebuild guide PDFs with `uv run --extra docs python docs/src/build_pdf.py <changed names>`.
- Modify: `CHANGELOG.md`, `pyproject.toml` / `uv.lock` (1.35.0), `tests/test_readme.py` version pin.
- Test: existing template/guide drift tests; add needles for `> Target repo:` in the bug skill and for the exact-branch wording.

- [ ] **Step 1: Write failing tests** (needles in `tests/test_templates.py`): bug skill mentions `> Target repo:`; no body contains `branch --list "*<` or `'auto/<ticket-id>*'`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Edit** skills, mirrors, guides (en+vi same facts), CHANGELOG, version; rebuild changed guide PDFs.
- [ ] **Step 4: Run** full gate: `ruff check . && ruff format --check . && pyright && pytest -q -n auto` → PASS (pre-existing offline failures excepted; no new ones).
- [ ] **Step 5: Commit** `docs: target repo for bugs, exact branch lookups, guides — 1.35.0`.
