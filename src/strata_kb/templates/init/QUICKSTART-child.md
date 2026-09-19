# Strata Quickstart (child repo)

This repo AUTHORS knowledge and publishes it to the main hub. It does not
host the company-wide search service — `kb query` / MCP / Web UI read only
the hub's `federation/`.

## Connect the hub (required)

1. **Point at the main hub** — fill `hub:` in `.kb/config.yaml` (a git URL
   or a kb-hub path) and commit it. New content appears in search only after
   `kb publish` and the PR is merged on the hub.
   Optionally also fill `intake:` (the hub's intake service URL) to publish
   from CI via OIDC instead — zero secrets on this repo (see step 5).
   **Warning:** `repo_id:` in this file must exactly match the id this repo
   is registered under in the hub's `federation/registry.yaml`. `kb publish`
   refuses a mismatch before anything is written, naming both ids. Over the
   `intake:` path it still succeeds and the PR opens, but the dev CLI will
   time out waiting for a PR that actually opened, and uploads lose
   incrementality (every publish becomes a full upload).

## Author and publish

2. **Pull the ingest image (optional but recommended)** — run
   `kb docker-setup` (in your assistant: `/kb-docker-setup`). It checks
   Docker and pulls the Strata image so ingest runs fully inside Docker —
   no local Python needed. Skip it if you install the ingest extra locally
   instead (`pip install "strata-kb[ingest]"`). Without Docker installed,
   pass `--no-docker` to just print the commands.
3. **Ingest the first document** — put the PDF in `source/`, then:
   `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"`
   In Claude Code, Copilot Chat, or Cursor, prefer the `/kb-ingest` slash
   command — it asks for the id/tags/revision so you don't have to remember
   flags. (needs the ingest extra: `pip install "strata-kb[ingest]"` — or run
   it inside Docker, no local Python needed:
   `docker compose run --rm hub kb ingest source/my-doc.pdf --id my-doc --no-summarize`)
4. **Summarize** — `kb ingest` does this automatically when the Claude Code or
   GitHub Copilot CLI is installed (config: `llm:` in `.kb/index.yaml`).
   Manual fallback: `/kb-summarize` in your assistant, or `kb summarize` later.
   Then validate: `kb build`
   After checking the summaries, mark them reviewed:
   `kb approve <doc-id>` (in your assistant: `/kb-approve`).
5. **Publish** — with `hub:` only, `kb publish` mirrors `.kb/` to the hub and
   opens a PR there directly (in your assistant: `/kb-publish` runs diff →
   confirm → publish). With `intake:` set, `kb publish` requires a clean
   committed `.kb/`, then tags and pushes a `kb-publish/<ts>` tag — the
   `kb-publish.yml` workflow in this repo picks it up, authenticates to the
   intake with a GitHub Actions OIDC token (no `GH_TOKEN` / `KB_HUB_URL`
   secrets needed on this repo), and opens the PR on the hub. Either way,
   merging that PR on the hub makes the content searchable.

## Query (reads the hub)

6. **Query** — `kb query "your question"` (hub from `.kb/config.yaml`), the
   hub's web UI, or MCP (see step 7).
7. **Connect the shared MCP server** — run `kb mcp-setup` (in your assistant:
   `/kb-mcp-setup`). It asks for the hub's HTTP base URL and token, writes
   both into `.env`, makes sure git ignores that file, and then verifies them
   against the hub so a wrong URL and a rejected token give you different
   errors.
   - `STRATA_KB_HUB_URL` — e.g. `http://kb-hub.example.com:8321`
   - `STRATA_KB_HTTP_TOKEN` — the hub token (ask the hub maintainer)

   `.mcp.json` (Claude Code) and `.cursor/mcp.json` (Cursor) already read
   those two variables from your environment, so load `.env` into your shell
   (`set -a; source .env; set +a`, or use direnv) and restart your assistant —
   MCP reads the environment only at startup.

   This is a *different* value from `hub:` in `.kb/config.yaml`, which is the
   git/path federation hub used by `kb query` and the lint gates.

## CLI reference

- `kb init` — scaffold or refresh a KB repo (asks hub|child; updates skills/templates; keeps `.kb/index.yaml`)
- `kb docker-setup` — child: check Docker + pull the ingest image; on the
  hub it also creates `.env` + token and starts the service
  (in your assistant: `/kb-docker-setup`)
- `kb ingest <pdf> --id <id>` — parse a PDF into `.kb/` sections
  (in Claude Code / Copilot Chat / Cursor: `/kb-ingest`)
- `kb summarize` — fill pending summaries via a headless LLM CLI
  (in your assistant: `/kb-summarize`)
- `kb approve <doc-id> [--section <id>]` — mark summarized sections as
  reviewed after SME check; `--all-changed --against <rev>` approves what
  changed since a rev (in your assistant: `/kb-approve`)
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
- `kb ticket lint <file|->` — Definition-of-Ready gate for BA tickets (in
  your assistant: part of /ba-ticket-author)
- `kb tags` — list every tag published on the hub federation
- `kb mcp-setup [--hub-url URL] [--token T] [--no-verify]` — write the hub's
  HTTP MCP credentials into `.env` and verify them. Re-run it bare to verify
  again without retyping anything.
  (in your assistant: `/kb-mcp-setup`; prefer the hidden prompt or
  `STRATA_KB_HTTP_TOKEN` over `--token` — it puts the token in your shell
  history)
