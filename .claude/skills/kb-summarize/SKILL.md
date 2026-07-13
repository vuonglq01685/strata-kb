---
name: kb-summarize
description: Fill pending L0/L1/L2 summaries in .kb/ after `kb ingest`. Use when asked to summarize the KB or fill summaries, when the user invokes /kb-summarize, or right after ingesting a new document when auto-summarize was skipped or failed.
---

# KB Summarize — parallel fill of the .kb/ scaffold

You are the ORCHESTRATOR of the manual summarize pipeline. `kb ingest`
generated the scaffold; read-only sub-agents draft the summaries in
parallel; you are the ONLY writer that touches files.

Note: `kb ingest` normally does this automatically by calling a headless
LLM CLI (`kb summarize`). Use this manual workflow when auto-summarize was
disabled (`--no-summarize`, `runner: none`), no LLM CLI was available, or
some sections failed and you want to fix them.

An optional argument narrows the run to one document id; no argument =
every document with pending sections.

## Workflow

1. **Collect** — run `kb status`; list the pending sections as
   (doc-id, section-id, L2 file). Filter by the doc-id argument if given.
   Nothing pending → report that and stop.
2. **Partition** — group the sections into batches of ~5, preferring
   sections that share the same L2 file. Schedule waves of at most 10
   batches (= at most 10 concurrent sub-agents).
3. **Dispatch** — spawn ALL sub-agents of the wave in a single message so
   they run concurrently. Each sub-agent prompt MUST contain:
   - the list of assigned sections: doc-id, section-id, title;
   - the command to read each source:
     `kb get <doc-id> <section-id> --level l3`;
   - the full "Writing rules" block below, copied verbatim;
   - the output contract: reply with ONLY a JSON array —
     `[{"section_id": "...", "l2_summary": "...", "l1_summary": "...", "table_only": false}, ...]`
     For a section with no prose (heading + tables only) set
     `"table_only": true`, `"l2_summary": ""` and
     `"l1_summary": "Table-only section: <title>."`;
   - the hard restriction: the sub-agent is READ-ONLY — it must not
     write, edit, or create any file.
4. **Merge** — you apply the results yourself, sequentially, never in
   parallel. For each returned section:
   a. Validate: every assigned section present; `l1_summary` ≤ 25 words;
      `l2_summary` non-empty unless `table_only`.
   b. In the L2 file, replace the marker line
      `<!-- TODO:summarize <section-id> -->` with the l2_summary
      paragraph — or delete the marker line (leave nothing) when
      `table_only`. Do NOT touch the markdown tables already present in
      the section — the tooling copies them verbatim.
   c. In `.kb/<doc-id>/_manifest.yaml`, set that section's `summary:` to
      the l1_summary and change `status: pending` → `status: summarized`.
5. **Verify the wave** — run `kb build --allow-pending`; it must pass.
   If it fails on table integrity a table was modified: restore it
   verbatim from the `.raw.md` file and build again. Then continue with
   the next wave (repeat steps 3–5).
6. **Finalize** — when every section of a doc is done: open
   `.kb/index.yaml`, fill or fix that doc's `summary` (one sentence) and
   verify its `title`, `revision` and `tags`. Run `kb build` (strict) —
   it must PASS. Report: sections filled, sections still pending (with
   reasons), total L2 tokens (see `kb stats`).

## Error handling

- A sub-agent reply that fails validation (broken JSON, missing section,
  over-length summary) → do NOT respawn an agent. Summarize the failed
  section yourself, sequentially: read its L3 and apply the Writing
  rules — one retry only.
- A section that still fails → leave it `status: pending` and list it in
  the final report.
- Never end a wave with a failing `kb build --allow-pending`.

## Writing rules (mandatory — copy verbatim into every sub-agent prompt)

- Write both summaries in the **same language as the source text** you read
  with `kb get ... --level l3` — never translate. English source → English
  summary; Vietnamese source → Vietnamese summary. The only exception is the
  fixed `Table-only section: <title>.` label below, which stays in English so
  that it matches what `kb summarize` writes for the same case.
- Summarize the prose ONLY. Never describe, list, or reconstruct table
  contents — the tables are already copied verbatim into the section.
- If a section has no prose (heading + tables only): report it as
  table-only — set `"table_only": true` and the l1_summary to
  `Table-only section: <title>.` — do NOT invent prose about the tables.
- Keep the L2 paragraph under ~35% of the original prose length. If your
  draft is longer, compress harder.
- L2 paragraph: condense the prose to ~20–30% of the original length and
  keep the logical structure.
- Preserve VERBATIM: codes (P, R, D...), record/field names (UR, PA...),
  numeric values, units, cross-references (§x.y). Never paraphrase
  technical terms.
- Do NOT infer beyond the source text. When unsure, keep the original
  sentence.
- Do NOT summarize tables, create new tables, or delete tables.
- L1 summary (manifest): one sentence ≤ 25 words stating what the section
  covers and what kind of data it contains (so BM25 matches technical
  keywords).
