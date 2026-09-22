---
description: Fill the SA-owned "Technical grounding" section of a BA ticket (or "Services & order" of a mission plan) from the hub's <repo>-code document, via the sa-ticket-ground skill
argument-hint: "<ticket-or-mission-file> [--mission]"
---

Invoke the `sa-ticket-ground` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the file path, and `--mission`
through when given.

Pipeline: Intake → Load → Fill → Gate → Handover. Hard rules the skill
enforces: every line of the SA-owned section (`## Technical grounding`,
or `## Services & order` with `--mission`) points at a section id that
exists in `<repo>-code`, or carries `[NEW: D<n>]` naming a DECIDED row
of the parent mission's `## Technology decisions` (`[NEW: <reason>]`
only when there is no parent mission), or goes under `Open decisions`;
a thing the code does not have yet is a design decision, not missing
data — propose it as a `## Technology decisions` row (status OPEN, a
human owner), never park "not built yet" under `Open decisions`; you
may APPEND rows to that table and never edit, delete or re-status an
existing one — only a human flips OPEN to DECIDED; code that exists and
the document cannot prove → `Open decisions`, never inference;
never edit a BA-owned section — a contradiction is quoted there, not
corrected; `Grounded on: <repo-id>:<doc-id> @ <revision>` is the first
line, copied from the hub document's manifest revision; never write
internal flow or failure modes — the document cannot prove them; the
gate is `kb ticket check <file> [--missions-dir <dir>]`, or
`kb ticket check --heading "## Services & order" <file>` for a mission,
and failing to RUN is not a PASS; the handover ends with the fixed
`## Needs input` block naming every decision still waiting for a human;
never tick a Definition of Ready checkbox — only the BA confirms DoR.
