---
description: Log a bug or production hotfix as a BA ticket (environment, numbered steps, expected/actual result, screenshots), via the ba-bug-report skill
argument-hint: "[what broke | --child-of BUG-<n>]"
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

After Intake, `/sa-ticket-ground --scope "<symptoms>"` proposes the first
responder repo; the BA accepts or picks another (`> Target repo:`). Bug
numbers are the highest digits-only `BUG-<n>.md` stem plus one.

`--child-of BUG-<n>` turns a bug into a parent bug: it reads the `Split
proposal for BUG-<n>:` question, requires the first responder's claim to be
`stopped` (`split into child bugs`, read with `kb claim list --json`),
sets `> Kind: parent bug`, adds
`## Split` (own row with `Own fix`, one row per child) and writes child
bugs (`- Blocked by:` under `## Dependencies`) with `> Parent bug: <BUG-id> @ rev N+1`. Write files only: never
commit or publish. It answers the question only after every child's Definition of Ready is ticked (the BA ticks them; the lint leaves them unticked), or the children stay off the hub.
