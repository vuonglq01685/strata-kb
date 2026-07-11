# Deploying Remote HTTP MCP for BAs (Phase 3)

Goal: BAs query the KB via MCP without cloning the repo (Phase 3 spec §10).

## Internal server

1. Clone the hub: `git clone <kb-hub-url> /srv/kb-hub`
2. Install the tool: `pip install center-kb` (add `.[embed]` if you want semantic search)
3. Set a token: `export CENTER_KB_HTTP_TOKEN=$(openssl rand -hex 24)` — store it in a secret manager
4. Start the server:
   `python -m center_kb.mcp --kb /srv/kb-hub/.kb --hub /srv/kb-hub --transport http --host 0.0.0.0 --port 8321`
5. Cron to keep the hub fresh (every 5 minutes): `*/5 * * * * git -C /srv/kb-hub pull --ff-only`

### Sample systemd unit

    [Unit]
    Description=CENTER-KB remote MCP
    After=network.target

    [Service]
    Environment=CENTER_KB_HTTP_TOKEN=<token>
    ExecStart=/usr/bin/python3 -m center_kb.mcp --kb /srv/kb-hub/.kb --hub /srv/kb-hub --transport http --host 0.0.0.0 --port 8321
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target

## Client config (Claude Code / Cowork)

    {
      "mcpServers": {
        "center-kb": {
          "type": "http",
          "url": "http://kb.internal:8321/mcp",
          "headers": { "Authorization": "Bearer <token>" }
        }
      }
    }

Note: run only on an internal network/VPN — documents are copyrighted. The server
refuses to start without `CENTER_KB_HTTP_TOKEN`.
