---
name: kb-mcp-setup
description: Connect this repo to the hub's HTTP MCP — write STRATA_KB_HUB_URL and STRATA_KB_HTTP_TOKEN into .env and verify them against the hub. For child, ba and dev repos; run after kb init.
---

# kb-mcp-setup — connect this repo to the hub's MCP

Thin wrapper around the `kb mcp-setup` CLI. `.mcp.json` and
`.cursor/mcp.json` were scaffolded with `${STRATA_KB_HUB_URL}` and
`${STRATA_KB_HTTP_TOKEN}` placeholders that your editor expands from the
process environment. This command fills them in and proves they work.

Hard rules:
- **NEVER ask for the token in chat, and never print it.** You run the CLI
  in a non-TTY subprocess, so its hidden prompt is unavailable, and a token
  typed into chat becomes part of this transcript. The user enters it in
  their own terminal.
- Never write `.env`, `.mcp.json` or `.cursor/mcp.json` by hand.
- Non-zero exit → show the error verbatim and stop. Do not retry with a
  guessed URL.

## Workflow

1. Read `kind:` from `.kb/config.yaml`. If it is `hub`, say that the hub
   serves MCP over stdio and needs no setup, then stop.
2. Ask the user for the hub's HTTP base URL — for example
   `http://kb-hub.example.com:8321`. This is not a secret. It is a different
   value from `hub:` in `.kb/config.yaml`, which is the git/path federation
   hub; do not reuse one for the other.
3. Tell the user to run this in **their own terminal**, where the hidden
   prompt works:

   ```
   kb mcp-setup --hub-url <the URL from step 2>
   ```

   The token is typed at the prompt. If they do not have one, they ask the
   hub maintainer.
4. When they confirm it finished, run bare `kb mcp-setup`. It reads both
   values back from `.env`, re-verifies against the hub, and asks nothing.
   Relay its output.
5. Finish by telling them to restart Claude Code — MCP servers read the
   environment only at client startup, so the new tools appear after a
   restart, not before.
