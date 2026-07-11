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

- Write in English.
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
