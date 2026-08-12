# <Mission title — one line, imperative>

<!-- Mission id format: lowercase letters/digits, hyphen-separated, e.g. M-checkout-v2 -->
> Mission: M-<slug>

## Summary
<1–2 lines: what this feature is, at epic level>

## Business goal
<why this exists and how success is measured; every industry-standard
claim cites `doc-id §section`>

## Scope
**In scope:** <what this mission covers>

**Out of scope:** <what it deliberately does not>

## System context (C4 L1)
```mermaid
C4Context
  Person(user, "Role — replace", "…")
  System(sys, "System — replace", "…")
  Rel(user, sys, "…")
```

## Containers (C4 L2)
```mermaid
C4Container
  Container(app, "Container — replace", "…", "…")
  ContainerDb(db, "Database — replace", "…", "…")
  Rel(app, db, "…", "…")
```

<!-- Optional: if you have real component detail, add a "## Components (C4 L3)" section with a C4Component mermaid fence. Never invent components. -->

## Technology decisions
<!-- Every `%%TODO: verify against codebase%%` in the C4 sections has
exactly one row here. A placeholder without an owner means the mission
is not ready, even when lint passes. Status is OPEN or DECIDED. -->
| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | <e.g. storage engine choice> | OPEN | <who> | <US id> |

## Non-functional requirements
<!-- At least one quantified NFR is mandatory when the mission touches
large data volumes, concurrency, or real-time constraints.
Unsettled → `OPEN(<owner>)`, never blank. -->
| Concern | Target | How to measure | Source |
|---|---|---|---|

## Constraints & assumptions
<constraints and any detail that would need code knowledge — mark those
`%%TODO: verify against codebase%%`, never invent them. Questions that
need an answer go to `## Open questions`, not here.>

## US backlog
| US ID | Title |
|---|---|
| M-<slug>-US1 | <story title> |
| M-<slug>-US2 | <story title> |

## Sequencing
<!-- Separate section on purpose: the `## US backlog` header row
'| US ID | Title |' is matched verbatim by lint — never add columns. -->
| US ID | Depends on | Size | Notes |
|---|---|---|---|

## Open questions
<!-- Architecture-changing questions are flagged here and must be
closed BEFORE foundational stories start. -->
- [ ] Q1 — <question> — owner: <who> — impact: <architecture / scope / cost> — blocks: <US id>

## KB context
```yaml
kb-context:
  version: "<hub commit>"
  refs:
    - <repo:doc-id §section>
  tags: [ … ]
```

## Definition of Ready
- [ ] Business goal, scope, L1 + L2 diagrams, backlog present
- [ ] Every citation resolves at the pinned version (kb mission lint PASS)
- [ ] Backlog reviewed with the team; no known missing slice
- [ ] Every `%%TODO%%` has an owned row in Technology decisions
- [ ] Sequencing covers the whole backlog
- [ ] Architecture-impacting open questions closed
