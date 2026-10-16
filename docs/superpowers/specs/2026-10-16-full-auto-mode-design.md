# Full-auto mode for BA and Dev repos — design

Date: 2026-10-16
Status: draft, awaiting owner approval

## 1. Intent

strata-kb already covers the whole loop from mission to merged code: the BA
plans a mission and writes tickets, the hub publishes them, the Dev
implements them and asks the BA questions through hub Q&A, and handover
records each finished story on the hub. Every step, though, is started by a
person and every gate waits for one: ticking the last DoR box, deciding a
mission D-row, answering a question, approving a design or plan, merging a
PR, running `kb publish`.

The owner wants a **switch per repo** that, once on, lets the BA repo and the
Dev repo run on their own, on the owner's own machine in Claude Code CLI
(signed in with a Claude subscription, not an API key), until **every ticket
on the hub is done**. In this mode no step waits for a person: the agent
reviews its own work, picks the best option, decides, and records why.

## 2. Goals

- A switch in each `ba` and `dev` repo turns full-auto mode on or off.
- With the switch on, one command runs that repo's loop in a terminal until
  the product is done.
- Each task runs in a **fresh context**: when the BA or the Dev finishes a
  task, the context is cleared before the next task starts.
- **BA loop:** pick the next work from the mission, write or amend the
  ticket, fix it until it passes, merge, publish, amend the mission when
  needed, and repeat.
- **BA Q&A job:** always running in the background beside the BA loop. When
  a Dev question arrives, it answers it in its **own separate thread** (own
  process, own context), even while the BA loop is busy with another task.
- **Dev loop:** pick a suitable ready ticket, implement it, ask the BA when
  a business question blocks it, wait for the answer, continue, merge,
  publish, and repeat.
- **Dev Q&A job:** whenever the Dev has an open question, a job checks it
  until it is answered, then the Dev continues that ticket.
- Every human gate becomes an agent decision when the switch is on: the
  agent self-reviews and, if the result meets the standard, ticks the box,
  approves the gate or merges.
- A PR into `main` merges only on green CI. Red CI: the agent fixes and
  pushes again until it is green, then merges.
- Bugs and tickets with no mission get a status: **done** once the Dev's
  implementation history shows the ticket implemented and its PR merged.
- `kb init` scaffolds a `.claude/settings.json` permission allowlist so the
  headless runs do not stop on permission prompts.
- The loop stops by itself when every ticket on the hub is done.

## 3. Non-goals

- Running in Claude Code on the web, cloud sessions, scheduled tasks, or a
  hosted server. Local machine and Claude Code CLI only.
- Using the Anthropic API or an API key. The subscription login of the local
  `claude` CLI is the only credential for the model.
- Parallel work in one repo. The BA does one main task at a time; the Dev
  does one ticket at a time. The BA's Q&A thread is the only concurrency.
- Writing the first mission. A person writes the mission(s) (`/ba-mission-plan`)
  before turning the switch on; the loop works the backlog it is given.
- Auto mode for `hub` or `child` repos.
- Changing the behaviour of any skill while the switch is off.

## 4. Anti-goals (a failure even if it technically works)

- A context that carries one task into the next (a long-lived chat that
  "just keeps going").
- The Q&A answer and the BA's current task sharing a context or editing the
  same working tree at the same time.
- Merging on red CI, or skipping, disabling or weakening a test to get green.
- Running with all permissions bypassed (`--dangerously-skip-permissions` /
  `bypassPermissions`).
- An agent decision with no written reason: every gate the agent passes in
  auto mode leaves a short record of what it checked and why it passed.
- The loop dying silently when the subscription hits its usage limit.

## 5. Constraints

- Local machine, Claude Code CLI, subscription login. The runner calls the
  `claude` executable headless (`claude -p`), as `kb summarize` already does
  (`src/strata_kb/llm.py`), and inherits whatever login `claude` has.
- Python, inside this package, following the existing layout and the
  daemon pattern of `src/strata_kb/codesync/runner.py` (`run_once` as the
  unit, `run_loop` only repeats it, interval validated, the loop outlives
  any one failed run).
- Skills are shared bodies under `src/strata_kb/templates/init/bodies/`,
  rendered for Claude Code, Copilot and Cursor. Auto-mode behaviour goes in
  those bodies, behind a check of the switch, so the off path is byte-for-byte
  the current behaviour.
- Existing gates stay the definition of "passes": `kb ticket lint`
  (`DoR: PASS`), `kb ticket check`, every DoR box ticked, CI green on the PR.
- Repo conventions: TDD, 80% coverage, `CHANGELOG.md`, version bump.

## 6. What gets built

### 6.1 The switch

- `.kb/config.yaml` of a `ba` or `dev` repo gains an `auto:` block, off by
  default and commented in `templates/init/config-ba.yaml` and
  `config-dev.yaml`:

  ```yaml
  auto:
    enabled: false
    qa_interval: 300     # seconds between Q&A checks
    idle_interval: 600   # seconds to wait when there is no work yet
  ```

- `kb auto on` / `kb auto off` flip `enabled` and `kb auto status` prints the
  switch, the current task, and the last result. `kb auto on` prints one
  plain warning that the repo will merge and publish without human review.
  *(Builder's call whether `on`/`off` also commit the config change.)*
- **The switch is the single source of truth.** Skills read it (through
  `kb auto status --json` or the config loader) to decide whether a gate is
  human or agent. With the switch on, a skill run by hand also takes the
  auto path. *(Designer's call.)*
- `kb auto run` refuses to start when the switch is off, or the repo kind is
  not `ba`/`dev`. `kb auto off` makes a running loop stop at the next task
  boundary; it never kills a task midway.

### 6.2 The runner: `kb auto run`

A Python loop (new module, e.g. `src/strata_kb/autorun/`). It holds no model
context of its own; it chooses the next task, runs it, reads the result,
and repeats.

- **One task = one fresh `claude -p` process.** The process exits when the
  task ends, so the next task always starts with a clean context. This is
  how "clear context before the next task" is met.
- The prompt names the skill and its argument (e.g.
  `/dev-implement-ticket M-x-US3`), states that auto mode is on, and asks
  the agent to end with a machine-readable result line, e.g.
  `AUTO-RESULT: done | blocked-qa <question ids> | failed <reason>`.
  The runner parses the `--output-format json` envelope and this line.
- Runs from the repo root, so the project's `.claude/settings.json`
  (allowlist, hooks) and `CLAUDE.md` apply. Permission mode: the allowlist
  plus `acceptEdits` at most, never bypass.
- No fixed timeout that would cut a long implementation short; a generous
  per-task ceiling is the builder's call.
- **State** in `.kb/auto/` (git-ignored): `state.json` (current task,
  attempt count, what it waits on) and one log file per task (prompt,
  result, duration, exit). After a crash or a restart the runner reads the
  state and re-runs the same task; the skills are already re-entrant
  (`dev-implement-ticket` resumes from `docs/impl/<id>/`, the branch and
  open PRs).
- **Usage limit.** When `claude` reports the subscription usage limit, the
  runner logs it, sleeps until the reset time if the message gives one
  (otherwise backs off, e.g. 15 minutes, doubling up to an hour), and
  retries the same task. A usage-limit stop is never counted as a task
  failure.
- **Stop condition.** Before each task the runner checks the hub. When every
  mission story is `done` and every unparented ticket and bug is `done`
  (§6.6), it logs a summary and exits 0. *(The BA side must also have no
  open questions and no to-draft stories before it stops.)*

### 6.3 BA loop

Each turn, the runner takes the first of these that applies
(`kb mission next --json` supplies the statuses):

1. **A story is `blocked` by an OPEN mission D-row** → run
   `/ba-mission-plan --amend <mission>` in auto mode: the agent decides the
   D-row, records the reason, and flips it to `DECIDED`.
2. **A story is `draft`** (ticket exists, not yet passing) → run
   `/ba-ticket-author --amend <ticket>` until it passes.
3. **A story is `to-draft`** → run `/ba-ticket-author` for the `Next:` story.
4. **Nothing to do** → sleep `idle_interval` and check again (the BA waits
   for Dev progress and questions; it does not stop while Dev work is open).

Every task that changed the repo ends the same way: commit on a branch,
open a PR, wait for CI, fix and push until green, merge. Merging to `main`
already triggers `kb-publish-request.yml`, which publishes; the BA hub
intake must have `auto_merge: true` (the runner checks this at start and
refuses with a clear message if not). *(Whether one PR per ticket or per
task is the builder's call; one per ticket is the default.)*

"Amend the mission when needed" means: a D-row that blocks a story (step 1),
or a Q&A answer that changes mission scope (the Q&A thread runs
`/ba-mission-plan --amend` itself, §6.4).

### 6.4 BA Q&A job

- A background thread of `kb auto run` on the BA repo, always on while the
  loop runs. Every `qa_interval` it lists questions in state `open` for this
  BA repo's tickets.
- If there are any and no Q&A thread is running, it starts a **separate
  `claude -p "/ba-answer-questions"` process** in its **own git worktree**
  (e.g. `.kb/auto/worktrees/qa`, on its own branch). It runs alongside the
  main BA task, with its own context and its own files.
- In auto mode the Q&A thread answers from the mission, the ticket and the
  KB, amends the ticket when the answer changes it, re-ticks the DoR after
  self-review, and goes through the same PR → green CI → merge → publish
  path. A merge conflict with the main task is resolved by whichever side
  merges second (merge `main`, re-run lint/check, push).
- At most one Q&A thread at a time; new questions wait for the next check.

### 6.5 Dev loop and Dev Q&A job

- **One ticket at a time.** The runner picks from `kb mission next
  --from-hub --json` and the unparented list: a `ready` story or bug whose
  dependencies are done. Order: bugs first, then stories in mission order.
  *(Designer's call; builder may refine the dependency check.)*
- Runs `/dev-implement-ticket <id>` in auto mode: design, plan, execute,
  handover, with GATE 1–4 decided by the agent, then PR → green CI → merge,
  then `kb publish` so the `hist` row reaches the hub and the story shows
  `done`.
- **Waiting on Q&A.** If the task ends with `blocked-qa`, the Dev does not
  start another ticket. The Dev Q&A job checks those question ids every
  `qa_interval`; when all are `answered` (not just `waiting`: the amended
  ticket must be on the hub), the runner re-runs `/dev-implement-ticket <id>`
  in a fresh process, which picks up the answers as it already does.

### 6.6 Done for bugs and unparented tickets

`planstatus` today gives no status to tickets without a mission (they sit in
`PlanRepo.unparented`). Extend it: such a ticket or bug is **done** when its
id appears in a `hist.*` row of the Dev repo's `-svc` on the hub, which
`/dev-handover` writes only after implementation and which reaches the hub
only after the PR merged and the Dev published. Otherwise it is `ready` once
published. `kb mission next --from-hub --json` (and the MCP tool) expose
this list with statuses so the runner's stop check covers it.

### 6.7 Skill changes (auto path only)

Each human gate gets an auto branch. In every case the agent first
self-reviews, using an independent reviewer subagent (fresh context) for
anything the skill already reviews, and writes a short **Auto decision**
note: what it checked, the options, what it chose and why.

| Gate today | Skill body | Auto path |
|---|---|---|
| BA picks KB search refs ("never auto-pick") | `ba-ticket-author.md` | agent picks the best-matching refs, notes why |
| DoR box "Every AC is Given/When/Then…" (BA only) | `ba-ticket-author.md` | agent reviews every AC, ticks only if all pass, else rewrites first |
| Amend asks the BA for the trigger | `ba-ticket-author.md` | trigger comes from the runner (D-row, Q&A, failing check) |
| D-row `OPEN` → `DECIDED` | `ba-mission-plan.md` | agent decides with reasons in the change log |
| "Never answer a question yourself" | `ba-answer-questions.md` | agent answers from mission, ticket and KB; amends and re-ticks DoR |
| BA skills never commit/push/publish | BA bodies | runner-driven PR → green CI → merge |
| `/kb-publish` go/no-go | `kb-publish` skill | agent reviews the diff and proceeds |
| GATE 1 design approval | `dev-design.md` | independent review; flips `status: approved` |
| GATE 2 plan approval | `dev-plan.md` | independent review; flips `status: approved` |
| `dev-plan` asks for build/test commands | `dev-plan.md` | agent reads them from the repo (CI config, conventions) |
| "Let the Dev choose" on findings | `dev-execute.md`, `dev-plan.md` | agent chooses, notes why |
| Stale citations / `[warn]` / blocked deps: "Dev decides" | `dev-implement-ticket.md` | agent decides; a real blocker becomes a BA question |
| GATE 3/4: human opens and merges the PR | `dev-handover.md` | agent opens the PR, fixes CI until green, merges |
| Dev runs `kb publish` after merge | `dev-handover.md` | agent runs it |
| Open blocking question → STOP | `dev-implement-ticket.md` | STOP and report `blocked-qa <ids>` to the runner |

Off path: the text a skill shows today is unchanged.

### 6.8 Permission allowlist

`kb init` for `ba` and `dev` writes (or merges into) `.claude/settings.json`
beside the existing usage hooks:

- **allow:** `kb` commands, `git` (add, commit, checkout, branch, switch,
  worktree, merge, fetch, pull, push to non-`main` branches), `gh pr`
  (create, view, checks, merge), `gh run` (view, watch, rerun), file
  read/edit/write in the repo, the `strata-kb` MCP tools, and the repo's
  test and build commands (the Dev side derives these per language from the
  conventions templates).
- **deny:** force-push, pushing straight to `main`, `rm -rf` outside the
  repo, `gh repo delete`, editing `.claude/settings.json` itself.
- Merging an existing `.claude/settings.json` keeps the user's own entries.
  *(Exact rule list is the builder's call within this allow/deny shape.)*

## 7. Left to the builder

- Module layout, the result-line format, the exact `kb auto` sub-command
  flags, state file shape, log retention.
- How the runner reads Q&A states (an MCP call to the hub, or a thin
  `kb qa list --json` CLI added for it).
- Per-task time ceiling and the usage-limit message parsing.
- Docs: README section, `QUICKSTART-ba.md` / `QUICKSTART-dev.md`, and
  whether the PDF guides under `docs/` are regenerated in this change.
- Tests: the runner against a fake `claude` executable (task chaining,
  fresh process per task, usage-limit backoff, crash resume, stop
  condition, `kb auto off` at a task boundary), the BA Q&A thread running
  in its own worktree, `planstatus` done for unparented tickets, the
  allowlist merge in `kb init`, and the off path of every changed skill body
  rendering as today.
