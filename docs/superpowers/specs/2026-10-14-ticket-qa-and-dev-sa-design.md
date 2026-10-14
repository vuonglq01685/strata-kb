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
- The hub has a **Q&A** menu listing questions per ticket with their state
  (open / answered), who asked, when, and the answer.
- The BA answers from the BA repo with a new `/ba-answer-questions` command
  that also edits the ticket, publishes it, and records the changed ticket
  sections with the answer.
- When the Dev comes back to the ticket, `/dev-implement-ticket` shows the
  answers and the changed sections, fetches the new ticket, and continues.
- A technical question during `/dev-design` or `/dev-plan` is handed to the
  Dev-repo SA agent, and its decision is written into the Dev's design or
  plan.

## 3. Non-goals

- Chat notifications (Slack/Teams webhooks), reminders, or any push to
  people. People keep pinging each other in chat; they paste the hub Q&A
  link instead of copying text.
- Threads. One question has one answer. A follow-up is a new question that
  may cite the earlier one's number. *(Designer's call — the owner did not
  ask for threads.)*
- Answering or editing tickets from the hub web UI. The web page is
  read-only.
- Sending technical questions to the hub, or storing the Dev-repo SA's
  decisions on the hub. They live only in the Dev's `design.md`/`plan.md`.
- Per-person authentication on MCP writes (see §5.4).

## 4. Anti-goals

- An answer that changes behaviour while the ticket stays unchanged. The
  ticket is the source of truth; the Q&A record only points at it.
- A Dev continuing past a business question that blocks an AC as if it were
  answered.
- The Dev-repo SA deciding business behaviour. It decides *how*, never
  *what*; a business ambiguity it finds becomes a BA question.

## 5. Q&A store on the hub

### 5.1 Storage

- SQLite on the hub server, decided by the owner. File
  `<hub root>/.kb-qa/qa.db`, beside `.kb-auth/` on the same `/data` volume.
- `.kb-qa/` is kept out of git exactly like `.kb-auth/`: written to
  `.git/info/exclude` at startup (generalise `accounts.ensure_git_exclude`
  to take the directory name) and added to `hub-gitignore.txt`.
- Table `questions`:
  | column | type | notes |
  |---|---|---|
  | `id` | INTEGER PK | shown as `Q<id>` |
  | `repo` | TEXT | BA repo-id holding the ticket |
  | `ticket` | TEXT | ticket id (file stem, e.g. `M-checkout-US1`) |
  | `question` | TEXT | ≤ 4000 chars |
  | `context` | TEXT | where it came from, e.g. `design §Data model`, ≤ 1000 chars, may be empty |
  | `asked_by` | TEXT | self-declared name, ≤ 100 chars |
  | `asked_at` | TEXT | UTC ISO-8601 |
  | `status` | TEXT | `open` or `answered` |
  | `answer` | TEXT | ≤ 4000 chars, NULL while open |
  | `ticket_sections` | TEXT | JSON list of changed ticket section headings, `[]` when the ticket did not change |
  | `answered_by` | TEXT | self-declared name |
  | `answered_at` | TEXT | UTC ISO-8601 |
  | `ticket_rev` | TEXT | hub revision of the ticket when the answer was recorded |
- Stdlib `sqlite3`, one short-lived connection per call, same style as
  `serving/accounts.py`. No new dependency.

### 5.2 MCP tools (the only write path)

All questions and answers go through MCP, decided by the owner. These are
the first MCP tools that write; they follow the existing tool pattern in
`mcp.py` (`@mcp.tool()`, `async def … -> str`, sync body in
`anyio.to_thread.run_sync`).

- `kb_question_ask(ticket: str, question: str, asked_by: str, context: str = "") -> str`
  - `ticket` is a bare id or `<repo>:<id>`, resolved with the same rules as
    `kb_ticket_fetch` (`ticketfetch.find`). Unknown → error text "not on the
    hub — ask the BA to run kb publish"; ambiguous → "qualify it as
    `<repo>:<id>`".
  - Returns `Q<id>` and the hub link to the ticket's Q&A page.
- `kb_question_list(ticket: str = "", repo: str = "", status: str = "open") -> str`
  - Filters by ticket, by BA repo, or both; `status` is `open`, `answered`
    or `all`. Returns a plain-text list, newest last, each item with id,
    ticket, status, question, context, asked_by/at, and for answered ones the
    answer, changed sections and `ticket_rev`.
- `kb_question_answer(id: int, answer: str, answered_by: str, ticket_sections: list[str]) -> str`
  - Only an `open` question can be answered; answering an already answered
    one is an error naming who answered it.
  - Every name in `ticket_sections` must be a section heading of the
    ticket **as currently on the hub**. A name not found → error listing
    the ticket's headings. This forces the BA to publish the updated ticket
    before recording the answer, so the Dev never reads an answer that
    points at a ticket change the hub does not have yet.
  - Records the ticket's current hub revision as `ticket_rev`.
- No withdraw/delete tool. *(Designer's call: a question no longer needed is
  answered "no longer needed" with `[]`.)*

### 5.3 Limits and validation

- Length caps as in §5.1; empty `question`/`answer`/`asked_by`/
  `answered_by` rejected.
- Text is stored as given and only ever rendered through autoescaped
  templates.

### 5.4 Who can write

- MCP over HTTP is authenticated by the shared bearer token, so any repo
  connected to the hub can ask and answer. `asked_by`/`answered_by` are
  self-declared (skills pass `git config user.name`). This is tracking, not
  authentication, and the docs say so.
- MCP over stdio (a local hub) has no auth today; same behaviour.

## 6. Hub web page: Q&A menu

- New left-rail item **Q&A** at `/ui/questions`, visible to every logged-in
  user and to bearer requests (read-only, like the other menus).
- `/ui/questions` — tickets that have questions, grouped by BA repo, each row
  with the ticket id (linking to its existing ticket page), open count,
  answered count, and the age of the oldest open question. Filter: open only
  (default) / all.
- `/ui/questions/{repo}/{ticket}` — every question for that ticket, newest
  last: number, status chip, question, context, asked by/at; for answered
  ones the answer, the changed ticket sections, answered by/at.
- The existing ticket page shows a one-line "N open questions" link when
  N > 0.
- Same route/template pattern as `planui.py`; same shell, styles and
  autoescaping. No forms.

## 7. BA side: `/ba-answer-questions`

New BA-repo skill + command (four files, like `ba-ticket-author`:
Claude skill, Claude command, Copilot prompt, Cursor command; shared body in
`templates/init/bodies/`).

Workflow:
1. **List** — `kb_question_list(repo=<this repo-id>, status=open)`. Nothing
   open → say so and stop.
2. **Walk** — one ticket at a time: show each open question with its
   context and the relevant part of the local ticket file.
3. **Answer** — the BA gives the answer. If it changes behaviour, the skill
   edits the ticket under the same rules as `ba-ticket-author` (it must
   still lint clean) and notes the headings it changed. An answer that
   changes nothing in the ticket is allowed only when the BA confirms the
   ticket already says it.
4. **Publish** — once per batch: `kb publish` for the edited tickets and
   wait until it is on the hub (merged; the repo is expected to have
   auto-merge on). If it does not land (PR left open), stop and tell the BA
   the answers are not recorded yet.
5. **Record** — `kb_question_answer` for each question with the answer and
   the changed headings.
6. **Report** — list `Q<id> → answered (sections …)` and the hub Q&A link
   the BA can paste in chat.

## 8. Dev side

### 8.1 Asking the BA (`dev-design`, `dev-plan`)

- When the design or plan hits a business question, the skill decides
  whether it **blocks** an AC.
  - Posts it with `kb_question_ask(ticket, question, asked_by, context)`.
  - Records it in the design/plan under `## Open questions` as
    `- Q<id> — <question> — blocks: <AC#|none>`.
  - Blocking → the gate cannot be passed: the skill stops with
    `State: waiting on BA (Q<ids>)` and the hub Q&A link for the Dev to
    paste in chat.
  - Non-blocking → work continues on the parts it does not touch.
- This replaces today's "write `OPEN(BA)` and report it in the PR notes"
  for questions raised during design/plan. `OPEN(BA)` stays for the
  execution-time case in `dev-execute` (return to design, which then asks).

### 8.2 Resuming (`dev-implement-ticket`)

- On every entry, for the ticket in flight, call
  `kb_question_list(ticket=…, status=all)`.
- Newly answered questions → show each answer with its changed sections,
  re-fetch the ticket with `kb_ticket_fetch` into `docs/impl/<id>/ticket.md`,
  mark the `## Open questions` lines as answered in the design/plan, and
  route back to `dev-design` if a changed section touches an approved
  design (the design goes back to `draft`).
- Still open and blocking → say so in the state line; do not continue.

### 8.3 The Dev-repo SA agent

- New Dev-repo skill `dev-sa` (four files like the other dev skills; added
  to the `DEV_TEMPLATES` skill-name tuple), usable two ways:
  - **Dispatched** by `dev-design`/`dev-plan` as a subagent when a technical
    question comes up, following the existing review-dispatch contract
    (fresh context, artefacts passed as file paths, model named).
  - **Directly** by the Dev: `/dev-sa <question>` for the ticket in flight.
- Inputs: the question, the ticket (`docs/impl/<id>/ticket.md`), the
  current design/plan draft.
- It reads the repo source freely and uses `kb_search`/`kb_get_section` for
  the hub's `-code`, `-svc` and domain docs.
- Output (returned to the caller, which writes it): decision, reasoning,
  rejected alternatives, and evidence as `path:line` and `doc §section`
  citations.
- Written into `design.md` (or `plan.md`) under `## Technical decisions` as
  `- SA-<n>: <decision> — why — evidence`. Nothing goes to the hub.
- It never changes business behaviour: a question whose answer would change
  what an AC means is returned as "business question" and the caller asks
  the BA per §8.1.

## 9. Docs

- QUICKSTART-ba: the `/ba-answer-questions` step and that answers require a
  published ticket.
- QUICKSTART-dev / guide-dev: business vs technical questions, the waiting
  state, `/dev-sa`.
- QUICKSTART-hub / README: the Q&A menu, `.kb-qa/`, the new MCP tools
  (write tools, self-declared names).
- CHANGELOG and minor version bump.

## 10. Testing expectations

- Store: create/list/answer, status transitions, answering twice refused,
  length caps, ticket_sections validation against the hub ticket.
- MCP tools: ticket resolution (unknown, ambiguous, qualified), error text,
  round trip ask → list → answer → list.
- Web: Q&A list and ticket pages render, escaping of question/answer text,
  open-count link on the ticket page, read-only for every role.
- Templates: new skills installed for the right repo kind; skill bodies
  contain the gate and state-line rules (pinned like existing skill tests).

## 11. Decided by the owner

- Ticket stays the source of truth; an answer that updates the ticket must
  say which parts changed.
- Q&A on the hub is for BA questions only.
- Technical questions go to a new SA agent in the Dev repo, separate from
  the BA-repo SA; its decisions live only in the Dev's design/plan.
- Every write to the hub's Q&A goes through MCP; storage is SQLite.
- No chat notifications or reminders.

## 12. Calls made by the designer (check these)

- One question, one answer; no threads; no withdraw tool.
- `.kb-qa/qa.db` as a separate file from accounts.
- `kb_question_answer` refuses section names not in the hub's current
  ticket, which forces publish-before-answer.
- A blocking BA question stops the design/plan gate; a non-blocking one
  does not.
- The BA-side command publishes once per batch and records answers only
  after the publish lands.
