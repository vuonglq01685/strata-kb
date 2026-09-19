---
description: Turn an approved BA ticket into a technical design for this codebase — classify the work as spike / bounded / architectural, then design how to implement it
argument-hint: "[ticket id]"
---

Invoke the `dev-design` skill with the Skill tool and follow its workflow
exactly. Pass "$ARGUMENTS" as the ticket id when given; when empty, ask
for it before continuing.

The ticket **is** the specification — the BA already wrote and pinned it;
this phase decides **how to implement it in this codebase**, not whether
the business need is right, and it ends at **GATE 1**: the Dev approves
before any plan is written, so presenting the design and starting the
plan in the same turn skips the gate.

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

Classify the ticket out loud before designing, so the Dev can override
it: **spike** — a feasibility question the ticket itself raises, answered
with a recommendation and any throwaway build labelled as such;
**bounded** — a change to a flow that already exists in this repo, with
a design a few sentences to a few short paragraphs long; **architectural**
— a new service, new table, new interface, or a change to how components
fit, with a design covering every item under *Design content* below.
Classification measures the repo, not your familiarity with it, so no
existing flow to change means it is not bounded; between two paths,
take the heavier one. The ratchet turns **one-way**: complexity that
surfaces mid-ticket promotes the path — say so when it does — and
nothing ever demotes it. Every path writes
`docs/impl/<ticket-id>-design.md` — one paragraph on the bounded path is
the resume point the orchestrator reads, not ceremony — opening with two
header lines under its title: `path: <spike|bounded|architectural>` and
`status: draft`. A spike's body is the question, what was tried, the
recommendation, and the sentence "anything built for this is throwaway";
it ends there — no plan, no execute — with `dev-handover` as its next
step, putting the recommendation under `## Findings`. When the Dev
approves, flip the header to `status: approved` before anything else —
`dev-plan` refuses a `draft` design; a file's existence is not approval,
its `status:` line is. A spike's design is flipped to `status: approved`
here too — approving the recommendation, not a plan — so `design ✅`
reads correctly if the ticket is re-opened. The design content covers
modules touched, interfaces added or changed, data changes, and the
placeholder resolutions from the orchestrator's Placeholders step, with every
standard-derived value quoted verbatim with its `doc-id §section`; any
AC that cannot be implemented as written becomes `OPEN(BA)` —
reinterpreting an AC is forbidden.

## A1 — independent design review (before GATE 1)

Write the design in its own context: dispatch a `design-author` subagent with
the resolved context cache path, the ticket's acceptance criteria, the
conventions paths, and this phase's own authoring rules above — what the
design must cover, and how placeholders and standard values are cited — and
let it write `docs/impl/<ticket-id>-design.md` with `status: draft`. You
orchestrate; you do not draft and then judge your own draft.

That design is a draft until a reviewer that never saw it being written
says otherwise. Dispatch a `design-reviewer` subagent and hand it exactly
three things: the path `docs/impl/<ticket-id>-design.md`, the ticket's
acceptance criteria, and the `## Pre-code axes` of the rubric. Not your
reasoning, not this conversation.

It returns pass/fail per axis plus a gap list in which every gap names the
section it lives in, its severity, and a proposed fix. Apply BLOCKER and
SUGGESTED gaps through a fix subagent, then re-review — at most 3 rounds.

Record every round in the design file's `## Review record` table, creating it
below the design body on round 1:

    | Date | Round | Verdict | Reviewer | Open gaps |
    |---|---|---|---|---|
    | <date> | 1 | BLOCKER x1 | design-reviewer | AC3 not addressed |

GATE 1 is offered only after A1 comes back clean — clean means no BLOCKER and
no SUGGESTED gap left open; NOTE and NITS are recorded, not fixed. A BLOCKER
surviving round 3 goes to the Dev with the reviewer's text and yours, and the
flow stops there.

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
- Criteria come from `docs/pr-review-rubric.md`, then
  `docs/pr-review-rubric.local.md` — the local file wins. Severity is always
  BLOCKER / SUGGESTED / NOTE / NITS.
- Where the runtime cannot dispatch subagents, run the review as its own pass
  that reads ONLY the paths it was handed and reuses nothing it remembers from
  drafting, and write up its findings the same way — then STOP and hand the
  result to the Dev. The phase does not advance on a fallback pass: one
  context reviewing itself is a weaker substitute, not an equivalent.

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
