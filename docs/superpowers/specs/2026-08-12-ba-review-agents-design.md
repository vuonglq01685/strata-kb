# BA Review Agents — Maturity Review for Missions & Tickets — Design

Date: 2026-08-12
Status: approved by BA (brainstorming session)

## Goal

After the BA authoring skills produce a mission plan or ticket, dispatch
review agents that measure two maturity axes — **business coverage** and
**dev implementability** — score them 1–5 against a scaffolded rubric,
loop on the gaps, and persist the result in the document itself. The DoR
lints stay deterministic; the maturity review is an authoring-time agent
layer on top, not a new hard gate.

## Decisions made

| Decision | Choice |
|---|---|
| Where the review runs | Inside the authoring skills (`ba-mission-plan`, `ba-ticket-author`), after lint PASS, before presenting to the BA. No new CLI command. |
| Gate mechanism | Loop to threshold: fix gaps, re-lint, re-review; max 3 rounds or stop early when both axes ≥ 4. Unfixable gaps become `OPEN(<owner>)` + an Open questions row — never guessed at. |
| Reviewer composition | 2 separate agents in parallel — business-coverage reviewer (PO/stakeholder role) and dev-implementability reviewer (implementing-dev role). Perspectives stay unblended. |
| Scoring | 5-level maturity scale per axis + concrete pass/fail checklist as evidence. Threshold: ≥ 4. Score = lowest level whose criteria are ALL satisfied — no averaging. |
| Rubric location | New scaffolded doc `docs/review-rubric.md` (source: `templates/init/review-rubric.md`), same pattern as `ac-quality.md`. BA can tune it per domain without a center-kb release (NT1). |
| Result persistence | `## Review record` section in the mission/ticket itself; append one row per review run, keep history. |
| Lint enforcement | New checks are **warnings only** (missing/placeholder Review record); DoR verdict never flips. Consistent with the weasel-word policy: the BA judges. |
| Mirrors without subagents | cursor/copilot variants fall back to sequential self-review: two distinct role passes with the same rubric and the same record format. |

## Review flow (inside each authoring skill)

1. Author the document; run `kb mission lint` / `kb ticket lint`; reach PASS.
2. Dispatch two subagents in parallel:
   - **Business-coverage reviewer** — acts as PO/stakeholder. Input: the
     document, `docs/review-rubric.md`, KB context via the MCP tools.
     Judges: does the backlog cover the mission scope; do ACs cover happy
     path + edge + error/empty states; is out-of-scope explicit; is the
     business value of each story clear; are NFRs quantified where the
     mission touches large data / concurrency / real-time; are
     architecture-blocking open questions closed; no contradiction with
     KB sources.
   - **Dev-implementability reviewer** — acts as the dev who will pick up
     the ticket. Judges: can it be implemented without asking anything
     back; are ACs measurable with concrete values; does the UI spec say
     *by what means*; are sample data + expected values present; are
     dependencies and sequencing workable; does every `OPEN(...)` have an
     owner; no weasel words.
3. Each agent returns: score 1–5, checklist results (pass/fail per item),
   and a gap list where every gap names the section it lives in and a
   proposed fix.
4. The skill applies the fixes, re-runs lint, re-reviews. Max 3 rounds;
   stop early when both axes ≥ 4.
5. Gaps the skill cannot fix itself (missing business decision, missing
   input) are never invented: write `OPEN(<owner>)` at the spot and add an
   `## Open questions` row (NT3).
6. Append a `## Review record` row and present the document to the BA with
   a summary of scores and remaining owned gaps.

## `## Review record` format

Added to both templates (ticket + mission) with the placeholder body
"Not yet reviewed." — the template determines the output (NT1).

```markdown
## Review record

| Date | Round | Business | Dev | Reviewer |
|---|---|---|---|---|
| 2026-08-12 | 2 | 4 | 4 | agent |

Open gaps: Q3 (owner: BA), Q5 (owner: dev-lead)
```

Re-reviews append rows; history shows maturity progressing over time.

## `review-rubric.md` (new scaffolded doc)

English guidance (headings never localized), two axes:

- **Business coverage checklist** (~8 items): every mission-scope area has
  a corresponding US; every US has ACs covering happy/edge/error-empty;
  out-of-scope lists the things easily mistaken as in-scope; per-story
  business value stated; NFRs quantified when volume/concurrency/real-time
  applies; architecture-blocking open questions closed; consistent with KB
  sources.
- **Dev implementability checklist** (~8 items): implementable without
  follow-up questions; ACs acceptance-testable with concrete values; UI
  spec states the means (label, color, shape, grouping); test data with
  expected values; dependencies listed; sequencing feasible; every
  `OPEN(...)` owned; no weasel words (`docs/ac-quality.md`).
- **5-level scale** (per axis): 1 initial (sections missing) → 2 skeletal
  (structure present, content vague) → 3 structured (complete structure,
  gaps owned) → 4 acceptable to dev/PO, all gaps owned (**threshold**) →
  5 no blocking open questions remain.
- **Scoring rule**: the score is the lowest level whose criteria are all
  satisfied. No averaging across items.

## File map (all under `src/center_kb/` unless noted)

| Change | Files |
|---|---|
| Rubric (new) | `templates/init/review-rubric.md` + `BA_TEMPLATES` entry in `initcmd.py` → scaffolds to `docs/review-rubric.md` |
| Ticket template | `templates/init/ticket-template.md` — add `## Review record` |
| Mission template | `templates/init/mission-template.md` — add `## Review record` |
| Mission skill + mirrors | `templates/init/claude-skill-ba-mission-plan.md`, `cursor-ba-mission-plan.md`, `copilot-ba-mission-plan.prompt.md`, `claude-command-ba-mission-plan.md` (full copy — kept in sync) |
| Ticket skill + mirrors | `templates/init/claude-skill-ba-ticket-author.md`, `cursor-ba-ticket-author.md`, `copilot-ba-ticket-author.prompt.md` (claude-command variant is a thin pointer — untouched) |
| Lint warnings | `missionlint.py`, `ticketlint.py`: warn when `## Review record` is missing or still holds the "Not yet reviewed." placeholder; never an error |

## Constraints honored

- New `##` sections keep `DoR: PASS` (verified in the v2 template upgrade).
- No MCP tool for the review — it runs inside the authoring skill session,
  which already has filesystem + MCP access (mirrors the missionlint §9
  rationale).
- Warnings-only lint policy preserved: nothing here can flip a DoR verdict.

## Testing

- `initcmd` scaffold test: `kb init --kind ba` produces `docs/review-rubric.md`.
- `missionlint`/`ticketlint` tests: warning fires on missing Review record
  and on the untouched placeholder; verdict unchanged in both cases;
  a filled record produces no warning.
- Template round-trip: the updated templates still lint PASS.
