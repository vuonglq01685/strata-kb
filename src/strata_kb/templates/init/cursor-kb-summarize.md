---
name: kb-summarize
description: Fill pending CENTER-KB summaries — kb status → --print-prompt → edit L2/L1 → kb build --strict
---

# /kb-summarize — fill pending summaries

Fill every pending summary in `.kb/` by editing the files directly. The
`.cursor/rules/kb-summarize.mdc` file's "How to write a summary" and
"Validate" sections apply to all `.kb/**` edits — follow them exactly.

## Workflow

1. Run `kb status` and list the pending sections. An argument, if given, is
   a doc-id filter — only process that document.
2. For each pending document (from step 1; `--print-prompt` requires a
   document id, so with no argument repeat this step once per document),
   run `kb summarize <doc-id> --print-prompt` and, for each printed
   prompt, write the two summaries it asks for (respecting its
   `HARD LIMIT` on `l2_summary`), then:
   - in the L2 `.md` file, replace the
     `<!-- TODO:summarize <section-id> -->` marker with the l2_summary
     paragraph (never touch the tables);
   - in `_manifest.yaml`, set the section's `summary` to the l1_summary
     (≤ 25 words) and flip `status: pending` → `status: summarized`.
3. When every section of a doc is summarized, fill the doc's one-sentence
   `summary` in `.kb/index.yaml`.
4. Run `kb summarize <doc-id>` (this doc-id is optional — omit it to
   cover every pending document) to fill the `[no LLM needed: …]`
   sections.
5. Validate with `kb build --strict` — it must pass (use
   `kb build --allow-pending --strict` for a partial run, while sections
   are still pending). If it reports a table integrity error, restore
   the table verbatim from the `.raw.md` file. A `(quality)` error names
   the rule the summary broke — rewrite that section from its printed
   prompt.
