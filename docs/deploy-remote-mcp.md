# Deploying Remote HTTP MCP for BAs (Phase 3)

Goal: BAs query the KB via MCP without cloning the repo (Phase 3 spec §10).

## Internal server

Note: hub clones used by the server/publishers should keep `core.autocrlf=false`
(the tool sets this repo-locally during publish/intake; a global
`autocrlf=true` on other hub clones degrades no-op detection but not
correctness).

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

## Publish intake (OIDC → PR on the hub)

The same server can accept publishes from child repos with **zero secrets on
the children**. Child CI authenticates with a GitHub Actions OIDC JWT; the
server verifies it, checks `federation/registry.yaml` on the hub, and opens
the PR itself using a GitHub App.

1. Create a GitHub App (hub owner): permissions `Contents: Read and write` +
   `Pull requests: Read and write`; install it on the hub repo only.
   Download the private key PEM.
2. Extra env for the server:

       Environment=CENTER_KB_GH_APP_ID=<app id>
       Environment=CENTER_KB_GH_APP_KEY=/etc/center-kb/app-key.pem
       Environment=CENTER_KB_INTAKE_AUDIENCE=https://kb.internal:8321

   All three present → `/intake/*` routes turn on. Any missing → intake stays
   off, read-only MCP still works.
3. Register each child on the hub: add `owner/repo: repo-id` under `repos:`
   in `federation/registry.yaml` (a normal PR — also your review gate for who
   may contribute). **Warning:** the `repo-id` here must exactly match
   `repo_id:` in the child's `.kb/config.yaml`. On mismatch, publish still
   succeeds and the PR opens, but the dev CLI will time out waiting for a PR
   that actually opened, and uploads lose incrementality (every publish
   becomes a full upload).
4. Install deps on the server: `pip install "center-kb[server]"`.

`/intake/*` is exempt from `CENTER_KB_HTTP_TOKEN` (children don't hold that
token): POST /intake/publish is OIDC-authenticated; GET manifest/status carry
only path+hash metadata — same internal-network assumption as the MCP itself.

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
