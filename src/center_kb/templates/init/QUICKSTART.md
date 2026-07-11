# CENTER-KB Quickstart

Five steps from empty repo to a searchable knowledge base.

1. **Configure the token** — `cp .env.example .env`, then edit
   `CENTER_KB_HTTP_TOKEN` (any long random string).
2. **Ingest the first document** — put the PDF in `source/`, then:
   `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"`
   In Claude Code or Copilot Chat, prefer the `/kb-ingest` slash command —
   it asks for the id/tags/revision so you don't have to remember flags.
   (needs the ingest extra: `pip install "center-kb[ingest]"` — or run it
   inside Docker: `docker compose run --rm hub kb ingest source/my-doc.pdf --id my-doc`)
3. **Summarize** — `kb ingest` does this automatically when the Claude Code or
   GitHub Copilot CLI is installed (config: `llm:` in `.kb/index.yaml`).
   Manual fallback: run the `kb-summarize` skill in Claude Code, or
   `kb summarize` later. Then validate: `kb build`
4. **Serve the hub** — `docker compose up -d` → web UI at
   http://localhost:8321/ui (sign in with the token).
   Without Docker: `python -m center_kb.mcp --hub . --transport http`
   (requires the `CENTER_KB_HTTP_TOKEN` env var).
5. **Query** — `kb query "your question"`, the web UI, or point Claude Code
   at `.mcp.json` (MCP over stdio) / the HTTP endpoint.

## CLI reference

- `kb init` — scaffold a KB repo (this skeleton)
- `kb ingest <pdf> --id <id>` — parse a PDF into `.kb/` sections
  (in Claude Code / Copilot Chat: `/kb-ingest`)
- `kb summarize` — fill pending summaries via a headless LLM CLI
- `kb status` — list docs and their pending sections
- `kb build` — validate the KB (manifests, tables, tokens)
- `kb query "<question>"` — BM25 search over the summaries
- `kb get <doc> <section> [--level l2|l3]` — read one section
- `kb stats` — token counts per level
- `kb diff <doc> --against <rev>` — changed sections vs a git rev
- `kb approve <doc> --section <id>` — mark sections reviewed
  (in Claude Code / Copilot Chat: `/kb-publish` runs diff → approve → publish)
- `kb publish --hub <hub>` — push the L0+L1 snapshot to the federation hub
- `kb resolve <file>` — resolve a kb-context block and check freshness
- `kb doctor` — sanity-check the setup
