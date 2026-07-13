---
name: kb-summarize
description: Fill pending CENTER-KB summaries — kb status → edit L2/L1 per the writing rules → kb build
---

# /kb-summarize — fill pending summaries

Fill every pending summary in `.kb/` by editing the files directly. The
writing rules in `.cursor/rules/kb-summarize.mdc` apply to all `.kb/**`
edits — follow them exactly.

## Workflow

1. Run `kb status` and list the pending sections. An argument, if given, is
   a doc-id filter — only process that document.
2. For each pending section, read the matching `.raw.md` (L3) source, then:
   - in the L2 `.md` file, replace the
     `<!-- TODO:summarize <section-id> -->` marker with a condensed
     paragraph (never touch the tables);
   - in `_manifest.yaml`, set the section's one-sentence `summary`
     (≤ 25 words) and flip `status: pending` → `status: summarized`.
3. When every section of a doc is summarized, fill the doc's one-sentence
   `summary` in `.kb/index.yaml`.
4. Validate with `kb build` — it must pass. If it reports a table integrity
   error, restore the table verbatim from the `.raw.md` file.
