---
description: Answer the Dev side's open questions about this repo's tickets; amend the ticket when an answer changes behaviour, then record the answers on the hub, via the ba-answer-questions skill
argument-hint: "[ticket]"
---

Invoke the `ba-answer-questions` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the ticket to restrict to when given;
when empty, walk every ticket with an open question.

**Hub access — MCP first.** The question tools `kb_question_list` and
`kb_question_answer` (MCP server `strata-kb`) have no CLI twin, so MCP is
required; they work only against the shared hub server. Any other MCP
target answers `Q&A needs the shared hub server — point MCP at it (kb
mcp-setup)`: stop, repeat it to the BA, change and record nothing.

Pipeline: List → Walk → Answer → Record → Report. List: `kb_question_list`
for this repo's `repo_id`, status `open`; none → say so and stop. Walk: one
ticket at a time, each question beside the local ticket. Answer: the BA's
words only; when an answer changes behaviour, amend the ticket under
`ba-ticket-author`'s amend rules, one amendment per ticket — `> Revision:`
N+1, one change-log row with Trigger `question`, What changed `Q<ids>: …`,
Affected = the changed sections, one maturity round, `kb_ticket_lint` (CLI
`kb ticket lint`) to PASS — and do not record any answer for a ticket whose
Definition of Ready is not fully ticked (show the unticked boxes, the BA
re-ticks). Record: `kb_question_answer` per question with `answer_rev` = N+1
and `ticket_sections` = Affected, or `answer_rev` None and `[]` when the
ticket did not change. Report: `Q<id> → answered (rev N+1: sections …)`,
remind the BA to commit and merge the ticket change as usual (the hub shows
the answers as waiting for publish until it lands), and give the hub Q&A
link to paste in chat. The agent never commits, pushes or publishes.

End every response with `## Next step` (an ordered list, option 1 is the
next step in flow) and a `State:` line: `State: questions <n>/<m> answered ·
tickets amended <n> · publish <✅ on the hub|⬜ waiting for commit and
merge|n/a (no ticket changed)>`.
