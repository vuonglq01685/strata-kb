---
mode: agent
description: Close out a ticket — re-check citation freshness, run the full suite and paste the real output, record service history, and assemble the PR description
---

# /dev-handover — close out the ticket: verify, record, assemble the PR

You are phase 4 of the ticket-implementation pipeline: with every
task ticked in the approved plan, you close out the ticket. You
verify it again, record what happened, and assemble a PR
description complete enough for the Dev to review, open, and
merge.

*Counterpart in the superpowers plugin:
`superpowers:verification-before-completion`.*

## Freshness re-check (run this FIRST, every time)

Cheap check first: `kb resolve --status-only --cache
docs/impl/<ticket-id>-context.md <ticket-file>` (no CLI → `kb_resolve`;
check the cache `version:` yourself). Exit 0 → use the cache, do NOT
re-pull pinned content. A `cache-*` line or a non-ok verdict → `kb resolve
--write-cache <same path> <ticket-file>` (no CLI → `kb_resolve`, write the
layout by hand), then fill `## Placeholder map` below the marker; never
edit above it.

- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a
  citation that no longer resolves.
- **stale** → show BOTH versions, humans decide: the resolve gives the
  pinned content and the reason, `kb get <doc-id> <section> [--level l3]`
  the current hub version. Do NOT use `kb diff` — it compares the local
  `.kb/` worktree to a local git rev, not this repo to the hub.
- **ok** → continue.

## Steps

- **A `path: spike` design has no plan and usually no code** — skip the
  plan/execute-specific steps below; put the recommendation from the
  design under `## Findings` in the PR body, or as a ticket comment when
  there is no PR, and mark the ticket's plan state `n/a (spike)`.
- **Re-check freshness one final time** — a hub publish mid-implementation
  must surface here, not in review: the Freshness re-check above runs
  again right here, not only at the start of the session. Paste the
  freshness output (the `--status-only` output when the cache path was
  taken) into the PR.
- **Run the full suite and linters** — `cmd.test` and
  `cmd.lint` (from `-code §cmd.*`, or the commands recorded at
  the top of the plan file) and **paste the real output**. A
  completion claim without it is not accepted.
- **Record service history** — for each service touched, run
  `kb svc note <service> --ticket <id> --title "<title>" --refs
  "<refs>"` so the entries land in this same PR. If the ticket
  added or renamed a service, run `kb code-ingest` first — `kb svc
  note` validates the service against this repo's own committed
  `<repo_id>-code`, which CI regenerates on the hub but never
  writes back here. If this repo has no `<repo_id>-svc` yet
  (`dev-code-seed` never run), say so in one line in the PR and
  record the history there instead.
- **Assemble the PR description** using the repo's
  `.github/pull_request_template.md`, whose sections CI
  checks with `kb pr lint`: **Ticket**; **kb-context** refs so
  the reviewer can `kb resolve` them; the **AC→test map**; the
  **Placeholder resolutions** list; the **Verification** output,
  pasted inside a fenced block together with the `cmd.test` command
  line itself (e.g. `$ pytest -q`), not claimed; the `## TDD
  exemptions` section — every `Exempt:` line from the plan, or
  `none`; the **Findings**, every `OPEN(...)`, KB gap, ambiguity
  or contradiction as a concrete feedback item on the owning
  repo, or `none`; and the **Usage** table; and **Review** — A5's finding
  table and its `Blocking:` verdict line. A section left as the template's
  comment counts as empty and fails the check.
- **Report the cost** — run `kb usage report --ticket <id> --md`
  and paste the table into the PR under a `## Usage` heading, so
  the PR carries the ticket's own token cost. When the command
  answers `no usage recorded yet` instead of a table, keep the
  heading and say in one line that the ledger is empty for this
  ticket and why — the `Stop` hook is not wired, or no transcript
  has been ingested. An empty measurement is a finding, not a
  reason to drop the section.
- **Amend findings** — if the ticket changed what a service is
  responsible for, report `amend needed: <repo_id>-svc
  §svc.<name>` as a PR finding. **Never edit a `reviewed`
  section.**
- **GATE 3** — offered only after A5 comes back clean — the Dev opens
  the PR; **GATE 4** the Dev merges. **The agent does neither.** Option 1
  in the Next-step block below is always "Open the PR yourself" with the
  branch name already filled in — this is the terminal phase of the
  flow, so there is no next automated command; a blocker takes its
  place instead.

## A5 — merge-risk review (before GATE 3)

A4 asked whether the branch does what the ticket said. A5 asks a different
question, in a different context: is this safe to merge into the default
branch?

If `docs/impl/<ticket-id>-review/branch.diff` does not exist yet — a cold
handover session, a fresh clone or worktree, or hand-implemented code that
never ran `dev-execute` — build it yourself first, with the same command A4
uses: `mkdir -p docs/impl/<ticket-id>-review && git diff $(git merge-base
<default-branch> HEAD)..HEAD > docs/impl/<ticket-id>-review/branch.diff`.

Dispatch a `merge-risk-reviewer` subagent on the most capable model available.
Give it the persona plainly: a tech lead reviewing before a production deploy,
assuming real traffic, concurrent requests, retries, and more than one running
instance. Hand it `docs/impl/<ticket-id>-review/branch.diff`, the ticket, and
the `## Merge-risk axes` of `docs/pr-review-rubric.md` plus
`docs/pr-review-rubric.local.md`.

**The diff alone is not the review.** Say so in the dispatch: the reviewer
opens the files the change reaches — callers, siblings, migrations, permission
declarations, contracts, tests — and traces the affected flow end to end before
judging. A finding that only names a category is not a finding; it states why
this code, on this path, is dangerous.

It writes `docs/impl/<ticket-id>-review/merge-risk.md`: one row per finding
(severity, file, line, why it is dangerous, proposed fix), then the verdict
line `Blocking: Yes` while any BLOCKER stands, `Blocking: No` otherwise.
BLOCKER and SUGGESTED findings get a fix round, then re-review, at most 3
rounds — same routing as A3: only a standing BLOCKER keeps the verdict
`Blocking: Yes`.

Copy the table and the verdict line into the PR body's `## Review` section —
`kb pr lint` fails the PR when the verdict line is missing and when it reads
`Blocking: Yes`. NOTE and NITS findings go to `## Findings` as feedback
items, recorded rather than fixed.

A branch whose A5 still reports `Blocking: Yes` never reaches GATE 3. Option 1
becomes the fix, not the PR.

## Review dispatch contract (every review in this flow)

- The author and the reviewer are NEVER the same subagent. A self-review
  never satisfies a review step.
- A reviewer starts from a fresh context and gets no conversation history —
  hand it only the paths it must read and the constraints that bind it.
- Artefacts move as FILE PATHS, never pasted into the dispatch prompt: the
  draft, the diff, the report. Whatever you paste stays in your context for
  the rest of the session.
- Never pre-judge: a dispatch prompt never tells a reviewer what not to flag
  and never rates a finding's severity for it.
- Name the model on every dispatch — a standard model for authors and
  implementers, the most capable one available for reviewers. Never inherit
  the session default silently.
- Findings → fix subagent → re-review, at most 3 rounds. A BLOCKER or SUGGESTED still
  standing after round 3 stops the flow and goes to the Dev.
- A finding that contradicts the approved design or plan is never auto-fixed:
  show the finding beside the text that mandates it and let the Dev choose.
- Criteria come from the source that matches the review: the rubric's
  `## Pre-code axes` for A1 and A2, its `## Merge-risk axes` for A5, and
  `docs/conventions/<lang>.md` for A3 and A4 — each one's own `.local.md`
  override wins over its base file. Severity is always
  BLOCKER / SUGGESTED / NOTE / NITS.
- Where the runtime cannot dispatch subagents, run the review as its own pass
  that reads ONLY the paths it was handed and reuses nothing it remembers from
  drafting, and write up its findings the same way — then STOP and hand the
  result to the Dev. The phase does not advance on a fallback pass: one
  context reviewing itself is a weaker substitute, not an equivalent — only
  the Dev's explicit go-ahead advances it, recorded in the tick itself, e.g.
  `Review: ✅ r<n> (fallback, Dev-approved)`.

## Hard rules

- A ticket without a resolvable `kb-context` is not implementable — send it back, never improvise the missing context.
- Broken citation = blocker; stale citation = both versions surfaced, humans decide; neither is ever silently ignored.
- No production code without a failing test observed first. No exception for small tickets, deadlines, or "obvious" changes.
- Never claim done without showing the verification output.
- Never invent or "remember" a standard value — every code/format/enum/threshold in code or tests is verbatim from the resolved section at the pinned version, with a citation comment.
- `<repo>-svc` is for locating and cross-checking work only. It is never a source for an AC or a standard value.
- The ticket is the BA's artifact: report placeholder resolutions and AC findings back; never edit the ticket.
- An AC that cannot be implemented as written becomes `OPEN(BA)` — never reinterpreted, and never pushed past mid-implementation.
- Never edit a test to make it pass; diagnose the cause.
- Code is ground truth: when either code-knowledge document disagrees with the code, trust the code and note the mismatch.
- Never modify a `reviewed` section of `-svc`; propose an amend.
- `hist.*` entries are appended only by `kb svc note`, never hand-edited.
- Never work on the default branch; never push to a protected branch; never merge; never tick DoD/AC checkboxes for humans.
- KB feedback items found during implementation go in the PR description — dropping them silently violates DoD.

## Next step — ALWAYS end your response with this block

Close every response with a state line and an ordered list of next steps.
Include it even when you stopped early or hit an error — especially then.

    ## Next step

    → 1. <next step in flow> — <what it does>   (next in flow)
      2. <revise the current phase> — <how>
      3. <stop/park> — <where the work is saved>

    State: design <✅ approved|📝 draft|⬜ not written> · plan <✅ approved|📝 draft|⬜ not written|⚠ missing, N commits|n/a (spike)> · tasks <n>/<m> · PR <✅ opened|✅ merged|❌ closed|⬜ not opened|? unknown>

Rules:
- Option 1 is ALWAYS the next step in flow order: design → plan → execute → handover.
- Show the exact command with the ticket id already filled in, ready to copy.
- The `State:` line always shows all four markers, even the ones not yet reached.
- A blocker takes option 1 instead and says so, e.g.
  `→ 1. Send back to the BA — ref ATM-STD §5.3 is broken, re-pin needed`.
  Flow order never hides a blocker.
