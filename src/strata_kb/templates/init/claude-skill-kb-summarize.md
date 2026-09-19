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

An optional argument narrows the run to one document id. `--print-prompt`
(step 2) always requires a document id, though — with no argument, loop
step 2 once per pending document listed in step 1.

The engine and this workflow send the model the SAME prompt: you never
read L3 yourself and never restate the writing rules — `kb summarize
<doc-id> --print-prompt` prints, per pending section, the exact prompt
the engine would send (tables already removed, a `HARD LIMIT: l2_summary
must be at most N characters` line, the JSON contract). Sections that
need no LLM (table-only or brief prose) are marked `[no LLM needed: …]`
— leave them to `kb summarize`, which fills them deterministically.

## Workflow

1. **Collect** — run `kb status`; list the pending sections as
   (doc-id, section-id, L2 file). Filter by the doc-id argument if given.
   Nothing pending → report that and stop.
2. **Print prompts** — for each pending document from step 1 (one call
   per document — `--print-prompt` requires a document id), run
   `kb summarize <doc-id> --print-prompt` (add `--section <id>` to narrow
   further). Keep each `=== <doc-id>/<id> ===` block with its
   `HARD LIMIT … at most N characters` line; skip the
   `[no LLM needed: …]` blocks.
3. **Partition** — group the printed prompts into batches of ~5,
   preferring sections that share the same L2 file. Schedule waves of at
   most 10 batches (= at most 10 concurrent sub-agents).
4. **Dispatch** — spawn ALL sub-agents of the wave in a single message so
   they run concurrently. Each sub-agent prompt MUST contain:
   - the printed prompt blocks for its sections, verbatim;
   - an override: each printed prompt individually ends by asking for a
     single JSON object (`{"l2_summary": "...", "l1_summary": "..."}`) —
     that per-block instruction is superseded by the batch-level output
     contract below;
   - the output contract: reply with ONLY a JSON array, one element per
     assigned section, adding `section_id` to each —
     `[{"section_id": "...", "l2_summary": "...", "l1_summary": "..."}, ...]`;
   - the hard restriction: the sub-agent is READ-ONLY — it must not
     write, edit, or create any file, and must not run `kb get`.
5. **Merge** — you apply the results yourself, sequentially, never in
   parallel. For each returned section:
   a. Validate: every assigned section present; `l1_summary` ≤ 25 words;
      `len(l2_summary)` ≤ the `HARD LIMIT` printed in that section's
      prompt (count characters, not words).
   b. In the L2 file, replace the marker line
      `<!-- TODO:summarize <section-id> -->` with the l2_summary
      paragraph. Do NOT touch the markdown tables or `Figure:` lines
      already present in the section — the tooling copies them verbatim.
   c. In `.kb/<doc-id>/_manifest.yaml`, set that section's `summary:` to
      the l1_summary and change `status: pending` → `status: summarized`.
6. **Verify the wave** — run `kb build --allow-pending --strict`; it must
   pass. A table-integrity error means a table was modified: restore it
   verbatim from the `.raw.md` file. A `(quality)` error names the rule
   the summary broke (ratio, invented code, table transcription, lexical
   overlap): redo that section yourself, sequentially — one retry only.
   Then continue with the next wave (repeat steps 4–6).
7. **Fill the rest** — run `kb summarize <doc-id>` (unlike `--print-prompt`,
   this doc-id is optional — omit it to cover every pending document) so
   the engine fills the `[no LLM needed: …]` sections (no LLM CLI is
   required for those).
8. **Finalize** — when every section of a doc is done: open
   `.kb/index.yaml`, fill or fix that doc's `summary` (one sentence,
   max 30 words, same language as the section summaries) and verify
   its `title`, `revision` and `tags`. Run `kb build --strict` — it
   must PASS. Report: sections filled, sections still pending (with
   reasons), total L2 tokens (see `kb stats`).

## Error handling

- A sub-agent reply that fails validation (broken JSON, missing section,
  over-length summary) → do NOT respawn an agent. Summarize the failed
  section yourself, sequentially, from its printed prompt — one retry only.
- A section that still fails → leave it `status: pending` and list it in
  the final report.
- Never end a wave with a failing `kb build --allow-pending --strict`.
