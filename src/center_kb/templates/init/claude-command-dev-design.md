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

Before anything else, re-resolve the ticket's `kb-context`: call the MCP tool
`kb_resolve` when available, otherwise `kb resolve <ticket-file>` (or
`kb resolve - < ticket.md`). The hub may have published since the last session,
so a ref that was `ok` yesterday can be `stale` today — checking only at
handover is too late, because the plan may already rest on changed content.

- **broken** → STOP. This is a blocker: report to the BA that the ticket needs
  re-pinning. Never implement around a citation that no longer resolves.
- **stale** → show BOTH versions and let the humans decide: `kb resolve` returns
  the pinned content plus the reason; `kb get <doc-id> <section> [--level l3]`
  returns the CURRENT hub version. Do NOT use `kb diff` — it compares the local
  `.kb/` worktree against a local git rev, and this repo holds no local copy of
  the cited domain document.
- **ok** → continue.

Classify the ticket out loud before designing, so the Dev can override
it: **spike** — a feasibility question the ticket itself raises, answered
with a recommendation and any throwaway build labelled as such;
**bounded** — a change to a flow that already exists in this repo,
written as a few sentences to a few short paragraphs **in chat** with no
design file; **architectural** — a new service, new table, new
interface, or a change to how components fit, written to
`docs/impl/<ticket-id>-design.md` (**architectural path only**).
Classification measures the repo, not your familiarity with it, so no
existing flow to change means it is not bounded; between two paths,
take the heavier one; the ratchet is **one-way** — hidden complexity
found later upgrades the path and you say so, nothing downgrades
mid-ticket. The design content covers modules touched, interfaces added
or changed, data changes, and the placeholder resolutions from the
orchestrator's Placeholders step, with every standard-derived value
quoted verbatim with its `doc-id §section`; any AC that cannot be
implemented as written becomes
`OPEN(BA)` — reinterpreting an AC is forbidden.

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
GATE 1 passes; a blocker takes its place instead.

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
