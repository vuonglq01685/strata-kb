# /kb-auto — full-auto mode from your editor

Thin wrapper around the `kb auto` CLI for a `ba` or `dev` repo. The argument
is one of `on`, `off`, `status` (the default when empty) or `run`. Everything
here is a human action on the owner's machine: the loop itself runs each task
in its own `claude -p` process, so nothing of this session is carried into it.

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
pid of a live `kb auto run` in this repo, or `null`) and `default_branch`
(the branch the switch must be pushed to, or `null` outside git).

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

5. **`run`**, in this order; stop at the first step that fails.
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

Do not run `kb auto run` in the foreground of this session, and never from
inside an auto-mode task: the task process carries `STRATA_KB_AUTO_TASK=1`,
under which `kb auto on`, `off` and `run` refuse, and the runner holds
`.kb/auto/run.lock` anyway.
