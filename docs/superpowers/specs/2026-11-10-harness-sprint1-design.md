# Harness sprint 1 — unattended-safe merge, run record, result contract (design)

Date: 2026-11-10 · Size: project (seven parts) · Version: 1.35.0 → 1.36.0

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
7. A PR that needs a human review parks the task instead of stopping the loop.

## Decisions made by the owner

- **Merge policy C.** The agent may merge its own PR, but only when every
  required check is green. Enforcement lives on GitHub: protection on the
  default branch that the runner's identity cannot bypass (see the identity
  rule in G1), and `CODEOWNERS` forcing a human review on sensitive paths. Rejected: A (a human
  approves every PR — the loop would run at human speed) and B (a separate
  reviewer bot — a second token and App to manage).
- **Identity: accept both** a non-admin bot and an admin token behind
  no-bypass protection (G1). Rejected: non-admin only (cloud auto mode
  impossible), admin + ruleset only (no hardening path).
- **Review wait: park** (`blocked-review`, G7). Rejected: stop the loop (every
  dev repo would halt on its first task).
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

**Identity rule (owner's call: accept both).** `GET /repos/{o}/{r}` →
`permissions.admin` reflects the *user's* role, not the token's grant, so a
PAT made by an admin owner still reads `admin: true`, and in Claude Code cloud
the session acts as the owner. Preflight therefore passes in either case:

- **non-admin identity** (machine user or GitHub App, write but not admin) and
  the default branch requires the kind's checks; or
- **admin identity** and the default branch is protected in a way an admin
  cannot bypass: a ruleset with an empty `bypass_actors`, or classic
  protection with `enforce_admins: true`; plus required checks and code-owner
  review. An admin token can read all of this, so it is checked, not assumed.
  Residual risk, stated in the guides: an admin token can still edit the
  ruleset; only the allowlist (no `gh api`) stops the agent from doing so.
  A non-admin bot identity is the documented hardening.

What preflight checks (`ghrest.api`, refusal reasons in today's style):

- Required checks on the default branch, read from the ruleset
  (`GET /repos/{o}/{r}/rules/branches/{b}`) or classic protection
  (`GET /repos/{o}/{r}/branches/{b}` → `protection.required_status_checks`;
  admin: `/branches/{b}/protection`). Either source counts.
  - dev → `pr-lint`, plus every job of `.github/workflows/kb-test.yml` once
    that file exists on the default branch (before it exists, the first task
    is `dev-test-workflow`, so `pr-lint` alone is enough). *Builder's call
    recorded: "tests green" is part of C.*
  - ba → `lint` (job of `kb-ticket-lint`).
- Code-owner review required (`pull_request.require_code_owner_review` in the
  ruleset, or `required_pull_request_reviews.require_code_owner_reviews`).
  Required approvals may be 0.
- `.github/CODEOWNERS` exists on the default branch and has no `@OWNER`
  placeholder left (GitHub ignores those lines, so the review would silently
  not apply).
- Admin identity only: no bypass (above).
- Any GitHub API failure, or a missing `permissions` block, is a refusal
  ("could not read …: <why>"), never a silent pass: unattended means fail
  closed.

Everything else in G1:

- `kb doctor` reports the same findings as issues, with the fix text.
- `kb init` (ba and dev) scaffolds `.github/CODEOWNERS` as **created once,
  never refreshed** (like the local-overrides files), covering
  `.github/CODEOWNERS`, `.github/workflows/**`, `.claude/settings.json`,
  `.claude/agents/**`, `.claude/skills/**`, `.claude/commands/**`, and the
  repo's rubric/exemption files (`pr-review-rubric.md`, `tdd-exemptions.md`
  wherever init puts them). Owner placeholder `@OWNER` plus a comment telling
  the human to set it.
- Docs (BA + Dev guides, en + vi): replace the classic-protection
  "include administrators" advice with the C setup: a ruleset JSON sample
  (required PR, required checks, code-owner review, approvals 0, no bypass
  actors), the identity rule above and its residual risk. Applied once by a
  human admin; the runner never applies it.
- Skills: drop the "`--admin` when refused for want of a review" sentence from
  `bodies/dev-handover.md`, `ba-ticket-author.md`, `dev-test-workflow.md` and
  the inline copies `claude-command-dev-handover.md`,
  `claude-skill-ba-ticket-author.md`. A merge refused for want of a review
  ends `AUTO-RESULT: blocked-review <pr-url>` (G7).
- `bodies/kb-auto.md`: step 9 drops `--admin` (no-op today), step 2 drops
  "admin-merged"; a merge refused for want of a review stops the switch with a
  message telling the owner to review and merge `auto/switch`, then re-run.
- `autorun/switch.py` `ADMIN_WARNING`: reword — auto mode merges its own PRs
  when every required check is green; PRs touching code-owned paths wait for a
  human.
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
  passes), print `{"decision": "block", "reason": "<the allowed result forms, incl. blocked-review>"}`.
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

### G7. `blocked-review` — a PR that waits for a human (owner's call: park)

PRs touching code-owned paths cannot merge unattended. The first Dev task,
`dev-test-workflow`, always is one (it writes `.github/workflows/kb-test.yml`).

- New result form `AUTO-RESULT: blocked-review <pr-url>` (`parse_result`,
  `prompt_for`, the Stop guard's list, the "Auto mode" sections of skills
  that merge).
- `_settle`: no attempt counted; the task and PR url are saved in a new
  `state.json` field `waiting_review` (additive, default empty — an old state
  file loads unchanged; `tests-gate/regression` covers it).
- Each loop turn, before picking: for each parked PR, `kb pr view` →
  merged → the task counts as done (same path as `done`); closed unmerged →
  drop it and log a warning (picker may re-pick); still open → keep waiting.
- Picker skips a task whose PR is parked. When nothing else is pickable, the
  loop waits like `blocked-qa` (`wait_for_change` / sleep), never exits.
- `kb auto status` lists parked PRs.

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
  intended forcing function). `state.json` gains only the additive
  `waiting_review` field (G7).
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
- Live-check against GitHub before relying on it: `permissions` shape for
  App installation tokens; code-owner review enforced with approvals 0.
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
- `kb-ticket-lint.yml`: `ticket check` step runs only for ready tickets.
- preflight: admin + ruleset with bypass actor → refusal; admin + empty
  bypass → pass; classic protection accepted; CODEOWNERS missing or
  placeholder → refusal; dev with `kb-test.yml` but its jobs not required →
  refusal.
- `blocked-review`: parse; parked PR merged → done; closed → dropped; open →
  waiting, loop does not exit; old `state.json` loads.
- `llm.Runner` child env has no `STRATA_KB_AUTO_TASK`.
