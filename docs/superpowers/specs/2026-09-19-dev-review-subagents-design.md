# Independent review subagents across the dev ticket flow — Design

**Date:** 2026-09-19
**Status:** Approved
**Extends:** `2026-08-19-dev-agent-design.md`

## Problem

The dev flow (`/dev-implement-ticket` → `dev-design` → `dev-plan` →
`dev-execute` → `dev-handover`) has four human gates and no independent
machine review anywhere:

1. **One agent does everything in one context.** The orchestrator writes the
   design, writes the plan, and assembles the PR. Each phase judges its own
   output with the same context that produced it.
2. **`dev-execute`'s "review checkpoint" is a self-review.** Step 3 of the
   per-task loop (`claude-skill-dev-execute.md:57`) runs *inside* the
   implementer subagent that just wrote the code. There is no second pair of
   eyes on any diff before the PR.
3. **No merge-risk pass at all.** `dev-handover` assembles evidence; nothing
   asks whether this branch is safe to merge into `main` — security, data
   integrity, scale, contract breakage, rollout.
4. **Everything above GATE 3 is prompt-only.** `kb pr lint` is the single
   machine gate. GATE 1/2 and every TDD rule are reminders an agent can skip
   with nothing failing.

The BA side already solved the shape: `ba-ticket-author.md:92` dispatches two
review subagents in parallel with separate perspectives and a `gap-verifier`
for later rounds. Dev has none of it.

## Decisions

| # | Decision |
|---|---|
| D1 | Independent author + reviewer subagents in `dev-design`, `dev-plan`, `dev-execute`. `dev-handover` gets a wide merge-risk reviewer. |
| D2 | Keep **both** end-of-branch reviews, with different lenses: a narrow one at the end of `dev-execute` (does the branch fulfil the ticket) and a wide one in `dev-handover` (is it safe to merge into main). |
| D3 | Rubric ships as `docs/pr-review-rubric.md` with a `docs/pr-review-rubric.local.md` override, matching `ac-quality.md` / `review-rubric.md` / `conventions/<lang>.md`. |
| D4 | Findings → fix subagent → re-review, **max 3 rounds**. Unresolved blockers stop the flow for a human. A finding that contradicts the approved design/plan is a human decision, never auto-fixed. |
| D5 | Review state lands in files that already exist — no new ledger. |
| D6 | `kb pr lint` gains a ninth required section, `## Review`, and fails on `Blocking: Yes`. The second pair of eyes becomes a CI gate, not a reminder. |

## Naming

Human gates keep their numbers (GATE 1 design, GATE 2 plan, GATE 3 open PR,
GATE 4 merge). Agent reviews are **A1–A5** so the two ladders never blur:

| ID | Where | Lens |
|---|---|---|
| A1 | `dev-design`, before GATE 1 | design fits the ticket |
| A2 | `dev-plan`, before GATE 2 | plan is executable and test-first |
| A3 | `dev-execute`, per task | this diff meets this task's spec, and is well built |
| A4 | `dev-execute`, after last task | branch fulfils the whole ticket |
| A5 | `dev-handover`, before GATE 3 | branch is safe to merge into main |

## Dispatch map

### `dev-design` — author + A1

- `design-author` subagent. Receives: path to the resolved context cache, the
  ticket's AC, the conventions paths. Writes `docs/impl/<id>-design.md` with
  `status: draft`.
- `design-reviewer` subagent, **fresh context, never sees the drafting**.
  Receives: the design file path, the ticket's AC, the rubric's `Pre-code
  axes`. Returns pass/fail per axis plus a gap list; every gap names the
  section it lives in and a proposed fix.
- Fix loop per D4, then the design is presented at GATE 1.

### `dev-plan` — author + A2

Same shape. `plan-reviewer` checks: exactly one task per AC; every task states
its failing test first; each task's **Interfaces** entry is complete enough
that an implementer never has to read wider; any `Exempt:` line names a
category from `docs/tdd-exemptions.md`. Then GATE 2.

### `dev-execute` — implementer + A3 per task, then A4

Per unticked task:

1. `implementer` subagent, unchanged inputs (its task block, that task's
   Interfaces entry, `cmd.test` / `cmd.lint`). Red → green → verify → commit.
   Its self-review stays — it is cheap and catches slips before handoff, but
   it never counts as review.
2. The orchestrator records `BASE` **before** dispatching, and afterwards
   writes `git diff <BASE>..HEAD` to `docs/impl/<id>-review/task-<n>.diff`.
   Never `HEAD~1` — it silently drops all but the last commit of a
   multi-commit task.
3. `task-reviewer` subagent, fresh context. Receives **three paths** — the
   task brief, the implementer's report, the diff file — plus the binding
   constraints copied verbatim from the plan. Returns **two verdicts, both
   required**: spec compliance (✅/❌, nothing missing and nothing extra) and
   code quality. A report carrying only one verdict is invalid.
4. Critical/Important findings → fix subagent → re-review (D4).
5. Only once clean: the orchestrator ticks the task's checkboxes and appends
   `Review: ✅ r<n>` under the task in the plan file.

After the last task, A4: `branch-reviewer`, narrow — every AC covered, nothing
extra built, no later task broke an earlier one. Input:
`docs/impl/<id>-review/branch.diff` (`merge-base..HEAD`) and the plan.

### `dev-handover` — A5, merge-risk

`merge-risk-reviewer` subagent. Persona: a tech lead reviewing before a
production deploy, assuming a live system with real traffic, concurrent
requests, retries and multiple instances. Goal is production risk, not style.

- Input: `docs/impl/<id>-review/branch.diff`, the ticket, and
  `docs/pr-review-rubric.md` + `.local.md`.
- **Hard rule: the diff alone is not the review.** The reviewer opens related
  files — callers, siblings, migrations, permission declarations, contracts —
  and traces the affected flow end to end before judging.
- Output: one row per finding (severity | file | line | why it is dangerous,
  tracing the concrete logic | proposed fix), a summary with counts, and a
  `Blocking:` verdict.
- Any BLOCKER left → the flow does not reach GATE 3. Non-blocking findings go
  into the PR's `## Findings`.

## Shared subagent contract

These rules are what makes "independent context" real rather than decorative.
They appear in every dispatching skill:

- No subagent receives conversation history. The controller composes exactly
  what it needs.
- A reviewer receives the artefact as a **path**, never pasted into the prompt
  — the diff stays out of the controller's context too.
- Author and reviewer are never the same subagent, and a self-review never
  satisfies a review step.
- No pre-judging: a dispatch prompt never tells a reviewer what not to flag
  and never pre-rates a finding's severity.
- Dispatches name the model explicitly: standard model for authors and
  implementers, the most capable model available for reviewers. Template text
  never hard-codes a model id — those rot.

## Rubric

`kb init --kind dev` writes `docs/pr-review-rubric.md`, one file with two
halves, plus a `docs/pr-review-rubric.local.md` stub. Local entries override
base ones by id.

**`## Pre-code axes`** (A1, A2): AC coverage · standard-derived values
verbatim with a citation · work classification (spike / bounded /
architectural) · one task per AC · Interfaces completeness · YAGNI.

**`## Merge-risk axes`** (A5 only — A4 judges ticket fulfilment against the
plan, not merge risk): security & authorization
· data integrity (duplicates, race conditions, idempotency, transaction
scope) · performance & scale (N+1, queries or external calls in loops, missing
pagination or index, unbounded in-memory work) · contract & backward
compatibility · migration, rollout & rollback · observability (no sensitive
data in logs, enough context to debug) · test adequacy · production readiness
(timeouts, dependency failure handling).

Each entry carries a default severity on the ladder **BLOCKER / SUGGESTED /
NOTE / NITS**. Rule: no approval while a BLOCKER stands.

The base file stays stack-agnostic. Stack-specific checklists (framework
layering rules, permission decorators, UI component conventions) belong in the
`.local.md`.

## State and artefacts

| Artefact | Location | Committed |
|---|---|---|
| diffs, reviewer reports | `docs/impl/<id>-review/` | no — `impl-gitignore.txt` gains `*-review/` |
| A1/A2 verdicts | `## Review record` table in the design / plan file | yes |
| A3 verdict | `Review: ✅ r<n>` under the task in the plan file | yes |
| A4/A5 outcome | PR body `## Review`; non-blocking items in `## Findings` | in the PR |

A task's checkbox is ticked **only** after its review is clean, so the plan
file is the progress ledger: a new session reads it and resumes at the first
unticked task without re-dispatching finished work. No second source of truth.

## Machine gate

`prlint.REQUIRED_SECTIONS` gains `"Review"` (ninth entry). Rules:

- Missing section, or a section still holding only the template's comment →
  FAIL, as with every other required section.
- The section must contain a line matching `^Blocking:\s*(Yes|No)\b`
  (case-insensitive). Absent → FAIL: the review verdict was never recorded.
- `Blocking: Yes` → FAIL, naming the blocking count.
- `## Review` is **not** a sentinel section: `none` does not satisfy it. A
  clean review still states `Blocking: No`.

`pull-request-template.md` gains the matching section with a comment showing
the finding table and the `Blocking:` line.

## Degraded runtimes

Copilot and Cursor variants cannot dispatch subagents. They follow the idiom
already used on the BA side — separate sequential passes — with an explicit
instruction that a review pass reads only the paths it was handed and does not
reuse recollection from the drafting pass. The templates say plainly that this
is a weaker substitute, not an equivalent: one context cannot truly review
itself.

## Scope

**In:** the four dev phase skills × four variants (claude skill, claude
command, copilot prompt, cursor rule) = 16 template files, body-identical per
`tests/test_templates.py:458`; two new template resources (rubric + local
stub) in `initcmd.py` — the base rubric in `DEV_TEMPLATES` (create-or-
refresh), the `.local.md` in a new `DEV_LOCAL_OVERRIDES` map applied exactly
as `BA_LOCAL_OVERRIDES` is (created once, never refreshed, not protected);
`impl-gitignore.txt`;
`pull-request-template.md`; `prlint.py`; tests for each; both `docs/src/guide-dev.*.md` files, §4.3 (four gates → four human gates plus five agent reviews) and
§5.2 (the `## Review` rule moves from "prompt-only" to "machine-enforced");
CHANGELOG.

**Out:** `/dev-implement-ticket`'s own phases (intake, resolve, ground,
placeholder verification) keep their current shape — no independent verifier
subagent this round; `dev-code-seed`; the BA and hub sides; any new CLI
command; porting the superpowers `task-brief` / `review-package` scripts —
`git diff` to a path is enough.

## Risks

- **Cost.** Every ticket roughly doubles its agent invocations. The `## Usage`
  table already in the PR will show it; that is the intended measurement.
- **Still prompt-driven, except one rule.** A1–A4 remain reminders. Only A5
  gains CI teeth, via `Blocking: No`. An agent that skips A1–A3 and writes an
  honest `Blocking: No` still passes. Accepted: the PR gate is where a merge
  actually happens.
- **Review loops can stall.** The 3-round cap converts a stall into a human
  decision instead of an infinite fix/re-review exchange.
