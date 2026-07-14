# CENTER-KB Quickstart (child repo)

This repo AUTHORS knowledge and publishes it to the main hub. It does not
host the company-wide search service — `kb query` / MCP / Web UI read only
the hub's `federation/`.

## Connect the hub (required)

1. **Point at the main hub** — fill `hub:` in `.kb/config.yaml` (a git URL
   or a kb-hub path) and commit it. New content appears in search only after
   `kb publish` and the PR is merged on the hub.
   Optionally also fill `intake:` (the hub's intake service URL) to publish
   from CI via OIDC instead — zero secrets on this repo (see step 4).

## Author and publish

2. **Ingest the first document** — put the PDF in `source/`, then:
   `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"`
   In Claude Code, Copilot Chat, or Cursor, prefer the `/kb-ingest` slash
   command — it asks for the id/tags/revision so you don't have to remember
   flags. (needs the ingest extra: `pip install "center-kb[ingest]"` — or run
   it inside Docker, no local Python needed:
   `docker compose run --rm hub kb ingest source/my-doc.pdf --id my-doc --no-summarize`)
3. **Summarize** — `kb ingest` does this automatically when the Claude Code or
   GitHub Copilot CLI is installed (config: `llm:` in `.kb/index.yaml`).
   Manual fallback: `/kb-summarize` in your assistant, or `kb summarize` later.
   Then validate: `kb build`
4. **Publish** — with `hub:` only, `kb publish` mirrors `.kb/` to the hub and
   opens a PR there directly (in your assistant: `/kb-publish` runs diff →
   confirm → publish). With `intake:` set, `kb publish` instead: commits your
   changes must already be clean, then creates and pushes a `kb-publish/<ts>`
   tag — the `kb-publish.yml` workflow in this repo picks it up, authenticates
   to the intake with a GitHub Actions OIDC token (no `GH_TOKEN` / `KB_HUB_URL`
   secrets needed on this repo), and opens the PR on the hub. Either way,
   merging that PR on the hub makes the content searchable.

## Query (reads the hub)

5. **Query** — `kb query "your question"` (hub from `.kb/config.yaml`), the
   hub's web UI, or MCP. `.mcp.json` (Claude Code) and `.cursor/mcp.json`
   (Cursor) are pre-wired to the hub's HTTP endpoint — set two environment
   variables locally:
   - `CENTER_KB_HUB_URL` — e.g. `http://kb-hub.example.com:8321`
   - `CENTER_KB_HTTP_TOKEN` — the hub token (ask the hub maintainer)

## CLI reference

- `kb init` — scaffold or refresh a KB repo (asks hub|child; updates skills/templates; keeps `.kb/index.yaml`)
- `kb ingest <pdf> --id <id>` — parse a PDF into `.kb/` sections
  (in Claude Code / Copilot Chat / Cursor: `/kb-ingest`)
- `kb summarize` — fill pending summaries via a headless LLM CLI
  (in your assistant: `/kb-summarize`)
- `kb status` — list docs and their pending sections
- `kb build` — validate the KB (manifests, tables, tokens)
- `kb query "<question>"` — hybrid search (keyword + semantic) over the summaries
- `kb get <doc> <section> [--level l2|l3]` — read one section
- `kb stats` — token counts per level
- `kb diff <doc> --against <rev>` — changed sections vs a git rev
- `kb publish` — mirror `.kb/` to the federation hub (hub from
  `.kb/config.yaml` or `--hub`); opens a PR on the hub by default
  (in your assistant: `/kb-publish` runs diff → confirm → publish)
- `kb resolve <file>` — resolve a kb-context block and check freshness
- `kb doctor` — sanity-check the setup
