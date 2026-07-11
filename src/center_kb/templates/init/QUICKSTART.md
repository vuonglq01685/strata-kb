# CENTER-KB Quickstart

Five steps from empty repo to a searchable knowledge base.

1. **Configure the token** — `cp .env.example .env`, then edit
   `CENTER_KB_HTTP_TOKEN` (any long random string).
2. **Ingest the first document** — put the PDF in `source/`, then:
   `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"`
   (needs the ingest extra: `pip install "center-kb[ingest]"` — or run it
   inside Docker: `docker compose run --rm hub kb ingest source/my-doc.pdf --id my-doc`)
3. **Summarize** — open Claude Code in this repo and run the `kb-summarize`
   skill for the pending sections, then validate: `kb build`
4. **Serve the hub** — `docker compose up -d` → web UI at
   http://localhost:8321/ui (sign in with the token).
   Without Docker: `python -m center_kb.mcp --hub . --transport http`
   (requires the `CENTER_KB_HTTP_TOKEN` env var).
5. **Query** — `kb query "your question"`, the web UI, or point Claude Code
   at `.mcp.json` (MCP over stdio) / the HTTP endpoint.
