---
description: Draft a Dev-ready ticket (story, ACs, use cases, Mermaid diagrams) grounded in the KB with pinned citations, via the ba-ticket-author skill
argument-hint: "[business need]"
---

Invoke the `ba-ticket-author` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the business need when given;
when empty, ask for it during Intake.

Pipeline: Intake → Parent mission → Ground → Draft → Pin → Lint → Review,
saved to `tickets/<ticket-id>.md` — or `tickets/<mission-id>-US<n>.md`
when the ticket has a parent mission, so the back-link check can find it.
When the BA names a parent mission, read it for the story title, put
`> Parent mission: <mission-id>` on its own line directly under the
ticket's H1 title, and inherit its pinned refs as STARTING CANDIDATES
ONLY — never copy its `kb-context` wholesale; pin the ticket's own refs
fresh. Hard rules the skill enforces: citations are mandatory
for standard claims; present ALL `kb_search` candidates and let the BA
choose — mandatory when the ambiguity note fires, never auto-pick; pin
only BA-confirmed refs via `kb_context_new`;
unverifiable code detail becomes `%%TODO: verify against codebase%%`,
never invented; `kb ticket lint` must report `DoR: PASS` before handover;
never push to Jira — the BA publishes; never tick a Definition of Ready
checkbox yourself — only the BA confirms DoR items.
