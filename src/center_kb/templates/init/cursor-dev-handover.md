---
name: dev-handover
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

Re-resolve the ticket's `kb-context` first: `kb_resolve`, else
`kb resolve <ticket-file>`. The hub may have published since last session.

- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a
  citation that no longer resolves.
- **stale** → show BOTH versions, humans decide: `kb resolve` gives the pinned
  content and the reason, `kb get <doc-id> <section> [--level l3]` the current
  hub version. Do NOT use `kb diff` — it compares the local `.kb/` worktree to
  a local git rev, not this repo to the hub.
- **ok** → continue.

## Steps

- **Re-check freshness one final time** — a hub publish
  mid-implementation must surface here, not in review: the
  Freshness re-check above runs again right here, not only at
  the start of the session.
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
- **Assemble the PR description**, containing: the **ticket
  id**; the **kb-context** refs so the reviewer can `kb resolve`
  them; the **AC→test map**; the **placeholder-resolution**
  list; every `OPEN(...)` finding; the verification output; and
  every **KB gap**, ambiguity, or contradiction found, as a
  concrete feedback item (issue or PR on the owning child repo /
  hub).
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
- **GATE 3** the Dev opens the PR; **GATE 4** the Dev merges.
  **The agent does neither.** Option 1 in the Next-step block
  below is always "Open the PR yourself" with the branch name
  already filled in — this is the terminal phase of the flow,
  so there is no next automated command; a blocker takes its
  place instead.

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

    State: design <✅ approved|⬜ not written> · plan <✅ approved|⬜ not written> · tasks <n>/<m> · PR <✅ opened|⬜ not opened>

Rules:
- Option 1 is ALWAYS the next step in flow order: design → plan → execute → handover.
- Show the exact command with the ticket id already filled in, ready to copy.
- The `State:` line always shows all four markers, even the ones not yet reached.
- A blocker takes option 1 instead and says so, e.g.
  `→ 1. Send back to the BA — ref ATM-STD §5.3 is broken, re-pin needed`.
  Flow order never hides a blocker.
