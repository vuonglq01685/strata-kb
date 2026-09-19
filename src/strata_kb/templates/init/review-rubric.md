# Maturity review rubric — missions & tickets

Used by the maturity-review step of `ba-mission-plan` and
`ba-ticket-author`. Round 1 is the two-reviewer scoring pass: two
reviewers score the document independently, one axis each. Rounds 2
and 3 are a single `gap-verifier` pass instead — it returns pass/fail
per gap and does not score. Edit this file to tune the criteria for
your domain; the skills read it at review time.

## Business coverage

Reviewer role: PO / stakeholder. Question: does this document cover
the business need, or only the happy path someone remembered?

Checklist (pass/fail each item):

- [ ] Every in-scope area of the mission has a corresponding US
      (missions) / every part of the story is covered by an AC (tickets).
- [ ] ACs cover the happy path AND edge cases AND error/empty states.
- [ ] Out of scope lists the things easily mistaken as in-scope —
      not just "everything else".
- [ ] The business value of the story/mission is stated and concrete.
- [ ] NFRs are quantified where the work touches large data volumes,
      concurrency, or real-time constraints.
- [ ] No architecture-blocking open question is still OPEN
      (missions: none blocking foundational stories).
- [ ] No statement contradicts the pinned KB sources.
- [ ] Every unknown is owned: `OPEN(<owner>)` + an `## Open questions`
      row — vagueness without an owner fails this item.

## Dev implementability

Reviewer role: the dev who picks this up next sprint. Question: can I
implement this without asking the BA anything?

Checklist (pass/fail each item):

- [ ] Implementable end-to-end without a follow-up question.
- [ ] Every AC is acceptance-testable with concrete values — no weasel
      words (banned list: `docs/ac-quality.md`).
- [ ] The UI spec names the MEANS of every visual distinction (label,
      color, shape, grouping) — or `N/A` / `OPEN(<owner>)`.
- [ ] Test data with expected values is present (or owned `OPEN`).
- [ ] Dependencies are listed ("None" counts; blank does not).
- [ ] Sequencing is feasible — nothing depends on later work.
- [ ] Every `OPEN(...)` and `%%TODO%%` has an owner.
- [ ] No weasel words anywhere in the body.

## Maturity scale

Score each axis 1–5:

| Level | Meaning |
|---|---|
| 1 | Initial — required sections missing or empty |
| 2 | Skeletal — structure present, content vague |
| 3 | Structured — complete structure, gaps exist but every gap is owned |
| 4 | Ready — a dev/PO would accept it; all checklist items pass or are owned `OPEN` (**threshold**) |
| 5 | Mature — no blocking open questions remain |

## Scoring rule

The score is the LOWEST level whose criteria are ALL satisfied.
Never average across checklist items. Threshold to stop the review
loop: both axes ≥ 4. Results are appended to the document's
`## Review record` section, one row per round.

An axis's score rises only when every gap of that axis passes the
round 2/3 `gap-verifier` pass; otherwise it carries forward unchanged
from the previous round.
