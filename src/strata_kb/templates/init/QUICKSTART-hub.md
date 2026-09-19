# Strata Quickstart (main hub)

This repo IS the hub: it hosts `federation/` (the single source of truth for
search) and runs the shared HTTP MCP server + Web UI. Child repos publish
into it; merging their PRs here is the review gate.

1. **Set up Docker serving** — run `kb docker-setup` (in Claude Code /
   Copilot Chat / Cursor: `/kb-docker-setup`). It creates `.env`, generates
   `STRATA_KB_HTTP_TOKEN`, and starts the service (`docker compose up -d`) —
   web UI at http://localhost:8321/ui (sign in with the token). The token is
   auto-generated for convenience — replace it with your own secret for real
   deployments. Manual fallback: `cp .env.example .env`, edit the token,
   then `docker compose up -d`. Without Docker:
   `python -m strata_kb.mcp --hub . --transport http`
   (requires the `STRATA_KB_HTTP_TOKEN` env var).
2. **Ingest this repo's own documents (optional)** — the hub may keep its own
   `.kb/`: put the PDF in `source/`, then
   `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"`
   (prefer the `/kb-ingest` slash command; or run inside Docker:
   `docker compose run --rm hub kb ingest source/my-doc.pdf --id my-doc`)
   Summaries: automatic with a local LLM CLI, or `/kb-summarize`; validate
   with `kb build`; then `kb publish` mirrors into `federation/<repo-id>/`.
3. **Query** — `kb query "your question"`, the web UI, or MCP. The local
   `.mcp.json` / `.cursor/mcp.json` run the stdio server for the hub
   maintainer; remote clients (child repos, BA machines) use the HTTP
   endpoint instead:
   `http://<host>:8321/mcp` with header `Authorization: Bearer <token>`.
4. **Register child repos (optional)** — lets child repos publish from CI via
   OIDC with zero secrets, instead of pushing directly. Create
   `federation/registry.yaml` on the hub with one line per child:
   `owner/repo: repo-id` under a `repos:` key. **This also makes the hub
   *governed*:** once the file is non-empty, `kb publish` on the git path
   refuses any repo-id not listed here and refuses direct pushes — every
   child that publishes over git, not only those using this OIDC
   intake, must be registered. Then install a GitHub App on the hub repo
   (permissions `Contents: Read and write` + `Pull requests: Read and
   write`) and set `STRATA_KB_GH_APP_ID`, `STRATA_KB_GH_APP_KEY`,
   `STRATA_KB_INTAKE_AUDIENCE` on the server — see
   `docs/deploy-remote-mcp.md` § "Publish intake" for the full setup.
   **Warning:** `repo-id` here must exactly match `repo_id:` in the child's
   `.kb/config.yaml`. On the **git** path a mismatch is refused before
   anything is written, naming both ids. On this **intake** path publish
   still succeeds and the PR opens, but the dev CLI will time out waiting
   for a PR that actually opened, and uploads lose incrementality (every
   publish becomes a full upload).

## Asset storage

Image assets (`assets/<sha256>.png|webp`, referenced from markdown) live
either in git or in an S3-compatible object store, per `asset_store.mode` in
the hub's `.kb/config.yaml`. Configured once, hub-side — a child never
configures asset storage of its own.

- **`mode: none`** (the default) — assets stay in git under
  `federation/<rid>/assets/` and `.kb/<doc>/assets/`. Fine for a compressed
  corpus; `kb doctor` warns once the total crosses ~100 MB, suggesting
  `mode: s3` (`kb assets migrate`) or git-LFS.
- **Switching to s3** — create a **private** bucket (block public access),
  then credentials scoped to Get/Put/Head on the `assets/` prefix only.
  Export them via the standard AWS env chain (`AWS_ACCESS_KEY_ID` /
  `AWS_SECRET_ACCESS_KEY` / region) — set `endpoint` in the config instead
  for MinIO/R2 or another S3-compatible host. Install the extra:
  `pip install "strata-kb[s3]"`. Run `kb init --assets s3` (or hand-edit the
  `asset_store:` block already in `.kb/config.yaml`) and fill in `bucket` /
  `region` / `endpoint`. `kb doctor` confirms the store is reachable. If
  assets already exist in git, `kb assets migrate` diverts them rid by rid
  (idempotent, commits `federation/`); then `kb assets verify` confirms
  every `_assets.yaml` record resolves and every markdown reference is
  covered. That commit is local only — `kb assets migrate` never pushes, so
  push it like any other hub commit if the hub has a remote.
- **Manual rollback (s3 → none)** — for each rid, download every
  `assets/<sha>` named in that rid's `_assets.yaml` back into its tree,
  delete the `_assets.yaml` files, set `mode: none`, and commit. The
  local-first resolver keeps serving throughout, so there's no downtime.
- **Large `mode: none` corpora** — if s3 isn't an option but the repo is
  outgrowing plain git, git-LFS for `assets/**` is a reasonable alternative;
  `strata-kb` doesn't manage LFS itself, but the local-first read path works
  either way.

## CLI reference

- `kb init` — scaffold or refresh a KB repo (asks hub|child; updates skills/templates; keeps `.kb/index.yaml`)
- `kb docker-setup` — prepare Docker: hub creates `.env` + the HTTP token and
  starts the service; child repos pull the ingest image
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
- `kb tags` — list every tag published on the hub federation
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
