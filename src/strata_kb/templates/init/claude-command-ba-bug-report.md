---
description: Log a bug or production hotfix as a BA ticket (environment, numbered steps, expected/actual result, screenshots), via the ba-bug-report skill
argument-hint: "[what broke]"
---

Invoke the `ba-bug-report` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as what broke when given; when empty,
ask for it during Intake.

Pipeline: Intake → Related ticket → Draft → Ground → Lint → Hand over. The
bug is drafted from `docs/tickets/BUG-TEMPLATE.md` into
`tickets/bugs/BUG-<n>.md` (screenshots, PNG or WebP, in
`tickets/bugs/BUG-<n>/`) and linted until `kb_ticket_lint` (CLI
`kb ticket lint`) reports `DoR: PASS`. The BA reviews and commits it;
`kb publish` ships it to the hub.

Never invent steps, values or error text: a missing fact is
`OPEN(<owner>)` plus an `## Open questions` row. One bug per ticket. Never
edit a done story to describe a bug. A bug has no `> Parent mission:` line.
