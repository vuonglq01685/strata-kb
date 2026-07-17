---
description: Draft a Dev-ready ticket (story, ACs, use cases, Mermaid diagrams) grounded in the KB with pinned citations, via the ba-ticket-author skill
argument-hint: "[business need]"
---

Invoke the `ba-ticket-author` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the business need when given;
when empty, ask for it during Intake.

Pipeline: Intake → Ground → Draft → Pin → Lint → Review, saved to
`tickets/<ticket-id>.md`. Hard rules the skill enforces: citations are
mandatory for standard claims; pin only BA-confirmed refs via
`kb_context_new`; unverifiable code detail becomes
`%%TODO: verify against codebase%%`, never invented; `kb ticket lint`
must report `DoR: PASS` before handover; never push to Jira — the BA
publishes; never tick a Definition of Ready checkbox yourself — only
the BA confirms DoR items.
