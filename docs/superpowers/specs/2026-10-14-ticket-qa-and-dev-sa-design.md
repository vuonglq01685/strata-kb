# Ticket Q&A on the hub, and an SA agent in the Dev repo — design

Date: 2026-10-14
Status: draft, awaiting owner approval

## 1. Intent

Almost every ticket raises questions when the Dev writes the design or the
plan. Today those questions leave the system: the Dev copies them to the BA
over chat, the BA edits the ticket in the BA repo and publishes, and the Dev
waits for the new ticket. If the BA is busy or forgets, the ticket hangs, and
nobody can see which questions were asked, which were answered, or how long
they have waited.

Two kinds of question get two different paths:

- **Business questions (for the BA)** go on the hub, in a per-ticket Q&A
  list. The BA answers from the BA repo, updates the ticket (the ticket stays
  the single source of truth), and records which ticket sections changed so
  the Dev knows exactly what to re-read.
- **Technical questions** never leave the Dev repo. A new **SA agent**,
  running inside the Dev repo, reads the whole source tree plus the KB and
  makes the decision on the spot. This SA is a different role from the
  existing `sa-ticket-ground` in the BA repo: that one gives the system-wide
  view from the hub's `-code`/`-svc` documents; this one is the technical
  lead for one ticket's implementation, with the real code in front of it.

## 2. Goals

- A Dev's Claude can post a BA question for a ticket to the hub without the
  Dev copying anything.
- The hub has a **Q&A** menu listing questions per ticket with their state,
  who asked, when, and the answer.
- The BA answers from the BA repo with a new `/ba-answer-questions` command
  that also amends the ticket and records the changed ticket sections with
  the answer.
- When the Dev comes back to the ticket, `/dev-implement-ticket` shows the
  answers and the changed sections once the updated ticket is on the hub,
  fetches it, and continues.
- A technical question during `/dev-design` or `/dev-plan` is handed to the
  Dev-repo SA agent, and its decision is written into the Dev's design or
  plan.

## 3. Non-goals

- Chat notifications (Slack/Teams webhooks), reminders, or any push to
  people. People keep pinging each other in chat; they paste the hub Q&A
  link instead of copying text.
- Threads. One question has one answer; a follow-up is a new question that
  may cite the earlier one's number. No withdraw/delete: a question no
  longer needed is answered "no longer needed" with no ticket change.
- Answering or editing tickets from the hub web UI. The web page is
  read-only.
- Sending technical questions to the hub, or storing the Dev-repo SA's
  decisions on the hub. They live only in the Dev's `design.md`/`plan.md`.
- Per-person authentication on MCP writes (see §5.5).
- Q&A across nested federations (a BA on a mid-tier hub, a Dev on the
  root). Both sides use the same hub (§5.1).

## 4. Anti-goals

- An answer that changes behaviour while the ticket stays unchanged. The
  ticket is the source of truth; the Q&A record only points at a ticket
  revision.
- A Dev acting on an answer before the ticket revision it points at is on
  the hub.
- A Dev continuing past a business question that blocks an AC.
- The Q&A flow knocking a ticket off the hub (§7, DoR).
- The Dev-repo SA deciding business behaviour. It decides *how*, never
  *what*; a business ambiguity it finds becomes a BA question.

## 5. Q&A store on the hub

### 5.1 Where it lives

- SQLite, decided by the owner. File `<config.kb_dir.parent>/.kb-qa/qa.db`
  (in Docker: `/data/.kb-qa/qa.db`), beside `.kb-auth/` on the same volume.
- `.kb-qa/` is kept out of git like `.kb-auth/`: added to
  `.git/info/exclude` at startup (generalise `accounts.ensure_git_exclude`
  to take the directory name) and to `hub-gitignore.txt`.
- The write tools work only on a hub served from its own local checkout
  (the shared HTTP hub server). An MCP server whose hub is a URL resolved to
  a local cache clone refuses the write tools with "Q&A needs the shared
  hub server — point MCP at it (kb mcp-setup)", because writes there would
  be private to one machine and lost on reclone.
- BA and Dev therefore talk to the same hub: the one their MCP points at.

### 5.2 Ticket revision

- A ticket's revision is its own `> Revision: N` line (`planrev`), which the
  hub copy keeps. `N` is read from the ticket text that `ticketfetch`
  resolves (absent line = 1, as `planrev` reads it). This — not the hub's
  git HEAD — is the "ticket revision" everywhere in this design.

### 5.3 Table `questions`

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | shown as `Q<id>` |
| `repo` | TEXT | full repo-id of the BA repo holding the ticket (may contain `/`) |
| `ticket` | TEXT | ticket id (file stem, e.g. `M-checkout-US1`) |
| `question` | TEXT | ≤ 4000 chars |
| `context` | TEXT | where it came from, e.g. `design §Data model`; ≤ 1000 chars; may be empty |
| `blocks` | TEXT | AC ids it blocks, e.g. `AC-2,AC-3`, or empty |
| `asked_by` | TEXT | self-declared name, ≤ 100 chars |
| `asked_at` | TEXT | UTC ISO-8601 |
| `asked_rev` | INTEGER | ticket revision on the hub when asked |
| `answer` | TEXT | ≤ 4000 chars; NULL while open |
| `answer_rev` | INTEGER | ticket revision that carries the answer; NULL when the ticket did not change |
| `ticket_sections` | TEXT | JSON list of changed section names (the change-log row's `Affected`); `[]` when the ticket did not change |
| `answered_by` | TEXT | self-declared name |
| `answered_at` | TEXT | UTC ISO-8601 |

State is derived, not stored:
- **open** — no answer.
- **answered, waiting for publish** — answer recorded, `answer_rev` set,
  and the hub's ticket revision is still below `answer_rev`.
- **answered** — answer recorded, and `answer_rev` is NULL or the hub's
  ticket revision is ≥ `answer_rev`.

Stdlib `sqlite3`, one short-lived connection per call, same style as
`serving/accounts.py`. No new dependency.

### 5.4 MCP tools (the only write path)

All questions and answers go through MCP, decided by the owner. They follow
the existing pattern in `mcp.py` (`@mcp.tool()`, `async def … -> str`, sync
body in `anyio.to_thread.run_sync`) and are the first MCP tools that write.

- `kb_question_ask(ticket: str, question: str, asked_by: str, context: str = "", blocks: str = "") -> str`
  - `ticket` is a bare id or `<repo>:<id>`, resolved with the same rules
    and error texts as `kb_ticket_fetch` (`ticketfetch.find`).
  - Records `asked_rev` from the hub ticket.
  - Returns `Q<id>` and the hub link to the ticket's Q&A page.
- `kb_question_list(ticket: str = "", repo: str = "", status: str = "open") -> str`
  - Filter by ticket, by BA repo-id, or both; `status` is `open`,
    `waiting` (answered, waiting for publish), `answered`, or `all`.
  - Returns plain text, oldest first; each item has id, ticket, derived
    state, question, context, blocks, asked by/at/rev, and when answered:
    answer, `answer_rev`, sections, answered by/at, and the hub's current
    ticket revision.
- `kb_question_answer(id: int, answer: str, answered_by: str, answer_rev: int | None, ticket_sections: list[str]) -> str`
  - Only an open question can be answered; answering an answered one is an
    error naming who answered it and when.
  - `answer_rev` set → it must be greater than the hub's current ticket
    revision (otherwise: "the hub already has revision X — amend the ticket
    and bump its revision"), and `ticket_sections` must be non-empty.
  - `answer_rev` NULL → `ticket_sections` must be empty. Allowed only for
    answers that do not change the ticket (it already says it, or "no
    longer needed").
- Limits: length caps as in §5.3; empty `question`/`answer`/names
  rejected; at most 50 open questions per ticket (51st → error). Text is
  stored as given and rendered only through autoescaped templates.

### 5.5 Who can write

- Any caller the hub already authenticates: the shared bearer token, or a
  web session cookie of any role. So any connected repo can ask and answer.
- `asked_by`/`answered_by` are self-declared (skills pass
  `git config user.name`). This is tracking, not authentication, and the
  docs say so.
- No extra rate limit beyond the 50-open-per-ticket cap and the length
  caps.

## 6. Hub web page: Q&A menu

- New left-rail item **Q&A** at `/ui/questions`, read-only, visible to every
  logged-in user and to bearer requests (like the other menus).
- `/ui/questions` — tickets that have questions, grouped by BA repo: ticket
  id, open / waiting / answered counts, and the age of the oldest open
  question. Filter: unresolved only (open + waiting, default) / all.
- `/ui/questions/ticket?repo=<repo-id>&ticket=<id>` — every question for that
  ticket, oldest first: number, state chip, question, context, blocks, asked
  by/at/rev; for answered ones the answer, the changed sections, the
  `answer_rev` (and "not on the hub yet" while waiting), answered by/at. The
  repo goes in the query string because repo-ids can contain `/` (same
  reason as `planui`).
- Each ticket id links to its existing ticket page; the group part of that
  URL is derived at render time from the hub plan (`planstatus`).
- The existing ticket page shows a one-line "N unresolved questions" link
  when N > 0.
- Same route/template pattern as `planui.py`; same shell, styles and
  autoescaping. No forms.

## 7. BA side: `/ba-answer-questions`

New BA-repo skill + command (four files, like `ba-ticket-author`: Claude
skill, Claude command, Copilot prompt, Cursor command; shared body in
`templates/init/bodies/`).

The BA flow already publishes from the BA repo's `main` (CI, intake route,
auto-merge when the registry says so). The skill does not commit, push or
publish — consistent with `ba-ticket-author` — and does not wait for the
publish: the answer is recorded with the revision it expects, and the hub
shows it as "waiting for publish" until that revision lands.

Workflow:
1. **List** — `kb_question_list(repo=<this repo-id>, status=open)`. Nothing
   open → say so and stop.
2. **Walk** — one ticket at a time: each open question with its context and
   blocked ACs, beside the relevant part of the local ticket file.
3. **Answer** — the BA gives each answer. If the answer changes behaviour,
   the skill amends the ticket under `ba-ticket-author`'s amend rules, all
   questions of that ticket in **one** amendment:
   - bump `> Revision:` to N+1;
   - one `## Change log` row with Trigger `question` (a new member of
     `planrev.TRIGGERS`), What changed = `Q<ids>: <one line>`, Affected =
     the changed section names;
   - one maturity review round, as amend mode already requires;
   - Definition of Ready: amend mode unticks boxes whose evidence changed,
     and `kb plan-ingest` drops a ticket whose DoR is not fully ticked. The
     skill shows the unticked boxes and asks the BA to re-check and re-tick
     them. It does not record any answer for that ticket while DoR is not
     fully ticked, so the ticket never leaves the hub because of Q&A.
   - `kb ticket lint` must pass.
4. **Record** — `kb_question_answer` for each question: answer,
   `answer_rev = N+1` and `ticket_sections` = the change-log row's Affected;
   or `answer_rev = None` and `[]` when the ticket did not change.
5. **Report** — list `Q<id> → answered (rev N+1: sections …)`, remind the BA
   to commit and merge the ticket change as usual so it publishes, and give
   the hub Q&A link to paste in chat.

## 8. Dev side

### 8.1 Raising questions (`dev-design`, `dev-plan`)

The design and plan are written by `design-author`/`plan-author`
subagents, which cannot dispatch subagents themselves. So:

- The author subagent never calls the hub. It lists what it could not
  decide in a `## Questions raised` section of its draft, each item tagged
  `business` or `technical`, with the AC it blocks (or `none`).
- The orchestrating skill (`dev-design`/`dev-plan` main flow) then:
  - **technical** → dispatches `dev-sa` (§8.3) per question, writes each
    decision into the draft's `## Technical decisions`, and re-dispatches
    the author/fix round with those decisions;
  - **business** → `kb_question_ask(ticket, question, asked_by, context, blocks)`
    and moves the item to the draft's `## Open questions` as
    `- Q<id> — <question> — blocks: <AC ids|none>`. A question the SA
    returned as business is handled the same way.
- Gate: a design or plan with an open BA question that blocks an AC cannot
  pass its gate. The skill stops with the hub Q&A link for the Dev to paste
  in chat. Non-blocking questions do not stop the gate; reviewers (A1/A2)
  treat them as known open items, not as defects.
- `State:` line: a fifth marker `BA-Q: none | open Q<ids> | waiting Q<ids>`
  joins the existing four; tests that pin the four markers are updated.
- This replaces "write `OPEN(BA)` and report it in the PR notes" for
  questions found during design/plan. `OPEN(BA)` stays for the
  execution-time case in `dev-execute`, which returns to `dev-design`, which
  then asks per this section.

### 8.2 Resuming (`dev-implement-ticket`)

On every entry, for the ticket in flight,
`kb_question_list(ticket=…, status=all)`:
- **answered** questions not yet marked in the design/plan → show each
  answer with its changed sections, re-fetch the ticket with
  `kb_ticket_fetch` into `docs/impl/<id>/ticket.md`, mark the `## Open
  questions` lines as answered (`— answered rev N`), and route back to
  `dev-design` if a changed section touches an approved design (it goes
  back to `draft`).
- **waiting** (answer recorded, revision not on the hub yet) → show the
  answer text as information only, say which revision it waits for, and do
  not act on it.
- **open** and blocking → say so in the state line; do not continue past
  the gate.

### 8.3 The Dev-repo SA agent

- New Dev-repo skill `dev-sa` (four files like the other dev skills; added
  to the `DEV_TEMPLATES` skill-name tuple), usable two ways:
  - **Dispatched** by the `dev-design`/`dev-plan` orchestrator as a
    subagent, following the existing review-dispatch contract (fresh
    context, artefacts passed as file paths, model named).
  - **Directly** by the Dev: `/dev-sa <question>` for the ticket in flight.
- Inputs: the question, `docs/impl/<id>/ticket.md`, the current design/plan
  draft.
- It reads the repo source freely and uses `kb_search`/`kb_get_section` for
  the hub's `-code`, `-svc` and domain documents.
- Output, returned to the caller (which writes it): decision, reasoning,
  rejected alternatives, and evidence as `path:line` and `doc §section`
  citations; or "business question: <why>" when the answer would change
  what an AC means.
- Written into `design.md` (or `plan.md`) under `## Technical decisions` as
  `- SA-<n>: <decision> — why — evidence`. Nothing goes to the hub.

## 9. Docs

- QUICKSTART-ba: `/ba-answer-questions`, the `question` change-log trigger,
  re-ticking DoR, "waiting for publish".
- QUICKSTART-dev / guide-dev: business vs technical questions, the `BA-Q`
  state marker, `/dev-sa`.
- QUICKSTART-hub / README: the Q&A menu, `.kb-qa/`, the new MCP write tools
  (any authenticated caller, self-declared names, shared hub server only).
- CHANGELOG and minor version bump.

## 10. Testing expectations

- Store: ask/list/answer, derived states (open → waiting → answered as the
  hub revision moves), answering twice refused, `answer_rev` must exceed the
  hub revision, sections required iff `answer_rev`, caps (length, 50 open).
- MCP tools: ticket resolution (unknown, ambiguous, qualified, nested
  repo-id), refusal on a cache-clone hub, error texts, full round trip.
- `planrev`: `question` accepted as a trigger.
- Web: list and ticket pages render, states, escaping of question/answer
  text, query-string repo with `/`, unresolved-count link on the ticket
  page, read-only for every role.
- Templates: new skills installed for the right repo kind; bodies contain
  the gate rule, the `BA-Q` marker, the DoR rule and "never commits or
  publishes" (pinned like existing skill tests).

## 11. Decided by the owner

- The ticket stays the source of truth. An answer that updates the ticket
  must say which parts changed.
- Q&A on the hub is for BA questions only.
- Technical questions go to a new SA agent in the Dev repo, separate from
  the BA-repo SA. Its decisions live only in the Dev's design/plan.
- Every write to the hub's Q&A goes through MCP. Storage is SQLite.
- No chat notifications or reminders.

## 12. Calls made by the designer (check these)

- One question gets one answer. There are no threads and no withdraw tool.
- `.kb-qa/qa.db` is its own file, separate from accounts.
- "Ticket revision" means the ticket's own `> Revision: N`. An answer that
  changes the ticket names the revision that carries it. The hub shows it
  as "waiting for publish" until that revision lands, so the BA side never
  has to wait for, or itself perform, a publish.
- A new change-log trigger `question`, with one amendment per ticket per
  answering session.
- No answer is recorded while the ticket's DoR is not fully ticked. This
  stops Q&A from knocking the ticket off the hub.
- The write tools refuse a hub served from a cache clone.
- Any authenticated caller may answer. There is a 50-open-question cap per
  ticket and no other rate limit.
- Author subagents only list questions. The orchestrator posts BA questions
  and dispatches `dev-sa`.
- A blocking BA question stops the design/plan gate. A non-blocking one
  does not.
- A fifth `BA-Q` marker joins the `State:` line.
