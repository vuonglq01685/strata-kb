# Ticket Q&A and Dev-repo SA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-ticket BA Q&A store on the hub (SQLite, written only through MCP, shown read-only on a new Q&A menu), a BA-repo `/ba-answer-questions` command, Dev skills that post BA questions and wait on them, and a new Dev-repo `dev-sa` agent for technical questions.

**Architecture:** A new `ticketqa.py` holds the SQLite store and the hub-aware operations (resolve the ticket, read its `> Revision:`, derive open/waiting/answered). Three MCP tools in `mcp.py` and a read-only `web/qaui.py` call it. The BA and Dev behaviour is skill text (templates under `templates/init/`), installed per repo kind by `initcmd.py`.

**Tech Stack:** Python 3.11–3.13, stdlib `sqlite3`, FastMCP (existing), Starlette + Jinja2 (existing), Markdown skill templates, pytest, ruff, pyright.

**Spec:** `docs/superpowers/specs/2026-10-14-ticket-qa-and-dev-sa-design.md`

## Global Constraints

- No new dependency. The store uses stdlib `sqlite3` with one short-lived connection per call, in the style of `serving/accounts.py`.
- DB path: `<kb_dir.parent>/.kb-qa/qa.db`. `.kb-qa/` is kept out of git through `.git/info/exclude` at server start and through `hub-gitignore.txt`.
- Caps: question ≤ 4000 chars, answer ≤ 4000, context ≤ 1000, names ≤ 100, at most 50 open questions per ticket. Empty question, answer or names are rejected.
- "Ticket revision" is the ticket's own `> Revision: N` (`planrev.parse_revision`; absent = 1), never the hub's git HEAD.
- Derived state: `open` (no answer); `waiting` (answered, `answer_rev` set, hub ticket revision < `answer_rev`); `answered` (otherwise).
- The MCP write tools refuse a hub that is not a local served checkout. Exact error text: `Q&A needs the shared hub server — point MCP at it (kb mcp-setup)`.
- Ticket resolution, and its error texts, reuse `ticketfetch.find` and `ticketfetch.split_ref` unchanged.
- Web pages are read-only and autoescaped. The repo-id goes in the query string (`?repo=`), because repo-ids can contain `/`.
- New change-log trigger: `question`, added to `planrev.TRIGGERS`.
- New state-line marker in the Dev skills: `BA-Q: none | open Q<ids> | waiting Q<ids>` (the fifth marker).
- The BA skill never commits, pushes or publishes. The Dev author subagents never call the hub.
- Gates before every commit: `uv run --frozen ruff check .`, `ruff format --check .`, `pyright`, and `pytest -q`. The full suite may show only the 19 known env failures (test_sectioner ×16, test_ingest_seam, test_ingest_cli, and test_cli_errors::test_reindex_read_only_index_yaml_is_one_line_not_a_traceback).
- Version `1.26.0` → `1.27.0`, with a CHANGELOG entry (Task 6).

## Review Focus

- A ticket answered twice in a row (two BA sessions) must still require `answer_rev` > the hub revision each time. Test in Task 1.
- A question asked about a bug/hotfix ticket must resolve like a story, because `ticketfetch` already handles both. Test in Task 2, using a bug ticket fixture if the conftest has one; otherwise skip with a reason.
- Question text containing `<script>`, Markdown or newlines must render escaped on both pages and keep its newlines in the MCP list output. Tests in Tasks 2 and 3.
- A ticket removed from the hub (DoR unticked by a later publish) while it has questions: list and pages must still show the questions, with the hub revision shown as `—` (unknown) and state derived as `waiting` for answered-with-rev, never a crash. Tests in Tasks 1 and 3.
- A nested repo-id such as `mid/ba-x` must round-trip through ask, list and the web URL. Tests in Tasks 2 and 3.

---

### Task 1: Q&A store and hub-aware operations

**Files:**
- Create: `src/strata_kb/ticketqa.py`
- Modify: `src/strata_kb/planrev.py` (add `"question"` to `TRIGGERS`)
- Modify: `src/strata_kb/serving/accounts.py` (`ensure_git_exclude(repo_root, entry=".kb-auth/")`; existing callers keep working)
- Modify: `src/strata_kb/hub.py` (extract `is_local_hub(hub: str) -> bool` from `resolve_hub`'s first branch and use it there)
- Test: `tests/test_ticketqa.py`, plus one case each in `tests/test_planrev.py` (or wherever TRIGGERS is tested) and `tests/test_accounts.py`

**Interfaces:**
- Produces:
  - `QaError(KbError)`
  - `MAX_QUESTION = 4000`, `MAX_ANSWER = 4000`, `MAX_CONTEXT = 1000`, `MAX_NAME = 100`, `MAX_OPEN_PER_TICKET = 50`
  - `@dataclass(frozen=True) Question`, with fields `id: int`, `repo: str`, `ticket: str`, `question: str`, `context: str`, `blocks: str`, `asked_by: str`, `asked_at: str`, `asked_rev: int`, `answer: str | None`, `answer_rev: int | None`, `ticket_sections: list[str]`, `answered_by: str | None`, `answered_at: str | None`
  - `qa_db_path(kb_dir: Path) -> Path` → `kb_dir.parent / ".kb-qa" / "qa.db"`
  - `class QaStore(db_path: Path)`, with methods:
    - `ask(repo, ticket, question, context, blocks, asked_by, asked_rev) -> Question`
    - `get(id) -> Question | None`
    - `list(repo: str | None = None, ticket: str | None = None) -> list[Question]` (ordered by id)
    - `answer(id, answer, answered_by, answer_rev, ticket_sections) -> Question`
  - `derive_state(q: Question, hub_rev: int | None) -> Literal["open", "waiting", "answered"]`
  - `ticket_revision(hub: HubHandle, repo: str, ticket: str) -> int | None`. Returns None when the ticket is no longer on the hub.
  - `ask_question(hub, store, ticket_ref, question, asked_by, context="", blocks="") -> Question`
  - `answer_question(hub, store, id, answer, answered_by, answer_rev: int | None, ticket_sections: list[str]) -> Question`
  - `list_questions(hub, store, ticket_ref="", repo="", status="open") -> list[tuple[Question, str, int | None]]`, returning (question, derived state, hub revision); `status` ∈ {`open`, `waiting`, `answered`, `all`}
  - `format_questions(rows) -> str`, plain text for MCP
  - `hub.is_local_hub(hub: str) -> bool`

- [ ] **Step 1: Write failing tests.** Use the `fed_hub` fixture plus a helper that publishes a ticket with a given `> Revision:` into a `*-plan` doc. Reuse how `tests/test_ticketfetch*.py` (or the planstatus tests) build one.

```python
def test_ask_records_hub_revision_and_lists_open(hub_with_ticket, tmp_path):
    store = QaStore(tmp_path / "qa.db")
    q = ask_question(hub_with_ticket(rev=3), store, "M-x-US1", "Which currency?", "dev1", context="design §Pricing", blocks="AC-2")
    assert (q.repo, q.ticket, q.asked_rev, q.blocks) == ("ba-repo", "M-x-US1", 3, "AC-2")
    [(row, state, rev)] = list_questions(hub_with_ticket(rev=3), store, ticket_ref="M-x-US1")
    assert (row.id, state, rev) == (q.id, "open", 3)

def test_answer_with_rev_is_waiting_until_hub_catches_up(...):
    # answer_rev=4, sections=["Acceptance Criteria"] while hub rev=3 -> "waiting"; republish rev 4 -> "answered"

def test_answer_rev_must_exceed_hub_revision(...):
    with pytest.raises(QaError, match="the hub already has revision 3"):
        answer_question(hub, store, q.id, "EUR", "ba1", answer_rev=3, ticket_sections=["Scope"])

def test_sections_required_iff_answer_rev(...):
    # answer_rev=4 with [] -> QaError; answer_rev=None with ["Scope"] -> QaError; None with [] -> answered at once

def test_answering_twice_names_first_answerer(...):  # QaError mentions "ba1"

def test_second_answer_session_still_needs_a_higher_rev(...):  # q1 answered rev 4, hub at 4; q2 with answer_rev=4 -> QaError; 5 -> ok

def test_caps_and_empties(...):  # 4001-char question, 1001 context, 101 name, empty answer -> QaError; 51st open question on one ticket -> QaError

def test_unknown_and_ambiguous_ticket_reuse_ticketfetch_errors(...):  # "not on the hub", "qualify it as"

def test_ticket_removed_from_hub_keeps_questions(...):  # ticket gone: list returns rows with hub rev None; answered-with-rev -> "waiting"; open -> "open"; no exception

def test_nested_repo_id_round_trips(...):  # repo "mid/ba-x" stored and filterable

def test_derive_state_table():
    # (answer None) -> open; (answer, rev None) -> answered; (rev 4, hub 3) -> waiting; (rev 4, hub 4) -> answered; (rev 4, hub None) -> waiting
```

Also add:
- `"question"` is accepted by `planrev.check_revision`.
- `ensure_git_exclude(root, ".kb-qa/")` appends that entry only.
- `is_local_hub` is True for a dir containing `.kb/` and False for a URL.

- [ ] **Step 2: Run** `uv run --frozen pytest tests/test_ticketqa.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement.**
  - The schema is spec §5.3. `ticket_sections` is stored as JSON.
  - `ticket_revision` calls `ticketfetch.render(hub, f"{repo}:{ticket}")`, then `planrev.parse_revision`, defaulting to 1. It returns None on `TicketFetchError`.
  - `list_questions` computes each distinct ticket's revision once per call.
  - `format_questions` prints one block per question: `Q<id> [<state>] <repo>:<ticket> (hub rev <n|—>)`, then labelled lines for question, context, blocks, asked, and, when present, answer, `answer_rev`, sections and answered.
- [ ] **Step 4: Run** the tests. Expected: PASS. Then run `pytest tests/test_accounts.py tests/test_hub.py -q` and confirm no regression.
- [ ] **Step 5: Commit** `feat: ticket Q&A store with derived open/waiting/answered state`.

---

### Task 2: MCP tools

**Files:**
- Modify: `src/strata_kb/mcp.py`. Add 3 tools and update the module docstring's tool list.
- Modify: `src/strata_kb/web/app.py`. At startup, call `ensure_git_exclude(config.kb_dir.parent, ".kb-qa/")` next to the existing `.kb-auth/` call.
- Test: `tests/test_mcp_qa.py`. Follow how `tests/test_mcp.py` calls tools.

**Interfaces:**
- Consumes: Task 1 (`QaStore`, `qa_db_path`, `ask_question`, `answer_question`, `list_questions`, `format_questions`, `QaError`, `hub.is_local_hub`).
- Produces these MCP tools. Each returns `str` and turns `QaError`/`TicketFetchError` into their message.
  - `kb_question_ask(ticket: str, question: str, asked_by: str, context: str = "", blocks: str = "") -> str`. Returns `Q<id> asked on <repo>:<ticket> — <hub link>`. The link path is `/ui/questions/ticket?repo=<urlencoded>&ticket=<id>`; build it from the existing hub base URL setting if one exists, otherwise print the path only.
  - `kb_question_list(ticket: str = "", repo: str = "", status: str = "open") -> str`
  - `kb_question_answer(id: int, answer: str, answered_by: str, ticket_sections: list[str], answer_rev: int | None = None) -> str`
  - The write tools (`ask`, `answer`) return the Global Constraints refusal text when `not hub.is_local_hub(config.hub)`. `list` works on any hub.

- [ ] **Step 1: Write failing tests:**
  - `test_round_trip_ask_list_answer` checks that the text contains `Q1`, `[open]`, then `[waiting]`, then `[answered]` after republishing.
  - `test_write_tools_refuse_cache_clone_hub` uses a config whose hub is a URL string and expects the exact refusal text; `list` still works or reports the hub down.
  - `test_unknown_ticket_message`
  - `test_question_text_with_newlines_and_markup_round_trips`
  - `test_bug_ticket_can_be_asked_about` (Review Focus)
  - `test_nested_repo_ref_mid_slash_ba` (Review Focus)
- [ ] **Step 2: Run** `pytest tests/test_mcp_qa.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use the existing tool pattern: `@mcp.tool()`, `@_canonical_docstring`, then a sync `_run` passed to `anyio.to_thread.run_sync`, returning `HUB_DOWN` when `_hub()` is None. The store is `QaStore(qa_db_path(config.kb_dir))`. Docstrings say who may write (any authenticated caller, self-declared names).
- [ ] **Step 4: Run** `pytest tests/test_mcp_qa.py tests/test_mcp.py tests/test_mcp_http.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: kb_question_ask/list/answer MCP tools`.

---

### Task 3: Q&A web pages

**Files:**
- Create: `src/strata_kb/web/qaui.py`, `src/strata_kb/templates/web/questions.html`, `src/strata_kb/templates/web/questions_ticket.html`
- Modify: `src/strata_kb/web/app.py`. Add `routes += qaui.qa_routes(config)` after `planui`.
- Modify: `src/strata_kb/templates/web/_partials/left_rail.html`. Add a **Q&A** item linking to `/ui/questions`, active when `shell.screen` starts with `questions`.
- Modify: `src/strata_kb/web/planui.py` and `src/strata_kb/templates/web/plan_ticket.html`. Add the one-line "N unresolved questions" link when N > 0.
- Test: `tests/test_web_questions.py`

**Interfaces:**
- Consumes: Task 1 (`QaStore`, `qa_db_path`, `list_questions`, `derive_state`).
- Produces: `qa_routes(config: ServerConfig) -> list[Route]`, which serves:
  - `GET /ui/questions`, with `?all=1` to include answered questions;
  - `GET /ui/questions/ticket?repo=&ticket=`. A missing parameter returns 400 through `render_error_page`. A ticket with no questions returns a 200 page that says "No questions".
- Ticket links on these pages point at the existing `/ui/tickets/{group}/{story}?repo=` page. Derive the group with `planstatus` at render time; when the ticket is no longer on the hub, render the id without a link.

- [ ] **Step 1: Write failing tests**, using the `web_client` and `web_client_logged_in` fixtures:
  - `test_menu_link_on_every_page`
  - `test_list_groups_by_repo_with_counts_and_oldest_age` (open/waiting/answered counts)
  - `test_default_hides_fully_answered_tickets_all_shows_them`
  - `test_ticket_page_shows_states_answers_sections_and_waiting_note`, where the waiting note text is `not on the hub yet`
  - `test_script_in_question_and_answer_is_escaped` (Review Focus)
  - `test_nested_repo_id_in_query_string` (Review Focus)
  - `test_ticket_gone_from_hub_renders_id_without_link_and_rev_dash` (Review Focus)
  - `test_ticket_page_shows_unresolved_link`
  - `test_pages_have_no_forms` (assert `<form` is absent in `<main>`)
  - `test_bearer_and_dev_role_can_view`
- [ ] **Step 2: Run** `pytest tests/test_web_questions.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use the same handler shape as `planui.py`: a sync handler, `api.hub_handle(config)` (503 when it returns None), then `ui._render_page(...)`. Use only the existing `style.css` classes (badge, chip, kicker).
- [ ] **Step 4: Run** `pytest tests/test_web_questions.py tests/test_web_plans.py tests/test_web_ui.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: read-only Q&A menu on the hub UI`.

---

### Task 4: BA skill `/ba-answer-questions`

**Files:**
- Create:
  - `src/strata_kb/templates/init/bodies/ba-answer-questions.md`
  - `claude-skill-ba-answer-questions.md`
  - `claude-command-ba-answer-questions.md`
  - `copilot-ba-answer-questions.prompt.md`
  - `cursor-ba-answer-questions.md`

  The four wrappers copy the shape of the `ba-ticket-author` files.
- Modify: `src/strata_kb/initcmd.py`. Add 4 `BA_TEMPLATES` rows, like `ba-ticket-author`.
- Modify: `src/strata_kb/templates/init/bodies/ba-ticket-author.md`. In amend mode, list `question` among the allowed triggers, and use it only for amendments made from `/ba-answer-questions`.
- Test: extend `tests/test_init.py`, `tests/test_templates.py` and `tests/test_template_bodies.py`, following how they pin `ba-ticket-author`/`sa-ticket-ground`.

**Interfaces:**
- Consumes: the MCP tools from Task 2, the `question` trigger from Task 1, and the existing amend rules in `ba-ticket-author`.

- [ ] **Step 1: Write failing tests:**
  - `kb init --kind ba` installs all 4 files.
  - The body contains these pinned phrases:
    - `kb_question_list`
    - `kb_question_answer`
    - `Trigger` `question`
    - `one amendment per ticket`
    - the DoR rule: `do not record any answer for a ticket whose Definition of Ready is not fully ticked`
    - `never commits, pushes or publishes`
    - `answer_rev`
    - `waiting for publish`
  - The CLI fallback names are listed for clients without MCP: `kb` has no CLI for these, so the body says MCP is required.
- [ ] **Step 2: Run** the three test files. Expected: FAIL.
- [ ] **Step 3: Write the body.** Follow the workflow in spec §7: List → Walk → Answer (amend under `ba-ticket-author` rules, one amendment per ticket, Revision N+1, change-log row Trigger `question`, What changed `Q<ids>: …`, Affected = changed sections, one maturity round, re-tick DoR or stop, `kb ticket lint` passes) → Record (`answer_rev = N+1`, `ticket_sections` = Affected; or None and `[]`) → Report (list, remind to commit and merge as usual, paste the hub Q&A link). End with the repo's usual `## Next step` / `State:` convention used by the other BA skills.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: /ba-answer-questions BA skill`.

---

### Task 5: Dev skills — BA questions, resume, and the `dev-sa` agent

**Files:**
- Create:
  - `src/strata_kb/templates/init/bodies/dev-sa.md`
  - `claude-skill-dev-sa.md`
  - `claude-command-dev-sa.md`
  - `copilot-dev-sa.prompt.md`
  - `cursor-dev-sa.md`
- Modify: `src/strata_kb/initcmd.py`. Add `"dev-sa"` to the `DEV_TEMPLATES` skill-name tuple. Keep it out of the tests' `DEV_WORKFLOW_SKILLS` canon, as `dev-code-seed` is.
- Modify:
  - `src/strata_kb/templates/init/bodies/dev-design.md`
  - `bodies/dev-plan.md`
  - `claude-skill-dev-implement-ticket.md`
  - `claude-command-dev-implement-ticket.md`
  - `bodies/dev-implement-ticket.md`
  - `bodies/dev-execute.md` (the `OPEN(BA)` line now says design asks via Q&A)
- Test: extend `tests/test_init.py`, `tests/test_templates.py` and `tests/test_template_bodies.py`, plus any test that pins the four `State:` markers.

**Interfaces:**
- Consumes: the MCP tools from Task 2.
- Produces skill text that later docs (Task 6) quote:
  - the `## Questions raised` section, whose items are tagged `business`/`technical` and carry `blocks: <AC ids|none>`;
  - the `## Open questions` line format `- Q<id> — <question> — blocks: <AC ids|none>`;
  - `## Technical decisions` entries in the form `- SA-<n>: <decision> — why — evidence`;
  - the fifth state marker `BA-Q: none | open Q<ids> | waiting Q<ids>`.

- [ ] **Step 1: Write failing tests**, pinning phrases in the bodies:
  - **dev-design / dev-plan.** The author subagent never calls the hub. The orchestrator handles each raised question:
    - technical → dispatch `dev-sa`, write the result under `## Technical decisions`, then re-dispatch the author;
    - business → `kb_question_ask`, then record it under `## Open questions`.
    
    Two more rules:
    - A blocking open BA question stops the gate.
    - A non-blocking one does not stop the gate, and reviewers treat it as a known open item, not a defect.
  - **dev-implement-ticket.** On entry it calls `kb_question_list(ticket=…, status=all)` and handles each state:
    - answered → re-fetch with `kb_ticket_fetch`, mark the `## Open questions` line `— answered rev N`, and go back to `dev-design` when an approved design is touched;
    - waiting → show the answer as information only;
    - open + blocking → stop.
  - **dev-sa.** Inputs; it reads source and uses `kb_search`/`kb_get_section`. Its output is the decision, reasoning, rejected alternatives and `path:line` / `doc §section` evidence. Two more rules:
    - It answers `business question:` when the question is about what an AC means.
    - It never writes to the hub.
  - **Installation.** `kb init --kind dev` installs the 4 `dev-sa` files.
  - **State line.** It now has five markers, including `BA-Q:`.
- [ ] **Step 2: Run** the three test files. Expected: FAIL.
- [ ] **Step 3: Edit the bodies** per spec §8.1–8.3. Keep the existing review-dispatch contract text and the gates. Make only the additions and replacements the spec names.
- [ ] **Step 4: Run** the three files, then the full suite once. Expected: PASS, with only the known env failures.
- [ ] **Step 5: Commit** `feat: dev skills ask the BA via hub Q&A; dev-sa agent for technical questions`.

---

### Task 6: Docs, templates, version

**Files:**
- Modify:
  - `src/strata_kb/templates/init/hub-gitignore.txt` (add `.kb-qa/`)
  - `QUICKSTART-ba.md`, `QUICKSTART-dev.md`, `QUICKSTART-hub.md`
  - `README.md` (Q&A menu, MCP tool list, `.kb-qa/`, `/ba-answer-questions` and `/dev-sa` in the command tables)
  - `docs/src/guide-*.{en,vi}.md` where the BA/Dev flows are described
  - `CHANGELOG.md`
  - `pyproject.toml` (`1.27.0`) and the project's own line in `uv.lock`
- Test: `tests/test_readme.py`, `tests/test_init.py`, `tests/test_templates.py`. Add pins for each new item.

- [ ] **Step 1:** Grep `kb_ticket_fetch`, `OPEN(BA)`, `Open questions` and `MCP tools` in README.md, docs/src and the templates, then update every place that describes the flows changed by spec §9.
  - **Docs must state:**
    - the MCP write tools need the shared hub server;
    - any authenticated caller may write, and names are self-declared;
    - an answer that changes the ticket stays "waiting for publish" until its revision lands;
    - the BA must re-tick DoR after the amendment.
  - **CHANGELOG:** the guide PDFs are not rebuilt.
- [ ] **Step 2:** Add the pins, then run `pytest tests/test_readme.py tests/test_init.py tests/test_templates.py -q`. Expected: PASS.
- [ ] **Step 3:** Run all the gates and the full suite. Expected: only the known env failures.
- [ ] **Step 4: Commit** `docs: ticket Q&A, /ba-answer-questions, dev-sa — 1.27.0`.
