---
name: ba-mission-plan
description: Draft an epic-level Mission Plan (C4 L1/L2 diagrams, scope, US backlog) grounded in the KB with pinned citations, for a large feature that will be split into several tickets. Use when a BA asks to plan a big feature / epic / mission, or invokes /ba-mission-plan.
---

# ba-mission-plan — draft a grounded, epic-level mission plan

You are the ORCHESTRATOR of the mission-planning pipeline: Intake →
Ground → Draft → Split → Ground services → Pin → Lint → Maturity
review → Review. The mission you write is a **draft** — the BA reviews
and commits it. It
sits UPSTREAM of `ba-ticket-author`: each story in the backlog is
drafted later, one at a time, by that skill.

Use a mission for a large feature that spans several User Stories. Small
work goes straight to `/ba-ticket-author` — a mission is not mandatory.

An optional argument gives the business need directly; no argument = ask
for it during Intake.
<!-- strata-kb:include bodies/ba-mission-plan.md -->
