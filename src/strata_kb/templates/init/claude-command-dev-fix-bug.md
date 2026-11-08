---
description: Fix a BA bug or hotfix ticket by systematic debugging — reproduce with a failing test, find the root cause, fix once, hand over
argument-hint: "[BUG id, path, or pasted bug]"
---

Invoke the `dev-fix-bug` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the bug when given; when empty, ask
for it during Intake.

Pipeline: Intake → Reproduce → Root cause → Fix → Handover. Iron Law: NO
FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST — no fix without a failing
reproduction test first. Three failed hypotheses stop the flow: question
the architecture with the Dev. This command is also the safe re-entry
point: called again on a bug in progress it derives the state from
`docs/impl/<id>/rootcause.md` and offers the next step rather than redoing
finished phases.

Root cause in another repo: append `## Child bug proposal` to
`rootcause.md`, record a `Split proposal for <BUG-id>:` question on the hub,
run `kb claim update <BUG-id> --stopped "split into child bugs"` and stop;
the BA runs `/ba-bug-report --child-of`. Never create a ticket. Auto mode
ends `AUTO-RESULT: blocked-split BUG-<n>`.

*Counterpart in the superpowers plugin: `superpowers:systematic-debugging`
— same Iron Law and phases, inside the strata-kb flow.*
