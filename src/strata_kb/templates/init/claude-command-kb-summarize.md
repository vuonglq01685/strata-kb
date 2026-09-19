---
description: Fill pending KB summaries with parallel sub-agents (manual fallback after kb ingest)
argument-hint: "[doc-id]"
---

Invoke the `kb-summarize` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the doc-id filter; when it is
empty, process every document that has pending sections.
