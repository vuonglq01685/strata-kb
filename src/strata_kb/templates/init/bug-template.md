# BUG-<n> — <one-line symptom>
> Type: bug
> Severity: S2
> Revision: 1
> Related ticket: none

<!-- Header lines. `> Type:` is `bug`, or `hotfix` for a fix that ships
ahead of the next planned release, from the production line. `> Severity:`
is S1-S4:

| Sev | Meaning |
|---|---|
| S1 | Production down, data loss or security exposure; no workaround |
| S2 | A core function is broken; workaround painful or none |
| S3 | A function misbehaves; a reasonable workaround exists |
| S4 | Cosmetic / wording / layout |

`> Related ticket:` is the ticket id this bug was found in (for example
`M-billing-US3`), or `none`. A bug has no `> Parent mission:` line.
Id = file stem `BUG-<n>`; file `tickets/bugs/BUG-<n>.md`; images in
`tickets/bugs/BUG-<n>/`. Gate: `kb ticket lint` must report `DoR: PASS`. -->

## Summary
<1–2 lines: what is broken and for whom>

## Environment
<!-- Environment (production / staging / ...), app version or build,
device / browser / OS, account or role, when first seen. -->
<environment, version, device, role, first seen>

## Pre-conditions
<!-- The state that must hold before step 1: data, flags, logged-in role. -->
<state before step 1>

## Steps to reproduce
<!-- A numbered list; at least one step. -->
1. <step>
2. <step>

## Expected result
<!-- Concrete values. Cite `[doc-id §section]` when the expectation comes
from a standard or an AC. -->
<what should happen>

## Actual result
<!-- What happens, with concrete values. Quote error text verbatim. -->
<what happens instead>

## Attachments
<!-- PNG or WebP only, inside this bug's own folder: relative path
`BUG-<n>/<file>.png`. No absolute paths, no `..`, no http(s) images.
No screenshot to add -> `N/A — <reason>`. -->
![<caption>](BUG-<n>/<file>.png)

## Impact
<!-- Who and how many are hit, how often, and the workaround if any. -->
<who is hit, how often, workaround>

## Open questions
<!-- Every `OPEN(...)` and every `%%TODO%%` in this ticket must have a
row here, with an owner. -->
- [ ] Q1 — <question> — owner: <who> — blocks: <section>

<!-- Optional sections, validated only when present: `## KB context` (same
block as a story), `## Technical grounding` (SA-owned, `kb ticket check`),
`## Change log` (below). -->

<!-- The sections below are BA-internal. -->

## Definition of Ready
- [ ] Steps reproduce the actual result on the stated environment
- [ ] Expected and actual result stated with concrete values
- [ ] Attachments added, or `N/A — <reason>`
- [ ] Severity set; related ticket linked or `none`
- [ ] Every open question has an owner

## Change log
<!-- Append-only: one row per revision >= 2, in order; bump `> Revision:` under
the title in the same edit. Trigger is one or more of kb-context,
architecture, scope, delivery (comma-separated). Affected is section names, or `-`.
Review holds the amendment's maturity scores, e.g. `B4 D4 (agent)`;
amendments are not recorded in Review record. -->
| Rev | Date | Trigger | What changed | Affected | Review |
|---|---|---|---|---|---|
|   |   |   |   |   |   |
