---
description: Answer one technical question about this codebase for the ticket in flight — decision, reasoning, rejected alternatives and path:line / doc §section evidence — or return it as a business question for the BA
argument-hint: "<question>"
---

Invoke the `dev-sa` skill with the Skill tool and follow its workflow
exactly. Pass "$ARGUMENTS" as the question; when empty, ask for it before
continuing. The ticket in flight is the one under `docs/impl/<id>/`.

Pipeline: Read → Gather → Triage → Answer. The agent reads the repo source
freely and uses `kb_search` / `kb_get_section` for the hub's `-code`, `-svc`
and domain documents. It returns the decision, reasoning, rejected
alternatives and evidence as `path:line` / `doc §section` citations, or
`business question: <why>` when the answer would change what an AC means.
It never writes to the hub and never edits the ticket, design, plan or
code: the caller records the result under `## Technical decisions` as
`- SA-<n>: <decision> — why — evidence`.

*Counterpart in the superpowers plugin: none — this agent is strata-kb
specific.*
