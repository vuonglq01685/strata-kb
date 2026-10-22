# Ticket claims — several Devs on one repo — design

Date: 2026-10-22
Status: draft, awaiting owner approval

## 1. Intent

Strata's Dev side assumes one Dev per hub: `kb auto run` picks the first
`ready` ticket (`autorun/picker.py:pick_dev`) and the full-auto spec says
"with one Dev per hub, every ticket on the hub is this Dev's"
(`2026-10-16-full-auto-mode-design.md` §6.5). The owner now wants several
Devs on **one dev repo, on different machines**, working the hub's `ready`
tickets in parallel to finish them faster, without blocking each other.

Today nothing says a ticket is being worked on. `planstatus` knows `ready`,
`draft`, `to-draft`, `blocked`, `done`; `done` appears only after the PR
merged and the Dev published the `hist.*` row. Two `kb auto run` loops on two
machines therefore pick the **same** ticket. `.kb/auto/run.lock` only stops
two runs on one machine.

The fix: a **claim** on the hub. A Dev (a `kb auto run` loop, or a person
running `/dev-implement-ticket`) claims a ticket before working on it; the
hub grants one open claim per ticket; the Ticket menu shows
`In progress · taken by <who> · <phase> · updated <x> ago`. A claim nobody
keeps alive expires, and a hub admin can release one by hand, so an
abandoned ticket goes back to the pool.

## 2. Goals

- Two or more `kb auto run` loops on the same dev repo, on different
  machines, never work the same ticket at the same time. Each picks the next
  unclaimed `ready` ticket.
- A Dev working by hand (`/dev-implement-ticket`, `/dev-fix-bug`) claims the
  same way and is stopped, with the holder's name, when someone else holds
  the ticket.
- The hub web UI's Ticket menu shows, for a claimed ticket: status
  `In progress`, who holds it, the current phase, and when it was last
  updated. Visible to every logged-in role.
- The holder keeps the claim alive by updating it (phase changes and a
  periodic heartbeat). The owner said: "dev có thể đẩy lên update ticket đó".
- An abandoned claim is freed three ways:
  1. the holder releases it (`kb claim release`, or the runner on stop);
  2. it **expires** after `claim_ttl` without an update — **4 hours**,
     agreed with the owner, configurable on the hub;
  3. a **hub admin** releases it from the ticket's page in the web UI, with
     a reason. Only the `admin` role sees and may use this button (owner's
     decision).
- After a release or expiry, the next Dev who claims the ticket can continue
  the previous holder's branch.

## 3. Non-goals

- BA-side claims (two BAs drafting the same story). Dev tickets and bugs only.
- Several dev repos sharing tickets. One dev repo; the hub may still serve
  others, but claims are keyed by the ticket's `<repo>:<id>` like Q&A.
- Preventing two *different* tickets from touching the same files. Merge
  conflicts stay with PRs and the existing merge-conflict handling.
- A new `planstatus` status. `In progress` is an overlay on `ready`, read
  from the claim store; the derived plan status is unchanged.
- Assigning tickets to people (a lead choosing who does what). Claims are
  self-service, first come first served.
- A web page listing claim history across tickets, or Slack/email alerts on
  expiry.
- Changing how `/api`, `/mcp` or CI authenticate (the shared bearer token
  stays as is).

## 4. Anti-goals (a failure even if it technically works)

- Two machines both believing they hold one ticket (a check-then-claim race).
  The grant must be atomic on the hub.
- A ticket stuck forever because its holder vanished. Expiry needs no human
  and no background job.
- A live, working run losing its claim because a long task (up to the 4 h
  task timeout in `autorun/claude.py`) sent no update. The runner, not the
  agent, owns the heartbeat.
- Losing code when a claim expires or is released. A claim only gates who
  *starts* work; branches and PRs are never touched by claim logic.
- Auto mode stalling when the hub's claim route is missing (an old hub):
  the runner must fail loudly with an upgrade message, the way
  `hubapi._json` does for other routes, not silently pick unclaimed.
- Any role but `admin` able to release someone else's claim from the web.

## 5. Constraints (facts in the code today)

- **The hub already keeps runtime state in SQLite** for Q&A:
  `ticketqa.QaStore` at `ticketqa.qa_db_path(hub.root)`, written over MCP
  (`kb_question_ask`), read over `GET /api/questions`, shown in `web/qaui.py`.
  Claims follow this precedent. The Q&A routes refuse with
  `qa_needs_hub_server` unless the server serves its own hub checkout
  (`hub_serves_own_checkout`); claims have the same requirement.
- **Accounts and roles exist**: `serving/accounts.py` (`admin`, `ba`, `dev`),
  session login for `/ui`, `registry_routes.admin_or_403` and CSRF on every
  POST. The Release button reuses these. A bearer request has no account.
- **The runner already talks to the hub over HTTP, local and cloud**:
  `autorun/qa.py:QaClient` (`GET /api/questions`, from
  `STRATA_KB_HUB_URL` + `STRATA_KB_HTTP_TOKEN`) and, on cloud,
  `hubapi.HubApi`. So every machine running `kb auto run` already has hub
  HTTP credentials; a local clone of the hub (`HubHandle`) is read-only and
  cannot hold claims.
- **The runner's task is a blocking `claude -p` child** (`claude.run_task`,
  up to 4 h). A BA repo already runs a side thread for the loop's lifetime
  (`autorun/qathread.py:QaThread`). A heartbeat thread follows that shape.
- **Skills call `kb` CLI subcommands, not `gh` or raw HTTP**, and auto mode's
  permission allowlist is `templates/init/claude-settings-auto.json`
  (e.g. `Bash(kb pr *)`).
- **Identity**: Q&A's `asked_by` is `git config user.name`, and `kb-auto`
  for every auto run (`dev-design.md:347`) — which cannot tell two auto
  machines apart.
- Auto branches are `auto/<ticket-id>`; a manual branch is `<ticket-id>`
  (`dev-implement-ticket.md:171`). Auto already continues an open PR's
  branch after a crash (full-auto spec, "Already finished").

## 6. Approaches considered

**A. Claim by remote branch.** Before work, push `auto/<ticket-id>` with a
unique claim commit; git rejects the second push (non-fast-forward), so one
machine wins. Pick skips tickets with a branch on `origin`. Expiry = no new
commit for N hours and no open PR. No new infrastructure, works on cloud.
*Trade-off:* the hub web UI cannot show it without the hub reading every dev
repo's branches; phase and "taken by" have nowhere natural to live; the
manual branch name differs from the auto one.

**B. Claim on the hub (chosen).** A claim table next to the Q&A store, an
HTTP API with an atomic grant, a `kb claim` CLI over it, the runner and
skills calling it, the Ticket menu rendering it, and an admin-only Release
button. *Trade-off:* more code (hub store, routes, UI, client) and a hub
redeploy; the hub must be reachable to start a ticket.

**Dropped:** a `claims.yaml` committed to the default branch — fights branch
protection, races on push, and fills history with noise.

The owner picked B because the claim must show on the hub's Ticket menu as
`In progress · taken by`, with Devs pushing updates, and an admin able to
release it. The Q&A store shows the hub already accepts this kind of state.

## 7. What gets built

### 7.1 Claim store (hub)

A SQLite table next to the Q&A store (same file or a sibling — builder's
call), one row per claim:

| Column | Meaning |
|---|---|
| `id` | integer key |
| `repo`, `ticket` | the ticket, as Q&A keys it (`<repo>:<id>` resolved via `ticketfetch.find`) |
| `holder` | display name, see §7.4 |
| `token` | random secret returned to the claimer; required to update or release |
| `phase` | free text from a short known list (§7.5), last value wins |
| `claimed_at`, `last_seen` | **hub clock only**, never client timestamps |
| `closed_at`, `closed_by`, `close_reason` | set on release, expiry noticed, or done |

**Open claim** = `closed_at IS NULL AND last_seen > now - claim_ttl`.
Expiry is lazy: no background job. A read or a new claim that finds an
expired open row closes it with `close_reason = expired`.

**Atomic grant:** inside one transaction (`BEGIN IMMEDIATE`), close an
expired row for the ticket if any, then insert; a partial unique index on
`(repo, ticket) WHERE closed_at IS NULL` makes a second concurrent insert
fail. The loser gets "taken" with the current holder.

`claim_ttl` is a hub server setting (env or server config, default
`14400` s = 4 h). *(Designer's call: one TTL for auto and manual; the runner's
heartbeat keeps a live auto run far inside it.)*

### 7.2 HTTP API (hub, bearer auth like `/api/questions`)

- `POST /api/claims` `{ticket, holder}` → `201 {id, token, ...}`, or `409
  {error: "taken", holder, phase, last_seen}`, `404` unknown ticket, `503
  qa_needs_hub_server`-style when the hub does not serve its own checkout.
  Re-claiming a ticket you already hold (same `token` sent) is `200`, so a
  crashed run's retry is harmless.
- `PATCH /api/claims/{id}` `{token, phase?}` → bumps `last_seen`, sets
  `phase`. `409 {error: "lost", close_reason, closed_by}` when the claim was
  closed or expired — the holder must stop and re-claim.
- `DELETE /api/claims/{id}` `{token, reason}` → release by the holder.
- `GET /api/claims?repo=&ticket=` → open claims (after lazy expiry).

Request bodies are JSON with capped size (`web/bodycap`). The route names and
exact payloads are the builder's, kept consistent with `web/api.py`.

### 7.3 `kb claim` CLI (client)

Over the API, using the same env as `QaClient` (`STRATA_KB_HUB_URL`,
`STRATA_KB_HTTP_TOKEN`):

- `kb claim take <ticket> [--as <name>]` → prints the holder, exits `0`; exit
  `3` with `taken by <holder> (<phase>, updated <x> ago)` when someone else
  holds it.
- `kb claim update <ticket> --phase <phase>`
- `kb claim release <ticket> [--reason <text>]`
- `kb claim list [--json]` → open claims for this repo.

The claim `id` and `token` are kept locally in `.kb/auto/claims.json`
(gitignored with the rest of `.kb/auto/`), keyed by ticket, so `update` and
`release` need only the ticket id. *(Designer's call: CLI is the one path for
runner, skills and people; no MCP twin, since auto runs call the CLI and the
runner uses HTTP. An MCP tool can come later if a client needs it.)*

Add `Bash(kb claim *)` to `claude-settings-auto.json`.

### 7.4 Holder name

`<git config user.name>@<hostname>` by default, e.g. `vuong@laptop-2`;
`--as` or an env override (`STRATA_KB_CLAIM_AS`) replaces it, useful on
cloud where the hostname is random. *(Designer's call: this replaces
`kb-auto` for claims because two auto machines must be told apart; Q&A's
`asked_by` is unchanged.)*

### 7.5 Runner (`kb auto run`, dev repo)

- **Pick then claim:** `pick_dev` yields candidates in its current order
  (bugs, unparented tickets, stories with done dependencies), skipping
  tickets with an open claim held by someone else (`GET /api/claims`). The
  runner claims the first; on `409 taken` (a race lost) it moves to the next
  candidate. A task stored in `state.json` (crash, retry, answered Q&A)
  re-claims with its stored token; if the claim is now someone else's, the
  runner drops the task and picks again, logging who holds it.
- **Heartbeat thread** for the loop's lifetime, the `QaThread` shape: every
  `claim_heartbeat` seconds (default 900 = 15 min; *designer's call*) it
  `PATCH`es the held claim. A `409 lost` is logged and recorded; the runner
  does not start the next task step on a lost claim (exact interruption of a
  running child is the builder's call — at minimum the result is not merged
  under a lost claim, see §7.6).
- **Phases** the runner or skills report: `claimed`, `design`, `plan`,
  `execute`, `handover`, `ci`, `waiting-qa`. The runner sets `waiting-qa` on
  `blocked-qa` and keeps heartbeating while it waits, so a ticket waiting on
  the BA is not taken by another Dev.
- **Release:** on `done` (PR merged; the hub's plan will show `done` after
  publish), on a stop (`MAX_ATTEMPTS`, `ci-red`, any `_stop`) with the stop
  reason, and on a clean shutdown of the loop (Ctrl-C) with
  `reason = runner stopped`. A crash or kill releases nothing; expiry covers
  it.
- **Hub without claims:** a `404` on the claims route stops the run with
  `hub server has no /api/claims — upgrade it to strata-kb <version> or
  later`. *(Designer's call: no silent fallback to unclaimed picking.)*

### 7.6 Skills (dev repo templates)

- `dev-implement-ticket` and `dev-fix-bug`, at Intake, run
  `kb claim take <id>`. Exit `3` → STOP: "`<id>` is taken by `<holder>`
  (`<phase>`, updated `<x>` ago). Pick another ticket, or ask a hub admin to
  release it." In auto mode the runner already holds the claim, so `take`
  is the idempotent re-claim.
- Each phase skill (`dev-design`, `dev-plan`, `dev-execute`, `dev-handover`)
  runs `kb claim update <id> --phase <phase>` on entry; `dev-execute` also
  after each task commit (that is the manual Dev's heartbeat).
- `dev-handover`, before opening or merging the PR, runs `kb claim update`;
  a `lost` claim STOPs with "your claim on `<id>` was released by
  `<closed_by>` (`<reason>`); re-run `/dev-implement-ticket <id>` to claim it
  again" — no push to a branch someone else may now own.
- **Continuing someone's branch:** when a claim is new and `auto/<id>` or
  `<id>` exists on `origin`, the skill fetches it and continues there (the
  existing re-entry rules decide what is done), noting in the log which
  holder's work it took over. *(Designer's call.)*
- `QUICKSTART-dev.md` gains a short "Several Devs" section: claims, the 4 h
  expiry, `kb claim list|release`, the admin Release button.

### 7.7 Web UI (Ticket menu)

- `web/planui.py` ticket list and ticket page read open claims for the
  repo. A `ready` ticket with an open claim shows a badge
  `In progress` and, on its page,
  `Taken by <holder> · <phase> · updated <x> ago · since <claimed_at>`.
  `done`, `draft`, `blocked` tickets show their status as today (a claim on a
  `done` ticket is closed on read with `close_reason = done`).
- On the ticket page, an **admin** sees a **Release** button with a required
  reason field; a POST with CSRF (the `registry_routes` pattern) closes the
  claim with `closed_by = <admin username>`. Non-admins never see it; a
  non-admin or bearer POST gets `403`.
- The ticket page shows the last closed claim (who, when, why) so the next
  Dev knows the ticket was taken over or expired.
- A missing or unreadable claim store renders the page without claim info
  plus a short notice, never a 500 (the `qaui` pattern).

## 8. Left to the builder

- Same SQLite file as Q&A or a sibling; schema migration style.
- Exact route paths, JSON shapes and error codes, consistent with
  `web/api.py` and `hubapi._json`.
- Whether `pick_dev` reads claims itself or the runner filters its
  candidates; how the heartbeat thread signals a lost claim to the loop.
- Where the hub reads `claim_ttl` (env name, server config field).
- Wording of badges and messages, within the meaning above.
- Tests: the atomic grant under two concurrent claimers, lazy expiry with an
  injected clock, admin-only release (admin, ba, dev, bearer), runner pick
  skipping a claimed ticket and moving on after a lost race, heartbeat
  keeping a 4 h+ task alive, release on done/stop.
