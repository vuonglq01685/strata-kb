---
name: kb-docker-setup
description: Prepare this repo for Docker — hub: create .env + HTTP token + start the service; child: pull the ingest image. Kind-aware.
---

# /kb-docker-setup — prepare this repo for Docker

Thin wrapper around the `kb docker-setup` CLI. Run the command, relay its
output, keep any secret out of the chat.

The CLI reads `kind:` from `.kb/config.yaml` and adapts:
- **hub** — creates `.env` with a fresh `STRATA_KB_HTTP_TOKEN`, then runs
  `docker compose up -d` (manual next steps are printed when Docker is not
  available).
- **child** — no `.env`/token; requires Docker, runs `docker compose pull`,
  then prints the one-shot ingest command.

Hard rules:
- NEVER print the contents of `.env` (or the token) into the chat. The CLI
  deliberately does not echo the token; do not read the file to "show" it.
- Non-zero exit → show the error verbatim and stop. Do not retry with
  guessed fixes, do not create `.env` manually.

## Workflow

1. Run `kb docker-setup`.
   - Hub, "found existing .env" → ask the user whether to regenerate the
     token, and only then re-run with `--force`.
2. Relay the output (hub: .env written + warning + UI URL + MCP snippet;
   child: image pulled + ingest command).
