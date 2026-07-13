---
name: kb-docker-setup
description: Prepare the CENTER-KB hub for Docker HTTP serving — create .env and auto-generate the HTTP token. MAIN hub only; refuses on child repos.
---

# kb-docker-setup — prepare the hub for Docker HTTP serving

Thin wrapper around the `kb docker-setup` CLI. Your job: run the command,
relay its output, keep the secret out of the chat.

Hard rules:
- NEVER print the contents of `.env` (or the token) into the chat. The CLI
  deliberately does not echo the token; do not read the file to "show" it.
- This command is for the MAIN hub only. If the CLI refuses because the repo
  is a child (`kind: child` in `.kb/config.yaml`), relay that message — do
  NOT work around it by creating `.env` manually.

## Workflow

1. Run `kb docker-setup`.
   - It reports "found existing .env" → ask the user whether to regenerate
     the token, and only then re-run with `--force`.
2. Relay the output: `.env` written, the warning that the token was
   auto-generated (replace it with your own secret for real deployments and
   store it in a secret manager), and the next steps
   (`docker compose up -d`, the Web UI at http://localhost:8321/ui, the
   client MCP config snippet).
3. Non-zero exit → show the error verbatim and stop. Do not retry with
   guessed fixes.
