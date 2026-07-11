---
name: kb-summarize
description: Fill pending L0/L1/L2 summaries in .kb/ after `kb ingest`. Use when asked to summarize the KB or fill summaries, or right after ingesting a new document when auto-summarize was skipped or failed.
---

# KB Summarize — fill knowledge into the .kb/ scaffold

You are the "LLM half" of the CENTER-KB pipeline. `kb ingest` generated the
scaffold; your job is to fill in the summaries. Do NOT edit anything outside
the locations listed below.

Note: `kb ingest` normally does this automatically by calling a headless LLM
CLI (`kb summarize`). Use this manual workflow when auto-summarize was
disabled (`--no-summarize`, `runner: none`), no LLM CLI was available, or
some sections failed and you want to fix them by hand.

## Workflow

1. Run `kb status` — list the pending sections (doc, section id, file).
2. For EACH pending section:
   a. Read the original text: `kb get <doc-id> <section-id> --level l3`
   b. Open the L2 file (`.kb/<doc-id>/<file>.md`) and find the marker
      `<!-- TODO:summarize <section-id> -->` inside that section.
   c. Replace the marker with a condensed paragraph (see Writing rules).
      Do NOT touch the markdown tables already present in the section —
      the tooling copies them verbatim.
   d. Open `.kb/<doc-id>/_manifest.yaml`, fill `summary` (one sentence,
      ≤ 25 words) for that section and change `status: pending` →
      `status: summarized`.
3. When every section of a doc is done: open `.kb/index.yaml`, fill or fix
   that doc's `summary` (one sentence) and verify its `title`, `revision`
   and `tags`.
4. Run `kb build` — it must PASS. If it fails on table integrity you have
   edited a table; restore it verbatim from the `.raw.md` file.
5. Report: number of sections filled, total L2 tokens (see `kb stats`).

## Writing rules (mandatory)

- Write in **English**.
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

## Work in batches

Fill sections one at a time; every 5–10 sections re-run
`kb build --allow-pending` to catch mistakes early. Do not edit many files
in parallel.
