---
name: dev-design
description: Turn an approved BA ticket into a technical design for THIS codebase — classify the work as spike / bounded / architectural, then design how to implement it. Use as phase 1 of implementing a ticket, or when invoked as /dev-design.
---

# dev-design — phase 1: classify the ticket, then design the implementation

You are turning an approved ticket into a technical design for THIS
codebase. The ticket **is** the specification: the BA already wrote it,
cited it, and pinned it. This phase does not re-brainstorm the business
need — it decides **how to implement it here**: classify the work, then
design just enough to build it right.

*Counterpart in the superpowers plugin: `superpowers:brainstorming` — if it
is installed it is the newer source for the three-path method.*

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

## Path classification — say it out loud so the Dev can override it

- **spike** — a feasibility question the ticket itself raises; the
  output is an answer plus a recommendation, and anything built to get
  there is labelled throwaway.
- **bounded** — changes a flow that already exists in this repo; the
  design is a few sentences to a few short paragraphs.
- **architectural** — a new service, a new table, a new interface, or a
  change to how components fit; the design covers every item under
  *Design content* below.

Classification measures **the repo, not your familiarity** with it — no
existing flow to change means the ticket is not bounded. Between two
paths, **take the heavier one**. The ratchet is **one-way**: hidden
complexity found later upgrades the path, and you say so; nothing
downgrades mid-ticket.

Every path writes `docs/impl/<ticket-id>-design.md` — one paragraph on
the bounded path is not ceremony, it is the resume point the orchestrator
reads. The file opens with two header lines under its title:
`path: <spike|bounded|architectural>` and `status: draft`. A spike's
body is the question, what was tried, the recommendation, and the
sentence "anything built for this is throwaway"; a spike ends here — no
plan, no execute — and its next step is `dev-handover`, which puts the
recommendation under `## Findings`.

## Design content

Cover modules touched, interfaces added or changed, data changes, and the
placeholder resolutions carried over from the orchestrator's Placeholders
step. Quote every standard-derived value verbatim with its `doc-id
§section`. Any AC that cannot be implemented as written becomes
`OPEN(BA)` — reinterpreting an AC is forbidden, and so is deciding the
ambiguity yourself.

## GATE 1 — Dev approval before any plan is written

The Dev approves the design before the plan is started. Presenting the
design and starting the plan in the same turn is skipping the gate.
When the Dev approves, flip the header to `status: approved` before
anything else — `dev-plan` refuses a `draft` design. A file's existence
is not approval; its `status:` line is. A spike's design is flipped to
`status: approved` here too — approving the recommendation, not a plan —
so `design ✅` reads correctly if the ticket is re-opened.

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
- Findings → fix subagent → re-review, at most 3 rounds. A BLOCKER still
  standing after round 3 stops the flow and goes to the Dev.
- A finding that contradicts the approved design or plan is never auto-fixed:
  show the finding beside the text that mandates it and let the Dev choose.
- Criteria come from `docs/pr-review-rubric.md`, then
  `docs/pr-review-rubric.local.md` — the local file wins. Severity is always
  BLOCKER / SUGGESTED / NOTE / NITS.
- Where the runtime cannot dispatch subagents, run the review as its own pass
  that reads ONLY the paths it was handed and reuses nothing it remembers from
  drafting — and say so in the report: one context reviewing
  itself is a weaker substitute, not an equivalent.

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

For `dev-design`, option 1 below is always `/dev-plan <ticket-id>` once
GATE 1 passes — unless `path: spike`, where option 1 is `/dev-handover
<ticket-id>`; a blocker takes its place instead.

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
