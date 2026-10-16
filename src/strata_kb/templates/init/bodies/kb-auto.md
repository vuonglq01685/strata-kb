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

## Workflow

1. Read `kind:` from `.kb/config.yaml`. Anything but `ba` or `dev` → say auto
   mode is for BA and Dev repos only, then stop.

2. **`status`** (also when there is no argument). Run `kb auto status --json`
   and report it readably: the switch, the current task, attempts, the question
   ids it waits on, and the stop reason. Then read `.kb/auto/run.lock`: when it
   holds a pid that is alive, say the runner is running (pid N) and that the
   log is `.kb/auto/run.log`; otherwise say it is not running.

3. **`on`**. Run `kb auto on`, show its warnings verbatim, then say that `run`
   will commit and push `.kb/config.yaml` and `.claude/settings.json` to the
   default branch before it starts the loop.

4. **`off`**. Run `kb auto off`. Say that a running loop stops at the next task
   boundary (it never kills a task midway) and that the log shows the stop.

5. **`run`**, in this order:
   1. `kb auto status --json`; when `enabled` is false, run `kb auto on` and
      show its warnings verbatim.
   2. `git status --porcelain -- .kb/config.yaml .claude/settings.json`. When
      either file is untracked or modified: check the current branch
      (`git branch --show-current`) against the default branch
      (`git symbolic-ref --short refs/remotes/origin/HEAD`, stripped of
      `origin/`). On a different branch, stop and tell the owner to switch to
      the default branch first. On the default branch:
      `git add .kb/config.yaml .claude/settings.json`,
      `git commit -m "chore: enable full-auto mode"`, `git push origin HEAD`.
   3. Start the loop detached, so this session holds none of its context.
      POSIX: `nohup kb auto run > .kb/auto/run.log 2>&1 &` and note the pid.
      PowerShell: `Start-Process kb -ArgumentList "auto","run"
      -RedirectStandardOutput .kb/auto/run.log -NoNewWindow`.
   4. Wait about three seconds, then read `.kb/auto/run.log`. When the runner
      refused (preflight reasons, or "already running (pid N)"), show those
      lines verbatim and stop. Otherwise report the pid, the log path and
      `tail -f .kb/auto/run.log` to follow it, and `/kb-auto off` to stop it.

Do not run `kb auto run` in the foreground of this session, and do not run it
from inside an auto-mode task: the runner holds `.kb/auto/run.lock`, so a
nested run refuses anyway.
