# Full-auto: Q&A deadlock on stale refs, and five cloud-run fixes — design

Date: 2026-10-16
Status: approved by owner (2026-10-17)
Issue: #124
Builds on: `2026-10-16-full-auto-mode-design.md` (1.29.0), `2026-10-16-kb-auto-cloud-design.md` (1.30.0)

## 1. Intent

A BA repo running full-auto on Claude Code cloud (`myflix-ba`, 1.30.0) stopped
with no way to recover except a human. The Q&A thread (`ba-answer-questions`)
amended ticket `M-content-management-US1` to rev 2 for a Dev question, but the
ticket held a stale architecture ref (grounded at `b881436`, hub `myflix-code`
at `7a97b8f`, `§db.User` changed). `kb ticket check` still passed (only a
`[warn]`), so the skill was not allowed to run `/sa-ticket-ground`; the DoR box
"No stale refs" stayed unticked; the skill ended `failed dor-unticked`; it did
the same on the retry; `runner.py:285` saw `failed_twice` and stopped the
**whole loop**. The rev-2 draft was left uncommitted in `.kb/auto/worktrees/qa`,
which is reset on the next tick.

The same run surfaced five smaller problems. The owner wants all six fixed in
one change.

Success: one ticket the Q&A thread cannot finish never stops the BA loop, no
draft is lost, and a cloud session runs auto mode without a human touching
permissions, trust, or the session branch.

## 2. Goals

1. **G1 — deadlock (main).** Fix the root cause (A) and add a safety net (C):
   - **A.** The Q&A thread re-grounds a ticket itself when `kb_ticket_stale`
     reports an `architecture` finding.
   - **C.** Any `dor-unticked <ticket>` result parks that ticket's questions
     instead of counting toward the stop, and the draft is saved to a branch.
2. **G2 — `git -C`.** Tasks stop using `git -C`, so they stay inside the
   allowlist.
3. **G3 — model / effort.** `kb auto run --model <id> --effort <level>`.
4. **G4 — repo rules that need an unapprovable command.** The task skips that
   step and notes it in the PR, instead of stalling.
5. **G5 — untrusted workspace on cloud.** `kb auto run` marks its working
   directories trusted, on cloud only.
6. **G6 — session branch.** After each main-loop task the repo root is back on
   the branch it was on before the task.

## 3. Non-goals

- **Option B of the issue** (a new `--amend <id>` task kind in the main loop):
  dropped; A covers it with less code.
- Re-pinning stale **`kb-context`** refs from the Q&A thread. Only
  `architecture` findings are re-grounded there; a `kb-context` finding still
  ends `dor-unticked` and is parked by C (the main BA task owns re-pinning).
- Persisting parked tickets, retrying them on a timer, or showing them in
  `kb auto status`.
- Running the main task in its own worktree (rejected: a Dev repo's fresh
  worktree has no `node_modules` / `.venv` / `.env`).
- Adding `git -C *` allow entries or GitNexus tools to the allowlist.
- Deleting `auto/qa-parked/*` branches automatically.

## 4. Anti-goals

- Weakening the deny list. `git -C x switch main` does not match
  `Bash(git switch main)`; any change that makes `-C` usable defeats the denies.
- Writing trust into `~/.claude.json` on a local machine.
- Losing or corrupting the user's `~/.claude.json` (other keys, other projects).
- A second revision bump for one set of questions on one ticket.
- Any other Q&A failure (`ci-red`, `hub-refused`, `qa-needs-hub-server`, a
  crash) changing behaviour: those still stop the loop after two in a row.

## 5. Design (decided with the owner)

### 5.1 G1-A — re-ground from the Q&A thread

File: `src/strata_kb/templates/init/bodies/ba-answer-questions.md` (shared
body; the stubs include it).

- Step 3's amendment bullets and the hard rules currently say Trigger
  `question` is "the only amendment trigger this skill uses". Change: when
  `kb_ticket_stale` on the ticket reports an `architecture` finding, the one
  amendment carries triggers `question, architecture` (ba-ticket-author's amend
  mode already allows several triggers in one row). Run `/sa-ticket-ground`
  first, as a separate run, exactly as amend mode step 4 says for the
  `architecture` trigger; then the check, lint, review and DoR re-tick as now.
- The hard rule "run `/sa-ticket-ground` only when `kb ticket check` fails …"
  gains this second case.
- Still one amendment per ticket, one `> Revision:` bump, one change-log row.
- `question` stays exclusive to this skill; `architecture` is not new to amend
  mode, only to this skill.
- Applies in both manual and Auto mode (the manual BA hits the same wall).

### 5.2 G1-C — park instead of stop

File: `src/strata_kb/autorun/qathread.py` (plus `runner.py` only if needed).

- **One ticket per run.** Each tick, list open questions for this repo, drop
  those whose `ticket` is parked, take the ticket of the oldest remaining
  question (lowest `id`), and run `/ba-answer-questions <ticket>` (the skill
  already handles a named ticket: step 1 passes `ticket=`). No unparked open
  question → no run.
- **On `failed dor-unticked <ticket>`:**
  1. Add `<ticket>` to the parked set (in memory, lives as long as the
     `QaThread`; a new `kb auto run` starts empty).
  2. Do not count it as a failure: `failed_twice` and `stop_reason` are
     unaffected, and it does not reset the counter either.
  3. Save the draft before the next `_fresh_worktree`: in the qa worktree,
     create branch `auto/qa-parked/<ticket>` from the current HEAD, commit
     all changes (`gitio.commit_all`), push the branch. If nothing to commit,
     skip the push. A git error here is logged as a warning and does not stop
     the loop.
  4. Log one `WARNING` naming the ticket and the branch.
- The ticket parked is the one the runner launched the run with, not the
  token in `result.reason` (the model may write the id differently). A
  `dor-unticked` result therefore always parks the launched ticket.
- **Which results park.** In the skill, every ticket-level stop ends
  `failed dor-unticked <ticket-id>`: a DoR box left unticked, `kb ticket check`
  still failing after the re-ground (open decision, undecided `[NEW: D<k>]`,
  cited `SUPERSEDED` row), or `kb_ticket_lint` never passing. Only failures that
  are not about one ticket (`ci-red`, `hub-refused`, `qa-needs-hub-server`, a
  crash) use other reasons and keep the two-in-a-row stop.
- **Resume.** In the skill (5.1 file), step 3's "resume an unpublished N+1"
  bullet gains: run `git fetch origin auto/qa-parked/<ticket>`; when it exists,
  read the ticket's `> Revision:` on `FETCH_HEAD` and merge it
  (`git merge --no-edit FETCH_HEAD`) **only when** that revision is higher than
  both the default branch's and the hub's revision of the ticket; otherwise the
  draft is stale (already published, or overtaken by the main BA task) and is
  ignored. A merge conflict → `git merge --abort` and start the amendment fresh
  from the default branch. (`git fetch`, `git merge`, `git log`/`git diff` are in
  the allowlist; `git checkout <ref> -- <file>` and `git show` are not — read
  the revision with `git diff` or `git log -p` against `FETCH_HEAD`.)
- Every other failure kind keeps the current two-in-a-row stop.
- **Stop when only parked work is left (owner decided: stop, not idle).** A
  parked question stays `open` on the hub, and the Dev story it blocks never
  reaches `done`, so `all_done` can never be true. In `run_once`: when the main
  loop has no task to run (`_task_for` returns `None`), the Q&A thread has
  parked tickets, and every open question for this repo belongs to a parked
  ticket, stop through `_stop` with reason `parked: <ticket>[, <ticket>...]`
  and a hint naming the `auto/qa-parked/<ticket>` branches, then "fix the
  ticket, then run `kb auto run` to resume" (exit 2, like every stop). Open
  questions on unparked tickets, or a task still to run, keep the loop going.

### 5.3 G2 + G4 — two lines in the task prompt

File: `src/strata_kb/autorun/claude.py`, `prompt_for` (used by the main loop
and the Q&A thread, so it covers every skill):

- "Run git from the working directory; never use `git -C`." (G2)
- "When a rule of this repo (`CLAUDE.md`, `AGENTS.md`, …) needs a command you
  are not allowed to run, skip that step and name it under the PR's notes; do
  not stop or fail for it." (G4)

Exact wording is the builder's; the meaning is not.

### 5.4 G3 — `--model` / `--effort`

- `kb auto run` (`cli.py` `auto_run`) gains `--model` (default `opus` —
  **owner decided 2026-10-17**: every task the runner starts with `claude -p`
  runs on Opus; the alias tracks the newest Opus) and `--effort` (default
  empty). They are passed down to `claude.run_task` for both the main loop and
  the `QaThread`.
- Non-empty → `claude -p … --model <id>` and `--effort <level>`. Empty → no
  flag: `--model ""` hands the choice back to `ANTHROPIC_MODEL` / claude's
  default; an empty `--effort` leaves `CLAUDE_CODE_EFFORT_LEVEL` in charge.
- Not stored in config.

### 5.5 G5 — trust on cloud

- At `kb auto run` start, only when `strata_kb.cloud.is_cloud()`, mark trusted
  in `~/.claude.json` the resolved absolute paths of the repo root and, for a BA
  repo, the qa worktree (`.kb/auto/worktrees/qa`):
  `projects["<path>"]["hasTrustDialogAccepted"] = true`.
- Keep every other key. Create the file if missing. If it exists but is not
  valid JSON, do not touch it: log a warning and go on. Write atomically
  (temp file + replace).
- Local runs: nothing changes.

### 5.6 G6 — put the root back on its branch

File: `src/strata_kb/autorun/runner.py`, `run_once`, around `run_task`.

- Before the task: remember the root's current branch (`gitio.current_branch`).
- After the task (whatever its result, including an exception): if the root is
  on another branch now, check the remembered one out again (`gitio.checkout`).
- A checkout error (e.g. uncommitted changes left by the task) is a logged
  warning, not a stop.
- Applies to BA and Dev repos alike; the Q&A thread is untouched (it has its own
  worktree).

## 6. Constraints

- Shared skill text lives in `templates/init/bodies/`; edit the body, not the
  rendered copies (`tests/test_template_bodies.py`).
- Tests: extend `tests/test_autorun_qathread.py`, `test_autorun_claude.py`,
  `test_autorun_runner.py`, `test_cli_auto.py`, `test_autorun_cloud.py` (or the
  matching files). Run the repo's gate (`scripts/gate.sh`) before push.
- Versioning and `CHANGELOG.md` follow the repo's pattern. **Version:**
  — **owner decided**: patch release 1.30.2 (an issue fix), though it adds CLI flags.

## 7. Left to the builder

- Function names, where the trust helper lives, test layout.
- Whether `--effort` is a real `claude -p` flag in the installed CLI: check
  `claude --help`; if it is not, pass the effort as `CLAUDE_CODE_EFFORT_LEVEL`
  in the child env instead.
- `current_branch` on a detached HEAD: restore the commit instead, or skip.
- Which existing `gitio` push helper the parked-branch push uses.

## 8. Calls made by Claude (not discussed with the owner)

- Park is in memory only and cleared by restarting `kb auto run` — **owner
  confirmed**.
- When only parked questions are left, the loop stops with `parked: …` —
  **owner decided**. The exact condition (no main task + all open questions
  parked) is my call.
- The Q&A re-ground covers `architecture` only, not `kb-context`.
- The runner (not the skill) saves the parked draft, and the branch name is
  `auto/qa-parked/<ticket>`; parked branches are not cleaned up.
- One ticket per Q&A run (needed to skip parked tickets).
- Park keys on the ticket the runner launched, never on the parsed reason.
- Every ticket-level stop in the skill ends `dor-unticked <ticket>` (so it parks).
- A parked draft is merged on resume only when its revision is above the
  default branch's and the hub's; a conflict aborts the merge and starts fresh.
- `kb-auto.md` (the interactive `/kb-auto` skill) also uses `git -C`; it is not
  covered by `prompt_for` and is left as is (a human approves its prompts).
- (Version is the owner's call: 1.30.2.)
