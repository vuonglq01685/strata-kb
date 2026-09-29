# <Title — one line, imperative, with identifier>

<!-- CORE sections (Summary … Out of scope, then Technical grounding,
Open questions, KB context) are every ticket's. EXTENDED sections
(Sequence diagram, Non-functional requirements, UI / presentation spec,
Test data & verification) are opt-in: keep one only when the story needs
it, otherwise delete it or write `N/A — <reason>`. `kb ticket lint` warns
when the story's own words call for one that is missing. -->

## Summary
<1–2 lines business summary>

## User Story
As a <role>, I want <capability>, so that <value>.

## Background / Business context
<context; every industry-standard claim cites `[doc-id §section]`>

## Acceptance Criteria
<!-- One AC = one Given/When/Then: a starting state, one action, one
observable outcome with concrete values. No weasel words ("appropriate",
"configured", "a subset", "responsive", … — the full banned list is
docs/ac-quality.md). An unsettled value is written `OPEN(<owner>)` inside
the AC AND gets a row in the Open questions section below — never left
vague. Citations are bracketed: `[hr-handbook §4.12]`. Prose that merely
names a standard ("per the handbook") is not a citation and the gate
ignores it. -->
- [ ] AC1 — Given <state>, when <action>, then <observable outcome> (cite `[doc-id §section]` when it touches a standard)
- [ ] AC2 — Given …, when …, then …

## Use cases
### Main flow
### Alternate / exception flows

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

## Out of scope
<!-- This ticket's own boundary — distinct from the mission's
out-of-scope. List the things easily mistaken as belonging here. -->

<!-- ===== EXTENDED sections — keep only what this story needs ===== -->

## Sequence diagram
<!-- Optional. Keep it only when the interaction spans more than one
actor or system (an integration, a callback, a third party). A single
actor talking to one system is the Business flow above, drawn twice.
Code-level participants (service names, tables) are the Dev's to draw at
dev-design — never invent them here. -->
```mermaid
sequenceDiagram
  …
```

## Non-functional requirements
<!-- Only when the story touches load, bulk processing, concurrency,
latency or timing. Every row needs a number or a threshold, or
`OPEN(<owner>)`. Never "fast", "stable", "handles load". -->
| Concern | Target | How to measure | Source |
|---|---|---|---|

## UI / presentation spec
<!-- Only when the story has a screen. What the user sees: layout,
labels, empty state, error state, visual-distinction rules between types
(say BY WHAT MEANS — label, color, shape, grouping), display order, or a
mockup link. No design input yet → `OPEN(<owner>)`. Never stop at
"distinguished by type" without naming the means. -->

## Test data & verification
<!-- Only when the story processes records, files or formats. Sample
records + expected values. Tolerances for numeric checks. How to verify
each hard-to-test AC. No sample data yet → `OPEN(<owner>)`. -->

<!-- ===== end of EXTENDED sections ===== -->

## Technical grounding
<!-- SA-owned — filled by /sa-ticket-ground from the hub's <repo>-code
document, never by the BA. Every line points at a section id that exists
in that document, or carries [NEW: D<n>], or is parked under Open
decisions. Code the ticket will create → [NEW: D<n>], where D<n> is a
DECIDED row of the parent mission's Technology decisions. No parent
mission → [NEW: <reason>]. Open decisions is for code that EXISTS and
the document cannot prove — no internal flow, no failure modes — never
for a thing that is simply not built yet. Gate:
`kb ticket check <this file>` must report `Grounding: PASS` before Dev
starts; a D-row still OPEN is a FAIL a human resolves, not the SA.
`Volumes:` / `Healthchecks:` / `Devices:` are copied from the svc
records' own rows; a volume or device the ticket creates carries
`[NEW: D<n>]`. -->
- Grounded on: <repo-id>:<repo-id>-code @ <revision>
- Service: svc.<name>
- Files:
  - <path exactly as listed in struct.tree>
  - <path> [NEW: D<n>]
- Tables: db.<table>.<column>, … — or `none`
- Routes: api.<tag> — <METHOD> <path>, … — or `none`
- Externals: int.<name>, … — or `none`
- Volumes: svc.<name> — <volume>, …; svc.<name> — none — or `none`
- Healthchecks: svc.<name> — `<test command>`; svc.<name> — none; svc.<name> — disabled — or `none`
- Devices: svc.<name> — <driver:caps>; svc.<name> — none — or `none`
- Verify with: cmd.test — `<primary command, verbatim>`
- Open decisions:
  - none

## Open questions
<!-- Every `OPEN(...)` and every `%%TODO%%` in this ticket must have a
row here, with an owner. -->
- [ ] Q1 — <question> — owner: <who> — blocks: <AC# or section>

## KB context
```yaml
kb-context:
  version: "<hub commit>"
  refs:
    - <repo:doc-id> §<section>
  tags: [ … ]
```

<!-- The two sections below are BA-internal. `kb ticket export <file>`
prints the ticket without them (and without these comments) — that is
what goes into Jira. -->

## Definition of Ready
- [ ] Story, ACs, use cases, business flow present
- [ ] Every citation resolves at the pinned version (kb ticket lint PASS)
- [ ] No stale refs
- [ ] Every AC is Given/When/Then and acceptance-testable; no weasel words remain (docs/ac-quality.md)
- [ ] One user story and at most 10 acceptance criteria — a bigger scope is two tickets
- [ ] Dependencies and Out of scope filled or "N/A — <reason>"; every extended section kept is filled, the rest deleted
- [ ] Every open question has an owner
- [ ] Technical grounding filled by SA; kb ticket check PASS; Open decisions empty; no value in an AC rests on a `DECIDED` note instead of a section id or a D-row

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
