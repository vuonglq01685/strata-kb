---
applyTo: ".kb/**"
---

# Strata summarize instructions

Files under `.kb/` belong to a Strata knowledge base. When editing them
to fill in summaries (after `kb ingest`), follow these rules exactly.

## What to edit

- In `.kb/<doc-id>/<file>.md` (L2): replace each
  `<!-- TODO:summarize <section-id> -->` marker with a condensed paragraph,
  except sections the engine fills (`[no LLM needed: …]`) — leave those
  markers alone. Never touch the markdown tables — they are verbatim copies.
- In `.kb/<doc-id>/_manifest.yaml` (L1): set `summary` (one sentence,
  ≤ 25 words) per section and flip `status: pending` → `status: summarized`.
- In `.kb/index.yaml`: when every section of a doc is summarized, fill the
  doc's one-sentence `summary`.
- Nothing else. `.raw.md` files (L3) are read-only source text.

## How to write a summary

Never read the `.raw.md` file to write a summary. Run
`kb summarize <doc-id> --print-prompt` (add `--section <id>` to narrow):
it prints, per pending section, the exact prompt the `kb summarize`
engine sends — tables already removed, a `HARD LIMIT: l2_summary must be
at most N characters` line and the JSON contract. Answer that prompt and
nothing else; keep `l2_summary` at or under that `HARD LIMIT` and
`l1_summary` at or under 25 words. Sections marked `[no LLM needed: …]`
are filled by `kb summarize <doc-id>` deterministically — leave their
markers alone and run that command.

## Validate

After editing, run `kb build --strict` — it must pass (use
`kb build --allow-pending --strict` for a partial run, while sections
are still pending). A table integrity error means a table was modified:
restore it verbatim from the `.raw.md` file. A `(quality)` error names
the rule the summary broke — rewrite that section from its printed
prompt.

## CLI reference

- `kb init` — scaffold or refresh a KB repo (updates skills/templates; keeps `.kb/index.yaml`)
- `kb ingest <pdf> --id <id>` — parse a PDF into `.kb/` sections
  (prefer the `/kb-ingest` prompt in Copilot Chat)
- `kb summarize` — fill pending summaries via a headless LLM CLI
- `kb summarize <doc> --print-prompt` — print the engine's exact prompt for each pending section
- `kb status` — list docs and their pending sections
- `kb build` — validate the KB (manifests, tables, tokens)
- `kb build --strict` — validate the KB and treat quality findings as errors
- `kb query "<question>"` — hybrid search (keyword + semantic) over the summaries
- `kb get <doc> <section> [--level l2|l3]` — read one section
- `kb stats` — token counts per level
- `kb diff <doc> --against <rev>` — changed sections vs a git rev
- `kb publish` — mirror .kb/ (L0→L3) to the federation hub and open a PR
  (prefer the `/kb-publish` prompt in Copilot Chat) — the PR is the review gate
- `kb resolve <file>` — resolve a kb-context block and check freshness
- `kb tags` — list every tag published on the hub federation
- `kb doctor` — sanity-check the setup
