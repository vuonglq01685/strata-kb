---
applyTo: ".kb/**"
---

# CENTER-KB summarize instructions

Files under `.kb/` belong to a CENTER-KB knowledge base. When editing them
to fill in summaries (after `kb ingest`), follow these rules exactly.

## What to edit

- In `.kb/<doc-id>/<file>.md` (L2): replace each
  `<!-- TODO:summarize <section-id> -->` marker with a condensed paragraph.
  Never touch the markdown tables — they are verbatim copies.
- In `.kb/<doc-id>/_manifest.yaml` (L1): set `summary` (one sentence,
  ≤ 25 words) per section and flip `status: pending` → `status: summarized`.
- In `.kb/index.yaml`: when every section of a doc is summarized, fill the
  doc's one-sentence `summary`.
- Nothing else. `.raw.md` files (L3) are read-only source text.

## Writing rules (mandatory)

- Write every summary in the **same language as the source text** in the
  matching `.raw.md` (L3) file — never translate. English source → English
  summary; Vietnamese source → Vietnamese summary. The only exception is the
  fixed `Table-only section: <title>.` label below, which stays in English so
  that it matches what `kb summarize` writes for the same case.
- Summarize the prose ONLY. Never describe, list, or reconstruct table
  contents — the tables are already copied verbatim into the section.
- If a section has no prose (heading + tables only): delete the marker
  line (leave nothing) and set the manifest `summary` to
  `Table-only section: <title>.` — do NOT invent prose about the tables.
- Keep the L2 paragraph under ~35% of the original prose length. If your
  draft is longer, compress harder.
- L2 paragraph: ~20–30% of the original length, keep the logical structure.
- Preserve VERBATIM: codes (P, R, D...), record/field names (UR, PA...),
  numeric values, units, cross-references (§x.y). Never paraphrase
  technical terms.
- Do NOT infer beyond the source text. When unsure, keep the original
  sentence.
- Do NOT summarize, create, or delete tables.

## Validate

After editing, run `kb build` — it must pass. If it reports a table
integrity error, restore the table verbatim from the `.raw.md` file.

## CLI reference

- `kb init` — scaffold or refresh a KB repo (updates skills/templates; keeps `.kb/index.yaml`)
- `kb ingest <pdf> --id <id>` — parse a PDF into `.kb/` sections
  (prefer the `/kb-ingest` prompt in Copilot Chat)
- `kb summarize` — fill pending summaries via a headless LLM CLI
- `kb status` — list docs and their pending sections
- `kb build` — validate the KB (manifests, tables, tokens)
- `kb query "<question>"` — BM25 search over the summaries
- `kb get <doc> <section> [--level l2|l3]` — read one section
- `kb stats` — token counts per level
- `kb diff <doc> --against <rev>` — changed sections vs a git rev
- `kb publish` — mirror .kb/ (L0→L3) to the federation hub and open a PR
  (prefer the `/kb-publish` prompt in Copilot Chat) — the PR is the review gate
- `kb resolve <file>` — resolve a kb-context block and check freshness
- `kb doctor` — sanity-check the setup
