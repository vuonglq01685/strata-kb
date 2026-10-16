# /kb-auto — full-auto mode from your editor

Thin wrapper around the `kb auto` CLI for a `ba` or `dev` repo. The argument
is one of `on`, `off`, `status` (the default when empty) or `run`. Everything
here is a human action on the owner's machine (or, when `cloud` is true, in
this Claude Code cloud session): the loop itself runs each task in its own
`claude -p` process, so nothing of this session is carried into it.

Hard rules:
- Never pass `--dangerously-skip-permissions`, and never edit
  `.claude/settings.json` or `.kb/config.yaml` by hand — only the CLI does.
- Show the warnings `kb auto on` prints **verbatim**: they are the owner's
  security decision (admin merge, no human review, one Dev repo per hub).
- Never force-push. Never check out or push the default branch from another
  branch on the owner's behalf.
- Non-zero exit from any `kb auto` command → show its output verbatim and stop.

`kb auto status --json` is the one source for everything below. Its fields:
`enabled`, `task`, `attempts`, `waiting_on`, `stop_reason`, `running` (the
pid of a live `kb auto run` in this repo, or `null`), `default_branch`
(the branch the switch must be pushed to, or `null` outside git) and `cloud`
(true on Claude Code cloud: the switch then goes out as a PR, see `run`).

## Workflow

1. Read `kind:` from `.kb/config.yaml`. Anything but `ba` or `dev` → say auto
   mode is for BA and Dev repos only, then stop.

2. **`status`** (also when there is no argument). Run `kb auto status --json`
   and report it readably: the switch, the current task, attempts, the question
   ids it waits on, the stop reason, and whether the runner is running
   (`running` is a pid → "running (pid N), log in `.kb/auto/run.log`";
   `null` → "not running").

3. **`on`**. Run `kb auto on`, show its warnings verbatim, then say that `run`
   will commit and push `.kb/config.yaml` and `.claude/settings.json` to the
   default branch before it starts the loop.

4. **`off`**. Run `kb auto off`. Say that a running loop stops at the next task
   boundary (it never kills a task midway) and that the log shows the stop.

5. **`run`**, in this order; stop at the first step that fails. When `cloud`
   is true, follow **`run` on cloud** below instead of these steps.
   1. `kb auto status --json`. When `running` is a pid, say the loop is
      already running and stop. Take `default_branch` from it; when it is
      `null`, say the repo has no git default branch and stop.
   2. `git branch --show-current` must equal `default_branch`. On any other
      branch, stop and tell the owner to switch to the default branch first
      (the switch is only ever committed and pushed from there).
   3. When `enabled` is false, run `kb auto on` and show its warnings
      verbatim.
   4. Commit the switch when it is not committed: when
      `git status --porcelain -- .kb/config.yaml .claude/settings.json`
      prints anything, run
      `git add .kb/config.yaml .claude/settings.json` and
      `git commit -m "chore: enable full-auto mode" -- .kb/config.yaml .claude/settings.json`
      (the pathspec keeps anything else the owner had staged out of it).
   5. Push when the default branch is ahead of origin for those files: when
      `git log origin/<default_branch>..HEAD -- .kb/config.yaml .claude/settings.json`
      prints anything, run `git push origin HEAD`. Tell the owner first that
      this pushes every unpushed commit on the branch, not only the switch.
   6. Make the log directory: `mkdir -p .kb/auto` (PowerShell:
      `New-Item -ItemType Directory -Force .kb/auto`).
   7. Start the loop detached, so this session holds none of its context.
      POSIX: `nohup kb auto run > .kb/auto/run.log 2>&1 &`.
      PowerShell: `Start-Process kb -ArgumentList "auto","run"
      -RedirectStandardOutput .kb/auto/run.log
      -RedirectStandardError .kb/auto/run.err.log -WindowStyle Hidden`
      (the two files must differ; the loop logs to stderr).
   8. Poll `kb auto status --json` once a second for up to 60 seconds until
      `running` is a pid (preflight passed, the loop holds its lock) or
      `.kb/auto/run.log` holds a refusal (preflight runs a `git fetch` and
      reads the hub registry first, so it can take a while). On a refusal,
      show those lines verbatim and stop. Otherwise report the pid, the log
      path, `tail -f .kb/auto/run.log` to follow it, and `/kb-auto off` to
      stop it.

**`run` on cloud** (`cloud` is true). The session branch is not the default
branch and cannot push to it, so the switch reaches the default branch through
an `auto/switch` pull request that this session admin-merges (the owner
approved that by running `/kb-auto run`). Stop at the first step that fails.
1. `kb auto status --json`. When `running` is a pid, say the loop is already
   running and stop. The "must be on the default branch" check does not apply.
   Take `default_branch` from it; when it is `null`, say the repo has no git
   default branch and stop.
2. When `enabled` is false, run `kb auto on` and show its warnings verbatim.
3. Commit the switch on the session branch when it is not committed: when
   `git status --porcelain -- .kb/config.yaml .claude/settings.json` prints
   anything, run `git add .kb/config.yaml .claude/settings.json` and
   `git commit -m "chore: enable full-auto mode" -- .kb/config.yaml .claude/settings.json`.
4. Get the switch onto the default branch. Run
   `git fetch origin <default_branch>`, then read
   `git show origin/<default_branch>:.kb/config.yaml`. When its `auto:` block
   already has `enabled: true`, skip to step 5. Otherwise, **cleanup** means:
   `git worktree remove --force .kb/auto/worktrees/switch` when that path
   exists, then `git branch -D auto/switch` when that local branch exists.
   Run cleanup on every stop inside this step and after the merge (4.10), so
   a re-run starts clean. Never force-push to get past a conflict.
   1. Run cleanup now, in case an earlier run failed. Then run
      `kb pr find --head auto/switch --state open --json`. When it lists a PR,
      an earlier switch PR is still open: tell the owner to close that PR and
      delete the remote `auto/switch` branch on GitHub, then run `/kb-auto
      run` again, and stop.
   2. Tell the owner the switch PR will be admin-merged into
      `<default_branch>`, with no review.
   3. `git worktree add .kb/auto/worktrees/switch -b auto/switch FETCH_HEAD`.
   4. The PR flips only `auto.enabled`; it never copies files over the
      default branch, which could revert changes made there since the session
      branch forked. In the worktree run
      `kb auto on --kb-dir .kb/auto/worktrees/switch/.kb` and show its
      warnings verbatim. Then compare the permissions: when
      `git diff --no-index --quiet .claude/settings.json .kb/auto/worktrees/switch/.claude/settings.json`
      exits non-zero (they differ, or the worktree has none), do not copy
      the file. Run cleanup, tell the owner to commit the auto-mode settings
      (the `kb init --kind ba|dev` output) to `<default_branch>` first, and
      stop. Otherwise commit only what changed:
      `git -C .kb/auto/worktrees/switch add .kb/config.yaml` and
      `git -C .kb/auto/worktrees/switch commit -m "chore: enable full-auto mode"`.
   5. `git -C .kb/auto/worktrees/switch push -u origin HEAD`.
   6. Write the PR body to `.kb/auto/switch-pr.md` (run `mkdir -p .kb/auto`
      first). It must pass `kb pr lint`, so it has exactly these three
      sections, each filled in:
      `## Ticket` — "None: owner-approved chore, enable full-auto mode."
      `## Changes` — what changed: `auto.enabled: true` in `.kb/config.yaml`
      (nothing else).
      `## Testing` — a fenced block holding the real output of
      `git -C .kb/auto/worktrees/switch show --stat HEAD`, then a line
      `Blocking: No`.
      Run `kb pr lint .kb/auto/switch-pr.md`; on a failure fix the file and
      lint again before opening.
   7. `kb pr open --head auto/switch --base <default_branch> --title "chore: enable full-auto mode" --body-file .kb/auto/switch-pr.md`.
      Always pass `--base`: without it the PR could target the session branch.
   8. `kb pr checks auto/switch --watch`. Red (exit 1): show the failing
      checks, run cleanup, and stop; never merge on red or pending checks.
      The PR stays open: tell the owner to close it and delete the remote
      `auto/switch` branch on GitHub before a re-run.
   9. `kb pr merge auto/switch --squash --admin --delete-branch`. After an
      error, run `kb pr view auto/switch --json` before you stop: a merged PR
      is a success. On a real failure run cleanup and stop; the PR stays
      open, so tell the owner to close it and delete the remote `auto/switch`
      branch on GitHub before a re-run.
   10. Run cleanup.
5. `mkdir -p .kb/auto`, then start the loop detached exactly as in `run`
   steps 7 and 8 above (`nohup kb auto run > .kb/auto/run.log 2>&1 &`, then
   poll for the pid or a refusal in `.kb/auto/run.log`). On a refusal, show
   those lines verbatim and stop.
6. Arm the watcher, because a cloud session ends when it has nothing to do:
   run `kb auto wait --max 6600` with the Bash tool's `run_in_background` and
   `timeout: 7200000` (the default background timeout is 30 minutes, which
   would kill the command before `--max` elapses). Each time it returns, read
   its one line. A return with no `kb auto wait` line (the command was killed
   or printed nothing) counts as `still running`. Report the line to the
   owner only when it does not start with `still running`. Then re-arm it
   (the same background command) unless the line starts with `stopped:` or
   `not running`; those end the watch, and you report them and stop.

Do not run `kb auto run` in the foreground of this session, and never from
inside an auto-mode task: the task process carries `STRATA_KB_AUTO_TASK=1`,
under which `kb auto on`, `off`, `run` and `wait` refuse, and the runner holds
`.kb/auto/run.lock` anyway.
