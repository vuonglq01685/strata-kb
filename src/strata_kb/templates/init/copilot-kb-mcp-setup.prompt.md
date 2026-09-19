---
mode: agent
description: Connect this repo to the hub's HTTP MCP — write STRATA_KB_HUB_URL and STRATA_KB_HTTP_TOKEN into .env and verify them. For child, ba and dev repos.
---

# /kb-mcp-setup — connect this repo to the hub's MCP

Thin wrapper around the `kb mcp-setup` CLI. The scaffolded MCP config uses
`${STRATA_KB_HUB_URL}` and `${STRATA_KB_HTTP_TOKEN}` placeholders that your
editor expands from the process environment; this command fills them in and
proves they work.

Hard rules:
- **NEVER ask for the token in chat, and never print it.** You run the CLI
  in a non-TTY subprocess, so its hidden prompt is unavailable, and a token
  typed into chat becomes part of this transcript. The user enters it in
  their own terminal.
- Never write `.env` or the MCP config by hand.
- Non-zero exit → show the error verbatim and stop.

## Workflow

1. Read `kind:` from `.kb/config.yaml`. `hub` → say the hub serves MCP over
   stdio and needs no setup, then stop.
2. Ask for the hub's HTTP base URL, e.g. `http://kb-hub.example.com:8321`.
   Not a secret, and not the same value as `hub:` in `.kb/config.yaml`.
3. Tell the user to run `kb mcp-setup --hub-url <url>` in **their own
   terminal**, where the hidden token prompt works.
4. When they confirm, run bare `kb mcp-setup` — it re-reads both values from
   `.env` and re-verifies. Relay the output.
5. Finish with: restart the editor, because MCP reads the environment only
   at startup.
