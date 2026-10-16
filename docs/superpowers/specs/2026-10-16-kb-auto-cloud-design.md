# Full-auto mode on Claude Code cloud — design

Date: 2026-10-16
Status: approved by owner (2026-10-16)
Builds on: `2026-10-16-full-auto-mode-design.md` (1.29.0)

## 1. Intent

Full-auto mode (1.29.0) runs a BA or Dev repo's loop on the owner's own
machine: `nohup kb auto run`, one fresh `claude -p` per ticket, the hub read
from a local git clone, PRs through `gh pr`. The owner now wants the same
loop to run **inside one Claude Code cloud session** (claude.ai/code), for
both the BA repo and the Dev repo, with the hub reached through its HTTP/MCP
server instead of a clone.

The first attempt on cloud refused before anything ran:

- `kb auto status` named the session branch (`claude/amazing-johnson-at3v5j`)
  as the default branch, because the cloud clone has no `origin/HEAD` and
  `gitio.default_branch` falls back to the current branch.
- `/kb-auto run` step 2 requires standing on the default branch, but a cloud
  session always works on its own `claude/...` branch.
- Preflight reads the hub registry through `resolve_hub`, which `git clone`s
  the hub; the cloud session cannot clone the hub repo (it is outside the
  session's GitHub scope), and the owner does not want it to.
- `nohup` detaches from the session; a cloud container is reclaimed when the
  session goes idle, killing the loop.

## 2. Goals

- In a cloud session on its `claude/...` branch, `/kb-auto run` starts the
  loop for a `ba` or `dev` repo and it runs ticket after ticket until the
  product is done or a stop rule fires — same rules as local.
- Each task is still **one whole ticket** (`dev-implement-ticket`,
  `dev-fix-bug`, `ba-ticket-author`, `ba-mission-plan`, the BA Q&A answerer)
  in a **fresh context**: one new `claude -p` process per ticket, so nothing
  of one ticket is carried into the next (the cloud equivalent of `/clear`).
- No hub clone on cloud: the runner and the task processes reach the hub only
  through `STRATA_KB_HUB_URL` + `STRATA_KB_HTTP_TOKEN` (HTTP API and the MCP
  server declared in the repo's `.mcp.json`).
- GitHub work (list/create/view/merge PRs, read checks) works on cloud, where
  GraphQL is blocked.
- The session stays alive for as long as the loop runs, without the session's
  own context growing per ticket.

## 3. Non-goals

- A scheduled or multi-session design (one cloud session per ticket). The
  owner chose one long session.
- Changing the loop's rules: task picking, attempts, stop reasons, Q&A
  waiting, admin merge — all stay as in 1.29.0.
- Running the hub itself on cloud. The hub server already runs and the cloud
  session reaches it.
- Removing the hub clone path for local use.

## 4. Anti-goals (works, but still a failure)

- Local behaviour changes. A local `kb auto run` with a hub URL/path in
  config must give the same results as 1.29.0 (clone cache, `nohup`, same
  PRs and merges; §6.5 may route PR calls through `kb pr`).
- The loop silently runs on a guessed default branch, or merges into the
  wrong base.
- The session's own context fills up with ticket output (each ticket's log
  belongs in `.kb/auto/logs/`, not in the session transcript).
- A ticket killed midway because a tool-call time limit expired.
- Weakening the permission model: still no `--dangerously-skip-permissions`,
  still `acceptEdits` plus the committed allow/deny list.

## 5. Verified facts about the cloud container (2026-10-16)

Checked in a cloud session on this repo:

- `claude -p --output-format json --permission-mode acceptEdits` works and
  returns a normal result.
- A `claude -p` child sees MCP servers from settings and the project
  `.mcp.json` (it listed `gitnexus`), **not** claude.ai connectors (no GitHub
  MCP, no Atlassian). Hub MCP must therefore come from the repo's `.mcp.json`
  — which the owner's Dev/BA repos already use, with `${STRATA_KB_HUB_URL}` /
  `${STRATA_KB_HTTP_TOKEN}` expanded from the environment the child inherits.
- `gh` is installed and REST works through the agent proxy
  (`gh api repos/<o>/<r>` returned `default_branch` and admin permissions).
  GraphQL is refused: `HTTP 403: GitHub GraphQL is not available from Claude
  Code sessions; use the REST API`. So `gh pr list|view|create|merge|checks|edit`
  fail; `gh api` and (to verify) `gh run ...` work.
- Auto-merge, review threads and draft/ready use CCR routes on
  api.github.com (`PUT|DELETE /repos/{o}/{r}/pulls/{n}/ccr/auto_merge`, ...).
- `git ls-remote --symref origin HEAD` returns the real default branch.
- Bash `run_in_background` has a hard limit of 2 h per command; the task
  timeout in `autorun/claude.py` is 4 h.

## 6. Design

### 6.1 Cloud detection

One helper, e.g. `strata_kb.cloud.is_cloud()`: true when
`CLAUDE_CODE_REMOTE` is set truthy. Everything below that differs between
local and cloud keys off this helper (and only this), so local behaviour is
untouched. An explicit override env (`STRATA_KB_CLOUD=0|1`) lets tests and
odd setups force either side.

### 6.2 Default branch

`gitio.default_branch` keeps its order but gains a middle step: when
`refs/remotes/origin/HEAD` is missing and a remote exists, ask the remote
(`git ls-remote --symref origin HEAD`), and only then fall back to the
current branch. Optionally run `git remote set-head origin <branch>` once so
later calls are cheap. This fixes the wrong `default_branch` in `kb auto
status` on cloud and on any clone made without `origin/HEAD`, local
included — a strict improvement, not a cloud-only branch.

### 6.3 The switch on cloud

Why 1.29.0 needs the switch on the default branch: every ticket branch is
cut from `origin/<default>`, and the task process reads `auto.enabled` and
the auto `.claude/settings.json` from that branch. A switch that lives only
on `claude/...` would be missing on every `auto/<ticket-id>` branch.

So the switch must still reach the default branch, but on cloud the owner is
never asked to check it out:

- `/kb-auto run` on cloud drops the "must stand on the default branch" step.
- When the switch is not yet on `origin/<default>`, the skill cuts a fresh
  branch `auto/switch` from `origin/<default>` holding **only**
  `.kb/config.yaml` and `.claude/settings.json` (never the session branch,
  which may carry other unreviewed commits), pushes it, opens a PR into the
  default branch through REST with a body that passes `kb-pr-lint`, waits for
  its checks to go green, and — after telling the owner and showing the
  admin-merge warning verbatim — squash-merges it through REST. Red checks →
  stop and report; never merge past red. Auto mode merges every ticket PR as
  admin anyway; this is the same act, on the switch. *(Isolation, lint-clean
  body, green-before-merge and squash are the designer's calls.)*
- *(Owner's decision, 2026-10-16:)* on cloud the session itself opens and
  admin-merges this switch PR; the owner does not have to enable the switch
  on the default branch by hand first.
- When the switch is already on `origin/<default>` (enabled earlier through a
  normal PR), this step is a no-op.
- Preflight's `_switch_refusals` stays as it is: it already reads the switch
  from `origin/<default>` and refuses when it is not there.

Local `/kb-auto run` keeps step 2 and the direct push unchanged.

### 6.4 Hub over HTTP, no clone

The runner touches the hub in three places, all through `resolve_hub` (git
clone):

| Caller | Needs |
|---|---|
| `runner.preflight` / `switch.registry_or_reason` | registry: this repo's entry, `auto_merge`, Dev repo count |
| `runner._check_done`, `picker.pick_dev` | `planstatus.next_from_hub(hub)`: stories, unparented, notes |
| `switch.warnings_for_on` | registry (Dev repo count) |

Add read-only endpoints to the hub HTTP API (same bearer token, same rate
limiter as `/api/questions`):

- `GET /api/registry` — the parsed registry (repo key, `repo_id`, kind,
  `auto_merge`).
- `GET /api/plan/next` — exactly what `planstatus.next_from_hub` returns,
  serialised (stories with their status/reasons, unparented, notes).

In the runner, introduce one small hub-reader seam with two implementations:
the existing clone-backed `HubHandle` path, and an HTTP path built from
`STRATA_KB_HUB_URL` + `STRATA_KB_HTTP_TOKEN` (reuse `qa.py`'s HTTP client
and env names). Selection: on cloud, HTTP is required (missing URL/token is
a preflight refusal naming the variables); locally, HTTP is used only when
`cfg.hub` is empty and the env vars are set, otherwise the clone path as
today.

The hub server must be upgraded to the release that has these endpoints.
Preflight on the HTTP path calls them first; a 404 means "hub server too old"
and is a refusal saying which version is needed.

Q&A already uses `/api/questions`, and publish goes through intake (a tag
the repo's CI uploads), so neither needs a clone.

**The task processes too.** The owner wants *every* hub read on cloud to go
over HTTP/MCP, not only the runner's. The skills are already MCP-first for
most hub reads; the CLI commands they call that still reach the hub through
`_hub_or_exit` / `_hub_or_reason` (a clone) need an HTTP path on cloud:

- `kb mission next` — when the Dev's `<x>-svc` document is not in the local
  `.kb/`, it loads it from the hub to work out which stories are done
  (`cli.py` ~3882). `pick_ba` and every BA "Already finished" check depend on
  it. Needs an endpoint returning a published doc dir as `ticketcheck`
  expects (or reuse `/api/docs/{doc}` if it carries enough).
- `kb resolve --status-only --cache` / `--write-cache` — CLI-first in
  `dev-implement-ticket` (no MCP path). Needs an HTTP path.
- The MCP-first commands whose CLI is only a fallback (`kb ticket check|lint|
  stale`, `kb mission lint`, `kb context new`, `kb query`, `kb get`,
  `kb doctor`): on cloud the fallback must not clone; it fails with one line
  saying to use the `strata-kb` MCP tool. *(Builder's call: give a fallback
  an HTTP path instead when it is cheap.)*

The rule for the builder: on cloud, `_hub_or_exit` / `_hub_or_reason` never
clone. They return the HTTP reader where a command supports it, otherwise a
clear refusal. Grep every caller and classify it.

### 6.5 GitHub without GraphQL

The skills and `ghio.py` use `gh pr list|view|create|merge|checks|edit`.
On cloud those fail. Route them through `kb` subcommands that call the REST
API via `gh api`, and have the skills call the `kb` form everywhere (local
and cloud alike, so there is one code path in the skills):

- `kb pr find --head <branch> [--state open|merged|closed] --json` —
  `GET /repos/{o}/{r}/pulls?head=<owner>:<branch>&state=...`
  (merged = closed with `merged_at`).
- `kb pr open --head <branch> --base <base> --title ... --body-file ...` —
  `POST /repos/{o}/{r}/pulls`.
- `kb pr merge <n> --method squash|merge` — `PUT /repos/{o}/{r}/pulls/{n}/merge`.
- `kb pr checks <n> [--wait]` — check runs for the PR head SHA,
  `GET /repos/{o}/{r}/commits/{sha}/check-runs` (+ combined status).
- `kb pr edit <n> --body-file ...` — `PATCH /repos/{o}/{r}/pulls/{n}`.

*(Designer's call:)* the skills use `kb pr` on local too, so there is one
code path; "local behaviour unchanged" (§4) means the same outcome, not the
same `gh` subcommand. `kb pr` calls `gh api` with the host taken from
`origin`, so GitHub Enterprise keeps working; a non-GitHub remote gets the
same "gh unavailable" handling the skills have today.

`--admin` today: `gh pr merge --squash --delete-branch`, falling back to
`--admin` when a required review blocks it (`dev-handover.md:245`,
`ba-ticket-author.md:380`). REST `PUT .../merge` has no flag; an admin's
merge bypasses branch protection only when the rule allows admin bypass.
`kb pr merge --admin` keeps the flag for the skills' wording and the spike
(§6.6) checks it actually merges past a required review on cloud. Branch
delete after merge: `DELETE /repos/{o}/{r}/git/refs/heads/<branch>`.

`ghio.py` is used only by hub-to-hub publish (`publish.py`), outside the auto
loop: leave it on `gh` (including `gh repo view` / `gh issue list`) unless a
cloud caller turns up. *(Designer's call.)*
`claude-settings-auto.json` already allows `Bash(kb pr *)`; keep `gh pr *`
allowed for local use, and add `Bash(gh api *)` only if a skill still calls
it directly (prefer not). `gh run view|list|watch|rerun` stay if they are
verified to work over REST on cloud; otherwise wrap them too.

The exact flags of each `gh pr` call in the skills (e.g. `--admin`,
`--delete-branch`, `--json` fields read) decide what each `kb pr` command
must support; the builder inventories them (grep shows ~50 call sites across
`templates/init/bodies/*` and `claude-*.md`).

### 6.6 Keeping the session alive

The loop must outlive any one tool call (2 h cap) and the session must not go
idle. Design:

- `/kb-auto run` on cloud starts the loop detached exactly as locally
  (`nohup kb auto run > .kb/auto/run.log 2>&1 &`), so the loop's lifetime is
  not tied to one tool call and a ticket can run its full 4 h.
- The session then arms a **watcher**: a new `kb auto wait --max 6600`
  command run with `run_in_background`. It blocks until the loop exits, its
  `stop_reason` changes, or `--max` seconds pass, then prints one short line
  (`still running: <task> attempt <n>`, `stopped: <reason>`, `done`).
- When the watcher exits, the session is re-invoked, reads that one line,
  reports only on a change, and re-arms the watcher. The session's context
  grows by a few lines per ~2 h, not by ticket output.
- `/kb-auto off` and a stop rule end the loop as today; the watcher's next
  line says so and the session stops re-arming.

**Checkout.** The runner and its tasks share the session's checkout, as
locally: tasks switch the tree to `auto/...` branches and the session never
needs to return to its `claude/...` branch while the loop runs (`.kb/auto/`
is already gitignored by `kb init`, so logs leave the tree clean). The
session pushes nothing of its own during the loop. *(Designer's call.)*

**Spike first.** These are unverified and the rest of the plan rests on
them, so the first build step is a throwaway spike on cloud that checks:

1. A session whose only activity is a background `kb auto wait`-style
   command re-armed every ≤2 h survives > 3 h with a dummy loop.
2. Pushing a branch other than the session's (`auto/spike`) succeeds.
3. REST create PR, `PUT .../merge` into a protected default branch with and
   without a required review, and REST branch delete all succeed.
4. `gh run list|view` works over REST on cloud.

Any check failing → stop and come back to the owner before building the
rest; the per-ticket-branch model or the long-session model would need
redesign.

### 6.7 `/kb-auto` skill (`templates/init/bodies/kb-auto.md`)

Add a cloud path to `run`, chosen when `CLAUDE_CODE_REMOTE` is set:

1. `kb auto status --json`; `running` is a pid → say so and stop.
2. Skip the "must be on the default branch" check.
3. `kb auto on` if needed, warnings verbatim.
4. Switch not on `origin/<default>` → §6.3 (`auto/switch` from
   `origin/<default>` with only the two files, REST PR, green checks, tell
   owner, REST squash-merge).
5. `mkdir -p .kb/auto`, start detached (§6.6), poll for the pid or a refusal
   as today.
6. Arm the watcher (§6.6) and keep re-arming it until `done` or `stopped`.

The hard rules stay: never `--dangerously-skip-permissions`, never edit the
settings files by hand, never force-push, warnings verbatim.

## 7. Constraints

- Python package `strata_kb`; follow the repo's CLAUDE.md, tests in `tests/`,
  TDD, release-version bump convention of previous PRs.
- No new runtime dependency.
- Secrets: the token only ever comes from `STRATA_KB_HTTP_TOKEN`; never log
  it (reuse `gitio.redact_url` style redaction for URLs).
- Every `templates/init` change must keep `kb init` / doctor checks that
  compare scaffolded files consistent.

## 8. Left to the builder

- Names and module placement of the hub-reader seam and the `kb pr` commands.
- JSON shape of `/api/registry` and `/api/plan/next` (mirror the Python
  models).
- Whether `kb auto wait` is a new subcommand or a flag on `status`.
- How to fake the cloud env and the REST calls in tests.
- Order of work, with the §6.6 spike first.
