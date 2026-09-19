---
name: kb-docker-setup
description: Prepare this repo for Docker — MAIN hub: create .env, generate the HTTP token, start the service; child repo: pull the ingest image. Kind-aware; run after kb init.
---

# kb-docker-setup — prepare this repo for Docker

Thin wrapper around the `kb docker-setup` CLI. Your job: run the command,
relay its output, keep any secret out of the chat.

The CLI reads `kind:` from `.kb/config.yaml` and adapts:
- **hub** — creates `.env` with a fresh `STRATA_KB_HTTP_TOKEN`, then runs
  `docker compose up -d`. When Docker is not available it prints the manual
  next steps instead (still exit 0 — the token was written).
- **child** — no `.env`/token (nothing to secure); requires Docker, runs
  `docker compose pull` so the first ingest doesn't wait for the image,
  then prints the one-shot ingest command.

Hard rules:
- NEVER print the contents of `.env` (or the token) into the chat. The CLI
  deliberately does not echo the token; do not read the file to "show" it.
- Non-zero exit → show the error verbatim and stop. Do not retry with
  guessed fixes, do not create `.env` manually, do not run docker commands
  the CLI refused to run.

## Workflow

1. Run `kb docker-setup`.
   - Hub, "found existing .env" → ask the user whether to regenerate the
     token, and only then re-run with `--force`.
2. Relay the output. Hub: `.env` written, the auto-generated-token warning
   (replace with your own secret for real deployments; store it in a secret
   manager), the Web UI URL (http://localhost:8321/ui) and the client MCP
   config snippet. Child: image pulled and the
   `docker compose run --rm hub kb ingest ...` command.
