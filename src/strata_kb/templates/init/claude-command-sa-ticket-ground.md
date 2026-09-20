---
description: Fill the SA-owned "Technical grounding" section of a BA ticket (or "Services & order" of a mission plan) from the hub's <repo>-code document, via the sa-ticket-ground skill
argument-hint: "<ticket-or-mission-file> [--mission]"
---

Invoke the `sa-ticket-ground` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the file path, and `--mission`
through when given.

Pipeline: Intake → Load → Fill → Gate → Handover. Hard rules the skill
enforces: every line of `## Technical grounding` points at a section id
that exists in `<repo>-code`, or carries `[NEW: <reason>]`, or goes
under `Open decisions`; no data → `Open decisions`, never inference;
never edit a BA-owned section — a contradiction is quoted there, not
corrected; `Grounded on: <repo-id>:<doc-id> @ <revision>` is the first
line, copied from the hub document's manifest revision; never write
internal flow or failure modes — the document cannot prove them;
`kb ticket check` failing to RUN is not a PASS; never tick a
Definition of Ready checkbox — only the BA confirms DoR.
