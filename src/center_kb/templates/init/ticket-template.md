# <Title — one line, imperative, with identifier>

## Summary
<1–2 lines business summary>

## User Story
As a <role>, I want <capability>, so that <value>.

## Background / Business context
<context; every industry-standard claim cites `[doc-id §section]`>

## Acceptance Criteria
<!-- One observable outcome per AC, with concrete values. No weasel
words ("appropriate", "configured", "a subset", "responsive", … — the
full banned list is docs/ac-quality.md). An unsettled value is written
`OPEN(<owner>)` inside the AC AND gets a row in the Open questions
section below — never left vague. Citations are bracketed:
`[arinc-424 §5.129]`. Prose that merely names a standard ("per ARINC
424") is not a citation and the gate ignores it. -->
- [ ] AC1 … (cite `[doc-id §section]` when it touches a standard)
- [ ] AC2 …

## Use cases
### Main flow
### Alternate / exception flows

## Sequence diagram
```mermaid
sequenceDiagram
  …
```

## Business flow
```mermaid
flowchart TD
  …
```

## Dependencies
<!-- Write "None" when there are none — a blank section reads as
"not considered". -->
- Blocked by: <us-id or external item> — <why>
- Blocks: <us-id>

## Non-functional requirements
<!-- Every row needs a number or a threshold, or `OPEN(<owner>)`.
Never "fast", "stable", "handles load". A pure data/backoffice ticket
with no NFR writes "N/A — <reason>". -->
| Concern | Target | How to measure | Source |
|---|---|---|---|

## UI / presentation spec
<!-- What the user sees: layout, labels, empty state, error state,
visual-distinction rules between types (say BY WHAT MEANS — label,
color, shape, grouping), display order, or a mockup link.
No design input yet → `OPEN(<owner>)`. No UI in this ticket → "N/A".
Never stop at "distinguished by type" without naming the means. -->

## Out of scope
<!-- This ticket's own boundary — distinct from the mission's
out-of-scope. List the things easily mistaken as belonging here. -->

## Test data & verification
<!-- Sample records + expected values. Tolerances for numeric checks.
How to verify each hard-to-test AC. No sample data yet →
`OPEN(<owner>)`. -->

## Open questions
<!-- Every `OPEN(...)` and every `%%TODO%%` in this ticket must have a
row here, with an owner. -->
- [ ] Q1 — <question> — owner: <who> — blocks: <AC# or section>

## KB context
```yaml
kb-context:
  version: "<hub commit>"
  refs:
    - [repo:doc-id §section]
  tags: [ … ]
```

## Definition of Ready
- [ ] Story, ACs, use cases, both diagrams present
- [ ] Every citation resolves at the pinned version (kb ticket lint PASS)
- [ ] No stale refs
- [ ] Every AC is acceptance-testable; no weasel words remain (docs/ac-quality.md)
- [ ] Dependencies, NFR, UI spec, Out of scope, Test data filled or "N/A — <reason>"
- [ ] Every open question has an owner

## Review record
<!-- Filled by the maturity-review step (rubric: docs/review-rubric.md).
One row per review round; re-reviews append rows — keep the history.
Score = lowest maturity level fully satisfied; threshold is 4 per axis.
Gaps still open after the review are listed below the table and each
must have an owned row under Open questions. -->
Not yet reviewed.

| Date | Round | Business | Dev | Reviewer |
|---|---|---|---|---|

Open gaps: <none, or Q-ids with owners>
