---
description: Fill pending KB summaries with parallel sub-agents (manual fallback after kb ingest)
argument-hint: "[doc-id]"
---

Invoke the `kb-summarize` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the doc-id filter; when it is
empty, process every document that has pending sections.

A document whose L3 fidelity check still has unconfirmed findings is
blocked: `kb summarize` skips it (exit 1) and `kb build` errors on it. Do
not summarize it by hand. Report it, point the user to `kb l3 report
<doc-id>`, and let the reviewer run `kb l3 confirm <doc-id> --section <id>
| --all` first. (A `dev` repo has no L3 check: it never runs `kb ingest`.)
