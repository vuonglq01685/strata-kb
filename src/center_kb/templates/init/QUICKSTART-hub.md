# CENTER-KB Quickstart (main hub)

This repo IS the hub: it hosts `federation/` (the single source of truth for
search) and runs the shared HTTP MCP server + Web UI. Child repos publish
into it; merging their PRs here is the review gate.

1. **Configure the token** — run `kb docker-setup` (in Claude Code / Copilot
   Chat / Cursor: `/kb-docker-setup`). It creates `.env` and generates
   `CENTER_KB_HTTP_TOKEN`. The token is auto-generated for convenience —
   replace it with your own secret for real deployments. Manual fallback:
   `cp .env.example .env`, then edit the token yourself.
2. **Serve the hub** — `docker compose up -d` → web UI at
   http://localhost:8321/ui (sign in with the token).
   Without Docker: `python -m center_kb.mcp --hub . --transport http`
   (requires the `CENTER_KB_HTTP_TOKEN` env var).
3. **Ingest this repo's own documents (optional)** — the hub may keep its own
   `.kb/`: put the PDF in `source/`, then
   `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"`
   (prefer the `/kb-ingest` slash command; or run inside Docker:
   `docker compose run --rm hub kb ingest source/my-doc.pdf --id my-doc`)
   Summaries: automatic with a local LLM CLI, or `/kb-summarize`; validate
   with `kb build`; then `kb publish` mirrors into `federation/<repo-id>/`.
4. **Query** — `kb query "your question"`, the web UI, or MCP. The local
   `.mcp.json` / `.cursor/mcp.json` run the stdio server for the hub
   maintainer; remote clients (child repos, BA machines) use the HTTP
   endpoint instead:
   `http://<host>:8321/mcp` with header `Authorization: Bearer <token>`.

## CLI reference

- `kb init` — scaffold or refresh a KB repo (asks hub|child; updates skills/templates; keeps `.kb/index.yaml`)
- `kb docker-setup` — hub only: create `.env` + generate the HTTP token
  (in your assistant: `/kb-docker-setup`)
- `kb ingest <pdf> --id <id>` — parse a PDF into `.kb/` sections
  (in Claude Code / Copilot Chat / Cursor: `/kb-ingest`)
- `kb summarize` — fill pending summaries via a headless LLM CLI
  (in your assistant: `/kb-summarize`)
- `kb status` — list docs and their pending sections
- `kb build` — validate the KB (manifests, tables, tokens)
- `kb query "<question>"` — BM25 search over the summaries
- `kb get <doc> <section> [--level l2|l3]` — read one section
- `kb stats` — token counts per level
- `kb diff <doc> --against <rev>` — changed sections vs a git rev
- `kb publish` — mirror `.kb/` to the federation hub (hub from
  `.kb/config.yaml` or `--hub`); opens a PR on the hub by default
  (in your assistant: `/kb-publish` runs diff → confirm → publish)
- `kb resolve <file>` — resolve a kb-context block and check freshness
- `kb doctor` — sanity-check the setup
