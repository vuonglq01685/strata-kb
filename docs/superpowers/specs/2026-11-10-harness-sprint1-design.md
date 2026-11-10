# Harness sprint 1 — unattended-safe merge, run record, result contract (design)

Date: 2026-11-10 · Size: project (six independent parts) · Version: 1.35.0 → 1.36.0

Part of the roadmap "Strata as the outer harness for Claude Code": Claude Code
is the inner harness (tool loop, permissions, subagents); Strata is the outer
harness (picks work, supplies context, verifies, measures, learns). Scope is
Claude Code only. Sprint 1 of 6; later sprints: P1 verify, P2 retry + P3 rest,
P4 isolation/budget + P5 agents-as-files, P6 eval, P7 observability.

## Intent

The owner wants `kb auto run` to run unattended for days. That needs the
harness, not the agent's prompt, to hold the safety line, and it needs data on
every run so later sprints (verify, retry, eval) have something to stand on.
Sprint 1 is the cheap foundation:

1. Merges stay safe with no human watching (policy **C**, chosen by the owner).
2. Every task run leaves one durable record.
3. A task can no longer end without its `AUTO-RESULT:` line.
4. Skills stop failing on commands the auto allowlist forgot.
5. Ticket grounding is checked in CI, not only by the agent.
6. Running ba/dev repos can take these changes (`kb upgrade`, option **A**).

## Decisions made by the owner

- **Merge policy C.** The agent may merge its own PR, but only when every
  required check is green. Enforcement lives on GitHub: the runner's token has
  no admin right, the default branch's ruleset allows no bypass, and
  `CODEOWNERS` forces a human review on sensitive paths. Rejected: A (a human
  approves every PR — the loop would run at human speed) and B (a separate
  reviewer bot — a second token and App to manage).
- **Upgrade path A.** A human runs `kb upgrade`; it opens a PR and never
  merges. Rejected: B (runner opens upgrade PRs itself) — the upgrade PR
  touches `CODEOWNERS`-protected paths, so a human reviews it either way.

## Facts found in the code (drive the design)

- `kb pr merge --admin` is already a no-op (`cli.py:3878`, "REST merges with
  your rights"). Removing the flag from skills changes nothing by itself; the
  real control is the token's rights plus the ruleset.
- The auto allowlist has `Bash(gh pr *)`, so `gh pr merge --admin` is reachable.
- `_extract_reply` (`llm.py:100`) keeps only `result`; `run_task`
  (`autorun/claude.py:126`) drops the rest of the envelope.
- Re-running `kb init` already refreshes changed scaffold templates and
  union-merges `.claude/settings.json` (`initcmd.py:682 merge_settings`), so a
  dev's own permissions and hooks survive.
- `kb ticket check` needs the hub (it reads `-code` facts from it); the BA
  repo's `kb-ticket-lint.yml` already has `STRATA_KB_HUB` / `KB_HUB_TOKEN`.
  `kb-pr-lint.yml` (dev repos) deliberately has no hub and no token.
- `ghrest.api(root, method, path)` wraps `gh api` and is reusable for the
  GitHub checks below.

## Goals

### G1. Merge policy C — refuse to run when GitHub would let the agent bypass

- `runner.preflight` adds refusals (same list-of-reasons style as today):
  - token is admin on the repo: `GET /repos/{o}/{r}` → `permissions.admin` is
    true. Reason names the fix: use a token without admin (fine-grained PAT /
    App with `contents:write`, `pull_requests:write`, `checks:read`).
  - the default branch's effective rules
    (`GET /repos/{o}/{r}/rules/branches/{default}`) lack a
    `required_status_checks` rule containing the kind's gate job(s):
    dev → `pr-lint`; ba → `lint` (job of `kb-ticket-lint`). Job names are the
    frozen ones the workflow files already pin.
  - a GitHub API failure is a refusal too ("could not read …: <why>"), never
    a silent pass: unattended means fail closed.
- Bypass detection: the rules endpoint does not say who may bypass. Builder
  checks `GET /repos/{o}/{r}/rulesets` + each ruleset's `bypass_actors`
  (readable without admin? — verify; if not readable, fall back to the admin
  check alone and say so in the doctor output).
- `kb doctor` reports the same findings as issues, with the fix text.
- `kb init` (ba and dev) scaffolds `.github/CODEOWNERS` as **created once,
  never refreshed** (like the local-overrides files): lines for
  `.github/workflows/**`, `.claude/settings.json`, `.claude/agents/**`, and the
  repo's rubric/exemption files (`pr-review-rubric.md`, `tdd-exemptions.md`
  wherever init puts them). Owner placeholder `@OWNER` plus a comment telling
  the human to set it; `doctor` flags a placeholder still present.
- Docs: a ruleset JSON sample (required PR, required checks, code-owner review
  on, required approvals 0, no bypass actors) in the BA and Dev guides (en +
  vi), applied once by a human admin. The runner never applies it — that would
  need the admin right C forbids.
- Skills: drop the "`--admin` when refused for want of a review" sentence from
  `bodies/dev-handover.md`, `ba-ticket-author.md`, `dev-test-workflow.md`,
  `kb-auto.md` (and the matching `claude-command-*.md` copies). A merge refused
  for want of a review ends `AUTO-RESULT: failed merge-needs-review <pr-url>`.
- Allowlist: add deny `Bash(gh pr merge*--admin*)` and
  `Bash(kb pr merge*--admin*)`.

### G2. Run record (P0)

- `run_task` keeps from the envelope: `session_id`, `total_cost_usd`,
  `num_turns`, `duration_ms`, `is_error`, `subtype`. Missing keys → `None`
  (older CLI, plain-text stdout). `TaskResult` gains an optional `meta` field
  (frozen dataclass, default empty) — callers that ignore it keep working.
- One JSON line per `run_task` call — main loop **and** `QaThread` runs —
  appended to `.kb/auto/runs.jsonl` (written inside `run_task` from a context
  the caller passes; Q&A runs record `skill: ba-answer-questions` and their
  attempt). Each line is a single `O_APPEND` write, safe across threads:
  `schema: 1`, `run_id` (uuid4), `started_at`, `ended_at` (UTC ISO),
  `skill`, `arg`, `attempt`, `outcome` (TaskResult.kind), `reason`, `ids`,
  `session_id`, `cost_usd`, `turns`, `duration_ms`, `head_before`,
  `head_after` (`git rev-parse HEAD` in `root`), `log` (log file path).
  Timeout / OSError runs are recorded too, with the envelope fields `None`.
- Append-only, one `write` per line, UTF-8, `\n`. A write failure logs a
  warning and never fails the task (the record is evidence, not control).
- `.kb/auto/` is already git-ignored state; confirm `runs.jsonl` is covered.
- The usage ledger already stores `session`; the join key is `session_id`.
  No change to the ledger in this sprint.

### G3. `AUTO-RESULT` contract enforced by a Stop hook (part of P3)

- New hidden command `kb guard stop --hook-stdin`. Reads the Stop hook payload.
  When `STRATA_KB_AUTO_TASK=1` and the last assistant message in the
  transcript does not end with a valid `AUTO-RESULT:` line (reuse
  `claude.parse_result`; anything but "no result line"/"bad result line"
  passes), print `{"decision": "block", "reason": "<the four allowed forms>"}`.
- When `stop_hook_active` is true in the payload, never block (one nudge only;
  no loop). Not an auto task → exit 0, no output.
- Any internal error → exit 0, no output, one line to the auto log (a broken
  guard must not wedge a session; `parse_result` still catches it after).
- `claude-settings-auto.json` (ba + dev) adds this as its **own** Stop hook
  group (never inside the usage-ingest group: `merge_settings` skips a group
  whose command already exists, so upgraded repos would never get it). Order
  does not matter; Claude Code runs matching hooks in parallel.
- Nested `claude -p` processes are not tasks: `llm.Runner` (used by
  `kb summarize` / `kb ingest`) drops `STRATA_KB_AUTO_TASK` from the child
  env, so the guard never blocks a summary.

### G4. Allowlist gaps (G11)

- Builder greps every `bodies/*.md` and `claude-command-*.md` for `kb get`,
  `mkdir`, `kb build`, `kb summarize`, `kb approve` and adds the narrowest
  `allow` pattern for each form actually used (e.g. `Bash(mkdir -p *)`, not
  `Bash(mkdir*)`). A form a skill uses only outside auto mode is not added.
- A test pins: every `kb <sub>` and shell command named in a body's
  "Auto mode" path is matched by an allow pattern (or a documented exception).

### G5. `kb ticket check` in CI

- `kb-ticket-lint.yml` (BA): for each changed ticket that is ready — every
  `## Definition of Ready` box ticked, the same rule `missionnext` uses (reuse
  it; tickets carry no `status:` field) — also run `kb ticket check "$f" --hub "$STRATA_KB_HUB"
  --json`; FAIL fails the job and adds a column to the step summary table.
  Tickets not ready are skipped (grounding is not required before ready).
  Parent tickets follow `missionnext`'s own handling (builder's call).
- Same job, same job name — no new required check to provision.
- `kb-pr-lint.yml` (dev) is unchanged: no hub, no token, by design.

### G6. `kb upgrade`

- `kb upgrade [--no-pr]` in a ba/dev repo with a clean tree:
  1. refuse on a dirty tree, an unknown kind, or `STRATA_KB_AUTO_TASK=1`;
  2. `git switch -c kb/upgrade-<version>` from the default branch;
  3. run the same code path as a re-run `kb init` (no `--force`);
  4. nothing changed → delete the branch, print "already current", exit 0;
  5. commit `chore: kb upgrade to <version>`, push, `kb pr open` with the
     `InitReport` (created/updated/skipped) as the body. Never merges.
  `--no-pr` stops after the commit.
- Not in the auto allowlist (`kb init*` is already denied; add
  `Bash(kb upgrade*)` to deny as well).

## Non-goals

- Verifying "done" in the runner (P1, sprint 2).
- Retry policy or `--resume` (P2).
- PreToolUse / PostToolUse / SessionStart hooks (rest of P3).
- Worktree per task, turn/cost budgets (P4).
- Changing the usage ledger schema.
- Applying rulesets or editing GitHub settings from Strata.

## Anti-goals (a failure even if it works)

- A preflight that passes when GitHub cannot be read.
- A Stop hook that can loop a session or block a non-auto session.
- `kb upgrade` that overwrites a repo's own permissions, hooks or
  local-override files.
- A new required CI job name (would wedge already-provisioned repos).

## Constraints

- No new Python dependency.
- Backward compatible: repos not yet upgraded keep running until their next
  `kb auto run` preflight, which then refuses with the fix text (this is the
  intended forcing function). `state.json` schema unchanged.
- Template text is pinned by `tests/test_templates.py` and
  `tests/test_template_bodies.py`; update the canon with the change.
- Docs en + vi.

## Approaches considered

| Part | Picked | Rejected and why |
|---|---|---|
| Merge safety | Preflight/doctor check + CODEOWNERS scaffold + ruleset docs | Runner applies the ruleset: needs admin, contradicts C. Prompt-only rule: not enforcement |
| Upgrade | `kb upgrade` wrapping the init path, opens a PR | Docs-only "re-run `kb init`": steps get missed across many repos |
| Run record | Append-only `runs.jsonl` | Fields in `state.json`: it is a current-state snapshot, history is lost |
| Result line | Stop hook `block` with `stop_hook_active` guard | Runner `--resume` asking for the line: an extra call; belongs to P2 |

## Left to the builder

- Exact shape of `TaskResult.meta` and where the runner writes the record
  (around `_settle`, once per `run_task` call).
- Whether ruleset `bypass_actors` is readable with a non-admin token (G1).
- Exact allow patterns for G4.
- Where the CODEOWNERS owner placeholder check lives in `doctor`.
- `tests/fake_claude.py`: emit `session_id`, `total_cost_usd`, `num_turns`,
  `duration_ms` in its envelope.

## Tests

- `parse`/`run_task`: envelope fields kept; missing fields → None; timeout run
  recorded.
- `runs.jsonl`: one line per run, schema 1, write failure does not fail task.
- preflight: admin token → refusal; missing required check → refusal; API
  error → refusal; all good → no new reason. `ghrest.api` faked.
- `kb guard stop`: blocks on missing/bad line in auto task; passes with a
  valid line; never blocks when `stop_hook_active`; silent outside auto.
- `kb upgrade`: dirty tree refused; no-change exits clean and leaves no branch;
  change → branch + commit (+ PR faked); user permissions survive.
- templates: `--admin` sentence gone from all bodies and command copies; new
  deny rules present; Stop hook order; CODEOWNERS created once.
- `kb-ticket-lint.yml`: `ticket check` step runs only for `status: ready`.
